"""Serve the common FastAPI plus bounded archive frames and local map files."""

import argparse
import json
import os
from pathlib import Path

import uvicorn
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from meteo_bridge.map_archive import MapArchive
from meteo_bridge.precipitation_map import discover_map_sources, load_weather_map, map_html
from meteo_bridge.resources import MemoryGuard, size_bytes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    p.add_argument("--manifest", type=Path, help="default: largest completed local weather-v2 archive")
    p.add_argument("--scale-report", type=Path)
    p.add_argument("--directory", type=Path, default=root / "outputs/maps")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", choices=["127.0.0.1", "localhost"], default="127.0.0.1")
    p.add_argument("--memory-limit", default="16GiB")
    args = p.parse_args()
    if args.manifest is None:
        available = discover_map_sources(root)["synthetic"]
        if not available:
            p.error("No completed local weather-v2 archive found; supply --manifest.")
        args.manifest = max(available, key=lambda path: json.loads(path.read_text(encoding="utf8"))["data_bytes"])
    os.environ["METEOBRIDGE_MAP_MANIFEST"] = str(args.manifest.resolve())
    if args.scale_report:
        os.environ["METEOBRIDGE_MAP_SCALE_REPORT"] = str(args.scale_report.resolve())
    else:
        os.environ.pop("METEOBRIDGE_MAP_SCALE_REPORT", None)
    try:
        archive = MapArchive(args.manifest, args.scale_report)
        first = archive.catalog()["members"][0]
        viewer = map_html(load_weather_map(args.manifest, member=first["member"],
                                           first_hour=first["first_hour"]), "/map-archive")
    except (ValueError, OSError, KeyError) as exc:
        p.error(str(exc))
    from meteo_bridge.api import app

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def current_map():
        return viewer

    if args.directory.is_dir():
        app.mount("/", StaticFiles(directory=args.directory, html=True), name="map files")
    print(f"Map: http://{args.host}:{args.port}/", flush=True)
    with MemoryGuard(min(size_bytes(args.memory_limit), 16*2**30)) as guard:
        app.state.map_memory_guard = guard
        uvicorn.run(app, host=args.host, port=args.port, workers=1, limit_concurrency=8, access_log=False)


if __name__ == "__main__":
    main()
