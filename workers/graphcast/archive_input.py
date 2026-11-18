"""Prepare a two-state GraphCast input using the local archive and Google ARCO-ERA5."""
from __future__ import annotations

import ctypes
import json
import sys
from pathlib import Path

import numpy as np
import xarray as xr

LEVELS = [50, 100, 150, 200, 250, 300, 400, 500, 600, 700, 850, 925, 1000]
LATITUDES = np.arange(-90, 91)
LONGITUDES = np.arange(360)
PRESSURE = ("temperature", "geopotential", "u_component_of_wind", "v_component_of_wind",
            "vertical_velocity", "specific_humidity")
SURFACE = ("2m_temperature", "mean_sea_level_pressure", "10m_u_component_of_wind", "10m_v_component_of_wind")
RAIN = "convective_precipitation"


def open_netcdf(path):
    path = Path(path)
    with path.open("rb") as stream:
        if stream.read(3) == b"CDF":
            return xr.open_dataset(path, engine="scipy")
    native = str(path)
    if sys.platform == "win32":
        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(native, buffer, len(buffer)):
            native = buffer.value
    return xr.open_dataset(native, engine="netcdf4")


def longitude_grid(data):
    data = data.assign_coords(lon=data.lon % 360)
    return data.sel(lat=LATITUDES, lon=LONGITUDES)


def progress(state, message):
    print(json.dumps({"state": state, "message": message}, ensure_ascii=False), flush=True)


def read_arco(url, states, rain_hours, cache):
    try:
        import aiohttp
        import zarr
    except ModuleNotFoundError as error:
        raise ValueError("Установите зависимости Google ARCO-ERA5 через scripts/setup_graphcast.ps1.") from error

    names = PRESSURE + SURFACE + (RAIN,)
    options = {"client_kwargs": {"trust_env": True, "timeout": aiohttp.ClientTimeout(
        total=None, connect=20, sock_read=45)}}
    result = {}
    with zarr.config.set({"async.concurrency": 2}), xr.open_zarr(
        url, consolidated=True, chunks=None, zarr_format=2, storage_options=options,
    ) as source:
        start = source.attrs["valid_time_start"]
        stop = source.attrs.get("valid_time_stop_era5t") or source.attrs["valid_time_stop"]
        first, last = rain_hours[[0, -1]].astype("datetime64[D]")
        if first < np.datetime64(start, "D") or last > np.datetime64(stop, "D"):
            raise ValueError(f"Поля Google ARCO-ERA5 доступны с {start} по {stop} UTC.")
        missing = [name for name in names if name not in source]
        if missing:
            raise ValueError("В Google ARCO-ERA5 отсутствуют поля " + ", ".join(missing))

        for index, name in enumerate(names):
            progress("downloading", f"Поля Google ARCO-ERA5 · {index} из {len(names)}")
            times = rain_hours if name == RAIN else states
            coords = {"time": times, "lat": LATITUDES, "lon": LONGITUDES}
            if name in PRESSURE:
                coords = {"time": times, "level": LEVELS, "lat": LATITUDES, "lon": LONGITUDES}
            shape = tuple(len(values) for values in coords.values())
            path = cache / f"arco-{name}.npy"
            try:
                values = np.load(path, allow_pickle=False) if path.is_file() else None
            except (OSError, ValueError):
                values = None
            if values is None or values.shape != shape or not np.isfinite(values).all():
                field = source[name].rename({"latitude": "lat", "longitude": "lon"})
                field = field.assign_coords(lon=field.lon % 360)
                values = field.sel(coords).transpose(*coords).to_numpy().astype(np.float32, copy=False)
                if not np.isfinite(values).all():
                    raise ValueError(f"В поле {name} из Google ARCO-ERA5 есть пропуски.")
                partial = path.with_suffix(".npy.partial")
                with partial.open("wb") as stream:
                    np.save(stream, values, allow_pickle=False)
                partial.replace(path)
            result[name] = xr.DataArray(values, dims=tuple(coords), coords=coords)
    return result


def prepare_archive(arco_url, reference, static_fields, archive_rain, output):
    reference = np.datetime64(reference, "ns")
    states = reference - np.array([6, 0], dtype="timedelta64[h]")
    rain_hours = reference - np.arange(11, -1, -1, dtype="timedelta64[h]")
    fields = read_arco(arco_url, states, rain_hours, Path(output).parent)
    progress("preparing", "Поля ERA5 собираются в локальный NetCDF для ИИ")
    rain = fields.pop(RAIN).values.reshape(2, 6, LATITUDES.size, LONGITUDES.size)
    with open_netcdf(static_fields) as raw:
        static = raw[["geopotential_at_surface", "land_sea_mask"]]
        static = static.isel({name: 0 for name in ("batch", "time") if name in static.dims}, drop=True)
        static = longitude_grid(static.reset_coords(drop=True)).load()
    lsp = np.fromfile(archive_rain, dtype="<f4").reshape((2, LATITUDES.size, LONGITUDES.size))
    lsp = np.roll(lsp, -180, axis=2) / 1000  # Archive millimetres to model metres, with longitude 0..359.
    fields["total_precipitation_6hr"] = xr.DataArray(
        rain.sum(axis=1) + lsp, dims=("time", "lat", "lon"),
        coords={"time": states, "lat": LATITUDES, "lon": LONGITUDES},
    )
    data = xr.merge([xr.Dataset(fields), static], join="exact")
    if any(not np.isfinite(field.values).all() for field in data.data_vars.values()):
        raise ValueError("В полях для ИИ есть пропуски или бесконечные значения.")
    data.transpose("time", "level", "lat", "lon").to_netcdf(output, engine="scipy", format="NETCDF3_64BIT")


if __name__ == "__main__":
    try:
        prepare_archive(**json.load(sys.stdin))
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
