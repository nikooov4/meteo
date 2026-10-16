"""Bounded, deterministic synthetic observations. Each series has one representation."""

from __future__ import annotations

import json
import math
import os
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import netCDF4 as nc
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .domain import digest, utc_seconds
from .resources import MemoryGuard, atomic_json, run_metadata, sha256_file, size_bytes

SCHEMA = "meteobridge-synthetic-v1"


def _hash(x):
    with np.errstate(over="ignore"):
        x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        return x ^ (x >> np.uint64(31))


def amounts(seed, ids, hours):
    """Integer hundredths, correlated six-hour storm regimes, no random padding."""
    s = ids.astype("uint64")[None, :]
    t = hours.astype("uint64")[:, None]
    with np.errstate(over="ignore"):
        weather = _hash(s * np.uint64(104729) + (t // 6) * np.uint64(15485863) + np.uint64(seed))
        intensity = _hash(s * np.uint64(32452843) + t * np.uint64(49979687) + np.uint64(seed + 17))
    wet = (weather % 100) > 65
    uniform = ((intensity >> 11).astype("float64") + 1) / float(2**53 + 1)
    return np.rint(np.where(wet, -np.log(uniform) * (1 + (weather % 7)) * 45, 0)).astype("int32")


def generated_chunk(config, group, first_hour, count):
    a = group * config["series_per_shard"]
    b = min(config["series"], a + config["series_per_shard"])
    ids = np.arange(a, b, dtype="int64")
    # Halo starts at the real daily cycle, never at a file/chunk boundary.
    scheme = group % 3
    cycle_hour = first_hour // 24 * 24 if scheme == 1 else first_hour
    hours = np.arange(cycle_hour, first_hour + count, dtype="int64")
    truth = amounts(config["seed"], ids, hours)
    if scheme == 1:
        totals = np.empty_like(truth)
        for i, hour in enumerate(hours):
            totals[i] = truth[i] if hour % 24 == 0 else totals[i - 1] + truth[i]
        values = totals[first_hour - cycle_hour :].astype("float64") / 100
    else:
        values = truth[first_hour - cycle_hour :].astype("float64") / 100
    hs = np.arange(first_hour, first_hour + count, dtype="int64")
    with np.errstate(over="ignore"):
        flags = _hash(
            ids.astype("uint64")[None, :]
            + hs.astype("uint64")[:, None] * np.uint64(67867967)
            + np.uint64(config["seed"] + 31)
        )
    qc = np.zeros(values.shape, dtype="uint8")
    qc[(flags % 1000000) < int(config["missing_fraction"] * 1000000)] = 1
    qc[(flags // 1000000 % 1000000) < int(config["defect_fraction"] * 1000000)] = 2
    values[qc == 1] = np.nan
    values[qc == 2] = -1  # explicit controlled rejected defect; label kept in QC
    return ids, hs, values, qc


def _shard_entry(path, config, group, first_hour, count, rows):
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "rows": rows,
        "logical_bytes": rows * 9,
        "series_start": group * config["series_per_shard"],
        "series_end": min(config["series"], (group + 1) * config["series_per_shard"]),
        "first_hour": first_hour,
        "hours": count,
        "scheme": group % 3,
        "partition": [group, first_hour],
        "origin": "synthetic",
        "schema": SCHEMA,
    }


def _write_shard(task):
    config, output, ordinal = task
    groups = math.ceil(config["series"] / config["series_per_shard"])
    group, first_hour = ordinal % groups, ordinal // groups * config["hours_per_shard"]
    count = min(config["hours_per_shard"], config["hours"] - first_hour)
    if count <= 0:
        raise ValueError("unique series/time capacity exhausted before target bytes; extend range or series")
    path = Path(output) / f"part-{ordinal:06d}.{'nc' if config['format'] == 'netcdf' else 'parquet'}"
    config_hash = digest({k: v for k, v in config.items() if k != "worker_memory"})
    nseries = min(config["series_per_shard"], config["series"] - group * config["series_per_shard"])
    if path.exists():
        # Adopt an atomically finished orphan after a coordinator interruption.
        if config["format"] == "netcdf":
            with nc.Dataset(path) as ds:
                if ds.config_hash != config_hash or ds.ordinal != ordinal:
                    raise ValueError("existing shard configuration mismatch")
        else:
            md = pq.read_metadata(path).metadata
            if md[b"config_hash"].decode() != config_hash:
                raise ValueError("existing parquet configuration mismatch")
        return _shard_entry(path, config, group, first_hour, count, count * nseries)
    partial = path.with_suffix(path.suffix + ".partial")
    # Only this exact shard's unfinished file is replaced; completed files are immutable.
    partial.unlink(missing_ok=True)
    step = max(1, min(24, config["chunk_bytes"] // max(1, nseries * 16)))
    with MemoryGuard(config["worker_memory"]) as guard:
        if config["format"] == "netcdf":
            with nc.Dataset(partial, "w", format="NETCDF4") as ds:
                ds.set_fill_off()
                ds.setncatts(
                    {
                        "schema": SCHEMA,
                        "config_hash": config_hash,
                        "ordinal": ordinal,
                        "origin": "synthetic",
                        "seed": config["seed"],
                        "group": group,
                        "statistic": ["amount", "cumulative", "interval_mean_rate"][group % 3],
                        "unit": "mm/h" if group % 3 == 2 else "mm",
                        "cycle_hours": 24,
                        "start_utc": config["start"],
                        "time_label": "end",
                        "Conventions": "CF-1.12",
                        "product": "synthetic-precipitation",
                    }
                )
                ds.createDimension("time", count)
                ds.createDimension("series", nseries)
                ds.createDimension("bounds", 2)
                tvar = ds.createVariable("time", "i8", ("time",))
                tvar.units = "seconds since 1970-01-01 00:00:00"
                tvar.calendar = "proleptic_gregorian"
                tvar.bounds = "time_bounds"
                ts = config["start"] + (np.arange(first_hour, first_hour + count) + 1) * 3600
                tvar[:] = ts
                tb = ds.createVariable("time_bounds", "i8", ("time", "bounds"))
                starts = ts - 3600 if group % 3 != 1 else ts - ((ts - config["start"] - 1) % 86400 + 1)
                tb[:] = np.column_stack((starts, ts))
                ids = np.arange(
                    group * config["series_per_shard"], group * config["series_per_shard"] + nseries
                )
                ds.createVariable("series_id", "i8", ("series",))[:] = ids
                ds.createVariable("latitude", "f8", ("series",))[:] = -60 + (ids // 4000) * 0.1
                ds.createVariable("longitude", "f8", ("series",))[:] = -180 + (ids % 4000) * 0.09
                kwargs = {"compression": "zlib", "complevel": 1} if config["compression"] == "zlib" else {}
                value = ds.createVariable(
                    "precipitation",
                    "f8",
                    ("time", "series"),
                    chunksizes=(min(24, count), min(4096, nseries)),
                    **kwargs,
                )
                value.units, value.cell_methods = ds.unit, "time: mean" if group % 3 == 2 else "time: sum"
                value.standard_name = (
                    "lwe_precipitation_rate" if group % 3 == 2 else "lwe_thickness_of_precipitation_amount"
                )
                qcvar = ds.createVariable("qc", "u1", ("time", "series"), **kwargs)
                value.set_var_chunk_cache(16 * 2**20, 1009, 0.5)
                qcvar.set_var_chunk_cache(2 * 2**20, 1009, 0.5)
                for offset in range(0, count, step):
                    _, _, vals, flags = generated_chunk(
                        config, group, first_hour + offset, min(step, count - offset)
                    )
                    value[offset : offset + len(vals)] = vals
                    qcvar[offset : offset + len(vals)] = flags
                    guard.check()
        else:
            writer = None
            try:
                for offset in range(0, count, step):
                    ids, hs, vals, flags = generated_chunk(
                        config, group, first_hour + offset, min(step, count - offset)
                    )
                    table = pa.table(
                        {
                            "series_id": np.tile(ids, len(hs)),
                            "hour": np.repeat(hs, len(ids)),
                            "precipitation": vals.ravel(),
                            "qc": flags.ravel(),
                        }
                    )
                    table = table.replace_schema_metadata(
                        {"schema": SCHEMA, "config_hash": config_hash, "scheme": str(group % 3)}
                    )
                    if writer is None:
                        writer = pq.ParquetWriter(
                            partial,
                            table.schema,
                            compression=None if config["compression"] == "none" else "zstd",
                        )
                    writer.write_table(table, row_group_size=min(table.num_rows, 262144))
                    guard.check()
            finally:
                if writer is not None:
                    writer.close()
    os.replace(partial, path)
    return _shard_entry(path, config, group, first_hour, count, count * nseries)


def generate_scale(
    target_size="32MB",
    output="data/scale/smoke",
    seed=42,
    format="netcdf",
    compression="none",
    chunk_size="64MiB",
    shard_size="512MiB",
    series=4000000,
    series_per_shard=65536,
    regions=1,
    start="2023-01-01T00:00:00Z",
    end="2024-01-01T00:00:00Z",
    time_step=3600,
    missing_fraction=0.01,
    defect_fraction=0.001,
    workers=1,
    memory_limit="2GiB",
    disk_budget=None,
    resume=False,
    dry_run=False,
    max_shards=None,
):
    target, memory = size_bytes(target_size), min(size_bytes(memory_limit), 2**31)
    chunk, shard = size_bytes(chunk_size), size_bytes(shard_size)
    if target <= 0 or chunk <= 0 or shard < 1024:
        raise ValueError("positive sizes required")
    if workers < 1 or workers > 4 or series < 1 or series > 5200000 or regions < 1:
        raise ValueError("workers 1..4, series 1..5200000, positive regions")
    if time_step != 3600:
        raise ValueError("synthetic v1 supports hourly step only")
    if not 0 <= missing_fraction < 1 or not 0 <= defect_fraction < 1:
        raise ValueError("invalid fractions")
    if format not in {"netcdf", "parquet"} or compression not in (
        {"none", "zlib"} if format == "netcdf" else {"none", "zstd"}
    ):
        raise ValueError("unsupported format/compression combination")
    if workers * (256 * 2**20 + chunk * 5) + 256 * 2**20 > memory:
        raise ValueError("worker/chunk memory estimate exceeds total budget; reduce workers/chunk")
    ns = min(series_per_shard, series, max(1, shard // (9 * 24)))
    hours_per_shard = max(1, min(720, shard // (9 * ns)))
    if hours_per_shard >= 24:
        hours_per_shard = hours_per_shard // 24 * 24
    hours = (utc_seconds(end) - utc_seconds(start)) // 3600
    if hours < 1 or not 0 <= seed < 2**31:
        raise ValueError("invalid date range or seed")
    config = {
        "schema": SCHEMA,
        "seed": seed,
        "format": format,
        "compression": compression,
        "series": series,
        "regions": regions,
        "series_per_shard": ns,
        "hours_per_shard": hours_per_shard,
        "start": utc_seconds(start),
        "hours": hours,
        "chunk_bytes": chunk,
        "missing_fraction": missing_fraction,
        "defect_fraction": defect_fraction,
    }
    # Workers and budgets are execution settings, deliberately absent from content config/hash.
    worker_config = {**config, "worker_memory": (memory - 128 * 2**20) // workers}
    root = Path(output).resolve()
    ancestor = root
    while not ancestor.exists():
        ancestor = ancestor.parent
    free = shutil.disk_usage(ancestor).free
    estimated_shard = ns * hours_per_shard * (9 if format == "netcdf" else 25) + ns * 24 + 2**20
    planned = {
        "target_bytes": target,
        "target_GB": target / 1e9,
        "target_GiB": target / 2**30,
        "estimated_rows": math.ceil(target / (9 if format == "netcdf" else 25)),
        "estimated_files": math.ceil(target / estimated_shard),
        "maximum_shard_estimate": estimated_shard,
        "required_free_initial_bytes": math.ceil(target * 1.2) + estimated_shard,
        "disk_free_bytes": free,
        "memory_limit": memory,
        "workers": workers,
        "config": config,
        "status": "dry_run",
    }
    if dry_run:
        planned["resource_check"] = free >= planned["required_free_initial_bytes"]
        return planned
    root.mkdir(parents=True, exist_ok=True)
    mp = root / "manifest.json"
    if mp.exists() and not resume:
        raise ValueError("manifest exists: use --resume")
    manifest = (
        json.loads(mp.read_text())
        if mp.exists()
        else {
            "version": 1,
            "schema": SCHEMA,
            "origin": "synthetic",
            "config": config,
            "config_hash": digest(config),
            "target_bytes": target,
            "shards": [],
            "status": "generating",
            "resume_count": 0,
        }
    )
    if manifest["config"] != config or manifest["target_bytes"] != target:
        raise ValueError("resume config/target mismatch")
    if resume:
        manifest["resume_count"] += 1
    for entry in manifest["shards"]:
        from .resources import safe_data_path

        path = safe_data_path(root, entry["path"])
        if not path.exists() or path.stat().st_size != entry["bytes"] or sha256_file(path) != entry["sha256"]:
            raise ValueError("resume checksum mismatch")
    done = sum(s["bytes"] for s in manifest["shards"])
    if free < (target - done) * 1.2 + estimated_shard:
        raise OSError("insufficient disk for remaining data + 20% reserve + one temporary shard")
    if disk_budget and target + estimated_shard > size_bytes(disk_budget):
        raise OSError("disk budget below target + temporary shard")
    run_info = run_metadata()
    t0, written, completed = time.perf_counter(), 0, 0
    pending, ordinal = {}, len(manifest["shards"])
    try:
        with MemoryGuard(memory) as guard, ProcessPoolExecutor(max_workers=workers) as pool:
            while done < target:
                guard.check()
                if shutil.disk_usage(root).free < target * 0.2 + estimated_shard:
                    raise OSError("free disk reserve exhausted")
                # Do not oversubmit beyond target; final excess at most one shard.
                if not pending:
                    n = min(workers, max(1, int((target - done) // (shard * 1.1 + 8 * 2**20))))
                    for _ in range(n):
                        pending[ordinal] = pool.submit(_write_shard, (worker_config, str(root), ordinal))
                        ordinal += 1
                first = min(pending)
                entry = pending.pop(first).result()
                if entry["bytes"] > size_bytes(shard_size) * 1.1 + 8 * 2**20:
                    raise ValueError("shard exceeded storage budget")
                manifest["shards"].append(entry)
                done += entry["bytes"]
                written += entry["bytes"]
                completed += 1
                manifest.update(data_bytes=done, status="generating")
                atomic_json(mp, manifest)
                print(
                    json.dumps({"shards": len(manifest["shards"]), "data_GB": round(done / 1e9, 3)}),
                    flush=True,
                )
                if max_shards is not None and completed >= max_shards and done < target:
                    manifest["status"] = "interrupted"
                    break
            # Already submitted files are complete and must be accounted, not left as hidden duplicates.
            for first in sorted(pending):
                entry = pending[first].result()
                manifest["shards"].append(entry)
                done += entry["bytes"]
                written += entry["bytes"]
            manifest["data_bytes"] = done
            if done >= target:
                manifest["status"] = "complete"
            manifest["generation_run"] = {
                **run_info,
                "wall_s": time.perf_counter() - t0,
                "written_bytes_this_run": written,
                "peak_process_tree_rss": guard.peak,
                "workers": workers,
                "memory_limit": memory,
            }
            manifest.setdefault("generation_runs", []).append(manifest["generation_run"])
    except BaseException as exc:
        manifest.update(
            status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed", error=str(exc)
        )
        atomic_json(mp, manifest)
        raise
    if manifest["status"] == "complete":
        manifest["truth_labels"] = write_truth_labels(manifest, root)
    atomic_json(mp, manifest)
    return {
        "status": manifest["status"],
        "manifest": str(mp),
        "data_bytes": done,
        "generation_run": manifest.get("generation_run"),
    }


def write_truth_labels(manifest, root):
    from fractions import Fraction

    config, cases = manifest["config"], []
    seen = set()
    for shard in manifest["shards"]:
        if shard["scheme"] in seen:
            continue
        seen.add(shard["scheme"])
        ids = np.arange(shard["series_start"], min(shard["series_start"] + 3, shard["series_end"]))
        hour = shard["first_hour"] + 1
        truth = amounts(config["seed"], ids, np.arange(hour, hour + 6))
        for i, series_id in enumerate(ids):
            cases.append(
                {
                    "series_id": int(series_id),
                    "first_hour": hour,
                    "hours": 6,
                    "true_amount_mm": str(Fraction(int(truth[:, i].sum()), 100)),
                    "statistic": ["amount", "cumulative", "interval_mean_rate"][shard["scheme"]],
                    "family_id": f"synthetic-group-{series_id // config['series_per_shard']}",
                }
            )
    path = Path(root) / "truth-labels.json"
    atomic_json(
        path,
        {
            "role": "evaluation_only_not_available_to_policies",
            "config_hash": manifest["config_hash"],
            "seed": config["seed"],
            "recipe": "amounts(seed, stable series ids, hours), integer hundredths",
            "cases": cases,
        },
    )
    return {"path": path.name, "sha256": sha256_file(path), "role": "evaluation_only"}
