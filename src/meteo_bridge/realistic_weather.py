"""Monthly whole-cycle bootstrap surrogates, not a numerical weather forecast.

Real storm motion is retained within each 12 h block. Only training blocks enter
generation. A smooth, mean-one lognormal multiplier changes intensities; it does
not invent a new storm catalogue or justify continuity across block boundaries.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import netCDF4 as nc
import numpy as np
from scipy.ndimage import gaussian_filter

from .domain import digest
from .resources import MemoryGuard, atomic_json, run_metadata, safe_data_path, sha256_file, size_bytes

SCHEMA = "meteobridge-weather-bootstrap-v2"
CALIBRATION = "meteobridge-lsp-monthly-blocks-v1"
QUANTUM = 0.0001  # mm; the exact solver treats the encoded amount as the observation
BUCKET = "https://nsf-ncar-era5.s3.us-west-2.amazonaws.com"


def reference_url(year, month):
    return (f"{BUCKET}/e5.oper.fc.sfc.accumu/{year}{month:02d}/"
            f"e5.oper.fc.sfc.accumu.128_142_lsp.ll025sc.{year}{month:02d}0106_"
            f"{year}{month:02d}1606.nc")


def download_references(output, year=2023, months=range(1, 13)):
    """Public, bounded streaming downloads. Completed files are verified on reuse."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    mp = output / "sources.json"
    catalog = json.loads(mp.read_text(encoding="utf8")) if mp.exists() else {"sources": []}
    known = {s["url"]: s for s in catalog["sources"]}
    with httpx.Client(timeout=httpx.Timeout(120, connect=30), follow_redirects=True) as client:
        for month in months:
            url = reference_url(year, month)
            path = output / url.rsplit("/", 1)[1]
            if url in known and path.exists() and sha256_file(path) == known[url]["sha256"]:
                continue
            # The already available January source can be supplied to calibrate
            # directly; downloads never overwrite a different finished file.
            if path.exists() and url not in known:
                raise ValueError(f"unregistered existing reference: {path}")
            partial = path.with_suffix(".nc.partial")
            head = client.head(url)
            head.raise_for_status()
            length, etag = int(head.headers["Content-Length"]), head.headers["ETag"]
            checkpoint = path.with_suffix(".download.json")
            pin = {"url": url, "etag": etag, "bytes": length}
            if checkpoint.exists() and json.loads(checkpoint.read_text(encoding="utf8")) != pin:
                raise ValueError("remote reference changed during resume")
            offset = partial.stat().st_size if partial.exists() and checkpoint.exists() else 0
            if offset > length or shutil.disk_usage(output).free < length-offset + 2*2**30:
                raise OSError("invalid partial size or insufficient disk reserve")
            atomic_json(checkpoint, pin)
            # Short pinned ranges survive network/proxy connection lifetimes.
            # Append only a COMPLETE range: a failed request changes no prefix.
            with partial.open("ab" if offset else "wb") as stream:
                while offset < length:
                    end = min(length, offset + 4*2**20) - 1
                    for attempt in range(5):
                        try:
                            response = client.get(url, headers={"Range": f"bytes={offset}-{end}", "If-Match": etag})
                            response.raise_for_status()
                            if (response.status_code != 206 or len(response.content) != end-offset+1
                                    or response.headers.get("Content-Range") != f"bytes {offset}-{end}/{length}"):
                                raise OSError("invalid ranged response")
                            break
                        except (httpx.HTTPError, OSError) as exc:
                            event = {"download_retry": attempt+1, "month": month, "offset": offset,
                                     "error": str(exc), "unix_time": time.time()}
                            catalog.setdefault("events", []).append(event)
                            atomic_json(mp, catalog)
                            print(json.dumps(event), flush=True)
                            if attempt == 4:
                                raise
                            time.sleep(min(attempt+1, 3))
                    stream.write(response.content)
                    stream.flush()
                    offset = end+1
            # Validate conventions before adopting the source.
            with nc.Dataset(partial) as ds:
                _check_source(ds)
            os.replace(partial, path)
            known[url] = {"path": path.name, "url": url, "bytes": path.stat().st_size,
                          "sha256": sha256_file(path), "origin": "original"}
            catalog["sources"] = list(known.values())
            atomic_json(mp, catalog)
            print(json.dumps({"downloaded_month": month, "bytes": path.stat().st_size}), flush=True)
    return [output / s["path"] for s in catalog["sources"]]


