#!/usr/bin/env python3
"""Bounded, sequential Codex tasks with independent checks and Git checkpoints.

Python standard library only; intended for macOS/Linux terminals. Run inside the
Docker Sandbox for isolation. These workflow guards are not a security boundary.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import signal
import subprocess
import sys
import time
from zoneinfo import ZoneInfo


class LoopError(Exception):
    pass


SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "task_id": {"type": "string"},
        "status": {"type": "string", "enum": ["ready", "blocked"]},
        "summary": {"type": "string"},
    },
    "required": ["task_id", "status", "summary"],
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True)
    if result.returncode:
        raise LoopError(result.stderr.decode(errors="replace").strip() or "Git command failed")
    return result.stdout.decode(errors="replace").strip() if "-z" not in args else result.stdout.decode()


def read_progress(root, config):
    progress = json.loads(within(root, config["progress_file"]).read_text())
    if progress.get("version") != 1 or progress.get("plan") != config["plan"]:
        raise LoopError("Progress file must reference the configured plan")
    if not isinstance(progress.get("tasks"), dict):
        raise LoopError("Progress file needs a tasks object keyed by task ID")
    for task_id, task in progress["tasks"].items():
        if (not re.fullmatch(r"[A-Z][A-Z0-9]*-\d+", task_id) or not task.get("title") or
                task.get("status") not in {"not_started", "in_progress", "blocked", "complete"}):
            raise LoopError("Invalid structured task: " + task_id)
    return progress


def checklist_entry(text, task_id):
    """Locate only the human-readable mirror; never interpret task requirements."""
    pattern = re.compile(r"^- \[[ x]\] " + re.escape(task_id) + r"\s+[—–-]\s+[^\n]*\n(?:[ \t]+[^\n]*\n|\n)*", re.M)
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise LoopError("Need exactly one Markdown checklist entry for " + task_id)
    block = matches[0].group()
    for field in ("Status", "Completion notes"):
        if len(re.findall(r"^  - " + field + ":", block, re.M)) != 1:
            raise LoopError("Task needs one " + field + " field: " + task_id)
    return matches[0]


def within(root, name):
    path = (root / name).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise LoopError("Path escapes repository: " + name)
    return path


def read_config(root, path):
    raw = path.read_bytes()
    config = json.loads(raw)
    if config.get("version") != 1:
        raise LoopError("Unsupported config version")
    plan = within(root, config["plan"])
    if not plan.is_file():
        raise LoopError("Configured plan does not exist")
    parsed = read_progress(root, config)["tasks"]
    selected = config["tasks"]
    ids = [task["id"] for task in selected]
    if not ids or len(ids) != len(set(ids)) or any(t not in parsed for t in ids):
        raise LoopError("Config task IDs must be unique and present in structured progress")
    if not config.get("allowed_paths"):
        raise LoopError("Config needs allowed_paths")
    for item in selected:
        checklist_entry(plan.read_text(), item["id"])
        for dependency in item.get("dependencies", []):
            if dependency not in parsed:
                raise LoopError("Unknown dependency: " + dependency)
        checks = config.get("checks", []) + item.get("checks", [])
        if not checks:
            raise LoopError("Every task needs at least one independent check")
        for check in checks:
            if (not check.get("name") or not check.get("argv") or
                    not all(isinstance(s, str) and s for s in check["argv"]) or
                    check.get("timeout", 0) <= 0):
                raise LoopError("Invalid check specification")
            within(root, check.get("cwd", "."))
    if config.get("max_attempts", 0) < 1 or config.get("task_timeout", 0) < 1:
        raise LoopError("Positive max_attempts and task_timeout are required")
    for name in config.get("context", []):
        if not within(root, name).is_file():
            raise LoopError("Missing context file: " + name)
    config["fingerprint"] = digest(raw)
    return config


def changed(root):
    names = git(root, "diff", "--no-renames", "--name-only", "-z", "HEAD").split("\0")
    names += git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    return sorted(set(filter(None, names)))


def controls(root, config, config_path):
    # Runner/config/design edits cannot be folded into an implementation task.
    paths = git(root, "ls-files", "-z", "AGENTS.md", "design", "scripts", "ralph").split("\0")
    paths += config.get("protected_paths", []) + [str(config_path.relative_to(root))]
    return {name: digest(within(root, name).read_bytes()) if within(root, name).is_file() else None
            for name in set(filter(None, paths)) if name != config["progress_file"]}


def ensure_scope(root, config, plan, state):
    if git(root, "rev-parse", "HEAD") != state["head"] or git(root, "symbolic-ref", "--short", "HEAD") != state["branch"]:
        raise LoopError("Agent or another process changed HEAD/branch; inspect before resuming")
    if git(root, "diff", "--cached", "--name-only"):
        raise LoopError("Unexpected staged files; the runner owns staging and commits")
    if digest(plan.read_bytes()) != state["plan_digest"]:
        raise LoopError("Plan changed outside the runner; inspect before resuming")
    if digest(within(root, config["progress_file"]).read_bytes()) != state["progress_digest"]:
        raise LoopError("Structured progress changed outside the runner; inspect before resuming")
    for name, expected in state["controls"].items():
        path = within(root, name)
        actual = digest(path.read_bytes()) if path.is_file() else None
        if actual != expected:
            raise LoopError("Protected file changed: " + name)
    names = changed(root)
    for name in names:
        within(root, name)
        if name in {config["plan"], config["progress_file"]}:
            continue
        if (name.startswith(("design/", "progress/", "scripts/", "ralph/", ".git/")) or
                name == "AGENTS.md" or name in state["controls"] or
                not any(fnmatch.fnmatchcase(name, pattern) for pattern in config["allowed_paths"])):
            raise LoopError("Out-of-scope file changed: " + name)
    return names


@contextmanager
def repo_lock(root):
    path = Path(git(root, "rev-parse", "--git-common-dir"))
    if not path.is_absolute():
        path = root / path
    with (path / "ralph.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LoopError("Another Ralph runner holds this repository lock")
        try:
            yield path / "ralph"
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def save(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(path)


def stop_group(process):
    for sig, timeout in ((signal.SIGTERM, 15), (signal.SIGKILL, 3)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            continue
        # Also signal any surviving child processes after the parent exits.
        if sig == signal.SIGTERM:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        break


def execute(argv, cwd, env, log, timeout, stdin=None):
    """Stream logs while enforcing a wall deadline on the entire process group."""
    process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=stdin or subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    start = time.monotonic()
    try:
        with log.open("wb") as output, selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic() - start > timeout:
                    raise LoopError("Command timed out: " + argv[0])
                for key, _ in selector.select(0.2):
                    data = os.read(key.fd, 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    output.write(data)
                    output.flush()
                    sys.stdout.write(data.decode(errors="replace"))
                    sys.stdout.flush()
            remaining = timeout - (time.monotonic() - start)
            if remaining <= 0:
                raise LoopError("Command timed out: " + argv[0])
            try:
                return process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                raise LoopError("Command timed out: " + argv[0])
    finally:
        stop_group(process)
        process.stdout.close()


def update_plan(plan, task_id, status, area, note=None, entry=None):
    """Mirror one structured status into Markdown; no prose/contract parsing."""
    text = plan.read_text()
    match = checklist_entry(text, task_id)
    block = match.group()
    block = re.sub(r"^- \[[ x]\]", "- [x]" if status == "complete" else "- [ ]", block, count=1)
    block = re.sub(r"^  - Status:.*$", "  - Status: " + status, block, count=1, flags=re.M)
    if note:
        block = re.sub(r"^  - Completion notes:.*$", lambda _: "  - Completion notes: " + note,
                       block, count=1, flags=re.M)
    text = text[:match.start()] + block + text[match.end():]
    text = re.sub(r"^Area status:.*$", "Area status: `" + area + "`", text, count=1, flags=re.M)
    text = re.sub(r"^Planning status:.*$", "Planning status: ready. Current execution status and evidence are recorded in the task checklist and latest loop entries.", text, count=1, flags=re.M)
    if entry:
        text = text.rstrip() + "\n\n" + entry + "\n"
    plan.write_text(text)


def record_progress(root, config, task_id, status, summary=None, evidence=None, files=None):
    path = within(root, config["progress_file"])
    progress = read_progress(root, config)
    task = progress["tasks"][task_id]
    task["status"] = status
    if summary:
        task.update(summary=summary, checks=evidence, files=files)
    progress["area_status"] = "complete" if all(t["status"] == "complete" for t in progress["tasks"].values()) else "in_progress"
    save(path, progress)
    return progress["area_status"]


def prompt(config, task_id, title, feedback):
    return f"""Implement exactly one task in this repository.
