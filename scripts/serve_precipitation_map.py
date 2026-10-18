"""Serve the common FastAPI plus bounded archive frames and local map files."""

import argparse
import os
from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles

from meteo_bridge.resources import MemoryGuard, size_bytes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--scale-report", type=Path)
    p.add_argument("--directory", type=Path, default=Path("outputs/maps"))
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", choices=["127.0.0.1", "localhost"], default="127.0.0.1")
    p.add_argument("--memory-limit", default="16GiB")
    args = p.parse_args()
    os.environ["METEOBRIDGE_MAP_MANIFEST"] = str(args.manifest.resolve())
    if args.scale_report:
        os.environ["METEOBRIDGE_MAP_SCALE_REPORT"] = str(args.scale_report.resolve())
    from meteo_bridge.api import app

    app.mount("/", StaticFiles(directory=args.directory, html=True), name="map files")
    with MemoryGuard(min(size_bytes(args.memory_limit), 16*2**30)) as guard:
        app.state.map_memory_guard = guard
        uvicorn.run(app, host=args.host, port=args.port, workers=1, limit_concurrency=8, access_log=False)


if __name__ == "__main__":
    main()
