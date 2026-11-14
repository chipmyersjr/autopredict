# Ralph task loop

One task at a time: ask Codex to implement it, run the normal automated tests, record completion, and make one local commit. Repeat until the selected tasks are complete or a task needs attention. Nothing is pushed automatically.

## Three files, three roles

- `progress/.../plan.md`: requirements and acceptance criteria. The agent reads it; the runner does not interpret its prose.
- `ralph/ingress-backend.json`: task sequence, dependencies, test commands, and retry/time limits.
- `ralph/ingress-backend.progress.json`: structured execution progress, referencing the plan by path and task ID. Contains statuses and evidence, not copied requirements.

The JSON progress file drives task selection and resumption. After passing tests, the runner updates it and mirrors the task checkbox/status/completion notes into `plan.md`. Code, structured progress, and plan updates go into the same task commit. The Markdown mirror expects the existing task-ID checklist format with `Status` and `Completion notes` fields; it never infers dependencies or commands from plan prose.

## Run

Use the SSH-connected Docker Sandbox terminal with Python 3.9+, Git, authenticated Codex CLI, and Docker available. Configure your Git author identity there if needed. Commit this tooling and existing changes first; the loop requires a clean tree/index. Avoid editing the shared project from another window or agent while it runs.

```sh
make ralph-preview                       # Show tasks and checks; no edits/model calls
make ralph                               # Run BE-07–BE-12
make ralph RALPH_ARGS="--through BE-07"    # Start with just one task
make ralph RALPH_ARGS="--resume"          # Continue after inspecting a stopped run
```

Launching `make ralph` explicitly authorizes generated progress and plan updates for this run, as CHIP requested. For a different plan use `RALPH_CONFIG=ralph/your-run.json`.

The equivalent CLI is:

```sh
python3 scripts/ralph.py run --config ralph/ingress-backend.json \
  --allow-plan-updates --from BE-07 --through BE-12
```

The default worker uses `workspace-write` with no approval prompts. The runner runs tests separately, so worker restrictions do not prevent independent verification. `--permissions danger-full-access` is available if explicitly chosen inside the external Docker Sandbox; this script itself does not isolate the agent from your machine. Keep real provider keys outside the shared directory.

## Tests and manual verification

The ingress configuration runs familiar commands: `make db`, `docker compose build backend`, and the backend pytest suite through a one-off Compose container with the tests mounted read-only. `RUN_POSTGRES_TESTS=1` enables the existing fixtures that create/drop disposable test databases on the sandbox PostgreSQL server. Provider keys are blanked; the real-key environment is not used. There are no special smoke/checker scripts or new test services.

The loop retains automated tests for quota/concurrency, matching, imports, partial failures, and API behavior. Test coverage still requires reviewing the task commits; a passing command alone cannot prove every requirement.

After the loop, CHIP manually runs the backend and checks `POST /api/games/refresh` without keys. Expected: HTTP 200, `success=false`, `reason=configuration_error`, a useful safe message and full envelope, no accepted refresh attempt or provider calls, and saved data preserved. Then configure keys outside the sandbox and perform real-provider verification separately. The loop records both manual checks as pending, never as passed.

## Stop, inspect, resume

The loop has three attempts and a one-hour wall limit per task per launch. Failed checks feed their logs to another fresh Codex session. Exhausted limits, blocked work, unexpected file/Git edits, failed commits, or Ctrl+C stop the loop without discarding changes. Inspect the files, then use `--resume` to grant another bounded attempt allowance.

Local logs/results/recovery state live under `.git/ralph/` (or the equivalent Git directory). Structured task progress is committed; local diagnostics are not. Completed committed tasks are skipped. A repository lock prevents two Ralph runners from operating together. Workers must not edit design files, runner/configuration files, progress files, or Git state. The runner alone stages verified changes and commits; it does not bypass failing hooks/signing or perform resets/stashes.

These are workflow guardrails, not a security boundary against a malicious agent. Review source changes, hooks, and build configuration before running anything with real keys.

## Reuse

Copy the run configuration and structured progress file. Set their matching `plan` reference, task IDs/titles/statuses, completed prerequisite IDs, allowed source paths, check commands, and limits. Keep product requirements only in the referenced plan/design. Each check has `name`, `argv` (argument array), optional repository-relative `cwd`, and `timeout`. `{repo}` in an argument expands to the project root; no shell evaluation is performed. Keep environment overrides non-secret.

Runner regression tests use temporary Git repositories and fake Codex executables:

```sh
python3 -m unittest discover -s scripts/tests -v
```

They do not spend model credits, launch the real task loop, or change this repository's commits.
