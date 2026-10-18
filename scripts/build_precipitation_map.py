"""Create a standalone offline map/animation from one native ERA5 LSP cycle."""

import argparse
import json
from pathlib import Path

from meteo_bridge.precipitation_map import WORLD_BBOX, load_era5_map, load_weather_map, map_html
from meteo_bridge.resources import atomic_json, sha256_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--bbox", type=float, nargs=4, default=WORLD_BBOX, metavar=("WEST", "EAST", "SOUTH", "NORTH"))
    parser.add_argument("--cycle", help="UTC ISO time; default: first initialization")
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--member", type=int, default=0)
    parser.add_argument("--first-hour", type=int, default=0)
    parser.add_argument("--archive-api", help="e.g. /map-archive; enables bounded time selection via local server")
    parser.add_argument("--output", type=Path, default=Path("outputs/maps/era5_lsp_animation.html"))
    args = parser.parse_args()
    if args.input.suffix == ".json":
        data = load_weather_map(args.input, args.bbox, args.member, args.first_hour)
    else:
        data = load_era5_map(args.input, args.bbox, args.cycle, args.frames, allow_downsample=True)
    if args.output.exists():
        parser.error("output already exists; choose a new file to preserve prior/user maps")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(map_html(data, args.archive_api), encoding="utf8")
    metadata = {**data["metadata"], "html_sha256": sha256_file(args.output),
                "html_bytes": args.output.stat().st_size,
                "archive_api": args.archive_api,
                "boundaries_sha256": sha256_file(Path("data/fixtures/natural-earth-110m-geometries.json"))}
    atomic_json(args.output.with_suffix(".json"), metadata)
    print(json.dumps({"output": str(args.output), "frames": metadata["frames"],
                      "selected_values": metadata["selected_values"], "html_bytes": metadata["html_bytes"]}))


if __name__ == "__main__":
    main()
