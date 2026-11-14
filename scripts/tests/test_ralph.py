"""Exercise runner lifecycle in disposable repositories, without model calls."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

RUNNER = Path(__file__).resolve().parents[1] / "ralph.py"
spec = importlib.util.spec_from_file_location("ralph", RUNNER)
ralph = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ralph)


class TimestampTests(unittest.TestCase):
    def test_missing_timezone_data_falls_back_to_utc(self):
        with patch.object(ralph, "ZoneInfo", side_effect=ralph.ZoneInfoNotFoundError):
            stamp = ralph.log_timestamp()
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$")

PLAN = """# Example task plan

Area status: `not_started`
Planning status: ready.

## Tasks

- [ ] BE-01 — First task
  - Status: not_started
  - Scope: Implement first behavior.
  - Dependencies: None.
  - Acceptance criteria: First output exists.
  - Validation: Independent gate.
  - Completion notes: Pending.

- [ ] BE-02 — Second task
  - Status: not_started
  - Scope: Implement second behavior.
  - Dependencies: BE-01.
  - Acceptance criteria: Second output exists.
  - Validation: Independent gate.
  - Completion notes: Pending.

## Loop log
"""

# This test executable stands in for Codex, including its structured output file.
FAKE_AGENT = """#!/usr/bin/env python3
import json, os, pathlib, re, sys
prompt = sys.stdin.read()
task = re.search(r'^TASK_ID: (.+)$', prompt, re.M)[1]
result = pathlib.Path(sys.argv[sys.argv.index('--output-last-message') + 1])
root = pathlib.Path.cwd()
mode = os.environ.get('FAKE_MODE', '')
if mode == 'exit': sys.exit(7)
if mode == 'bad-json':
 result.write_text('not-json'); sys.exit(0)
if mode == 'blocked':
 result.write_text(json.dumps(dict(task_id=task,status='blocked',summary='Needs a design decision'))); sys.exit(0)
if mode == 'protected':
 (root/'design/spec.md').write_text('Unauthorized change')
elif mode == 'wrong-plan':
 p=root/'progress/example/backend/plan.md'; p.write_text(p.read_text().replace('Implement first behavior.', 'Weaken scope.'))
elif mode == 'wrong-progress':
 p=root/'ralph/progress.json'; data=json.loads(p.read_text()); data['tasks'][task]['status']='complete'; p.write_text(json.dumps(data))
elif mode == 'stage':
 import subprocess
 (root/'src/staged.txt').write_text('staged')
 subprocess.run(['git','add','src/staged.txt'],check=True)
elif mode == 'escape':
 (root/'unrelated.txt').write_text('unrelated')
elif mode == 'git-commit':
 import subprocess
 (root/'src/rogue.txt').write_text('rogue')
 subprocess.run(['git','add','src/rogue.txt'],check=True)
 subprocess.run(['git','commit','-m','agent-made commit'],check=True)
else:
 path=root/'src'/(task+'.txt')
 if mode == 'repair':
  path.write_text('fixed' if path.exists() else 'broken')
 elif mode != 'no-changes': path.write_text('implemented')
