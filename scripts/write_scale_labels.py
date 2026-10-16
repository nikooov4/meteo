import argparse
import json
from pathlib import Path

from meteo_bridge.resources import atomic_json
from meteo_bridge.scale_data import write_truth_labels

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if manifest["status"] != "complete" or manifest["origin"] != "synthetic":
        raise ValueError("completed synthetic manifest required")
    manifest["truth_labels"] = write_truth_labels(manifest, args.manifest.parent)
    atomic_json(args.manifest, manifest)
