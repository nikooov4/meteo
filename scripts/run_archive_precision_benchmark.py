"""Run/replay a frozen controlled precision study spanning a prepared archive."""

import argparse
import json
from pathlib import Path

from meteo_bridge.archive_precision import replay_archive_precision, run_archive_precision


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, default=Path("data/scale/synthetic-200gb/manifest.json"))
    p.add_argument("--protocol", type=Path, default=Path("configs/experiments/precision-archive-200gb-v1.json"))
    p.add_argument("--output", type=Path, default=Path("experiments/runs/precision-archive-200gb-v1"))
    p.add_argument("--resume", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--stop-after-shards", type=int)
    p.add_argument("--replay", action="store_true")
    args = p.parse_args()
    if args.replay:
        result = replay_archive_precision(args.output / "run.json", args.output / "replay.json")
    else:
        result = run_archive_precision(args.manifest, args.protocol, args.output, args.resume,
                                       args.dry_run, args.stop_after_shards)
    print(json.dumps(result, ensure_ascii=True))
    if result.get("status") == "failed" or result.get("passed") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
