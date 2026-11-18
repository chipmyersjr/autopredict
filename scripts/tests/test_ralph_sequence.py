"""Phase ordering, failure propagation and resumption without model calls."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ralph_sequence as sequence


class SequenceTests(unittest.TestCase):
    def execute(self, *, mode="run", completed=(), codes=(0, 0), resume=False, invalid=False, manifest=False, forwarded=()):
        configs = {name: {"plan": name, "tasks": [{"id": "T-01"}]} for name in ("be", "fe")}
        def config(root, path):
            if invalid and path.name == "fe":
                raise sequence.LoopError("Invalid frontend config")
            return configs[path.name]
        def progress(root, cfg):
            return {"tasks": {"T-01": {"status": "complete" if cfg["plan"] in completed else "not_started"}}}
        argv = ["sequence", mode, "--config", "be", "--config", "fe", "--allow-plan-updates"]
        if manifest:
            argv = ["sequence", mode, "--config", "all", "--allow-plan-updates"]
        argv.extend(forwarded)
        if resume:
            argv.append("--resume")
        def read_text(path):
            return '{"version": 1, "configs": ["be", "fe"]}' if path.name == "all" else '{}'
        with patch.object(sys, "argv", argv), patch.object(sequence, "git", return_value="/tmp"), \
                patch.object(Path, "read_text", read_text), \
                patch.object(sequence, "read_config", side_effect=config), \
                patch.object(sequence, "read_progress", side_effect=progress), \
                patch.object(sequence.subprocess, "run", side_effect=[
                    subprocess.CompletedProcess([], code) for code in codes]) as run:
            if invalid:
                with self.assertRaises(sequence.LoopError):
                    sequence.main()
                self.assertEqual(run.call_count, 0)
                return
            result = sequence.main()
            return result, [call.args[0] for call in run.call_args_list]

    def test_backend_precedes_frontend(self):
        result, calls = self.execute()
        self.assertEqual(result, 0)
        self.assertEqual([c[c.index("--config") + 1] for c in calls], ["be", "fe"])

    def test_backend_failure_prevents_frontend(self):
        result, calls = self.execute(codes=(1,))
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 1)

    def test_resume_skips_completed_backend_phase(self):
        result, calls = self.execute(completed=("be",), resume=True, codes=(0,))
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 1)
        self.assertIn("fe", calls[0])
        self.assertIn("--resume", calls[0])

    def test_frontend_failure_is_propagated(self):
        result, calls = self.execute(codes=(0, 2))
        self.assertEqual(result, 2)
        self.assertEqual(len(calls), 2)

    def test_preview_shows_completed_phases_too(self):
        result, calls = self.execute(mode="preview", completed=("be", "fe"))
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("preview" in command for command in calls))

    def test_all_configs_are_validated_before_start(self):
        self.execute(invalid=True)

    def test_one_manifest_selects_both_phases(self):
        result, calls = self.execute(manifest=True)
        self.assertEqual(result, 0)
        self.assertEqual([c[c.index("--config") + 1] for c in calls], ["be", "fe"])

    def test_worker_options_are_forwarded_to_both_phases(self):
        result, calls = self.execute(manifest=True, forwarded=("--codex", "custom-codex"))
        self.assertEqual(result, 0)
        self.assertTrue(all("custom-codex" in call for call in calls))
