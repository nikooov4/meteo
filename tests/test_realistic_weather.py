import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import netCDF4 as nc
import numpy as np
import pytest

from meteo_bridge.precipitation_map import WORLD_BBOX, load_weather_map, map_html, precipitation_figure
from meteo_bridge.readers import scale_case
from meteo_bridge.realistic_weather import WeatherModel, calibrate, generate_weather
from meteo_bridge.scale_benchmark import run_scale_benchmark, verify_scale_dataset
from meteo_bridge.services import solve_query
from meteo_bridge.weather_validation import validate_weather


@pytest.fixture
def calibration(tmp_path):
    path = tmp_path / "e5.oper.fc.sfc.accumu.128_142_lsp.ll025sc.2023010106_2023011606.nc"
    with nc.Dataset(path, "w") as ds:
        for name, n in (("forecast_initial_time", 4), ("forecast_hour", 12), ("latitude", 2), ("longitude", 4)):
            ds.createDimension(name, n)
        tv = ds.createVariable("forecast_initial_time", "i8", ("forecast_initial_time",))
        tv.units = "hours since 2023-01-01 00:00:00"
        tv[:] = [6, 18, 11*24+6, 11*24+18]
        ds.createVariable("forecast_hour", "i4", ("forecast_hour",))[:] = np.arange(1, 13)
        ds.createVariable("latitude", "f4", ("latitude",))[:] = [45, -45]
        ds.createVariable("longitude", "f4", ("longitude",))[:] = [45, 135, 225, 315]
        v = ds.createVariable("LSP", "f4", ("forecast_initial_time", "forecast_hour", "latitude", "longitude"))
        v.units, v.rda_dataset = "m", "ds633.0"
        x = np.arange(12*8).reshape(12, 2, 4) / 100000
        x[:, 0, 0] = 0
        v[0], v[1], v[2], v[3] = x, x*2, x*3, x*4
    out = tmp_path / "calibration"
    calibrate([path], out, spacing=90)
    # Python/JSON paths support Unicode. The installed Windows NetCDF/HDF5
    # build requires ASCII directories for native data files (documented).
    manifest = out / "калибровка.json"
    (out / "manifest.json").rename(manifest)
    return manifest


def test_calibration_separates_whole_cycles_and_generator_cannot_read_holdout(calibration):
    meta = json.loads(calibration.read_text(encoding="utf8"))
    assert meta["banks"]["train"]["blocks"] == meta["banks"]["holdout"]["blocks"] == 2
    init = int(datetime(2023, 1, 12, 6, tzinfo=timezone.utc).timestamp())
    model = WeatherModel(calibration)
    try:
        x, info = model.block(init)
        y, _ = model.block(init)
        z, _ = model.block(init, 1)
        assert np.array_equal(x, y) and not np.array_equal(x, z)
        assert info["training_initialization"] == int(model.inits[0])
        assert (x >= 0).all()
        with pytest.raises(ValueError, match="no training data"):
            model.block(int(datetime(2023, 2, 1, 6, tzinfo=timezone.utc).timestamp()))
    finally:
        model.close()
    # Generation requires only the training bank, even after holdout is removed.
    holdout = calibration.parent / "holdout.nc"
    holdout.rename(holdout.with_suffix(".unused"))
    model = WeatherModel(calibration)
    try:
        assert np.array_equal(model.block(init)[0], x)
    finally:
        model.close()


def test_weather_resume_global_map_and_exact_member_cycle_queries(calibration, tmp_path):
    params = dict(calibration=calibration, target_size="150KB", days_per_member=1, cycles_per_shard=1)
    out = tmp_path / "weather"
    first = generate_weather(**params, output=out, max_shards=1)
    assert first["status"] == "interrupted"
    resumed = generate_weather(**params, output=out, resume=True)
    fresh = generate_weather(**params, output=tmp_path / "fresh")
    assert [s["sha256"] for s in resumed["shards"]] == [s["sha256"] for s in fresh["shards"]]
    assert verify_scale_dataset(out / "manifest.json")["status"] == "full_verified"
    case, _ = scale_case(out / "manifest.json", 0, 1, 6)
    other, _ = scale_case(out / "manifest.json", 8, 1, 6)
    assert case.query.series != other.query.series
    assert case.query.series.quantity == "large_scale_precipitation"
    bundle = solve_query(case)
    assert bundle["checker"]["valid"] and bundle["result"]["status"] == "certified"
    assert bundle["result"]["lower"] == bundle["result"]["upper"]
    with pytest.raises(ValueError, match="distinct synthetic cycles"):
        scale_case(out / "manifest.json", 0, 10, 6)
    data = load_weather_map(out / "manifest.json")
    assert data["metadata"]["bbox"] == list(WORLD_BBOX)
    assert data["amounts_mm"].shape == (12, 2, 4)
    fig = precipitation_figure(data)
    assert fig.layout.dragmode == "pan" and len(fig.frames) == 12
    assert "СИНТЕТИКА" in fig.layout.title.text
    assert '"scrollZoom": true' in map_html(data)
    assert fig.layout.updatemenus[0].buttons[-1].method == "relayout"
    report = run_scale_benchmark(out / "manifest.json", output=tmp_path / "benchmark", sizes="smoke", query_count=2)
    assert not report["errors"]
    saved = json.loads(Path(report["report"]).read_text())
    assert len(saved["profiles"][0]["queries"]) == 4
    assert all(q["bundle"]["checker"]["valid"] and q["generating_truth_in_bounds"]
               for q in saved["profiles"][0]["queries"])


