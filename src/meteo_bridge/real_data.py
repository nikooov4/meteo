"""Explicit anonymous NCAR object selection; bounded downloads with immutable provenance."""

import json
import os
import shutil
import time
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
import netCDF4 as nc
import numpy as np
import yaml

from .domain import digest
from .resources import MemoryGuard, atomic_json, run_metadata, sha256_file, size_bytes


def _months(start, end):
    year, month = map(int, start.split("-"))
    last = tuple(map(int, end.split("-")))
    if not 1 <= month <= 12 or (year, month) > last:
        raise ValueError("invalid month range")
    while (year, month) <= last:
        yield f"{year:04d}{month:02d}"
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


def list_objects(config, target):
    base = config["bucket_url"]
    if urlparse(base).hostname not in {
        "nsf-ncar-era5.s3.us-west-2.amazonaws.com",
        "nsf-ncar-era5.s3.amazonaws.com",
    }:
        raise ValueError("profile must select the verified public NCAR bucket")
    if config["collection"] != "e5.oper.fc.sfc.accumu" or config["variable_pattern"] != ".128_142_lsp.":
        raise ValueError("verified profile selects large-scale precipitation, not unavailable total TP")
    objects, total = [], 0
    ns = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
    with httpx.Client(timeout=config.get("timeout_seconds", 120), follow_redirects=True) as client:
        for month in _months(config["start_month"], config["end_month"]):
            prefix = f"{config['collection']}/{month}/{config['collection']}{config['variable_pattern']}"
            token = None
            for _ in range(config.get("max_list_pages", 2)):
                params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
                if token:
                    params["continuation-token"] = token
                response = client.get(base, params=params)
                response.raise_for_status()
                if len(response.content) > 4 * 2**20:
                    raise ValueError("LIST response budget exceeded")
                xml = ET.fromstring(response.content)
                for item in xml.findall("s:Contents", ns):
                    key = item.findtext("s:Key", namespaces=ns)
                    if not key.endswith(".nc") or config["variable_pattern"] not in key:
                        continue
                    url = f"{base}/{quote(key, safe='/')}"
                    head = client.head(url)
                    head.raise_for_status()
                    size = int(head.headers["content-length"])
                    if size != int(item.findtext("s:Size", namespaces=ns)):
                        raise ValueError("LIST/HEAD size mismatch")
                    objects.append(
                        {
                            "key": key,
                            "url": url,
                            "bytes": size,
                            "etag": head.headers.get("etag"),
                            "source_version": head.headers.get("x-amz-version-id"),
                            "last_modified": head.headers.get("last-modified"),
                            "month": month,
                        }
                    )
                    total += size
                    if total >= target or len(objects) >= config.get("max_objects", 600):
                        return objects, total
                if xml.findtext("s:IsTruncated", namespaces=ns) != "true":
                    break
                token = xml.findtext("s:NextContinuationToken", namespaces=ns)
    return objects, total


def inspect_ncar(ds):
    candidates = [
        v
        for name, v in ds.variables.items()
        if name.upper() == "LSP" or "large-scale precipitation" in getattr(v, "long_name", "").lower()
    ]
    if len(candidates) != 1:
        raise ValueError("expected one supported large-scale precipitation variable")
    v = candidates[0]
    if getattr(v, "units", None) not in {"m", "mm", "kg m**-2", "kg m-2"}:
        raise ValueError("unsupported NCAR TP units")
    if v.ndim not in {3, 4}:
        raise ValueError("unsupported NCAR dimensions")
    return {
        "variable": v.name,
        "dimensions": v.dimensions,
        "shape": v.shape,
        "logical_bytes": int(v.size * v.dtype.itemsize),
        "attributes": {a: str(v.getncattr(a)) for a in v.ncattrs()},
        "time_coordinates": {
            name: {
                "shape": var.shape,
                "attributes": {a: str(var.getncattr(a)) for a in var.ncattrs()},
                "preview": np.asarray(var[: min(3, len(var))]).tolist() if var.ndim == 1 else [],
            }
            for name, var in ds.variables.items()
            if "time" in name or "hour" in name
        },
        "semantic_status": "requires documented accumulation period; collection name alone is insufficient",
    }


