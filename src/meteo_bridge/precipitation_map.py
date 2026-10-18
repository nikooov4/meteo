"""Bounded offline visualization of documented NSF NCAR ERA5 HRES LSP amounts."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import netCDF4 as nc
import numpy as np
import plotly.graph_objects as go

DEFAULT_BBOX = (-15.0, 65.0, 35.0, 72.0)
WORLD_BBOX = (-180.0, 180.0, -90.0, 90.0)
GEOMETRY = Path(__file__).resolve().parents[2] / "data/fixtures/natural-earth-110m-geometries.json"


def _datetime(value):
    return datetime(value.year, value.month, value.day, value.hour, value.minute, value.second,
                    tzinfo=timezone.utc)


def load_era5_map(path, bbox=DEFAULT_BBOX, cycle=None, frame_limit=12, max_cells=1_000_000,
                  allow_downsample=False):
    """Select one initialization and a small native grid; never interpolate time."""
    west, east, south, north = map(float, bbox)
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("Нужны west < east в [-180,180] и south < north в [-90,90].")
    if not 1 <= frame_limit <= 12 or not 1 <= max_cells <= 2_000_000:
        raise ValueError("Лимит карты: 1–12 кадров и до 2 миллионов значений.")
    path = Path(path)
    with nc.Dataset(path) as ds:
        v = ds.variables["LSP"]
        if (v.dimensions != ("forecast_initial_time", "forecast_hour", "latitude", "longitude") or
                getattr(v, "units", None) != "m" or getattr(v, "rda_dataset", None) != "ds633.0"):
            raise ValueError("Поддерживается NSF NCAR ERA5 LSP ds633.0 в m с известной hourly convention.")
        tv = ds.variables["forecast_initial_time"]
        calendar = getattr(tv, "calendar", "standard")
        if calendar not in ("standard", "gregorian", "proleptic_gregorian"):
            raise ValueError("Неподдерживаемый календарь карты.")
        initializations = [_datetime(t) for t in nc.num2date(tv[:], tv.units, calendar)]
        if not initializations:
            raise ValueError("В файле нет циклов ERA5.")
        chosen = initializations[0] if not cycle else datetime.fromisoformat(cycle.replace("Z", "+00:00"))
        if chosen.tzinfo is None or chosen not in initializations:
            raise ValueError("Цикл должен содержать UTC offset и присутствовать в файле.")
        ci = initializations.index(chosen)
        hours = np.asarray(ds.variables["forecast_hour"][:frame_limit], dtype=float)
        if not np.array_equal(hours, np.arange(1, len(hours)+1)):
            raise ValueError("Ожидаются последовательные почасовые шаги ERA5 HRES, начиная с 1.")
        lat = np.asarray(ds.variables["latitude"][:], dtype=float)
        lon = (np.asarray(ds.variables["longitude"][:], dtype=float)+180) % 360 - 180
        yi = np.flatnonzero((lat >= south) & (lat <= north))
        xi = np.flatnonzero((lon >= west) & (lon <= east))
        yi, xi = yi[np.argsort(lat[yi])], xi[np.argsort(lon[xi])]
        count = len(hours)*len(yi)*len(xi)
        if not count:
            raise ValueError("В выбранной области нет данных.")
        if count > max_cells:
            if not allow_downsample:
                raise ValueError(f"Область слишком велика: {count} значений; уменьшите её или число кадров.")
            stride = int(np.ceil(np.sqrt(count / max_cells)))
            while len(hours)*len(yi[::stride])*len(xi[::stride]) > max_cells:
                stride += 1
            yi, xi = yi[::stride], xi[::stride]
            count = len(hours)*len(yi)*len(xi)
        else:
            stride = 1
        # Native compressed chunks may cover the global grid for ONE cycle.
        # The cache is bounded; only the requested hyperslab is retained.
        v.set_var_chunk_cache(64*2**20, 1009, 0.5)
        amounts = np.asarray(np.ma.filled(v[ci, :len(hours), yi, xi], np.nan), dtype="float32")
        amounts *= 1000  # encoded previous-hour amount, m -> mm; no deaccumulation
        rejected = ~np.isfinite(amounts) | (amounts < 0)
        amounts[rejected] = np.nan
    intervals = [(chosen+timedelta(hours=float(h)-1), chosen+timedelta(hours=float(h))) for h in hours]
    metadata = {"source_file": str(path.resolve()), "source_bytes": path.stat().st_size,
                "source_mtime_ns": path.stat().st_mtime_ns,
                "origin": "original", "product": "NSF NCAR ERA5 LSP ds633.0",
                "quantity": "large_scale_precipitation", "unit": "mm",
                "semantics": "ERA5_HRES_previous_hour_amount", "cycle_utc": chosen.isoformat(),
                "bbox": [west, east, south, north], "frames": len(hours),
                "grid_shape": [len(yi), len(xi)], "selected_values": count,
                "retained_array_bytes": amounts.nbytes, "masked_or_negative_values": int(rejected.sum()),
                "intervals_utc": [[a.isoformat(), b.isoformat()] for a, b in intervals],
                "scope": "visualization only; not a Query certificate, total precipitation or station observation",
                "spatial_sampling_stride": stride, "display_label": "ERA5 LSP · архивные данные",
                "temporal_interpolation": False}
    return {"longitude": lon[xi], "latitude": lat[yi], "amounts_mm": amounts, "metadata": metadata}


def load_weather_map(manifest, bbox=WORLD_BBOX, member=0, first_hour=0, max_cells=1_000_000):
    """One synthetic cycle, bounded reading, explicit member and cycle identity."""
    from .realistic_weather import SCHEMA
    from .resources import safe_data_path, sha256_file

    mp = Path(manifest)
    meta = json.loads(mp.read_text(encoding="utf8"))
    if meta["schema"] != SCHEMA or first_hour < 0 or first_hour % 12:
        raise ValueError("Нужен manifest синтетики v2 и начало отдельного 12-часового цикла.")
    west, east, south, north = map(float, bbox)
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90) or max_cells < 12:
        raise ValueError("Некорректная область карты или лимит значений.")
    selected = [s for s in meta["shards"] if s["member"] == member and s["first_hour"] <= first_hour
                and first_hour + 12 <= s["first_hour"] + s["hours"]]
    if len(selected) != 1:
        raise ValueError("Этот member/cycle отсутствует в подготовленных shards.")
    s = selected[0]
    path = safe_data_path(mp.parent, s["path"])
    if sha256_file(path) != s["sha256"]:
        raise ValueError("Checksum выбранного shard не совпал.")
    with nc.Dataset(path) as ds:
        lat = np.unique(ds.variables["latitude"][:])
        lon = np.unique(ds.variables["longitude"][:])
        yi, xi = np.flatnonzero((lat >= south) & (lat <= north)), np.flatnonzero((lon >= west) & (lon <= east))
        stride = 1
        while 12 * len(yi[::stride]) * len(xi[::stride]) > max_cells:
            stride += 1
        yi, xi = yi[::stride], xi[::stride]
        if not len(yi) or not len(xi):
            raise ValueError("В области нет ячеек.")
        ids = (yi[:, None] * len(lon) + xi).ravel()
        start = first_hour - s["first_hour"]
        v = ds.variables["precipitation"]
        v.set_var_chunk_cache(4*2**20, 1009, .5)
        z = np.asarray(v[start:start+12, ids], dtype="float32").reshape(12, len(yi), len(xi))
        qc = np.asarray(ds.variables["qc"][start:start+12, ids]).reshape(z.shape)
        z[(qc != 0) | (z < 0)] = np.nan
    init = datetime.fromtimestamp(meta["config"]["start"] + first_hour*3600, timezone.utc)
    intervals = [[(init+timedelta(hours=h)).isoformat(), (init+timedelta(hours=h+1)).isoformat()]
                 for h in range(12)]
    metadata = {"origin": "synthetic", "schema": SCHEMA, "quantity": "large_scale_precipitation",
                "product": "monthly block-bootstrap ERA5 LSP", "unit": "mm", "member": member,
                "cycle_utc": init.isoformat(), "intervals_utc": intervals, "bbox": list(bbox),
                "display_label": "СИНТЕТИКА v2 · LSP · не прогноз", "frames": 12,
                "source_file": str(path.resolve()), "source_sha256": s["sha256"],
                "manifest_sha256": sha256_file(mp), "grid_shape": [len(yi), len(xi)],
                "selected_values": int(z.size), "retained_array_bytes": z.nbytes,
                "spatial_sampling_stride": stride, "temporal_interpolation": False,
                "scope": "synthetic intensity-perturbed training cycle; no new independent weather evidence"}
    return {"longitude": lon[xi], "latitude": lat[yi], "amounts_mm": z, "metadata": metadata}


def _outlines(bbox):
    west, east, south, north = bbox
    x, y = [], []
    for geometry in json.loads(GEOMETRY.read_text(encoding="utf8"))["geometries"]:
        polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
        for polygon in polygons:
            for ring in polygon:
                previous = None
                for lon, lat in ring:
                    if previous is not None and abs(lon - previous) > 180:
                        x.append(None)
                        y.append(None)
                    previous = lon
                    if west-2 <= lon <= east+2 and south-2 <= lat <= north+2:
                        x.append(lon)
                        y.append(lat)
                    else:
                        x.append(None)
                        y.append(None)
                x.append(None)
                y.append(None)
    return go.Scatter(x=x, y=y, mode="lines", line={"color": "#49556b", "width": 0.8},
                      hoverinfo="skip", showlegend=False)


def precipitation_figure(data):
    meta, z = data["metadata"], data["amounts_mm"]
    if not np.isfinite(z).any():
        raise ValueError("В области нет пригодных значений осадков.")
    top = max(float(np.nanmax(z)), 0.1)
    thresholds = [(0, "#edf5fa"), (.1, "#bee8ed"), (.5, "#61c9ae"), (1, "#3d9bd3"),
                  (2, "#4865bd"), (5, "#8b4ca8"), (10, "#cf6896"), (20, "#e6a34b")]
    colors = [[value/top, color] for value, color in thresholds if value < top]
    colors.append([1, next((color for value, color in thresholds if value >= top), thresholds[-1][1])])

    def title(i):
        a, b = meta["intervals_utc"][i]
        label = meta.get("display_label", "ERA5 LSP · архивные данные")
        return {"text": f"Осадки за час · {label}<br><sup>{a[:16]} — {b[:16]} UTC</sup>",
                "x": 0.04}

    heatmap = go.Heatmap(x=data["longitude"], y=data["latitude"], z=z[0], coloraxis="coloraxis",
                        zsmooth=False, connectgaps=False, hoverongaps=False,
                        hovertemplate="%{y:.2f}°N, %{x:.2f}°E<br>%{z:.4f} mm за час<extra></extra>")
    fig = go.Figure([heatmap, _outlines(meta["bbox"])])
    cities = [("Москва", 37.62, 55.75), ("Санкт-Петербург", 30.32, 59.94), ("Минск", 27.56, 53.90),
              ("Берлин", 13.40, 52.52), ("Варшава", 21.01, 52.23), ("Рим", 12.50, 41.90)]
    west, east, south, north = meta["bbox"]
    if east-west > 160:
        cities = [("Москва", 37.62, 55.75), ("Нью-Йорк", -74, 40.7), ("Рио", -43.2, -22.9),
                  ("Кейптаун", 18.4, -33.9), ("Дели", 77.2, 28.6), ("Токио", 139.7, 35.7),
                  ("Сидней", 151.2, -33.9)]
    cities = [(name, x, y) for name, x, y in cities if west <= x <= east and south <= y <= north]
    if cities:
        fig.add_trace(go.Scatter(x=[c[1] for c in cities], y=[c[2] for c in cities], text=[c[0] for c in cities],
                                mode="markers+text", textposition="top right", textfont={"size": 11},
                                marker={"size": 5, "color": "#29354b"}, hoverinfo="text", showlegend=False))
    fig.frames = [go.Frame(name=str(i), data=[go.Heatmap(z=values)], traces=[0],
                           layout={"title": title(i)}) for i, values in enumerate(z)]
    immediate = {"mode": "immediate", "frame": {"duration": 0, "redraw": True}, "transition": {"duration": 0}}
    fig.update_layout(
        title=title(0), template="plotly_white", height=760, font={"family": "Segoe UI, Arial"},
        dragmode="pan", uirevision="keep-map-zoom",
        margin={"l": 65, "r": 55, "t": 90, "b": 155}, plot_bgcolor="#d4dbe4",
        coloraxis={"cmin": 0, "cmax": top, "colorscale": colors, "colorbar": {"title": "mm за час"}},
        xaxis={"title": "Долгота, °E", "range": [west, east], "showgrid": False, "zeroline": False,
               "constrain": "domain"},
        yaxis={"title": "Широта, °N", "range": [south, north], "showgrid": False, "zeroline": False,
               "scaleanchor": "x", "scaleratio": 1/np.cos(np.radians((south+north)/2)), "constrain": "domain"},
        updatemenus=[{"type": "buttons", "direction": "left", "x": 0, "y": -0.13,
                      "buttons": [{"label": "▶ Воспроизвести", "method": "animate",
                                   "args": [None, {"fromcurrent": True, "frame": {"duration": 650, "redraw": True},
                                                   "transition": {"duration": 0}}]},
                                  {"label": "Ⅱ Пауза", "method": "animate", "args": [[None], immediate]},
                                  {"label": "🌐 Весь мир / сброс", "method": "relayout",
                                   "args": [{"xaxis.range": [west, east], "yaxis.range": [south, north]}]}]}],
        sliders=[{"x": 0, "y": -0.03, "len": 1, "currentvalue": {"prefix": "Конец часа UTC: "},
                  "steps": [{"label": b[11:16], "method": "animate", "args": [[str(i)], immediate]}
                            for i, (a, b) in enumerate(meta["intervals_utc"])]}],
        annotations=[{"text": "LSP · один 12-часовой цикл · колёсико: зум, перетаскивание: сдвиг · сетка не детализируется при зуме",
                      "xref": "paper", "yref": "paper", "x": 0, "y": -0.28, "showarrow": False,
                      "font": {"size": 11, "color": "#64748b"}}])
    return fig


def map_html(data):
    return precipitation_figure(data).to_html(include_plotlyjs=True, full_html=True, auto_play=False,
                                             config={"displaylogo": False, "responsive": True, "scrollZoom": True,
                                                     "toImageButtonOptions": {"filename": "precipitation_map"}})
