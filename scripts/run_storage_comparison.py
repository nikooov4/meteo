"""Small, identical logical observations under two storage profiles; never added to 200-GB credit."""

import json
from pathlib import Path

import netCDF4 as nc
import numpy as np

from meteo_bridge.resources import atomic_json, run_metadata
from meteo_bridge.scale_benchmark import run_scale_benchmark
from meteo_bridge.scale_data import generate_scale


def main():
    runs = {}
    for compression in ("none", "zlib"):
        root = Path(f"data/scale/storage-{compression}")
        generated = generate_scale(
            target_size="256KB",
            output=root,
            seed=42,
            series=1024,
            series_per_shard=1024,
            shard_size="16MiB",
            chunk_size="1MiB",
            compression=compression,
            resume=(root / "manifest.json").exists(),
        )
        manifest = json.loads((root / "manifest.json").read_text())
        if len(manifest["shards"]) != 1:
            raise ValueError("comparison must contain identical single-shard logical scope")
        benchmark = run_scale_benchmark(
            root / "manifest.json", output=f"reports/storage-{compression}", sizes="smoke", query_count=4
        )
        runs[compression] = {"generation": generated, "benchmark": benchmark, "manifest": manifest}
    first = runs["none"]["manifest"]["shards"][0]
    second = runs["zlib"]["manifest"]["shards"][0]
    with (
        nc.Dataset(Path("data/scale/storage-none") / first["path"]) as a,
        nc.Dataset(Path("data/scale/storage-zlib") / second["path"]) as b,
    ):
        for start in range(0, len(a.dimensions["time"]), 24):
            for variable in ("precipitation", "qc"):
                np.testing.assert_equal(a[variable][start : start + 24], b[variable][start : start + 24])
    report = {
        "environment": run_metadata(),
        "logical_observations_equal": True,
        "same_family_not_independent_data": True,
        "excluded_from_200GB_credit": True,
        "storage_bytes": {key: value["manifest"]["data_bytes"] for key, value in runs.items()},
        "runs": runs,
    }
    atomic_json("reports/storage_comparison.json", report)
    print(json.dumps({k: v for k, v in report.items() if k not in {"environment", "runs"}}, indent=2))


if __name__ == "__main__":
    main()
