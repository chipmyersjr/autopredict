"""Run existing Ralph configurations in order, stopping at the first failure."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys

from ralph import LoopError, git, read_config, read_progress, within


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["preview", "run"])
    parser.add_argument("--config", action="append", required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--allow-plan-updates", action="store_true")
    args, forwarded = parser.parse_known_args()
    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel")).resolve()
    names = []
    for name in args.config:
        raw = json.loads(within(root, name).read_text())
        if "configs" in raw:
            phases = raw["configs"]
            if (raw.get("version") != 1 or "plan" in raw or not isinstance(phases, list)
                    or not phases or not all(isinstance(p, str) and p for p in phases)):
                raise LoopError("Invalid sequence configuration: " + name)
            names.extend(phases)
        else:
            names.append(name)
    if len(names) != len(set(names)):
        raise LoopError("Sequence configurations must be unique")
    if len(names) > 1 and any(arg in {"--from", "--through"} or arg.startswith(("--from=", "--through=")) for arg in forwarded):
        raise LoopError("Task ranges require selecting a single area configuration")
    # Validate every configuration before beginning the first phase.
    configs = [(name, read_config(root, within(root, name))) for name in names]
    count = sum(len(config["tasks"]) for _, config in configs)
    if len(configs) > 1:
        print(f"Ralph sequence: {count} tasks across {len(configs)} plans, in order", flush=True)
    runner = Path(__file__).with_name("ralph.py")
    for name, config in configs:
        progress = read_progress(root, config)["tasks"]
        if args.mode == "run" and all(progress[t["id"]]["status"] == "complete" for t in config["tasks"]):
            print("SKIP completed phase: " + config["plan"], flush=True)
            continue
        command = [sys.executable, str(runner), args.mode, "--config", name]
        if args.resume:
            command.append("--resume")
        if args.allow_plan_updates:
            command.append("--allow-plan-updates")
        command.extend(forwarded)
        result = subprocess.run(command, cwd=root)
        if result.returncode:
            return result.returncode
    if args.mode == "preview" and len(configs) > 1 and len(args.config) == 1:
        print(f"\nStart all {count} tasks: make ralph RALPH_CONFIG=" + shlex.quote(args.config[0]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (LoopError, OSError, ValueError) as error:
        print("Ralph sequence stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
