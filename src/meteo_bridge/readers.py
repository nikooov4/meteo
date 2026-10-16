"""Bounded projection readers; the archive never becomes a single working model."""

import csv
import json
from pathlib import Path

import netCDF4 as nc
import numpy as np
import pyarrow.dataset as pads

from .domain import Case, Interpretation, IntervalObservation, Query, SemanticHypothesis, SeriesKey
from .resources import safe_data_path


def inspect_data(path):
    path = Path(path)
    if path.suffix == ".nc":
        with nc.Dataset(path) as ds:
            return {
                "dimensions": {k: len(v) for k, v in ds.dimensions.items()},
                "attributes": {k: str(ds.getncattr(k)) for k in ds.ncattrs()},
                "variables": {
                    k: {
                        "dimensions": v.dimensions,
                        "shape": v.shape,
                        "attributes": {a: str(v.getncattr(a)) for a in v.ncattrs()},
                    }
                    for k, v in ds.variables.items()
                },
            }
    if path.suffix == ".parquet":
        return {"schema": str(pads.dataset(path).schema)}
    with path.open(encoding="utf-8-sig") as f:
        rows = []
        for row in csv.DictReader(f):
            rows.append(row)
            if len(rows) >= 20:
                break
    return {"preview": rows, "limit": 20}


def scale_case(manifest_path, series_id, first_hour, hours=6):
    mp = Path(manifest_path)
    manifest = json.loads(mp.read_text())
    if manifest["origin"] != "synthetic":
        from .real_data import ncar_query_case

        return ncar_query_case(mp, series_id, first_hour, hours)
    config = manifest["config"]
    group = series_id // config["series_per_shard"]
    scheme = group % 3
    if scheme == 1 and first_hour // 24 != (first_hour + hours - 1) // 24:
        raise ValueError("Query spans distinct cumulative cycles; choose one SeriesKey cycle")
    select_start = first_hour // 24 * 24 if scheme == 1 else first_hour
    # Later cumulative totals in this same cycle can bound an earlier missing
    # subinterval. Read the whole bounded cycle, including its future halo.
    select_end = min((first_hour // 24 + 1) * 24, config["hours"]) if scheme == 1 else first_hour + hours
    selected = [
        s
        for s in manifest["shards"]
        if s["series_start"] <= series_id < s["series_end"]
        and s["first_hour"] < select_end
        and s["first_hour"] + s["hours"] > select_start
    ]
    key = SeriesKey(
        location=f"cell:{series_id}",
        spatial_support="synthetic grid cell",
        product="synthetic-precipitation",
        cycle=str(first_hour // 24) if scheme == 1 else None,
    )
    obs, logical_read = [], 0
    for shard in selected:
        path = safe_data_path(mp.parent, shard["path"])
        a, b = (
            max(select_start, shard["first_hour"]),
            min(select_end, shard["first_hour"] + shard["hours"]),
        )
        if path.suffix == ".nc":
            with nc.Dataset(path) as ds:
                ds.set_auto_mask(False)
                v = ds.variables["precipitation"]
                v.set_var_chunk_cache(2 * 2**20, 1009, 0.5)
                idx = series_id - shard["series_start"]
                values = v[a - shard["first_hour"] : b - shard["first_hour"], idx]
                qc = ds.variables["qc"][a - shard["first_hour"] : b - shard["first_hour"], idx]
                rows = zip(range(a, b), values, qc)
                logical_read += len(values) * 9
        else:
            dataset = pads.dataset(path, format="parquet")
            scanner = dataset.scanner(
                columns=["hour", "precipitation", "qc"],
                filter=(pads.field("series_id") == series_id)
                & (pads.field("hour") >= a)
                & (pads.field("hour") < b),
                batch_size=1024,
                use_threads=False,
            )
            records = []
            for batch in scanner.to_batches():
                if len(records) + batch.num_rows > 4096:
                    raise ValueError("Query row budget exceeded")
                records.extend(
                    zip(batch.column(0).to_pylist(), batch.column(1).to_pylist(), batch.column(2).to_pylist())
                )
                logical_read += batch.nbytes
            rows = records
        for hour, value, flag in rows:
            lo = "0" if not np.isfinite(value) else str(round(float(value), 2))
            start, end = config["start"] + int(hour) * 3600, config["start"] + (int(hour) + 1) * 3600
            spec = Interpretation(
                start=start,
                end=end,
                unit="mm/h" if scheme == 2 else "mm",
                statistic=["amount", "cumulative", "interval_mean_rate"][scheme],
                reset_start=config["start"] + (int(hour) // 24) * 86400 if scheme == 1 else None,
            )
            obs.append(
                IntervalObservation(
                    id=f"s{series_id}-h{hour}",
                    series=key,
                    lower=lo,
                    upper=lo,
                    original_value=str(value),
                    original_timestamp=str(end),
                    interval=spec,
                    reset_group=key.cycle,
                    qc="missing" if flag == 1 else "rejected" if flag == 2 else "accepted",
                    evidence_ids=[shard["sha256"]],
                )
            )
            if len(obs) > 4096:
                raise ValueError("bounded working model exceeded")
    q = Query(
        series=key,
        start=config["start"] + first_hour * 3600,
        end=config["start"] + (first_hour + hours) * 3600,
    )
    case = Case(
        id=f"scale-s{series_id}-h{first_hour}",
        observations=obs,
        hypotheses=[SemanticHypothesis(id="documented")],
        query=q,
        h_complete=True,
        completeness_basis="generator v1 schema and deterministic partition plan",
        family_id=f"synthetic-group-{group}",
    )
    return case, logical_read


def scan_shard(path, shard, config, guard):
    """Yield bounded normalized batches, preserving cumulative intervals as intervals."""
    path = Path(path)
    if path.suffix == ".nc":
        with nc.Dataset(path) as ds:
            ds.set_auto_mask(False)
            if "precipitation" not in ds.variables:
                from .real_data import scan_ncar

                yield from scan_ncar(ds, guard)
                return
            value = ds.variables["precipitation"]
            value.set_var_chunk_cache(4 * 2**20, 1009, 0.5)
            ds.variables["qc"].set_var_chunk_cache(2 * 2**20, 1009, 0.5)
            step = max(1, 32 * 2**20 // max(1, value.shape[1] * 16))
            for offset in range(0, value.shape[0], step):
                values = np.asarray(value[offset : offset + step], dtype="float64")
                flags = np.asarray(ds.variables["qc"][offset : offset + step])
                guard.check()
                yield values, flags
    else:
        scanner = pads.dataset(path, format="parquet").scanner(
            columns=["precipitation", "qc", "series_id", "hour"], batch_size=262144, use_threads=False
        )
        offset = 0
        for batch in scanner.to_batches():
            count = shard["series_end"] - shard["series_start"]
            ordinals = np.arange(offset, offset + batch.num_rows, dtype="int64")
            if not np.array_equal(batch.column(2).to_numpy(), shard["series_start"] + ordinals % count):
                raise ValueError("Parquet series partition/order mismatch")
            if not np.array_equal(batch.column(3).to_numpy(), shard["first_hour"] + ordinals // count):
                raise ValueError("Parquet time partition/order mismatch")
            offset += batch.num_rows
            values = batch.column(0).to_numpy(zero_copy_only=False)
            flags = batch.column(1).to_numpy(zero_copy_only=False)
            guard.check()
            yield values, flags