def _download(obj, path, client, guard):
    partial = path.with_suffix(".nc.partial")
    if partial.exists() and partial.stat().st_size == obj["bytes"]:
        with nc.Dataset(partial) as ds:
            metadata = inspect_ncar(ds)
        os.replace(partial, path)
        return metadata
    for attempt in range(4):
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > obj["bytes"]:
            raise ValueError("partial larger than source")
        headers = (
            {"Range": f"bytes={offset}-", "If-Match": obj["etag"]} if offset else {"If-Match": obj["etag"]}
        )
        try:
            with client.stream("GET", obj["url"], headers=headers) as response:
                response.raise_for_status()
                if offset and response.status_code != 206:
                    offset = 0
                if offset and not response.headers.get("content-range", "").startswith(f"bytes {offset}-"):
                    raise ValueError("invalid resumed range")
                with partial.open("ab" if offset else "wb") as f:
                    for block in response.iter_bytes(2**20):
                        if f.tell() + len(block) > obj["bytes"]:
                            raise ValueError("source exceeds HEAD size")
                        f.write(block)
                        guard.check()
                        if shutil.disk_usage(path.parent).free < 128 * 2**20:
                            raise OSError("disk exhausted")
                    f.flush()
                    os.fsync(f.fileno())
            if partial.stat().st_size != obj["bytes"]:
                raise OSError("incomplete object download")
            with nc.Dataset(partial) as ds:
                metadata = inspect_ncar(ds)
            os.replace(partial, path)
            return metadata
        except (httpx.HTTPError, OSError):
            if attempt == 3:
                raise
            time.sleep(min(2**attempt, 4))


