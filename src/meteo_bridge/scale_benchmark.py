import ctypes
import hashlib
import json
import os
import time
from pathlib import Path

import netCDF4 as nc
import numpy as np
import pyarrow.parquet as pq

from .domain import canonical, digest
from .oracle import solve_lp
from .readers import scale_case, scan_shard
from .resources import (
    MemoryGuard,
    atomic_json,
    run_metadata,
    safe_data_path,
    sha256_file,
    size_bytes,
    timed_io,
)
from .services import solve_query


def allocated_bytes(path):
    if os.name == "nt":
        high = ctypes.c_ulong(0)
        fn = ctypes.windll.kernel32.GetCompressedFileSizeW
        fn.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
        fn.restype = ctypes.c_ulong
        low = fn(str(Path(path).resolve()), ctypes.byref(high))
        return (high.value << 32) + low
    stat = os.stat(path)
    return getattr(stat, "st_blocks", 0) * 512 or None


def verify_scale_dataset(manifest, mode="full"):
    if mode not in {"sample", "full"}:
        raise ValueError("mode must be full or sample")
    mp = Path(manifest)
    data = json.loads(mp.read_text(encoding="utf8"))
    errors, checksums, identities, partitions, total, allocated, logical = [], set(), set(), set(), 0, 0, 0
    for index, entry in enumerate(data["shards"]):
        try:
            path = safe_data_path(mp.parent, entry["path"])
            if not path.is_file() or path.stat().st_size != entry["bytes"]:
                raise ValueError("size mismatch/missing shard")
            identity = (path.stat().st_dev, path.stat().st_ino)
            if entry["sha256"] in checksums or identity in identities:
                raise ValueError("duplicate content/file identity")
            checksums.add(entry["sha256"])
            identities.add(identity)
            if data["origin"] == "synthetic":
                if data["version"] not in (1, 2) or entry["schema"] != data["schema"]:
                    raise ValueError("schema/version mismatch")
                if data["version"] == 2:
                    from .realistic_weather import SCHEMA

                    if data["schema"] != SCHEMA:
                        raise ValueError("unknown v2 schema")
                part = tuple(entry["partition"])
                if part in partitions:
                    raise ValueError("duplicate partition")
                partitions.add(part)
                if path.suffix == ".nc":
                    with nc.Dataset(path) as ds:
                        if ds.schema != data["schema"] or ds.config_hash != data["config_hash"]:
                            raise ValueError("embedded schema/config mismatch")
                        rows = len(ds.dimensions["series"]) * len(ds.dimensions["time"])
                        if rows != entry["rows"] or ds.variables["precipitation"].dtype != np.dtype(
                            "float64"
                        ):
                            raise ValueError("shape/type mismatch")
                        ids = ds.variables["series_id"][:]
                        if not np.array_equal(ids, np.arange(entry["series_start"], entry["series_end"])):
                            raise ValueError("partition series range mismatch")
                        if data["version"] == 2:
                            cfg = data["config"]
                            step = cfg["spacing_degrees"]
                            lat, lon = np.arange(-90+step/2, 90, step), np.arange(-180+step/2, 180, step)
                            if (ds.member != entry["member"] or ds.quantity != "large_scale_precipitation"
                                    or ds.unit != "mm" or ds.cycle_hours != 12 or entry["scheme"] != 0
                                    or entry["series_start"] != entry["member"]*cfg["cells_per_member"]
                                    or entry["hours"] % 12 or entry["first_hour"] % 12
                                    or not np.array_equal(ds.variables["latitude"][:], np.repeat(lat, len(lon)))
                                    or not np.array_equal(ds.variables["longitude"][:], np.tile(lon, len(lat)))):
                                raise ValueError("v2 quantity/member/cycle/coordinates mismatch")
                        expected_t = (
                            data["config"]["start"]
                            + (entry["first_hour"] + np.arange(entry["hours"]) + 1) * 3600
                        )
                        if not np.array_equal(ds.variables["time"][:], expected_t):
                            raise ValueError("partition time range mismatch")
                        scheme = entry["scheme"]
                        if ds.statistic != ["amount", "cumulative", "interval_mean_rate"][scheme]:
                            raise ValueError("statistic convention mismatch")
                        expected_start = (
                            expected_t - 3600
                            if scheme != 1
                            else (expected_t - ((expected_t - data["config"]["start"] - 1) % 86400 + 1))
                        )
                        if not np.array_equal(
                            ds.variables["time_bounds"][:], np.column_stack((expected_start, expected_t))
                        ):
                            raise ValueError("interval/cycle bounds mismatch")
                        if ds.variables["precipitation"].shape != (entry["hours"], len(ids)):
                            raise ValueError("incomplete data arrays")
                else:
                    metadata = pq.read_metadata(path)
                    if (
                        metadata.num_rows != entry["rows"]
                        or metadata.metadata[b"schema"].decode() != data["schema"]
                    ):
                        raise ValueError("parquet shape/schema mismatch")
                if entry["logical_bytes"] != entry["rows"] * 9:
                    raise ValueError("logical byte accounting mismatch")
                if data["config"]["compression"] == "none" and path.suffix == ".nc":
                    if entry["bytes"] > entry["logical_bytes"] * 1.1 + 8 * 2**20:
                        raise ValueError("excess non-payload bytes")
            else:
                with nc.Dataset(path) as ds:
                    from .real_data import inspect_ncar

                    inspect_ncar(ds)
            physical = allocated_bytes(path)
            if physical is not None and physical + 65536 < entry["bytes"]:
                raise ValueError(
                    "sparse/compressed file: physical placement cannot establish claimed payload bytes"
                )
            if mode == "full" or index in {0, len(data["shards"]) - 1}:
                if sha256_file(path) != entry["sha256"]:
                    raise ValueError("checksum mismatch")
            total += entry["bytes"]
            allocated += physical or 0
            logical += entry.get("logical_bytes", 0)
        except (ValueError, OSError, KeyError) as exc:
            errors.append({"path": entry.get("path"), "error": str(exc)})
    if total != data.get("data_bytes"):
        errors.append({"error": "manifest aggregate bytes mismatch"})
    result = {
        "status": "failed" if errors else "full_verified" if mode == "full" else "sample_verified",
        "mode": mode,
        "manifest_sha256": sha256_file(mp),
        "data_bytes": total,
        "data_GB": total / 1e9,
        "data_GiB": total / 2**30,
        "logical_array_bytes": logical,
        "allocated_bytes": allocated,
        "files": len(data["shards"]),
        "errors": errors,
        "placement_note": "allocated bytes measured; filesystem deduplication/sharing not independently audited",
    }
    atomic_json(mp.parent / f"verification-{mode}.json", result)
    return result