def _check_source(ds):
    v = ds.variables["LSP"]
    if (v.dimensions != ("forecast_initial_time", "forecast_hour", "latitude", "longitude")
            or getattr(v, "units", None) != "m" or getattr(v, "rda_dataset", None) != "ds633.0"
            or not np.array_equal(ds.variables["forecast_hour"][:], np.arange(1, 13))):
        raise ValueError("expected documented NSF NCAR ERA5 LSP previous-hour amounts, leads 1..12")
    return v


def calibrate(paths, output, spacing=1.0, split_day=11, memory_limit="2GiB"):
    """Fixed geographical subsampling; entire cycles, days 1..10 train, 11..15 test.

    No spatial averaging or temporal disaggregation. Two separate NetCDF banks
    physically separate the training and held-out fields. Same source-year test
    data are a development holdout, not an independent climate validation.
    """
    if spacing < 1 or 180 / spacing != int(180 / spacing) or not 2 <= split_day <= 15:
        raise ValueError("spacing must divide 180 and be >=1 degree; split_day 2..15")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if any((output / name).exists() for name in ("manifest.json", "train.nc", "holdout.nc")):
        raise ValueError("calibration output already exists; use a new version directory")
    lat = np.arange(-90 + spacing / 2, 90, spacing)
    lon = np.arange(-180 + spacing / 2, 180, spacing)
    sources, months, counts = [], set(), {"train": 0, "holdout": 0}
    seen_cycles = set()
    started = time.perf_counter()
    banks = {}
    with MemoryGuard(min(size_bytes(memory_limit), 2 * 2**30)) as guard:
        try:
            for split in counts:
                ds = nc.Dataset(output / f"{split}.nc.partial", "w")
                banks[split] = ds
                for name, length in (("block", None), ("hour", 12), ("latitude", len(lat)),
                                     ("longitude", len(lon))):
                    ds.createDimension(name, length)
                ds.createVariable("latitude", "f4", ("latitude",))[:] = lat
                ds.createVariable("longitude", "f4", ("longitude",))[:] = lon
                ds.createVariable("initialization", "i8", ("block",))
                ds.createVariable("month", "i2", ("block",))
                v = ds.createVariable("lsp_mm", "f4", ("block", "hour", "latitude", "longitude"),
                                      compression="zlib", complevel=1, chunksizes=(1, 1, len(lat), len(lon)))
                v.units = "mm"
                v.set_var_chunk_cache(8 * 2**20, 1009, .5)
                ds.setncatts({"schema": CALIBRATION, "split": split,
                              "semantics": "previous_hour_amount", "quantity": "large_scale_precipitation"})
            for path in map(Path, paths):
                source = {"path": str(path.resolve()), "bytes": path.stat().st_size,
                          "sha256": sha256_file(path), "url": f"{BUCKET}/e5.oper.fc.sfc.accumu/"
                          f"{path.name.split('.')[-2][:6]}/{path.name}"}
                with nc.Dataset(path) as ds:
                    v = _check_source(ds)
                    v.set_var_chunk_cache(64 * 2**20, 1009, .5)
                    slat = np.asarray(ds.variables["latitude"][:])
                    slon = (np.asarray(ds.variables["longitude"][:]) + 180) % 360 - 180
                    yi = np.argmin(abs(slat[:, None] - lat), axis=0)
                    xi = np.argmin(abs(slon[:, None] - lon), axis=0)
                    if max(abs(slat[yi] - lat)) > .126 or max(abs(slon[xi] - lon)) > .126:
                        raise ValueError("reference grid cannot support requested sampling centres")
                    tv = ds.variables["forecast_initial_time"]
                    times = nc.num2date(tv[:], tv.units, getattr(tv, "calendar", "standard"))
                    for i, t in enumerate(times):
                        if t.hour not in (6, 18):
                            raise ValueError("unexpected initialization phase")
                        split = "train" if t.day < split_day else "holdout"
                        initialization = int(datetime(t.year, t.month, t.day, t.hour, tzinfo=timezone.utc).timestamp())
                        if initialization in seen_cycles:
                            raise ValueError("duplicate reference initialization; do not mix overlapping files/versions")
                        seen_cycles.add(initialization)
                        # One native cycle (~50 MB), not an archive. A single
                        # contiguous read avoids netCDF orthogonal indexing's
                        # thousands of tiny calls for a descending/wrapped grid.
                        native = np.asarray(np.ma.filled(v[i], np.nan), dtype="float32")
                        block = native[:, yi[:, None], xi[None, :]].copy()
                        block *= 1000
                        if not np.isfinite(block).all() or np.min(block) < -1e-5:
                            raise ValueError("invalid/negative reference field; explicit handling required")
                        block = np.maximum(block, 0)
                        bank, index = banks[split], counts[split]
                        bank.variables["lsp_mm"][index] = block
                        bank.variables["month"][index] = t.month
                        bank.variables["initialization"][index] = initialization
                        counts[split] += 1
                        months.add(t.month)
                        guard.check()
                sources.append(source)
                print(json.dumps({"calibrated_source": path.name, "blocks": counts}), flush=True)
        finally:
            for ds in banks.values():
                ds.close()
        guard.check()
    if not counts["train"] or not counts["holdout"]:
        raise ValueError("both train and held-out cycles required")
    entries = {}
    for split in counts:
        path = output / f"{split}.nc"
        os.replace(path.with_suffix(".nc.partial"), path)
        entries[split] = {"path": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path),
                          "blocks": counts[split]}
    manifest = {"schema": CALIBRATION, "quantity": "large_scale_precipitation", "unit": "mm",
                "spacing_degrees": spacing, "grid_shape": [len(lat), len(lon)], "months": sorted(months),
                "split_day": split_day, "split": "whole cycles by day of month, no hourly shuffle",
                "banks": entries, "sources": sources, "environment": run_metadata(),
                "seconds": time.perf_counter() - started, "peak_process_tree_rss": guard.peak,
                "scope": "first half of each available month, one year; development holdout only",
                "sampling": "nearest native grid point at declared centres; NOT a 1-degree area mean"}
    atomic_json(output / "manifest.json", manifest)
    return manifest


