"""Prepare a versioned global LSP training/held-out bank from public ERA5 files."""

import argparse
import json
from pathlib import Path

from meteo_bridge.realistic_weather import calibrate, download_references


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sources", type=Path, nargs="*", default=[])
    p.add_argument("--download", action="store_true")
    p.add_argument("--download-only", action="store_true")
    p.add_argument("--references", type=Path, default=Path("data/real/era5-weather-reference"))
    p.add_argument("--months", default="1,2,3,4,5,6,7,8,9,10,11,12")
    p.add_argument("--year", type=int, default=2023)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--spacing", type=float, default=1.)
    p.add_argument("--memory-limit", default="2GiB")
    a = p.parse_args()
    sources = a.sources
    if a.download:
        sources += download_references(a.references, a.year, [int(m) for m in a.months.split(",")])
    if not sources:
        p.error("provide --sources or --download")
    if a.download_only:
        print(json.dumps({"status": "download_complete", "files": len(sources)}))
        return
    result = calibrate(sources, a.output, a.spacing, memory_limit=a.memory_limit)
    print(json.dumps({"schema": result["schema"], "banks": result["banks"], "months": result["months"]}))


if __name__ == "__main__":
    main()