def run_scale_benchmark(
    manifest,
    memory_limit="16GiB",
    output="reports/scale",
    sizes="1GB,10GB,50GB,200GB",
    query_count=12,
    resume=False,
    stop_after_shards=None,
):
    invocation_started = time.perf_counter()
    mp, output = Path(manifest), Path(output)
    data = json.loads(mp.read_text(encoding="utf8"))
    limit = min(size_bytes(memory_limit), 16 * 2**30)
    report = {
        "environment": run_metadata(),
        "manifest_sha256": sha256_file(mp),
        "profiles": [],
        "memory_limit": limit,
        "cache_conditions": "first query in process then repeated; OS cache not flushed",
        "disk_type": "not automatically determined; local filesystem",
        "errors": [],
    }
    output.mkdir(parents=True, exist_ok=True)
    # Validate structure first; hash every file immediately before its normalized
    # scan so the second read can reuse bounded OS cache on a slow local disk.
    verification = verify_scale_dataset(mp, "sample")
    verified_hashes = set()
    report["verification"] = verification
    if verification["status"] == "failed":
        report["errors"] = verification["errors"]
        atomic_json(output / "scale_report.json", report)
        return report
    targets = [data["data_bytes"]] if sizes == "smoke" else [size_bytes(s.strip()) for s in sizes.split(",")]
    for target in targets:
        if data["data_bytes"] < target:
            report["profiles"].append(
                {"target_bytes": target, "status": "not_run", "reason": "insufficient prepared data bytes"}
            )
            continue
        subset, actual = [], 0
        for shard in data["shards"]:
            subset.append(shard)
            actual += shard["bytes"]
            if actual >= target:
                break
        name = f"{target}-bytes"
        checkpoint = output / f"{name}-checkpoint.json"
        subset_hash = digest(subset)
        state = {
            "normalization_version": "interval-stream-v1",
            "subset_hash": subset_hash,
            "completed": [],
            "rows": 0,
            "accepted": 0,
            "missing": 0,
            "rejected": 0,
            "normalized_partition_digests": [],
            "resume_count": 0,
            "scan_wall_s": 0.0,
            "checksum_wall_s": 0.0,
            "maximum_accepted_encoded_value": 0.0,
        }
        if checkpoint.exists() and resume:
            state = json.loads(checkpoint.read_text())
            if state["subset_hash"] != subset_hash:
                raise ValueError("scan resume subset changed")
            if state.get("normalization_version") != "interval-stream-v1":
                raise ValueError("scan normalization changed; use a new output/checkpoint directory")
            state["resume_count"] += 1
        io0, t0 = timed_io(), time.perf_counter()
        profile = {
            "target_bytes": target,
            "data_bytes": actual,
            "data_GB": actual / 1e9,
            "data_GiB": actual / 2**30,
            "files": len(subset),
            "status": "running",
            "queries": [],
        }
        profile_started = time.perf_counter()
        try:
            with MemoryGuard(limit) as guard:
                scanned = 0
                for shard in subset:
                    if shard["sha256"] not in verified_hashes:
                        hash_started = time.perf_counter()
                        if sha256_file(safe_data_path(mp.parent, shard["path"])) != shard["sha256"]:
                            raise ValueError("streaming full verification checksum mismatch")
                        state["checksum_wall_s"] = (
                            state.get("checksum_wall_s", 0) + time.perf_counter() - hash_started
                        )
                        verified_hashes.add(shard["sha256"])
                    if shard["sha256"] in state["completed"]:
                        t0 = time.perf_counter()
                        continue
                    digestor = hashlib.sha256()
                    digestor.update(
                        canonical(
                            {
                                k: shard.get(k)
                                for k in (
                                    "partition",
                                    "scheme",
                                    "series_start",
                                    "series_end",
                                    "first_hour",
                                    "hours",
                                    "key",
                                )
                            }
                        ).encode()
                    )
                    for values, qc in scan_shard(
                        safe_data_path(mp.parent, shard["path"]), shard, data.get("config"), guard
                    ):
                        accepted = (qc == 0) & np.isfinite(values)
                        if np.any(values[accepted] < 0):
                            raise ValueError("negative accepted precipitation")
                        if "maximum_accepted_encoded_value" in state:
                            state["maximum_accepted_encoded_value"] = max(
                                state["maximum_accepted_encoded_value"],
                                float(np.max(values, where=accepted, initial=0)),
                            )
                        state["rows"] += values.size
                        state["accepted"] += int(accepted.sum())
                        state["missing"] += int(((qc == 1) | ~np.isfinite(values)).sum())
                        state["rejected"] += int((qc == 2).sum())
                        # Preserve interval semantics; cumulative totals are not summed into hourly rain.
                        digestor.update(np.where(accepted, values, 0).astype("<f8").tobytes())
                        digestor.update(qc.astype("uint8").tobytes())
                    state["completed"].append(shard["sha256"])
                    state["normalized_partition_digests"].append(digestor.hexdigest())
                    state["scan_wall_s"] += time.perf_counter() - t0
                    state["peak_process_tree_rss"] = max(state.get("peak_process_tree_rss", 0), guard.peak)
                    t0 = time.perf_counter()
                    atomic_json(checkpoint, state)
                    scanned += 1
                    if stop_after_shards is not None and scanned >= stop_after_shards:
                        profile["status"] = "interrupted"
                        break
                if len(state["completed"]) == len(subset):
                    expected_rows = sum(s.get("rows", 0) for s in subset)
                    if expected_rows and state["rows"] != expected_rows:
                        raise ValueError("full scan row count disagrees with manifest")
                    for i in range(query_count):
                        shard = subset[(i * max(1, len(subset) // query_count)) % len(subset)]
                        series_id = shard.get("series_start", 0) + i % max(
                            1, shard.get("series_end", 1) - shard.get("series_start", 0)
                        )
                        if data.get("schema") == "meteobridge-weather-bootstrap-v2":
                            cells = data["config"]["cells_per_member"]
                            series_id = shard["series_start"] + (cells//2 + i*104729) % cells
                        hour = shard.get("first_hour", 0) + 1
                        for condition in ("first_process_query_OS_cache_uncontrolled", "repeat"):
                            query_io_before = timed_io()
                            qt = time.perf_counter()
                            case, read_bytes = scale_case(mp, series_id, hour, 6)
                            bundle = solve_query(case)
                            query_latency = time.perf_counter() - qt
                            query_io_after = timed_io()
                            if not bundle.get("checker", {}).get("valid"):
                                raise ValueError(f"scale Query/checker failed: {bundle['result']}")
                            truth_check = None
                            if data["origin"] == "synthetic":
                                from fractions import Fraction

                                from .scale_data import amounts

                                if data["version"] == 2:
                                    from .realistic_weather import WeatherModel

                                    cfg = data["config"]
                                    model = WeatherModel(cfg["calibration_path"], cfg["seed"], cfg["sigma"])
                                    try:
                                        values, _ = model.block(cfg["start"] + hour//12*12*3600,
                                                                series_id//cfg["cells_per_member"])
                                        cell = series_id % cfg["cells_per_member"]
                                        encoded = values.reshape(12, -1)[hour%12:hour%12+6, cell]
                                        true_amount = sum((Fraction(str(float(v))) for v in encoded), Fraction(0))
                                    finally:
                                        model.close()
                                else:
                                    true_amount = Fraction(
                                        int(
                                            amounts(
                                                data["config"]["seed"],
                                                np.array([series_id]),
                                                np.arange(hour, hour + 6),
                                            ).sum()
                                        ),
                                        100,
                                    )
                                bounds = bundle["result"]
                                truth_check = (
                                    (bounds["lower"] is None or Fraction(bounds["lower"]) <= true_amount)
                                    and (bounds["upper"] is None or Fraction(bounds["upper"]) >= true_amount)
                                    and bounds["status"] != "inconsistent_model"
                                )
                                if not truth_check:
                                    raise ValueError("synthetic generating truth outside Query bounds")
                            lp_t0 = time.perf_counter()
                            lp_checked = i < min(4, query_count)
                            if lp_checked:
                                lp = solve_lp(case)
                                for hid, world in bundle["certificate"]["worlds"].items():
                                    if world["feasible"] != lp[hid]["feasible"]:
                                        raise ValueError("scale LP feasibility disagreement")
                                    if world["feasible"]:
                                        from fractions import Fraction

                                        for side in ("lower", "upper"):
                                            a, b = world[side], lp[hid][side]
                                            if (a is None) != (b is None) or (
                                                a is not None and abs(float(Fraction(a)) - b) > 1e-7
                                            ):
                                                raise ValueError("scale LP bound disagreement")
                            profile["queries"].append(
                                {
                                    "case_hash": digest(case),
                                    "logical_bytes_read": read_bytes,
                                    "cache_condition": condition,
                                    "latency_s": query_latency,
                                    "os_io_delta": {
                                        k: v - query_io_before.get(k, 0) for k, v in query_io_after.items()
                                    },
                                    "lp_checked": lp_checked,
                                    "lp_validation_s": time.perf_counter() - lp_t0 if lp_checked else 0,
                                    "generating_truth_in_bounds": truth_check,
                                    "bundle": bundle,
                                }
                            )
                            guard.check()
                    profile["status"] = "complete"
                profile["peak_process_tree_rss"] = max(guard.peak, state.get("peak_process_tree_rss", 0))
                state["peak_process_tree_rss"] = profile["peak_process_tree_rss"]
                atomic_json(checkpoint, state)
            io_after = timed_io()
            profile.update(
                scan=state,
                scan_bytes=actual
                if profile["status"] == "complete"
                else sum(s["bytes"] for s in subset if s["sha256"] in state["completed"]),
                scan_throughput_MB_s=actual / 1e6 / state["scan_wall_s"] if state["scan_wall_s"] else None,
                normalized_digest=digest(state["normalized_partition_digests"]),
                io_before=io0,
                io_after=io_after,
                io_delta={key: value - io0.get(key, 0) for key, value in io_after.items()},
                application_spill_bytes=0,
            )
            lat = [q["latency_s"] for q in profile["queries"]]
            profile["latency_p50_s"] = float(np.percentile(lat, 50)) if lat else None
            profile["latency_p95_s"] = float(np.percentile(lat, 95)) if lat else None
            profile["solver_query_count"] = len(lat)
        except (ValueError, OSError, MemoryError) as exc:
            profile.update(status="failed", error=str(exc))
            report["errors"].append(str(exc))
        report["profiles"].append(profile)
        profile["wall_s_this_invocation"] = time.perf_counter() - profile_started
        if len(verified_hashes) == len(data["shards"]):
            report["verification"] = {
                **verification,
                "status": "full_verified",
                "mode": "full",
                "checksum_method": "all shards SHA256, integrated with streaming scan",
                "files_sha256_checked": len(verified_hashes),
            }
            atomic_json(mp.parent / "verification-full.json", report["verification"])
        else:
            report["verification"]["files_sha256_checked_in_streaming_pass"] = len(verified_hashes)
        atomic_json(output / "scale_report.json", report)
    report["wall_s_this_invocation"] = time.perf_counter() - invocation_started
    atomic_json(output / "scale_report.json", report)
    lines = [
        "# Scale report",
        "",
        f"Manifest SHA256: `{report['manifest_sha256']}`",
        "",
        "No extrapolation. RSS is sampled for the process tree; OS cache is uncontrolled.",
        "",
        "| Target bytes | Actual data bytes | Status | Scan MB/s | Peak RSS |",
        "|---|---|---|---|---|",
    ]
    for p in report["profiles"]:
        lines.append(
            f"| {p['target_bytes']} | {p.get('data_bytes', 0)} | {p['status']} | "
            f"{p.get('scan_throughput_MB_s')} | {p.get('peak_process_tree_rss')} |"
        )
    (output / "scale_report.md").write_text("\n".join(lines) + "\n", encoding="utf8")
    return {
        "report": str(output / "scale_report.json"),
        "profiles": [
            {
                k: p.get(k)
                for k in (
                    "target_bytes",
                    "data_bytes",
                    "status",
                    "scan_throughput_MB_s",
                    "peak_process_tree_rss",
                )
            }
            for p in report["profiles"]
        ],
        "errors": report["errors"],
    }
