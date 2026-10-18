"""Create a standalone offline map/animation from one native ERA5 LSP cycle."""

import argparse
import json
from pathlib import Path

from meteo_bridge.precipitation_map import DEFAULT_BBOX, load_era5_map, map_html
from meteo_bridge.resources import atomic_json, sha256_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--bbox", type=float, nargs=4, default=DEFAULT_BBOX, metavar=("WEST", "EAST", "SOUTH", "NORTH"))
    parser.add_argument("--cycle", help="UTC ISO time; default: first initialization")
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--output", type=Path, default=Path("outputs/maps/era5_lsp_animation.html"))
    args = parser.parse_args()
    data = load_era5_map(args.input, args.bbox, args.cycle, args.frames)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(map_html(data), encoding="utf8")
    metadata = {**data["metadata"], "html_sha256": sha256_file(args.output),
                "html_bytes": args.output.stat().st_size,
                "boundaries_sha256": sha256_file(Path("data/fixtures/natural-earth-110m-geometries.json"))}
    atomic_json(args.output.with_suffix(".json"), metadata)
    print(json.dumps({"output": str(args.output), "frames": metadata["frames"],
                      "selected_values": metadata["selected_values"], "html_bytes": metadata["html_bytes"]}))


if __name__ == "__main__":
    main()