def test_weather_holdout_diagnostic_and_dry_run(calibration, tmp_path):
    result = validate_weather(calibration, tmp_path / "diagnostic.json")
    assert result["heldout_cycles"] == 2 and result["train_holdout_intersection"] == 0
    assert set(result["metrics"]) == {"real_heldout", "legacy_v1", "unperturbed_block_bootstrap", "weather_v2"}
    dest = tmp_path / "not-created"
    plan = generate_weather(calibration, dest, target_size="200GB", dry_run=True)
    assert plan["target_bytes"] == 200_000_000_000 and not dest.exists()
    assert plan["calibration_check"] == {"training_bank_exists": True, "netcdf_open": True,
                                         "sha256": "not_checked_in_dry_run"}


def test_weather_dry_run_rejects_missing_training_payload(calibration, tmp_path):
    train = calibration.parent / "train.nc"
    train.rename(train.with_suffix(".saved"))
    dest = tmp_path / "not-created"
    with pytest.raises(FileNotFoundError, match="Calibration training bank is missing"):
        generate_weather(calibration, dest, dry_run=True)
    assert not dest.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows native-path diagnostic")
def test_existing_unicode_training_bank_gets_actionable_native_error(calibration, tmp_path, monkeypatch):
    copied = tmp_path / "Погода"
    copied.mkdir()
    manifest = copied / "manifest.json"
    shutil.copyfile(calibration, manifest)
    shutil.copyfile(calibration.parent / "train.nc", copied / "train.nc")
    assert (copied / "train.nc").is_file()

    def native_failure(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory")

    monkeypatch.setattr(nc, "Dataset", native_failure)
    dest = tmp_path / "not-created"
    with pytest.raises(OSError, match="non-ASCII paths"):
        generate_weather(manifest, dest, dry_run=True)
    assert not dest.exists()


def test_archive_time_selection_reads_only_one_frame_and_separates_cycles(calibration, tmp_path):
    from meteo_bridge.map_archive import MapArchive

    out = tmp_path / "archive"
    manifest = generate_weather(calibration, out, target_size="200KB", days_per_member=2, cycles_per_shard=1)
    archive = MapArchive(out / "manifest.json")
    catalog = archive.catalog()
    assert len(catalog["members"]) >= 2
    selected = archive.selection(0, "2023-01-01T17:00:00Z", "2023-01-01T20:00:00Z")
    assert selected["first_hour"] == 11 and selected["hours"] == 3
    first, h1 = archive.frame(0, 11)
    second, h2 = archive.frame(0, 12)
    assert len(first) == len(second) == 8*4
    assert h1["X-Cycle-UTC"] != h2["X-Cycle-UTC"]
    assert archive.stats["logical_data_bytes"] == 2*8*9
    with nc.Dataset(out / manifest["shards"][1]["path"]) as ds:
        expected = np.asarray(ds.variables["precipitation"][0], dtype="float32")
    assert np.array_equal(np.frombuffer(second, dtype="<f4"), expected)
    with pytest.raises(ValueError, match="outside"):
        archive.selection(0, "2023-01-03T06:00:00Z", "2023-01-03T07:00:00Z")
    with pytest.raises(ValueError, match="complete hourly"):
        archive.selection(0, "2023-01-01T06:30:00Z", "2023-01-01T07:00:00Z")


def test_map_archive_api_rejects_changed_identity_and_invalid_ranges(calibration, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from meteo_bridge.api import app

    out = tmp_path / "api-archive"
    generate_weather(calibration, out, target_size="200KB", days_per_member=2, cycles_per_shard=1)
    monkeypatch.setenv("METEOBRIDGE_MAP_MANIFEST", str(out / "manifest.json"))
    monkeypatch.delenv("METEOBRIDGE_MAP_SCALE_REPORT", raising=False)
    client = TestClient(app)
    catalog = client.get("/map-archive/catalog").json()
    response = client.get("/map-archive/frame", params={"hour": 12, "member": 1,
                                                       "manifest_sha256": catalog["manifest_sha256"]})
    assert response.status_code == 200 and len(response.content) == 32
    assert response.headers["X-Member"] == "1"
    assert client.get("/map-archive/frame", params={"hour": 0, "manifest_sha256": "changed"}).status_code == 409
    assert client.get("/map-archive/range", params={"start": "2023-01-01T06:00:00Z",
                                                   "end": "2023-01-01T06:00:00Z"}).status_code == 422
    assert client.get("/map-archive/frame", params={"hour": -1,
                                                    "manifest_sha256": catalog["manifest_sha256"]}).status_code == 422
    assert client.get("/map-archive/metrics").json()["frame_requests"] == 1
