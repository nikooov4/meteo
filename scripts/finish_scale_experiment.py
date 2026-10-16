"""Run or finalize the scale protocol without repeating a completed scan."""

import argparse
import json
import time
from pathlib import Path

import psutil

from meteo_bridge.resources import atomic_json, run_metadata, safe_data_path, sha256_file
from meteo_bridge.scale_benchmark import run_scale_benchmark
from meteo_bridge.scale_data import write_truth_labels


def storage_accounting(manifest, root):
    """Header-only logical array accounting; never read all precipitation values."""
    import netCDF4 as nc
    import numpy as np

    data_paths = set()
    physical = 0
    logical_all_arrays = 0
    supported = True
    for shard in manifest["shards"]:
        path = safe_data_path(root, shard["path"])
        data_paths.add(path.resolve())
        physical += path.stat().st_size
        if path.suffix == ".nc":
            with nc.Dataset(path) as ds:
                for variable in ds.variables.values():
                    if np.dtype(variable.dtype).hasobject:
                        supported = False
                    else:
                        logical_all_arrays += variable.size * np.dtype(variable.dtype).itemsize
        else:
            supported = False
    auxiliary, temporary = [], []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.resolve() in data_paths:
            continue
        entry = {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size}
        (temporary if path.name.endswith(".partial") else auxiliary).append(entry)
    return {
        "actual_data_file_bytes": physical,
        "data_GB": physical / 1e9,
        "data_GiB": physical / 2**30,
        "logical_precipitation_QC_bytes": sum(s["logical_bytes"] for s in manifest["shards"]),
        "logical_all_netcdf_arrays_bytes": logical_all_arrays if supported else None,
        "logical_note": "NetCDF numeric array shapes times dtype sizes, including coordinates; "
        "precipitation+QC reported separately. Not a second serialized archive.",
        "auxiliary_files": auxiliary,
        "auxiliary_bytes_at_finalization": sum(p["bytes"] for p in auxiliary),
        "temporary_files": temporary,
        "temporary_bytes_at_finalization": sum(p["bytes"] for p in temporary),
        "temporary_peak_bytes": None,
        "temporary_note": "Final directory snapshot only; a historical disk-space peak was not measured.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--generator-pid", type=int)
    parser.add_argument("--output", type=Path, default=Path("reports/scale"))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--acceptance-only", action="store_true", help="inspect the saved report; no data scan")
    parser.add_argument("--previous-report", type=Path, help="preserved report from an interrupted invocation")
    args = parser.parse_args()
    announced = 0
    monitor_errors = []
    while True:
        try:
            manifest = json.loads(args.manifest.read_text(encoding="utf8"))
        except (PermissionError, json.JSONDecodeError) as exc:
            monitor_errors.append({"unix_time": time.time(), "error": str(exc)})
            if args.generator_pid is None or not psutil.pid_exists(args.generator_pid):
                raise
            time.sleep(0.25)
            continue
        if manifest["status"] == "complete":
            break
        if args.acceptance_only:
            raise RuntimeError("acceptance requires a completed manifest")
        if args.generator_pid is None or not psutil.pid_exists(args.generator_pid):
            raise RuntimeError(f"generation ended with {manifest['status']}; scale acceptance not_run")
        if time.monotonic() - announced >= 60:
            print(json.dumps({"phase": "await_generation", "data_bytes": manifest["data_bytes"]}), flush=True)
            announced = time.monotonic()
        time.sleep(5)
    result = {"status": "existing_report_only"}
    if not args.acceptance_only:
        manifest["truth_labels"] = write_truth_labels(manifest, args.manifest.parent)
        atomic_json(args.manifest, manifest)
        print("Generation complete; start integrated full verification/scan/Queries", flush=True)
        result = run_scale_benchmark(
            args.manifest, output=args.output, memory_limit="16GiB", query_count=12, resume=args.resume
        )
    report_path = args.output / "scale_report.json"
    report = json.loads(report_path.read_text())
    if report["manifest_sha256"] != sha256_file(args.manifest):
        raise ValueError("report and manifest hashes disagree; acceptance cannot use another input")
    report["storage_accounting"] = storage_accounting(manifest, args.manifest.parent)
    for key, filename in (
        ("disk_hardware", "reports/disk-hardware.json"),
        ("cpu_hardware", "reports/cpu-hardware.json"),
    ):
        if Path(filename).exists():
            report[key] = json.loads(Path(filename).read_text(encoding="utf-8-sig"))
    if "disk_hardware" in report:
        report["disk_type"] = "see disk_hardware; measured locally"
    report["generation_run"] = manifest["generation_run"]
    report["generation_resume_count"] = manifest["resume_count"]
    report["monitor_transient_errors"] = monitor_errors
    report["generation_crash_exercise"] = "reports/scale/crash-exercise.json"
    report["finalization_environment"] = run_metadata()
    report["generation_measurement_limit"] = (
        "Successful final generation invocation has sampled process-tree peak RSS. "
        "The deliberately killed invocation has only a point RSS observation, not a saved peak; "
        "no complete peak or total wall-time measurement across that crash is claimed."
    )
    if args.previous_report:
        previous = json.loads(args.previous_report.read_text())
        if previous["manifest_sha256"] != report["manifest_sha256"]:
            raise ValueError("previous report is for another manifest")
        report["resumed_from"] = {
            "path": str(args.previous_report),
            "sha256": sha256_file(args.previous_report),
            "environment": previous["environment"],
            "note": "Per-shard normalization checkpoints reused; input SHA256 rechecked after pause. "
            "Scan times are accumulated completed-shard times across invocations; "
            "current invocation wall time also includes revalidation of completed shards.",
        }
        report["concurrency_conditions"] = (
            "During the resumed scan, small local regression/AppTest validation, header-only accounting "
            "and an NCAR LIST/HEAD metadata dry-run ran independently. No isolated-idle-host timing "
            "or controlled OS-cache claim. The benchmark RSS covers its own process tree."
        )
    largest = next((p for p in report["profiles"] if p["target_bytes"] == 200000000000), {})
    generation_runs = manifest.get("generation_runs", [manifest["generation_run"]])
    criteria = {
        "actual_data_bytes_at_least_200GB": manifest["data_bytes"] >= 200000000000,
        "actual_file_bytes_match_manifest": report["storage_accounting"]["actual_data_file_bytes"]
        == manifest["data_bytes"],
        "full_byte_verification": report["verification"]["status"] == "full_verified",
        "complete_full_scan": largest.get("status") == "complete"
        and largest.get("scan_bytes") == manifest["data_bytes"],
        "query_batch_checked": len(largest.get("queries", [])) >= 24
        and all(q["bundle"]["checker"]["valid"] for q in largest.get("queries", [])),
        "LP_samples_checked": sum(q["lp_checked"] for q in largest.get("queries", [])) >= 4,
        "all_size_profiles_completed": all(
            any(p["target_bytes"] == size and p["status"] == "complete" for p in report["profiles"])
            for size in (1000000000, 10000000000, 50000000000, 200000000000)
        ),
        "benchmark_RAM_within_16GiB": bool(report["profiles"])
        and all(p.get("peak_process_tree_rss", 2**64) <= 16 * 2**30 for p in report["profiles"]),
        "recorded_generator_runs_RAM_within_2GiB": bool(generation_runs)
        and all(r.get("peak_process_tree_rss", 2**64) <= 2**31 for r in generation_runs),
        "generation_resume_exercised": manifest.get("resume_count", 0) >= 2,
        "scan_resume_exercised": largest.get("scan", {}).get("resume_count", 0) >= 1,
        "no_duplicate_completed_shards": len(largest.get("scan", {}).get("completed", []))
        == len(set(largest.get("scan", {}).get("completed", [])))
        == len(manifest["shards"]),
        "no_unexpected_benchmark_errors": not report["errors"],
    }
    report["acceptance"] = {
        "status": "passed" if all(criteria.values()) else "failed",
        "criteria": criteria,
        "scope": "synthetic scale only; sampled RSS, interrupted generator peak unavailable; "
        "OS cache uncontrolled; no real-200GB claim",
    }
    atomic_json(report_path, report)
    atomic_json(
        args.output / "acceptance.json", {**report["acceptance"], "report_sha256": sha256_file(report_path)}
    )
    with (args.output / "scale_report.md").open("a", encoding="utf8") as f:
        f.write("\nSynthetic acceptance: **" + report["acceptance"]["status"] + "**.\n")
        f.write("\nHardware metadata and finalization/source lineage are in scale_report.json.\n")
        f.write("Generation resume was checked after an intentional worker crash. Real-200GB: not_run.\n")
        f.write("The killed generator invocation has no saved peak RSS; final successful invocation does.\n")
    print(json.dumps({"benchmark": result, "acceptance": report["acceptance"]}, indent=2), flush=True)
    if not all(criteria.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