def prepare_real_scale(
    provider, target_size, config, output, resume=False, dry_run=False, memory_limit="2GiB", disk_budget=None
):
    if provider != "ncar-era5":
        raise ValueError("supported provider: ncar-era5")
    cfg = yaml.safe_load(Path(config).read_text())
    target, root = size_bytes(target_size), Path(output).resolve()
    if cfg.get("concurrency", 1) != 1:
        raise ValueError("reference downloader uses one bounded stream; concurrency=1 required")
    root.mkdir(parents=True, exist_ok=True)
    mp, planpath = root / "manifest.json", root / "download-plan.json"
    if resume and planpath.exists():
        plan = json.loads(planpath.read_text())
        if plan["config_hash"] != digest(cfg) or plan["target_bytes"] != target:
            raise ValueError("resume source configuration changed")
    else:
        objects, total = list_objects(cfg, target)
        plan = {
            "provider": provider,
            "config_hash": digest(cfg),
            "config": cfg,
            "objects": objects,
            "selected_bytes": total,
            "target_bytes": target,
            "sufficient": total >= target,
            "license_url": cfg["license_url"],
            "documentation": cfg["documentation"],
            "environment": run_metadata(),
            "status": "dry_run",
        }
        atomic_json(planpath, plan)
    plan["free_disk_bytes"] = shutil.disk_usage(root).free
    plan["required_free_bytes"] = int(plan["selected_bytes"] * 1.2)
    plan["disk_budget_bytes"] = size_bytes(disk_budget) if disk_budget else None
    plan["resource_check"] = plan["free_disk_bytes"] >= plan["required_free_bytes"] and (
        plan["disk_budget_bytes"] is None or plan["selected_bytes"] <= plan["disk_budget_bytes"]
    )
    plan["resource_check_unix_time"] = time.time()
    atomic_json(planpath, plan)
    if dry_run:
        return plan
    if not plan["sufficient"]:
        raise ValueError("selected precipitation/date scope is smaller than target; extend date range")
    if plan["free_disk_bytes"] < plan["required_free_bytes"] and not (resume and mp.exists()):
        raise OSError("insufficient disk + 20% reserve")
    if disk_budget and plan["selected_bytes"] > size_bytes(disk_budget):
        raise OSError("source selection exceeds disk budget")
    manifest = (
        json.loads(mp.read_text())
        if resume and mp.exists()
        else {
            "version": 1,
            "origin": "original",
            "provider": provider,
            "config": cfg,
            "plan_hash": digest(plan["objects"]),
            "shards": [],
            "data_bytes": 0,
            "status": "downloading",
            "resume_count": 0,
        }
    )
    if mp.exists() and not resume:
        raise ValueError("manifest exists; use --resume")
    if resume:
        manifest["resume_count"] += 1
        if manifest["config"] != cfg or manifest["plan_hash"] != digest(plan["objects"]):
            raise ValueError("resume manifest/source plan mismatch")
    try:
        with (
            MemoryGuard(min(size_bytes(memory_limit), 2**31)) as guard,
            httpx.Client(timeout=cfg.get("timeout_seconds", 120), follow_redirects=True) as client,
        ):
            for obj in plan["objects"]:
                path = root / obj["key"].split("/")[-1]
                existing = next((s for s in manifest["shards"] if s["key"] == obj["key"]), None)
                if existing:
                    if path.stat().st_size != existing["bytes"] or sha256_file(path) != existing["sha256"]:
                        raise ValueError("real resume checksum mismatch")
                    continue
                if shutil.disk_usage(root).free < obj["bytes"] + int(plan["selected_bytes"] * 0.2):
                    raise OSError("disk reserve exhausted")
                metadata = _download(obj, path, client, guard)
                entry = {
                    **obj,
                    "path": path.name,
                    "sha256": sha256_file(path),
                    "metadata": metadata,
                    "logical_bytes": metadata["logical_bytes"],
                    "rows": int(np.prod(metadata["shape"])),
                    "origin": "original",
                    "license_url": cfg["license_url"],
                    "documentation": cfg["documentation"],
                }
                manifest["shards"].append(entry)
                manifest["data_bytes"] += entry["bytes"]
                atomic_json(mp, manifest)
            manifest.update(status="complete", peak_process_tree_rss=guard.peak)
    except BaseException as exc:
        manifest.update(
            status="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed", error=str(exc)
        )
        atomic_json(mp, manifest)
        raise
    atomic_json(mp, manifest)
    return {"status": manifest["status"], "data_bytes": manifest["data_bytes"], "manifest": str(mp)}


def scan_ncar(ds, guard):
    metadata = inspect_ncar(ds)
    v = ds.variables[metadata["variable"]]
    v.set_var_chunk_cache(64 * 2**20, 1009, 0.5)
    factor = 1000 if v.units == "m" else 1
    # Prefix dimensions can include initialization and step. Flattened iteration
    # preserves them in provenance and never constructs cross-cycle equalities.
    # Native chunks include all twelve steps and the grid (~50 MB float32).
    # Reading an initialization once avoids re-decompressing that chunk per row.
    prefix_shape = v.shape[:-3] if v.ndim == 4 else v.shape[:-2]
    tail = (slice(None),) * (3 if v.ndim == 4 else 2)
    for idx in np.ndindex(*prefix_shape):
        raw = np.asarray(v[idx + tail])
        missing = ~np.isfinite(raw) | (raw == getattr(v, "_FillValue", np.nan))
        values = np.where(missing, np.nan, raw).astype("float64") * factor
        flags = missing.astype("uint8")
        guard.check()
        yield values, flags


