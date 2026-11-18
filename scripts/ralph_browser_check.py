"""Run browser checks in the disposable Ralph image; optionally use its real API.

The existing guarded helper owns database creation/deletion. This wrapper never
updates scores or connects to a development database itself.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    env = {**os.environ, "CFBD_API_KEY": "", "ODDS_API_KEY": "",
           "LIVE_API": "", "LIVE_RUN_DB_FILE": "", "TEST_FRONTEND_PORT": "5175",
           "TEST_API_BASE_URL": "http://127.0.0.1:8017", "PLAYWRIGHT_CHANNEL": "chromium"}
    # Turn termination into normal unwinding so the fixture can drop its DB.
    def terminate(signum, frame):
        raise SystemExit(128 + signum)
    signal.signal(signal.SIGTERM, terminate)
    subprocess.run(["npm", "run", "build"], check=True, env=env)
    with tempfile.TemporaryDirectory(prefix="ralph-browser-") as directory:
        metadata = Path(directory) / "backend.json"
        server = None
        try:
            if args.live:
                server = subprocess.Popen([
                    "/opt/venv/bin/python", "tests/support/live_backend.py",
                    "--metadata", str(metadata), "--port", "8017",
                    "--origin", "http://127.0.0.1:5175"], env=env)
                deadline = time.monotonic() + 90
                while True:
                    if server.poll() is not None:
                        raise RuntimeError("Disposable browser backend exited before readiness")
                    if metadata.exists():
                        info = json.loads(metadata.read_text())
                        if not info["database"].startswith("autopredict_browser_"):
                            raise RuntimeError("Fixture did not create a disposable browser database")
                        try:
                            with urlopen(env["TEST_API_BASE_URL"] + "/api/ready", timeout=2) as response:
                                if response.status == 200:
                                    break
                        except (URLError, TimeoutError):
                            pass
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Disposable browser backend readiness timed out")
                    time.sleep(0.2)
                env.update(LIVE_API="1", LIVE_RUN_DB_FILE=str(metadata))
            subprocess.run(["npm", "test"], check=True, env=env)
        finally:
            if server is not None:
                if server.poll() is None:
                    server.terminate()
                try:
                    server.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
                    raise RuntimeError("Fixture cleanup timed out; inspect disposable test databases")
                if metadata.exists():
                    raise RuntimeError("Fixture left metadata behind; inspect disposable database cleanup")


if __name__ == "__main__":
    main()