TASK_ID: {task_id}
PLAN: {config['plan']}

Read AGENTS.md, the plan, and governing design before editing. Context files:
{json.dumps(config.get('context', []))}

Selected task: {title}. Read its scope, acceptance criteria, and validation in the
referenced plan. Structured progress is at {config['progress_file']}; it contains
execution status only and does not replace the plan's requirements.

The user authorizes this task's implementation and one commit after independent
verification. The runner, not you, owns structured progress, plan status/evidence updates, and Git
operations. Do not edit progress/, design/, AGENTS.md, scripts/, ralph/, the run
configuration, or existing protected migrations. Do not stage, commit, reset,
checkout, push, edit Git hooks/config, or discard changes. Use apply_patch for
manual source edits. Work only within these path patterns:
{json.dumps(config['allowed_paths'])}

Run instructions: {config.get('instructions', '')}

Required independent checks (the runner executes these after you finish):
{json.dumps(config.get('checks', []) + next(t for t in config['tasks'] if t['id'] == task_id).get('checks', []))}

Use fake credentials/mock provider responses. Do not read private env files,
configure real provider keys, make live provider calls, weaken checks, or change
acceptance criteria. Missing live credentials alone are not a blocker. If your
inner sandbox prevents running a check, implement it and let the runner execute
the configured commands; do not spend the turn requesting permissions.

