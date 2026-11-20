"""The live check must clean up its fixture even when browser tests fail."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ralph_browser_check as check


class BrowserCheckTests(unittest.TestCase):
    def test_controlled_checks_blank_keys_and_do_not_start_backend(self):
        with patch.object(sys, "argv", ["check"]), patch.object(check.signal, "signal"), \
                patch.object(check.subprocess, "run") as run, \
                patch.object(check.subprocess, "Popen") as start:
            check.main()
            start.assert_not_called()
            self.assertEqual([call.args[0] for call in run.call_args_list],
                             [["npm", "run", "build"], ["npm", "test"]])
            env = run.call_args.kwargs["env"]
            for name in ("CFBD_API_KEY", "ODDS_API_KEY", "LIVE_API", "LIVE_RUN_DB_FILE"):
                self.assertEqual(env[name], "")

    def test_failed_live_browser_test_still_stops_and_cleans_fixture(self):
        server = MagicMock()
        server.poll.return_value = None
        def start(argv, **kwargs):
            self.assertIn("--agent-worker", argv)
            metadata = Path(argv[argv.index("--metadata") + 1])
            metadata.write_text('{"database": "autopredict_browser_test"}')
            server.wait.side_effect = lambda **kw: metadata.unlink()
            return server
        ready = MagicMock()
        ready.__enter__.return_value.status = 200
        with patch.object(sys, "argv", ["check", "--live", "--backend-arg=--agent-worker"]), patch.object(check.signal, "signal"), \
                patch.object(check.subprocess, "run", side_effect=[None, subprocess.CalledProcessError(1, "npm test")]) as run, \
                patch.object(check.subprocess, "Popen", side_effect=start), \
                patch.object(check, "urlopen", return_value=ready):
            with self.assertRaises(subprocess.CalledProcessError):
                check.main()
            server.terminate.assert_called_once()
            server.wait.assert_called_once()
            self.assertEqual(run.call_args.kwargs["env"]["LIVE_API"], "1")

    def test_backend_arguments_require_live_mode(self):
        with patch.object(sys, "argv", ["check", "--backend-arg=--agent-worker"]), \
                patch.object(sys, "stderr"), patch.object(check.subprocess, "run") as run:
            with self.assertRaises(SystemExit) as error:
                check.main()
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()
