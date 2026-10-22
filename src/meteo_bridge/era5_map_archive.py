"""A sparse hourly index over local ERA5 files, with bounded frame reads."""

import hashlib
import json
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import netCDF4 as nc
import numpy as np

from .precipitation_map import WORLD_BBOX, _datetime
from .resources import netcdf_read_path

# NetCDF/HDF5 is not thread safe. Share this lock between indexing and HTTP reads.
READ_LOCK = threading.RLock()


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def era5_files(path):
    path = Path(path).expanduser().resolve()
    files = sorted(path.rglob("*.nc")) if path.is_dir() else [path] if path.is_file() else []
    if not files or any(p.suffix != ".nc" for p in files):
        raise ValueError("Укажите папку с файлами ERA5 .nc или один файл .nc.")
    return files


class Era5MapArchive:
    def __init__(self, paths, bbox=WORLD_BBOX, max_cells=100_000):
        west, east, south, north = map(float, bbox)
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError("Нужны west < east в [-180,180] и south < north в [-90,90].")
        if not 1 <= max_cells <= 1_000_000:
            raise ValueError("Лимит одного кадра: 1–1 000 000 ячеек.")
        self.bbox = [west, east, south, north]
        self.records, self.signatures, self.sources = {}, {}, []
        self.cycles = OrderedDict()
        self.duplicate_hours = 0
        self.stats = {"cycle_reads": 0, "frame_requests": 0}
        raw_lat = raw_lon = None
        with READ_LOCK:
            for path in sorted({Path(p).resolve() for p in paths}):
                stat = path.stat()
                self.signatures[path] = (stat.st_size, stat.st_mtime_ns)
                with nc.Dataset(netcdf_read_path(path)) as ds:
                    v = ds.variables.get("LSP")
                    if (v is None or v.dimensions != (
                            "forecast_initial_time", "forecast_hour", "latitude", "longitude")
                            or getattr(v, "units", None) != "m" or getattr(v, "rda_dataset", None) != "ds633.0"):
                        raise ValueError(f"{path.name}: нужен NCAR ERA5 LSP ds633.0 в метрах.")
                    lat = np.asarray(ds["latitude"][:], dtype=float)
                    lon = np.asarray(ds["longitude"][:], dtype=float)
                    if raw_lat is None:
                        raw_lat, raw_lon = lat, lon
                    elif not np.array_equal(raw_lat, lat) or not np.array_equal(raw_lon, lon):
                        raise ValueError(f"{path.name}: географическая сетка отличается от остальных файлов.")
                    tv = ds["forecast_initial_time"]
                    calendar = getattr(tv, "calendar", "standard")
                    if calendar not in ("standard", "gregorian", "proleptic_gregorian"):
                        raise ValueError(f"{path.name}: неподдерживаемый календарь ERA5.")
                    dates = [_datetime(t) for t in nc.num2date(tv[:], tv.units, calendar)]
                    hours = np.asarray(ds["forecast_hour"][:], dtype=float)
                    if (not len(hours) or len(hours) > 12
                            or not np.array_equal(hours, np.arange(1, len(hours) + 1))):
                        raise ValueError(f"{path.name}: ожидаются последовательные почасовые шаги от 1 до 12.")
                    for ci, cycle in enumerate(dates):
                        epoch = int(cycle.timestamp())
                        if cycle.timestamp() % 3600:
                            raise ValueError(f"{path.name}: цикл должен начинаться в целый час UTC.")
                        for hi, step in enumerate(hours):
                            hour_start = epoch + (int(step) - 1) * 3600
                            if hour_start in self.records:
                                self.duplicate_hours += 1
                            else:
                                self.records[hour_start] = (path, ci, hi, epoch, len(hours))
                self.sources.append({"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns})
        if not self.records:
            raise ValueError("В выбранных файлах нет почасовых данных ERA5.")
        normalized_lon = (raw_lon + 180) % 360 - 180
        yi = np.flatnonzero((raw_lat >= south) & (raw_lat <= north))
        xi = np.flatnonzero((normalized_lon >= west) & (normalized_lon <= east))
        yi, xi = yi[np.argsort(raw_lat[yi])], xi[np.argsort(normalized_lon[xi])]
        if not len(yi) or not len(xi):
            raise ValueError("В выбранной области нет ячеек ERA5.")
        stride = max(1, int(np.ceil(np.sqrt(len(yi) * len(xi) / max_cells))))
        while len(yi[::stride]) * len(xi[::stride]) > max_cells:
            stride += 1
        self.yi, self.xi = yi[::stride], xi[::stride]
        self.latitude, self.longitude = raw_lat[self.yi], normalized_lon[self.xi]
        self.shape = [len(self.yi), len(self.xi)]
        self.stride = stride
        self.start, self.end = min(self.records), max(self.records) + 3600
        self.hours = (self.end - self.start) // 3600
        self.coverage = []
        for hour in sorted(self.records):
            if self.coverage and hour == self.coverage[-1][1]:
                self.coverage[-1][1] = hour + 3600
            else:
                self.coverage.append([hour, hour + 3600])
        self.sha = hashlib.sha256(json.dumps([self.sources, self.bbox, self.shape], sort_keys=True).encode()).hexdigest()

    def catalog(self):
        return {"kind": "era5", "manifest_sha256": self.sha, "file_count": len(self.sources),
                "data_bytes": sum(s["bytes"] for s in self.sources), "grid_shape": self.shape,
                "start_epoch": self.start, "unit": "mm", "quantity": "large_scale_precipitation",
                "color_max_mm": 50, "color_scale_from_full_scan": False,
                "frame_bytes": int(np.prod(self.shape)) * 4, "available_hours": len(self.records),
                "gap_hours": self.hours - len(self.records), "duplicate_hours": self.duplicate_hours,
                "available_ranges": [[iso(a), iso(b)] for a, b in self.coverage],
                "members": [{"member": 0, "first_hour": 0, "hours": self.hours,
                             "start_utc": iso(self.start), "end_utc": iso(self.end)}],
                "semantics": "ERA5 HRES previous-hour amounts; missing hours remain empty"}

    def selection(self, member, start, end):
        def stamp(value):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.utcoffset() is None:
                raise ValueError("Выберите время с явным UTC offset.")
            return dt.timestamp()

        a, b = stamp(start), stamp(end)
        if member != 0 or a % 3600 or b % 3600 or not self.start <= a < b <= self.end:
            raise ValueError("Выберите полные часы внутри доступного диапазона ERA5.")
        available = sum(a <= hour < b for hour in self.records)
        hours = int((b - a) / 3600)
        return {"first_hour": int((a - self.start) / 3600), "hours": hours, "member": 0,
                "start_utc": iso(a), "end_utc": iso(b), "manifest_sha256": self.sha,
                "available_hours": available, "gap_hours": hours - available}

    def _values(self, hour):
        if not isinstance(hour, int) or not 0 <= hour < self.hours:
            raise ValueError("Час находится вне диапазона архива ERA5.")
        epoch = self.start + hour * 3600
        record = self.records.get(epoch)
        if record is None:
            return np.full(self.shape, np.nan, dtype="<f4"), None
        path, ci, hi, cycle, steps = record
        stat = path.stat()
        if (stat.st_size, stat.st_mtime_ns) != self.signatures[path]:
            raise ValueError("Файл ERA5 изменился. Повторно постройте карту.")
        key = (path, ci)
        if key not in self.cycles:
            with nc.Dataset(netcdf_read_path(path)) as ds:
                v = ds["LSP"]
                # Native chunks can contain an entire global 12-hour cycle (~50 MiB).
                # Keep one compressed block's decoded data in cache during strided reads.
                v.set_var_chunk_cache(64 * 2**20, 1009, .5)
                values = np.asarray(np.ma.filled(v[ci, :steps, self.yi, self.xi], np.nan), dtype="<f4")
                values *= 1000
                values[(values < 0) | ~np.isfinite(values)] = np.nan
            self.cycles[key] = values
            self.stats["cycle_reads"] += 1
            if len(self.cycles) > 2:
                self.cycles.popitem(last=False)
        self.cycles.move_to_end(key)
        return self.cycles[key][hi], {"path": str(path), "cycle": cycle}

    def frame(self, member, hour):
        if member != 0:
            raise ValueError("У реального ERA5 нет выбранного синтетического сценария.")
        with READ_LOCK:
            values, source = self._values(hour)
            available = source is not None and bool(np.isfinite(values).any())
            self.stats["frame_requests"] += 1
            return values.tobytes(), {"X-Frame-Start": iso(self.start + hour * 3600),
                                     "X-Data-Available": str(available).lower(),
                                     "X-Cycle-UTC": iso(source["cycle"]) if source else "",
                                     "X-Manifest-SHA256": self.sha, "Cache-Control": "no-store"}

    def initial_map(self, selection):
        with READ_LOCK:
            values, _ = self._values(selection["first_hour"])
            values = values.copy()[None, :, :]
        a = self.start + selection["first_hour"] * 3600
        return {"longitude": self.longitude, "latitude": self.latitude, "amounts_mm": values,
                "metadata": {"origin": "original", "archive_kind": "era5", "allow_empty_frame": True,
                             "display_label": "ERA5 LSP · архивные данные", "unit": "mm",
                             "quantity": "large_scale_precipitation", "bbox": self.bbox,
                             "grid_shape": self.shape, "frames": 1, "animation_hours": selection["hours"],
                             "selected_values": int(values.size), "spatial_sampling_stride": self.stride,
                             "selection": selection, "manifest_sha256": self.sha, "member": 0,
                             "first_hour": selection["first_hour"], "intervals_utc": [[iso(a), iso(a + 3600)]],
                             "available_ranges": self.catalog()["available_ranges"], "sources": self.sources,
                             "temporal_interpolation": False, "semantics": "ERA5_HRES_previous_hour_amount"}}