def ncar_query_case(manifest_path, series_id, first_hour, hours):
    from datetime import timezone

    from .domain import (
        Case,
        Interpretation,
        IntervalObservation,
        Query,
        SemanticHypothesis,
        SeriesKey,
        SourceManifest,
        utc_seconds,
    )

    mp = Path(manifest_path)
    manifest = json.loads(mp.read_text())
    # first_hour is a forecast-record index in this adapter, not an invented global time axis.
    init_index, shard_index = first_hour, 0
    while shard_index < len(manifest["shards"]):
        count = manifest["shards"][shard_index]["metadata"]["shape"][0]
        if init_index < count:
            break
        init_index -= count
        shard_index += 1
    if shard_index >= len(manifest["shards"]):
        raise ValueError("forecast initialization outside prepared manifest")
    shard = manifest["shards"][shard_index]
    if manifest["config"].get("semantics") != "ERA5_HRES_previous_hour_amount":
        raise NotImplementedError("native temporal convention has not been verified")
    with nc.Dataset(mp.parent / shard["path"]) as ds:
        metadata = inspect_ncar(ds)
        v = ds.variables[metadata["variable"]]
        if tuple(v.dimensions) != ("forecast_initial_time", "forecast_hour", "latitude", "longitude"):
            raise NotImplementedError("unsupported native dimension order")
        if not 0 <= series_id < v.shape[2] * v.shape[3] or init_index >= v.shape[0] or hours > 12:
            raise ValueError("grid/initialization/step limits exceeded")
        fv = ds.variables["forecast_initial_time"]
        dt = nc.num2date(
            fv[init_index],
            fv.units,
            calendar=fv.calendar,
            only_use_cftime_datetimes=False,
            only_use_python_datetimes=True,
        )
        base = utc_seconds(dt.replace(tzinfo=timezone.utc).isoformat())
        steps = ds.variables["forecast_hour"][:hours]
        if not np.array_equal(steps, np.arange(1, hours + 1)):
            raise ValueError("expected native hourly forecast periods 1..12")
        lat, lon = divmod(series_id, v.shape[3])
        v.set_var_chunk_cache(8 * 2**20, 1009, 0.5)
        values = v[init_index, :hours, lat, lon]
        key = SeriesKey(
            quantity="large_scale_precipitation",
            location=f"{float(ds['latitude'][lat])},{float(ds['longitude'][lon])}",
            spatial_support="0.25 degree ERA5 grid cell",
            product="NSF-NCAR ERA5 LSP",
            version="ds633.0",
            cycle=dt.replace(tzinfo=timezone.utc).isoformat(),
        )
        obs = []
        for index, value in enumerate(values):
            missing = np.ma.is_masked(value) or not np.isfinite(value)
            encoded = "0" if missing else str(Fraction.from_float(float(value)))
            obs.append(
                IntervalObservation(
                    id=f"step-{index + 1}",
                    series=key,
                    original_value=encoded,
                    original_timestamp=str(base + (index + 1) * 3600),
                    lower=encoded,
                    upper=encoded,
                    interval=Interpretation(
                        start=base + index * 3600, end=base + (index + 1) * 3600, unit=v.units
                    ),
                    qc="missing" if missing else "accepted",
                    reset_group=key.cycle,
                    evidence_ids=[shard["sha256"]],
                )
            )
    source = SourceManifest(
        dataset_id=shard["path"],
        provider="NSF NCAR",
        product_kind="reanalysis",
        upstream=["ECMWF ERA5"],
        version="ds633.0",
        url=shard["url"],
        license=shard["license_url"],
        sha256=shard["sha256"],
        documentation_version="ECMWF ERA5 terminology checked 2026-10-16",
        request={"key": shard["key"], "initialization": key.cycle, "grid_index": series_id},
    )
    return Case(
        id=f"ncar-lsp-{shard_index}-{init_index}-{series_id}",
        observations=obs,
        hypotheses=[SemanticHypothesis(id="native-hourly-period")],
        query=Query(series=key, start=base, end=base + hours * 3600),
        h_complete=True,
        completeness_basis="native dimensions/units checked; ECMWF ERA5 HRES previous-postprocessing period",
        origin="original",
        family_id="ncar-era5-lsp",
        source_manifests=[source],
        assumptions=[
            "nonnegative precipitation increments",
            "encoded reanalysis values used as exact inputs",
            "ERA5 HRES accumulation is previous hour, not cumulative since initialization",
        ],
    ), len(values) * 4
