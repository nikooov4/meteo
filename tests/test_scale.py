import json
from fractions import Fraction

import netCDF4 as nc
import numpy as np
import pytest

from meteo_bridge.oracle import solve_lp
from meteo_bridge.readers import scale_case
from meteo_bridge.resources import safe_data_path, size_bytes
from meteo_bridge.scale_benchmark import run_scale_benchmark, verify_scale_dataset
from meteo_bridge.scale_data import amounts, generate_scale
from meteo_bridge.services import solve_query


def options(output, **extra):
    return dict(
        target_size="110KB",
        output=output,
        series=6,
        series_per_shard=2,
        shard_size="8KB",
        chunk_size="1MiB",
        seed=42,
        memory_limit="2GiB",
        **extra,
    )


def test_scale_resume_workers_and_boundary_query(tmp_path, monkeypatch):
    root = tmp_path / "resumed"
    first = generate_scale(**options(root), max_shards=1)
    assert first["status"] == "interrupted"
    generate_scale(**options(root), workers=2, resume=True)
    mp = root / "manifest.json"
    manifest = json.loads(mp.read_text())
    assert manifest["status"] == "complete"
    assert manifest["data_bytes"] >= 110000
    assert verify_scale_dataset(mp, "full")["status"] == "full_verified"
    from fastapi.testclient import TestClient

    from meteo_bridge.api import app
    from meteo_bridge.catalog import register_manifest

    monkeypatch.setenv("METEOBRIDGE_HOME", str(tmp_path / "api-home"))
    registered = register_manifest("smoke-archive", mp)
    with TestClient(app) as client:
        assert client.get(f"/datasets/{registered['sha256']}/schema").status_code == 200
        response = client.post(
            "/queries",
            json={
                "dataset_id": registered["sha256"],
                "selection": {"series_id": 0, "first_hour": 1, "hours": 6},
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["checker"]["valid"]
    # Query spans an actual shard boundary for amount series, with a halo-free exact oracle.
    boundary = manifest["config"]["hours_per_shard"]
    if len(manifest["shards"]) >= 4:
        case, _ = scale_case(mp, 0, boundary - 2, 4)
        bundle = solve_query(case)
        assert bundle["checker"]["valid"]
        assert len(case.observations) == 4
        lp = solve_lp(case)
        assert float(Fraction(bundle["result"]["lower"])) == pytest.approx(lp["documented"]["lower"])
    clean = tmp_path / "clean"
    generate_scale(**options(clean), workers=1)
    second = json.loads((clean / "manifest.json").read_text())
    assert manifest["config_hash"] == second["config_hash"]
    for a, b in zip(manifest["shards"], second["shards"]):
        with nc.Dataset(root / a["path"]) as x, nc.Dataset(clean / b["path"]) as y:
            np.testing.assert_equal(x.variables["precipitation"][:], y.variables["precipitation"][:])
            np.testing.assert_equal(x.variables["qc"][:], y.variables["qc"][:])
    report = tmp_path / "report"
    interrupted = run_scale_benchmark(mp, output=report, sizes="smoke", query_count=2, stop_after_shards=1)
    assert interrupted["profiles"][0]["status"] == "interrupted"
    resumed = run_scale_benchmark(mp, output=report, sizes="smoke", query_count=2, resume=True)
    assert resumed["profiles"][0]["status"] == "complete", resumed
    saved = json.loads((report / "scale_report.json").read_text())
    assert saved["profiles"][0]["scan"]["resume_count"] == 1
    assert len(set(saved["profiles"][0]["scan"]["completed"])) == len(manifest["shards"])


@pytest.mark.parametrize("format,compression", [("netcdf", "zlib"), ("parquet", "none"), ("parquet", "zstd")])
def test_storage_profiles(tmp_path, format, compression):
    generate_scale(**options(tmp_path), format=format, compression=compression)
    mp = tmp_path / "manifest.json"
    assert verify_scale_dataset(mp)["status"] == "full_verified"
    case, _ = scale_case(mp, 0, 1, 6)
    assert solve_query(case)["checker"]["valid"]


def test_dry_run_budgets_dedup_and_padding(tmp_path):
    assert size_bytes("200GB") == 200000000000
    assert size_bytes("200GiB") == 214748364800
    dry = generate_scale(output=tmp_path / "absent", dry_run=True)
    assert dry["status"] == "dry_run" and not (tmp_path / "absent").exists()
    with pytest.raises(ValueError, match="memory"):
        generate_scale(output=tmp_path, workers=4, chunk_size="256MiB", dry_run=True)
    with pytest.raises(OSError, match="disk budget"):
        generate_scale(**options(tmp_path), disk_budget="1KB")
    generate_scale(**options(tmp_path))
    mp = tmp_path / "manifest.json"
    manifest = json.loads(mp.read_text())
    shard = tmp_path / manifest["shards"][0]["path"]
    with shard.open("ab") as f:
        f.write(b"padding")
    assert verify_scale_dataset(mp)["status"] == "failed"
    with pytest.raises(ValueError):
        safe_data_path(tmp_path, "../outside.nc")


def test_cumulative_chunk_halo_and_coordinate_truth():
    from meteo_bridge.scale_data import generated_chunk

    config = {"series": 6, "series_per_shard": 2, "seed": 42, "missing_fraction": 0, "defect_fraction": 0}
    _, _, a, _ = generated_chunk(config, 1, 5, 13)
    _, _, b, _ = generated_chunk(config, 1, 18, 7)
    ids = np.array([2, 3])
    truth = amounts(42, ids, np.arange(25))
    assert np.allclose(a[-1], truth[:18].sum(axis=0) / 100)
    assert np.allclose(b[0] - a[-1], truth[18] / 100)
    assert np.allclose(b[-1], truth[24] / 100)  # actual reset at midnight, not chunk start


def test_future_cumulative_total_bounds_missing_earlier_hour(tmp_path):
    from fractions import Fraction

    from meteo_bridge.resources import atomic_json, sha256_file

    generate_scale(
        target_size="70KB",
        output=tmp_path,
        series=3,
        series_per_shard=1,
        shard_size="8KB",
        chunk_size="1MiB",
        missing_fraction=0,
        defect_fraction=0,
    )
    mp = tmp_path / "manifest.json"
    manifest = json.loads(mp.read_text())
    cumulative = next(s for s in manifest["shards"] if s["scheme"] == 1)
    with nc.Dataset(tmp_path / cumulative["path"], "a") as ds:
        ds.variables["qc"][:2, 0] = 1
        expected_upper = Fraction(str(round(float(ds.variables["precipitation"][2, 0]), 2)))
    cumulative["sha256"] = sha256_file(tmp_path / cumulative["path"])
    atomic_json(mp, manifest)
    case, _ = scale_case(mp, 1, 0, 1)
    assert len(case.observations) == 24
    result = solve_query(case)["result"]
    assert Fraction(result["lower"]) == 0
    assert Fraction(result["upper"]) == expected_upper
