"""Read one hourly global field at a time; preserve member and cycle identity."""

import json
import os
import time
from bisect import bisect_right
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import netCDF4 as nc
import numpy as np
from fastapi import APIRouter, HTTPException, Request, Response

from .realistic_weather import SCHEMA
from .resources import safe_data_path, sha256_file


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


class MapArchive:
    def __init__(self, manifest, scale_report=None):
        self.path = Path(manifest).resolve()
        self.manifest = json.loads(self.path.read_text(encoding="utf8"))
        m = self.manifest
        if m.get("schema") != SCHEMA or m.get("status") != "complete":
            raise ValueError("map archive requires a completed weather-v2 manifest")
        self.sha = sha256_file(self.path)
        self.shape = m["config"]["grid_shape"]
        self.cells = int(np.prod(self.shape))
        if self.cells > 1_000_000:
            raise ValueError("map frame exceeds bounded grid budget")
        self.start = m["config"]["start"]
        self.members = {}
        for s in m["shards"]:
            self.members.setdefault(s["member"], []).append(s)
        for shards in self.members.values():
            shards.sort(key=lambda s: s["first_hour"])
            if any(a["first_hour"]+a["hours"] != b["first_hour"] for a, b in zip(shards, shards[1:])):
                raise ValueError("map member contains gaps or overlapping time partitions")
        self.starts = {member: [s["first_hour"] for s in shards] for member, shards in self.members.items()}
        self.verified = OrderedDict()  # signatures/checksums only, never data arrays
        self.stats = {"frame_requests": 0, "logical_data_bytes": 0, "checksum_files": 0,
                      "frame_seconds_total": 0., "frame_seconds_max": 0.}
        self.maximum, self.scale_verified = 50., False
        if scale_report:
            report = json.loads(Path(scale_report).read_text(encoding="utf8"))
            if report["manifest_sha256"] != self.sha:
                raise ValueError("map scale report belongs to a different manifest")
            for p in report["profiles"]:
                if (p["status"] == "complete" and p.get("scan_bytes") == m["data_bytes"]
                        and "maximum_accepted_encoded_value" in p["scan"]):
                    self.maximum = max(.1, p["scan"]["maximum_accepted_encoded_value"])
                    self.scale_verified = True
                    break
            if not self.scale_verified:
                raise ValueError("map requires a complete scan with its recorded maximum")

    def catalog(self):
        return {"manifest_sha256": self.sha, "data_bytes": self.manifest["data_bytes"],
                "grid_shape": self.shape, "start_epoch": self.start, "unit": "mm",
                "quantity": "large_scale_precipitation", "color_max_mm": self.maximum,
                "color_scale_from_full_scan": self.scale_verified, "cycle_hours": 12,
                "frame_bytes": self.cells*4, "server_verified_cache_limit": 16,
                "members": [{"member": member, "first_hour": shards[0]["first_hour"],
                             "hours": sum(s["hours"] for s in shards),
                             "start_utc": iso(self.start+shards[0]["first_hour"]*3600),
                             "end_utc": iso(self.start+(shards[-1]["first_hour"]+shards[-1]["hours"])*3600)}
                            for member, shards in sorted(self.members.items())],
                "semantics": "independent 12h episodes; individual hourly amounts, no cross-cycle totals"}

    def selection(self, member, start, end):
        def timestamp(value):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.utcoffset() is None:
                raise ValueError("time selection requires an explicit UTC offset")
            return dt.timestamp()

        a, b = timestamp(start), timestamp(end)
        h, duration = (a-self.start)/3600, (b-a)/3600
        if h != int(h) or duration != int(duration) or not 1 <= duration <= 8784:
            raise ValueError("select 1..8784 complete hourly intervals")
        shards = self.members.get(member, [])
        if not shards or h < shards[0]["first_hour"] or h+duration > shards[-1]["first_hour"]+shards[-1]["hours"]:
            raise ValueError("selected time range is outside this member's prepared data")
        return {"first_hour": int(h), "hours": int(duration), "start_utc": iso(a), "end_utc": iso(b),
                "member": member, "manifest_sha256": self.sha}

    def frame(self, member, hour):
        started = time.perf_counter()
        starts = self.starts.get(member, [])
        position = bisect_right(starts, hour)-1
        if position < 0:
            raise ValueError("member/hour not present")
        shard = self.members[member][position]
        if hour >= shard["first_hour"]+shard["hours"]:
            raise ValueError("hour is outside prepared data")
        path = safe_data_path(self.path.parent, shard["path"])
        stat = path.stat()
        signature = (str(path), stat.st_size, stat.st_mtime_ns)
        if signature not in self.verified:
            if stat.st_size != shard["bytes"] or sha256_file(path) != shard["sha256"]:
                raise ValueError("map shard checksum/size mismatch")
            self.stats["checksum_files"] += 1
            self.verified[signature] = True
            if len(self.verified) > 16:
                self.verified.popitem(last=False)
        self.verified.move_to_end(signature)
        with nc.Dataset(path) as ds:
            if ds.schema != SCHEMA or ds.member != member:
                raise ValueError("map quantity/member schema mismatch")
            v = ds.variables["precipitation"]
            v.set_var_chunk_cache(2*2**20, 1009, .5)
            q = ds.variables["qc"]
            q.set_var_chunk_cache(2**20, 1009, .5)
            offset = hour-shard["first_hour"]
            values = np.asarray(v[offset], dtype="<f4")
            flags = np.asarray(q[offset])
            values[(flags != 0) | (values < 0) | ~np.isfinite(values)] = np.nan
        if values.size != self.cells:
            raise ValueError("map frame shape mismatch")
        payload = values.tobytes()
        elapsed = time.perf_counter()-started
        self.stats["frame_requests"] += 1
        self.stats["logical_data_bytes"] += self.cells*9
        self.stats["frame_seconds_total"] += elapsed
        self.stats["frame_seconds_max"] = max(elapsed, self.stats["frame_seconds_max"])
        return payload, {"X-Frame-Start": iso(self.start+hour*3600),
                         "X-Cycle-UTC": iso(self.start+(hour//12)*12*3600),
                         "X-Member": str(member), "X-Source-SHA256": shard["sha256"],
                         "X-Manifest-SHA256": self.sha, "Cache-Control": "no-store"}


def make_map_router(read_lock):
    router = APIRouter(prefix="/map-archive", tags=["map archive"])
    cache = {}

    def archive(request):
        path = os.environ.get("METEOBRIDGE_MAP_MANIFEST")
        report = os.environ.get("METEOBRIDGE_MAP_SCALE_REPORT")
        if not path:
            raise HTTPException(503, "map archive not configured; use serve_precipitation_map.py")
        key = (path, report)
        if key not in cache:
            cache.clear()
            cache[key] = MapArchive(path, report)
        guard = getattr(request.app.state, "map_memory_guard", None)
        if guard:
            guard.check()
        return cache[key]

    @router.get("/catalog")
    def catalog(request: Request):
        with read_lock:
            try:
                return archive(request).catalog()
            except (ValueError, OSError) as exc:
                raise HTTPException(422, str(exc)) from exc

    @router.get("/range")
    def selection(request: Request, start: str, end: str, member: int = 0):
        with read_lock:
            try:
                return archive(request).selection(member, start, end)
            except (ValueError, OSError) as exc:
                raise HTTPException(422, str(exc)) from exc

    @router.get("/frame")
    def frame(request: Request, hour: int, member: int = 0, manifest_sha256: str = ""):
        with read_lock:
            try:
                current = archive(request)
                if manifest_sha256 != current.sha:
                    raise HTTPException(409, "archive changed; reload catalog")
                payload, headers = current.frame(member, hour)
                return Response(payload, media_type="application/octet-stream", headers=headers)
            except (ValueError, OSError, MemoryError) as exc:
                raise HTTPException(422, str(exc)) from exc

    @router.get("/metrics")
    def metrics(request: Request):
        with read_lock:
            current = archive(request)
            guard = getattr(request.app.state, "map_memory_guard", None)
            return {**current.stats, "verified_signatures_cached": len(current.verified),
                    "peak_process_tree_rss": guard.peak if guard else None,
                    "memory_limit": guard.limit if guard else None}

    return router