result.write_text(json.dumps(dict(task_id=task,status='ready',summary='Implemented '+task)))
"""


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="autopredict-ralph-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for folder in ("src", "design", "ralph", "progress/example/backend"):
            (self.root / folder).mkdir(parents=True)
        (self.root / "AGENTS.md").write_text("Test instructions\n")
        (self.root / "design/spec.md").write_text("Governing design\n")
        self.plan = self.root / "progress/example/backend/plan.md"
        self.plan.write_text(PLAN)
        self.progress = self.root / "ralph/progress.json"
        self.progress.write_text(json.dumps({"version": 1, "plan": "progress/example/backend/plan.md",
            "area_status": "not_started", "tasks": {
                "BE-01": {"title": "First task", "status": "not_started"},
                "BE-02": {"title": "Second task", "status": "not_started"}}}))
        self.agent = self.root / "fake-codex"
        self.agent.write_text(FAKE_AGENT.replace("#!/usr/bin/env python3", "#!" + sys.executable, 1))
        self.agent.chmod(0o755)
        self.config = {
            "version": 1, "plan": "progress/example/backend/plan.md",
            "progress_file": "ralph/progress.json",
            "context": ["design/spec.md"], "allowed_paths": ["src/*"],
            "max_attempts": 2, "task_timeout": 20,
            "checks": [{"name": "Source verification", "argv": [sys.executable, "-c",
                "from pathlib import Path; files=list(Path('src').glob('*.txt')); assert files; assert all(p.read_text() != 'broken' for p in files)"], "timeout": 3}],
            "tasks": [{"id": "BE-01"}, {"id": "BE-02", "dependencies": ["BE-01"]}],
        }
        self.config_path = self.root / "ralph/config.json"
        self.write_config()
        self.git("init", "-b", "test")
        self.git("config", "user.name", "Ralph Test")
        self.git("config", "user.email", "ralph-test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("add", ".")
        self.git("commit", "-m", "baseline")

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config))

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.STDOUT, text=True).strip()

    def call(self, *extra, mode="", command="run"):
        env = {**os.environ, "FAKE_MODE": mode}
        return subprocess.run([sys.executable, str(RUNNER), command, "--config", "ralph/config.json",
                               "--codex", str(self.agent), "--allow-plan-updates", *extra],
                              cwd=self.root, env=env, text=True, capture_output=True, timeout=30)

    def test_preview_never_edits_or_invokes_agent(self):
        result = self.call(command="preview", mode="protected")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BE-02", result.stdout)
        self.assertIn("nothing has been run", result.stdout)
        self.assertIn("2 unfinished, 0 already complete", result.stdout)
        self.assertEqual(result.stdout.count("Source verification"), 1)
        self.assertNotIn("files=list", result.stdout)
        self.assertEqual(self.plan.read_text(), PLAN)
        self.assertEqual(self.git("status", "--short"), "")
        self.assertFalse((self.root / ".git/ralph").exists())

    def test_verbose_preview_includes_commands_once(self):
        result = self.call("--verbose", command="preview")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("files=list"), 1)

    def test_preview_start_command_preserves_selected_range(self):
        result = self.call("--through", "BE-01", command="preview")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 unfinished, 0 already complete", result.stdout)
        self.assertIn("RALPH_CONFIG=ralph/config.json", result.stdout)
        self.assertIn("--from BE-01 --through BE-01", result.stdout)

    def test_one_commit_per_task_and_idempotent_rerun(self):
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "3")
        self.assertEqual(self.git("status", "--short"), "")
        plan = self.plan.read_text()
        self.assertIn("Area status: `complete`", plan)
        self.assertIn("- [x] BE-01", plan)
        self.assertIn("- [x] BE-02", plan)
        self.assertEqual(json.loads(self.progress.read_text())["tasks"]["BE-02"]["status"], "complete")
        self.assertIn("Independent checks: Source verification passed", plan)
        self.assertIn("Ralph-Task: BE-02", self.git("log", "-1", "--format=%B"))
        self.assertIn("Acceptance criteria: First output exists.", plan)
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "3")

    def test_task_range_and_later_resume_of_next_task(self):
        first = self.call("--through", "BE-01")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "2")
        self.assertIn("Area status: `in_progress`", self.plan.read_text())
        second = self.call("--from", "BE-02")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

    def test_failed_check_is_repaired_before_commit(self):
        result = self.call("--through", "BE-01", mode="repair")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RETRY", result.stdout)
        self.assertEqual((self.root / "src/BE-01.txt").read_text(), "fixed")
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "2")

    def test_failed_run_preserves_changes_and_requires_explicit_resume(self):
        failed = self.call("--through", "BE-01", mode="exit")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("Status: in_progress", self.plan.read_text())
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "1")
        refused = self.call("--through", "BE-01")
        self.assertIn("--resume", refused.stderr)
        resumed = self.call("--through", "BE-01", "--resume")
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "2")

    def test_dirty_worktree_is_never_committed(self):
        (self.root / "src/user-work.txt").write_text("User work")
        result = self.call()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("clean working tree", result.stderr)
        self.assertEqual(self.plan.read_text(), PLAN)

    def test_dependency_must_be_complete(self):
        result = self.call("--from", "BE-02")
        self.assertIn("Unfinished dependency", result.stderr)
        self.assertEqual(self.plan.read_text(), PLAN)

    def test_progress_json_drives_selection_without_parsing_plan_prose(self):
        self.plan.write_text(PLAN.replace("  - Dependencies: BE-01.", "  - Dependencies: Refer to governing design."))
        result = self.call(command="preview")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("BE-01  pending", result.stdout)
        self.assertIn("BE-02  pending", result.stdout)
        self.assertIn("First task", result.stdout)
        self.assertIn("Second task", result.stdout)

    def test_malformed_mirror_stops_before_status_updates(self):
        self.plan.write_text(PLAN.replace("  - Completion notes: Pending.", "", 1))
        before = self.progress.read_text()
        result = self.call(command="preview")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Completion notes field", result.stderr)
        self.assertEqual(self.progress.read_text(), before)

    def test_worker_cannot_mark_its_own_structured_progress_complete(self):
        result = self.call(mode="wrong-progress")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Structured progress changed outside the runner", result.stderr)
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "1")

    def test_invalid_result_and_no_change_cannot_complete_task(self):
        for mode in ("bad-json", "no-changes"):
            with self.subTest(mode=mode):
                result = self.call("--through", "BE-01", "--resume", mode=mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.git("rev-list", "--count", "HEAD"), "1")
                self.assertNotIn("- [x] BE-01", self.plan.read_text())

    def test_blocked_result_stops_without_committing(self):
        result = self.call(mode="blocked")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("User input required", result.stderr)
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "1")

    def test_protected_design_change_stops_immediately(self):
        result = self.call(mode="protected")
        self.assertIn("Protected file changed: design/spec.md", result.stderr)
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "1")

    def test_out_of_scope_and_plan_changes_stop(self):
        result = self.call(mode="escape")
        self.assertIn("Out-of-scope file", result.stderr)
        # Remove only this test fixture's unauthorized file to test a different violation.
        (self.root / "unrelated.txt").unlink()
        result = self.call("--resume", mode="wrong-plan")
        self.assertIn("Plan changed outside the runner", result.stderr)

    def test_agent_staging_stops(self):
        result = self.call(mode="stage")
        self.assertIn("Unexpected staged files", result.stderr)

    def test_agent_commit_stops(self):
        result = self.call(mode="git-commit")
        self.assertIn("changed HEAD/branch", result.stderr)

    def test_lock_prevents_second_runner(self):
        with ralph.repo_lock(self.root):
            result = self.call()
        self.assertIn("repository lock", result.stderr)

    def test_escaping_config_plan_is_rejected(self):
        self.config["plan"] = "../outside.md"
        self.write_config()
        result = self.call(command="preview")
        self.assertIn("Path escapes repository", result.stderr)

    def test_resume_recovers_commit_before_state_checkpoint(self):
        result = self.call("--through", "BE-01")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        state_path, = (self.root / ".git/ralph").glob("*/state.json")
        state = json.loads(state_path.read_text())
        state.update(head=self.git("rev-parse", "HEAD^"), task="BE-01")
        state_path.write_text(json.dumps(state))
        result = self.call("--from", "BE-02")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("rev-list", "--count", "HEAD"), "3")

    def test_timeout_kills_child_process_group(self):
        logfile = self.root / "timeout.log"
        start = time.monotonic()
        with self.assertRaises(ralph.LoopError):
            ralph.execute([sys.executable, "-c", "import time; time.sleep(30)"], self.root,
                          os.environ, logfile, 0.2)
        self.assertLess(time.monotonic() - start, 5)


if __name__ == "__main__":
    unittest.main()
