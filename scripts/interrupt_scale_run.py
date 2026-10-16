"""Explicit crash/recovery exercise; only a workspace-owned scale generator may be stopped."""

import argparse
import time
from pathlib import Path

import psutil

from meteo_bridge.resources import atomic_json, sha256_file

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", default="reports/scale/crash-exercise.json", type=Path)
    args = parser.parse_args()
    process = psutil.Process(args.pid)
    root = Path(__file__).resolve().parents[1]
    if (
        not Path(process.exe()).resolve().is_relative_to(root)
        or "scripts/generate_scale_dataset.py" not in process.cmdline()
    ):
        raise ValueError("refuse to stop a process outside this workspace's generator")
    children = process.children(recursive=True)
    record = {
        "event": "deliberate worker crash/recovery exercise",
        "unix_time": time.time(),
        "pid": process.pid,
        "worker_pids": [p.pid for p in children],
        "pre_crash_manifest_sha256": sha256_file(args.manifest),
        "observed_tree_rss_not_peak": sum(p.memory_info().rss for p in [process] + children),
        "pre_crash_manifest": args.manifest.read_text(),
        "expected": "failed/interrupted, completed shards reusable",
    }
    atomic_json(args.output, record)
    for child in children:
        child.terminate()
    # The coordinator records the broken pool and preserves completed manifest entries.
    _, alive = psutil.wait_procs([process], timeout=10)
    for parent in alive:
        parent.terminate()
    print("Stopped only the validated generator workers; manifest snapshot preserved.")