class WeatherModel:
    """Bounded one-block working set. Generation opens only the training bank."""

    def __init__(self, manifest, seed=42, sigma=.12):
        self.path = Path(manifest)
        self.meta = json.loads(self.path.read_text(encoding="utf8"))
        if self.meta["schema"] != CALIBRATION or not 0 <= sigma <= .5:
            raise ValueError("unknown calibration or invalid perturbation sigma")
        self.seed, self.sigma = seed, sigma
        bank = self.meta["banks"]["train"]
        path = safe_data_path(self.path.parent, bank["path"])
        if sha256_file(path) != bank["sha256"]:
            raise ValueError("training bank checksum mismatch")
        self.ds = nc.Dataset(path)
        if (self.ds.schema != CALIBRATION or self.ds.split != "train"
                or self.ds.variables["lsp_mm"].units != "mm"
                or self.ds.variables["lsp_mm"].shape[1:] != (12, *self.meta["grid_shape"])):
            self.ds.close()
            raise ValueError("training bank shape/conventions mismatch")
        self.ds.variables["lsp_mm"].set_var_chunk_cache(8 * 2**20, 1009, .5)
        self.months = np.asarray(self.ds.variables["month"][:])
        self.inits = np.asarray(self.ds.variables["initialization"][:], dtype="int64")
        self.lat = np.asarray(self.ds.variables["latitude"][:])
        self.lon = np.asarray(self.ds.variables["longitude"][:])

    def close(self):
        self.ds.close()

    def block(self, initialization, member=0):
        t = datetime.fromtimestamp(initialization, timezone.utc)
        if t.hour not in (6, 18) or t.minute or t.second or member < 0:
            raise ValueError("choose a 06/18 UTC initialization and nonnegative member")
        candidates = np.flatnonzero((self.months == t.month) & ((self.inits // 3600) % 24 == t.hour))
        if not len(candidates):
            raise ValueError(f"no training data for month {t.month}, phase {t.hour}; no seasonal extrapolation")
        rng = np.random.default_rng(np.random.SeedSequence([self.seed, member, initialization]))
        index = int(rng.choice(candidates))
        base = np.asarray(self.ds.variables["lsp_mm"][index], dtype="float64")
        # Correlation is retained by resampling a complete real storm sequence.
        # This small perturbation is a declared design parameter, not fitted on
        # the held-out data and not a new meteorological algorithm.
        state = np.zeros(base.shape[1:])
        scale = max(1., 4 / self.meta["spacing_degrees"])
        for h in range(12):
            noise = gaussian_filter(rng.standard_normal(state.shape), scale, mode=("reflect", "wrap"))
            noise = (noise - noise.mean()) / max(noise.std(), 1e-12)
            state = noise if h == 0 else .95 * state + math.sqrt(1 - .95**2) * noise
            base[h] *= np.exp(self.sigma * state - self.sigma**2 / 2)
        return np.round(base, 4), {"training_block": index,
                                  "training_initialization": int(self.inits[index]), "member": member}


def generate_weather(calibration, output, target_size="100MB", seed=42, sigma=.12,
                     start="2023-01-01T06:00:00+00:00", days_per_member=365,
                     cycles_per_shard=12, memory_limit="2GiB", disk_budget=None,
                     dry_run=False, resume=False, max_shards=None):
    """Unique (member, cycle, cell) payloads, no copied files or padding.

    Deterministic per-cycle seeds permit atomic shard resume without replaying
    prior members. The sequential worker stays below the generator's 2 GiB cap.
    """
    output, calibration = Path(output), Path(calibration).resolve()
    target = size_bytes(target_size)
    limit = min(size_bytes(memory_limit), 2 * 2**30)
    if target <= 0 or not 1 <= cycles_per_shard <= 120 or not 1 <= days_per_member <= 366:
        raise ValueError("invalid target, days or shard cycle count")
    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    if dt.utcoffset() is None or dt.utcoffset().total_seconds() or dt.hour not in (6, 18) or dt.minute or dt.second:
        raise ValueError("start must be 06/18 UTC, with UTC offset")
    cm = json.loads(calibration.read_text(encoding="utf8"))
    cells = math.prod(cm["grid_shape"])
    config = {"seed": seed, "sigma": sigma, "calibration_sha256": sha256_file(calibration),
              "calibration_path": str(calibration), "start": int(dt.timestamp()),
              "days_per_member": days_per_member, "cycles_per_shard": cycles_per_shard,
              "series_per_shard": cells, "cells_per_member": cells, "hours": days_per_member * 24,
              "grid_shape": cm["grid_shape"], "spacing_degrees": cm["spacing_degrees"],
              "compression": "none", "quantum_mm": QUANTUM, "memory_limit": limit}
    config_hash = digest(config)
    projected = cycles_per_shard * 12 * cells * 9 + cells * 24 + 2**20
    ancestor = output
    while not ancestor.exists():
        ancestor = ancestor.parent
    free = shutil.disk_usage(ancestor).free
    plan = {"schema": SCHEMA, "target_bytes": target, "config": config,
            "projected_max_shard_bytes": projected, "disk_free_bytes": free,
            "required_initial_free_bytes": int(target * 1.2) + projected,
            "workers": 1, "generator_memory_limit": limit,
            "scope": "resampled, perturbed hourly LSP; independent 12 h blocks, not a forecast"}
    if dry_run:
        return {**plan, "status": "dry_run", "disk_feasible": free >= plan["required_initial_free_bytes"]}
    output.mkdir(parents=True, exist_ok=True)
    mp = output / "manifest.json"
    if mp.exists():
        manifest = json.loads(mp.read_text(encoding="utf8"))
        if not resume or manifest["config_hash"] != config_hash or manifest["target_bytes"] != target:
            raise ValueError("existing output needs --resume with identical configuration and target")
        for s in manifest["shards"]:
            if sha256_file(safe_data_path(output, s["path"])) != s["sha256"]:
                raise ValueError("resume shard checksum mismatch")
    else:
        manifest = {**plan, "version": 2, "origin": "synthetic", "config_hash": config_hash,
                    "data_bytes": 0, "shards": [], "generation_runs": []}
    remaining = max(0, target - manifest["data_bytes"])
    if free < remaining * 1.2 + projected:
        raise OSError("insufficient disk including 20% remaining payload reserve")
    if disk_budget and manifest["data_bytes"] + remaining + projected > size_bytes(disk_budget):
        raise OSError("target and shard overshoot exceed disk budget")
    started, written = time.perf_counter(), 0
    run = {"environment": run_metadata(), "resume": resume, "status": "running"}
    manifest["generation_runs"].append(run)
    model = WeatherModel(calibration, seed, sigma)
    try:
        with MemoryGuard(limit) as guard:
            while manifest["data_bytes"] < target and (max_shards is None or written < max_shards):
                ordinal = len(manifest["shards"])
                per_member = math.ceil(days_per_member * 2 / cycles_per_shard)
                member, group = divmod(ordinal, per_member)
                first_cycle = group * cycles_per_shard
                count = min(cycles_per_shard, days_per_member * 2 - first_cycle)
                first_hour, hours = first_cycle * 12, count * 12
                name = f"weather-{ordinal:06d}.nc"
                path, partial = output / name, output / (name + ".partial")
                if path.exists():
                    # A crash after atomic replace but before manifest update:
                    # verify embedded identity and every value by replay below.
                    with nc.Dataset(path) as ds:
                        if ds.config_hash != config_hash or ds.ordinal != ordinal:
                            raise ValueError("orphan shard identity mismatch")
                        for j in range(count):
                            expected, _ = model.block(config["start"] + (first_hour + j * 12) * 3600, member)
                            if not np.array_equal(ds.variables["precipitation"][j*12:(j+1)*12], expected.reshape(12, cells)):
                                raise ValueError("orphan payload mismatch")
                else:
                    if shutil.disk_usage(output).free < projected + max(2**30, remaining // 5):
                        raise OSError("disk reserve exhausted")
                    with nc.Dataset(partial, "w") as ds:
                        ds.set_fill_off()
                        for key, n in (("time", hours), ("series", cells), ("bounds", 2), ("cycle", count)):
                            ds.createDimension(key, n)
                        ds.setncatts({"schema": SCHEMA, "config_hash": config_hash, "ordinal": ordinal,
                                      "origin": "synthetic", "statistic": "amount", "unit": "mm",
                                      "quantity": "large_scale_precipitation", "member": member,
                                      "product": "monthly-bootstrap-ERA5-LSP", "quantum_mm": QUANTUM,
                                      "cycle_hours": 12, "Conventions": "CF-1.12"})
                        ends = config["start"] + (np.arange(first_hour, first_hour + hours) + 1) * 3600
                        t = ds.createVariable("time", "i8", ("time",))
                        t.units, t.bounds = "seconds since 1970-01-01 00:00:00", "time_bounds"
                        t[:] = ends
                        ds.createVariable("time_bounds", "i8", ("time", "bounds"))[:] = np.column_stack((ends-3600, ends))
                        ds.createVariable("series_id", "i8", ("series",))[:] = member*cells + np.arange(cells)
                        ds.createVariable("latitude", "f8", ("series",))[:] = np.repeat(model.lat, len(model.lon))
                        ds.createVariable("longitude", "f8", ("series",))[:] = np.tile(model.lon, len(model.lat))
                        ds.variables["latitude"].units = "degrees_north"
                        ds.variables["longitude"].units = "degrees_east"
                        v = ds.createVariable("precipitation", "f8", ("time", "series"), chunksizes=(1, cells))
                        v.units, v.cell_methods = "mm", "time: sum"
                        v.coordinates = "latitude longitude"
                        qc = ds.createVariable("qc", "u1", ("time", "series"), chunksizes=(1, cells))
                        provenance = ds.createVariable("training_initialization", "i8", ("cycle",))
                        for j in range(count):
                            values, info = model.block(config["start"] + (first_hour+j*12)*3600, member)
                            v[j*12:(j+1)*12] = values.reshape(12, cells)
                            qc[j*12:(j+1)*12] = 0
                            provenance[j] = info["training_initialization"]
                            guard.check()
                    os.replace(partial, path)
                rows = hours * cells
                entry = {"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path),
                         "rows": rows, "logical_bytes": rows*9, "schema": SCHEMA,
                         "series_start": member*cells, "series_end": (member+1)*cells,
                         "member": member, "first_hour": first_hour, "hours": hours,
                         "partition": [member, first_hour], "scheme": 0, "origin": "synthetic"}
                manifest["shards"].append(entry)
                manifest["data_bytes"] += entry["bytes"]
                remaining = max(0, target-manifest["data_bytes"])
                written += 1
                atomic_json(mp, manifest)
                print(json.dumps({"generated_shard": name, "data_bytes": manifest["data_bytes"]}), flush=True)
            guard.check()
        run.update(status="complete" if manifest["data_bytes"] >= target else "interrupted",
                   seconds=time.perf_counter()-started, peak_process_tree_rss=guard.peak,
                   newly_written_shards=written)
    except Exception as exc:
        run.update(status="failed", error=str(exc), seconds=time.perf_counter()-started)
        raise
    finally:
        model.close()
        atomic_json(mp, manifest)
    manifest["status"] = run["status"]
    atomic_json(mp, manifest)
    return manifest