Return JSON matching the supplied schema. status=ready means implementation is
ready for independent verification, not that the task has been marked complete.
Use blocked only for a concrete dependency/design decision requiring the user.

Previous attempt's feedback:
{feedback or 'First attempt.'}
"""


def run(root, config, config_path, chosen, args, storage):
    key = digest((config["plan"] + config["fingerprint"]).encode())[:16]
    directory = storage / key
    directory.mkdir(parents=True, exist_ok=True)
    state_path = directory / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else None
    plan = within(root, config["plan"])
    branch = git(root, "symbolic-ref", "--short", "HEAD")
    head = git(root, "rev-parse", "HEAD")
    if state and state.get("task"):
        # Recover a commit that succeeded immediately before a runner interruption.
        expected = f"Ralph-Config: {config['fingerprint']}\nRalph-Task: {state['task']}"
        if (head != state["head"] and not changed(root) and
                git(root, "rev-parse", "HEAD^") == state["head"] and
                expected in git(root, "log", "-1", "--format=%B") and
                read_progress(root, config)["tasks"][state["task"]]["status"] == "complete"):
            state = None
        elif not args.resume:
            raise LoopError("An unfinished run exists. Inspect its files, then use --resume")
    if not state or not state.get("task"):
        if changed(root) or git(root, "diff", "--cached", "--name-only"):
            raise LoopError("Start from a clean working tree and index; commit tooling/other work first")
        state = {"head": head, "branch": branch, "task": None, "attempts": 0,
                 "plan_digest": digest(plan.read_bytes()), "controls": controls(root, config, config_path),
                 "progress_digest": digest(within(root, config["progress_file"]).read_bytes()),
                 "feedback": ""}
    ensure_scope(root, config, plan, state)
    if state["task"] and state["task"] not in [t["id"] for t in chosen]:
        raise LoopError("Selected range excludes the unfinished task")
    env = {**os.environ, **config.get("environment", {}), "GIT_TERMINAL_PROMPT": "0"}
    schema = directory / "result.schema.json"
    schema.write_text(json.dumps(SCHEMA))
    for item in chosen:
        task_id = item["id"]
        current = read_progress(root, config)["tasks"]
        if current[task_id]["status"] == "complete" and state["task"] != task_id:
            print("SKIP " + task_id + " (already complete in committed plan)")
            continue
        if any(current[d]["status"] != "complete" for d in item.get("dependencies", [])):
            raise LoopError("Unfinished dependency for " + task_id)
        state["task"] = task_id
        area = record_progress(root, config, task_id, "in_progress")
        update_plan(plan, task_id, "in_progress", area)
        state["plan_digest"] = digest(plan.read_bytes())
        state["progress_digest"] = digest(within(root, config["progress_file"]).read_bytes())
        save(state_path, state)
        task_start = time.monotonic()
        for _ in range(config["max_attempts"]):
            state["attempts"] += 1
            stem = f"{task_id}-{state['attempts']:03d}"
            result_path = directory / (stem + ".result.json")
            input_path = directory / (stem + ".prompt.txt")
            input_path.write_text(prompt(config, task_id, current[task_id]["title"], state["feedback"]))
            save(state_path, state)
            remaining = config["task_timeout"] - (time.monotonic() - task_start)
            if remaining <= 0:
                raise LoopError("Task time limit reached; changes preserved")
            argv = [args.codex, "exec", "-c", 'approval_policy="never"', "--sandbox", args.permissions,
                    "--json", "--output-schema", str(schema), "--output-last-message", str(result_path), "-"]
            print(f"\nIMPLEMENT {task_id}, attempt {state['attempts']} | logs: {directory}", flush=True)
            try:
                with input_path.open("rb") as stdin:
                    code = execute(argv, root, env, directory / (stem + ".agent.jsonl"), remaining, stdin)
                ensure_scope(root, config, plan, state)
                if code:
                    raise LoopError(f"Codex exited {code}; inspect {stem}.agent.jsonl")
                result = json.loads(result_path.read_text())
                if (not isinstance(result, dict) or set(result) != {"task_id", "status", "summary"} or result["task_id"] != task_id or
                        result["status"] not in {"ready", "blocked"} or
                        not isinstance(result["summary"], str) or not result["summary"].strip()):
                    raise LoopError("Invalid agent result")
                if result["status"] == "blocked":
                    state["feedback"] = "User input required: " + result["summary"]
                    save(state_path, state)
                    raise LoopError(state["feedback"])
                checks = config.get("checks", []) + item.get("checks", [])
                evidence = []
                for number, check in enumerate(checks):
                    remaining = config["task_timeout"] - (time.monotonic() - task_start)
                    if remaining <= 0:
                        raise LoopError("Task time limit reached")
                    log = directory / f"{stem}.check-{number}.log"
                    print("\nVERIFY " + check["name"], flush=True)
                    command = [arg.replace("{repo}", str(root)) for arg in check["argv"]]
                    code = execute(command, within(root, check.get("cwd", ".")), env,
                                   log, min(check["timeout"], remaining))
                    ensure_scope(root, config, plan, state)
                    if code:
                        raise LoopError(f"Check {check['name']} failed ({code}):\n" + log.read_text(errors="replace")[-8000:])
                    evidence.append(check["name"] + " passed")
                names = ensure_scope(root, config, plan, state)
                if not [name for name in names if name not in {config["plan"], config["progress_file"]}]:
                    raise LoopError("No implementation/test/documentation changes for this task")
            except (LoopError, OSError, ValueError) as error:
                # Unsafe scope/Git/plan edits are never sent to the agent for automatic repair.
                ensure_scope(root, config, plan, state)
                state["feedback"] = str(error)
                save(state_path, state)
                if state["feedback"].startswith("User input required:"):
                    raise LoopError(state["feedback"])
                print("\nRETRY: " + str(error), flush=True)
                continue
            break
        else:
            raise LoopError("Attempt limit reached for " + task_id + "; changes/logs preserved. Inspect, then --resume")
        summary = " ".join(result["summary"].split())
        now = datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M %Z")
        note = f"{summary} Independent checks: {'; '.join(evidence)}. Files: {', '.join(names)}. Logs: .git/ralph/{key}/{stem}.*."
        if config.get("completion_note"):
            note += " " + config["completion_note"]
        entry = f"### {now} — {task_id} Ralph execution\n\n- Completed tasks: {task_id}.\n- Validation: {'; '.join(evidence)}.\n- Completion notes: {summary}\n- Next: Continue the configured task sequence; live-provider verification remains separately reported."
        area = record_progress(root, config, task_id, "complete", summary, evidence, names)
        update_plan(plan, task_id, "complete", area, note, entry)
        state["plan_digest"] = digest(plan.read_bytes())
        state["progress_digest"] = digest(within(root, config["progress_file"]).read_bytes())
        save(state_path, state)
        names = ensure_scope(root, config, plan, state)
        git(root, "diff", "--check")
        git(root, "add", "--", *names)
        staged = git(root, "diff", "--cached", "--name-only", "-z").split("\0")
        if sorted(filter(None, staged)) != names:
            raise LoopError("Staged paths differ from verified paths; inspect index")
        message = f"feat: {task_id} {current[task_id]['title']}\n\nRalph-Plan: {config['plan']}\nRalph-Config: {config['fingerprint']}\nRalph-Task: {task_id}"
        # Do not retry Git failures or silently bypass user commit hooks/signing.
        git(root, "commit", "-m", message)
        print("\nCOMMITTED " + task_id + " " + git(root, "rev-parse", "--short", "HEAD"), flush=True)
        state.update(head=git(root, "rev-parse", "HEAD"), task=None, feedback="")
        save(state_path, state)
        if changed(root):
            raise LoopError("Files changed during commit; inspect before continuing")
    print("\nSelected tasks complete. No changes were pushed.")


def show_preview(root, config, selected, verbose=False):
    progress = read_progress(root, config)["tasks"]
    complete = sum(progress[t["id"]]["status"] == "complete" for t in selected)
    print("Ralph preview — nothing has been run")
    print("Plan: " + config["plan"])
    print(f"\nTask queue: {len(selected) - complete} unfinished, {complete} already complete")
    labels = {"not_started": "pending", "in_progress": "in progress", "blocked": "blocked", "complete": "complete (skip)"}
    for item in selected:
        task = progress[item["id"]]
        print(f"  {item['id']}  {labels[task['status']]:<16} {task['title']}")
        for check in item.get("checks", []):
            print("    Additional check: " + check["name"])
            if verbose:
                print("      " + shlex.join(arg.replace("{repo}", str(root)) for arg in check["argv"]))
    shared = config.get("checks", [])
    if shared:
        print("\nChecks before EVERY task commit:")
        for check in shared:
            print("  - " + check["name"])
            if verbose:
                print("    " + shlex.join(arg.replace("{repo}", str(root)) for arg in check["argv"]))
    minutes = config["task_timeout"] / 60
    print("\nPer task: implement → check → update progress/plan → commit locally")
    print(f"Limits: up to {config['max_attempts']} attempts and {minutes:g} minutes per task, per launch.")
    print("No automatic push. Only the configured checks run.")
    if config.get("completion_note"):
        print("Follow-up: " + config["completion_note"])
    if changed(root):
        print("\nWorking tree has changes. Fresh runs require a clean tree; --resume is for an interrupted run.")
    config_arg = (" RALPH_CONFIG=" + shlex.quote(str(config["config_name"]))
                  if config["config_name"] != "ralph/ingress-backend.json" else "")
    range_arg = ""
    if selected != config["tasks"]:
        range_arg = " RALPH_ARGS=" + shlex.quote("--from " + selected[0]["id"] + " --through " + selected[-1]["id"])
    print("\nTo start: make ralph" + config_arg + range_arg)
    if not verbose:
        print('Exact commands: make ralph-preview' + config_arg + ' RALPH_ARGS="--verbose"')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["preview", "run"])
    parser.add_argument("--config", default="ralph/ingress-backend.json")
    parser.add_argument("--from", dest="first")
    parser.add_argument("--through", dest="last")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--verbose", action="store_true", help="Include exact check commands in preview")
    parser.add_argument("--allow-plan-updates", action="store_true", help="Authorize generated status/evidence updates for this run")
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--permissions", choices=["workspace-write", "danger-full-access"], default="workspace-write")
    args = parser.parse_args(argv)
    try:
        root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel")).resolve()
        config_path = within(root, args.config)
        config = read_config(root, config_path)
        config["config_name"] = args.config
        selected = config["tasks"]
        ids = [t["id"] for t in selected]
        first = ids.index(args.first) if args.first else 0
        last = ids.index(args.last) if args.last else len(ids) - 1
        if first > last:
            raise LoopError("Invalid task range")
        selected = selected[first:last + 1]
        if args.mode == "preview":
            show_preview(root, config, selected, args.verbose)
            return 0
        if not args.allow_plan_updates:
            raise LoopError("Pass --allow-plan-updates to authorize status/evidence updates")
        with repo_lock(root) as storage:
            run(root, config, config_path, selected, args, storage)
        return 0
    except (LoopError, OSError, ValueError, KeyError) as error:
        print("Ralph stopped: " + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nRalph interrupted; changes preserved. Inspect, then use --resume.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
