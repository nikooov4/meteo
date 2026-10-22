import netCDF4 as nc
import numpy as np
import pytest

from meteo_bridge.precipitation_map import discover_map_sources, load_era5_map, map_html, precipitation_figure


@pytest.fixture
def native_grid(tmp_path):
    path = tmp_path / "controlled-lsp.nc"
    with nc.Dataset(path, "w") as ds:
        for name, n in [("forecast_initial_time", 2), ("forecast_hour", 3), ("latitude", 2), ("longitude", 3)]:
            ds.createDimension(name, n)
        t = ds.createVariable("forecast_initial_time", "i8", ("forecast_initial_time",))
        t.units = "hours since 2023-01-01 06:00:00"
        t[:] = [0, 12]
        ds.createVariable("forecast_hour", "i4", ("forecast_hour",))[:] = [1, 2, 3]
        ds.createVariable("latitude", "f8", ("latitude",))[:] = [42, 40]
        ds.createVariable("longitude", "f8", ("longitude",))[:] = [0, 1, 359]
        v = ds.createVariable("LSP", "f4", ("forecast_initial_time", "forecast_hour", "latitude", "longitude"))
        v.units, v.rda_dataset = "m", "ds633.0"
        v[:] = .003
        v[0, 0, 0, 0] = .002
        v[0, 1, 0, 0] = .001  # decreasing HOURLY amounts, not cumulative
        v[1, :, :, :] = .009  # different cycle must not enter the first map
        v[0, 2, 1, 1] = -1
    return path


def test_native_map_preserves_hour_amounts_and_separates_cycles(native_grid):
    data = load_era5_map(native_grid, (-2, 2, 39, 43))
    assert data["longitude"].tolist() == [-1, 0, 1]
    assert data["latitude"].tolist() == [40, 42]
    assert data["amounts_mm"][:, 1, 1] == pytest.approx([2, 1, 3])
    assert np.isnan(data["amounts_mm"][2, 0, 2])
    assert data["metadata"]["masked_or_negative_values"] == 1
    assert data["metadata"]["intervals_utc"][0] == ["2023-01-01T06:00:00+00:00", "2023-01-01T07:00:00+00:00"]
    second = load_era5_map(native_grid, (-2, 2, 39, 43), cycle="2023-01-01T18:00:00Z")
    assert np.nanmax(second["amounts_mm"]) == pytest.approx(9)


def test_native_map_reads_unicode_path_without_copying(native_grid, tmp_path):
    directory = tmp_path / "данные осадков"
    directory.mkdir()
    path = native_grid.rename(directory / "осадки.nc")
    data = load_era5_map(path, (-2, 2, 39, 43))
    assert data["amounts_mm"][:, 1, 1] == pytest.approx([2, 1, 3])
    assert data["metadata"]["source_file"] == str(path.resolve())
    assert list(directory.iterdir()) == [path]


def test_map_source_discovery_after_relocation(tmp_path, monkeypatch):
    import json

    real = tmp_path / "data/real/era5-weather-reference/e5.oper.fc.sfc.accumu.128_142_lsp.january.nc"
    real.parent.mkdir(parents=True)
    real.touch()
    manifest = tmp_path / "data/scale/weather-global-10gb-v2/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"schema": "meteobridge-weather-bootstrap-v2", "status": "complete",
                                    "shards": [{"path": "weather-000000.nc"}]}), encoding="utf8")
    unrelated = tmp_path / "data/scale/legacy/manifest.json"
    unrelated.parent.mkdir()
    unrelated.write_text('{"schema":"legacy-v1"}', encoding="utf8")
    monkeypatch.chdir(tmp_path.parent)
    assert discover_map_sources(tmp_path) == {"real": [real.resolve()], "synthetic": [manifest.resolve()]}


def test_map_rejects_excessive_selection_and_unknown_conventions(native_grid):
    with pytest.raises(ValueError, match="слишком велика"):
        load_era5_map(native_grid, (-2, 2, 39, 43), max_cells=5)
    with pytest.raises(ValueError, match="west < east"):
        load_era5_map(native_grid, (2, -2, 39, 43))
    with pytest.raises(ValueError, match="UTC offset"):
        load_era5_map(native_grid, (-2, 2, 39, 43), cycle="2023-01-01T06:00:00")
    with nc.Dataset(native_grid, "a") as ds:
        ds.variables["LSP"].units = "unknown"
    with pytest.raises(ValueError, match="NCAR ERA5"):
        load_era5_map(native_grid)


def test_map_animation_uses_shared_scale_and_no_temporal_smoothing(native_grid):
    data = load_era5_map(native_grid, (-2, 2, 39, 43))
    fig = precipitation_figure(data)
    assert len(fig.frames) == 3
    assert len(fig.layout.sliders[0].steps) == 3
    assert fig.data[0].zsmooth is False and fig.data[0].connectgaps is False
    assert fig.layout.coloraxis.cmin == 0
    assert fig.layout.updatemenus[0].buttons[0].args[1]["transition"]["duration"] == 0
    html = map_html(data)
    assert "cdn.plot.ly" not in html.split("</script>")[-1]
    assert '<script src="' not in html  # JS and map outlines are bundled, no remote basemap


def test_streamlit_map_view(native_grid, tmp_path, monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("METEOBRIDGE_HOME", str(tmp_path / "catalog"))
    at = AppTest.from_file(Path("ui/app.py").resolve(), default_timeout=60).run()
    at.sidebar.radio[0].set_value("Карта осадков").run()
    next(t for t in at.text_input if t.label == "Папка или файл NCAR ERA5 LSP").set_value(str(native_grid)).run()
    next(b for b in at.button if b.label == "Построить карту").click().run()
    assert not at.exception and not at.error
    assert at.session_state.precipitation_map[1]["animation_hours"] == 15
    assert at.session_state.precipitation_map[1]["selection"]["gap_hours"] == 9
    assert at.session_state.precipitation_map_url.startswith("http://127.0.0.1:")


def test_real_archive_crosses_files_and_preserves_empty_hours(native_grid, tmp_path):
    import shutil

    from meteo_bridge.era5_map_archive import Era5MapArchive, era5_files

    later = tmp_path / "later.nc"
    shutil.copyfile(native_grid, later)
    with nc.Dataset(later, "a") as ds:
        ds["forecast_initial_time"][:] = [24, 36]
        ds["LSP"][:] = .012
    archive = Era5MapArchive(era5_files(tmp_path), (-2, 2, 39, 43))
    catalog = archive.catalog()
    assert catalog["file_count"] == 2
    assert catalog["available_hours"] == 12
    assert catalog["gap_hours"] == 27
    assert catalog["members"][0]["hours"] == 39
    for hour, expected in [(0, 2), (1, 1), (12, 9), (24, 12), (36, 12)]:
        payload, headers = archive.frame(0, hour)
        values = np.frombuffer(payload, dtype="<f4").reshape(archive.shape)
        assert values[1, 1] == pytest.approx(expected)
        assert headers["X-Data-Available"] == "true"
    payload, headers = archive.frame(0, 3)
    assert np.isnan(np.frombuffer(payload, dtype="<f4")).all()
    assert headers["X-Data-Available"] == "false"
    assert len(archive.cycles) == 2
    assert sum(a.nbytes for a in archive.cycles.values()) <= 2 * 12 * 100_000 * 4
    selection = archive.selection(0, "2023-01-01T06:00:00Z", "2023-01-02T21:00:00Z")
    assert selection["hours"] == 39 and selection["available_hours"] == 12 and selection["gap_hours"] == 27


def test_real_archive_all_gap_selection_and_http(native_grid):
    from fastapi.testclient import TestClient

    from meteo_bridge.era5_map_archive import Era5MapArchive
    from meteo_bridge.era5_map_server import create_era5_map_app

    archive = Era5MapArchive([native_grid], (-2, 2, 39, 43))
    selected = archive.selection(0, "2023-01-01T09:00:00Z", "2023-01-01T18:00:00Z")
    assert selected["available_hours"] == 0 and selected["gap_hours"] == 9
    data = archive.initial_map(selected)
    assert np.isnan(data["amounts_mm"]).all()
    html = map_html(data, "/archive/test")
    assert "В данном промежутке данные не найдены" in html
    assert '"hours": 9' in html
    client = TestClient(create_era5_map_app({"test": archive}, {"test": html}))
    assert client.get("/viewer/test").status_code == 200
    assert client.get("/archive/test/catalog").json()["gap_hours"] == 9
    params = {"hour": 3, "manifest_sha256": archive.sha}
    response = client.get("/archive/test/frame", params=params)
    assert response.status_code == 200 and response.headers["X-Data-Available"] == "false"
    assert np.isnan(np.frombuffer(response.content, dtype="<f4")).all()
    params["hour"] = 12
    response = client.get("/archive/test/frame", params=params)
    assert response.status_code == 200 and response.headers["X-Data-Available"] == "true"
    assert np.frombuffer(response.content, dtype="<f4").max() == pytest.approx(9)
    assert client.get("/archive/test/frame", params={"hour": 0}).status_code == 409
    assert client.get("/archive/test/range", params={"start": selected["start_utc"],
                                                   "end": selected["end_utc"]}).json() == selected
    assert client.get("/archive/test/range", params={"start": "2023-01-01T09:30:00Z",
                                                   "end": selected["end_utc"]}).status_code == 422


def test_real_archive_duplicate_hours_grid_mismatch_and_changed_source(native_grid, tmp_path):
    import os
    import shutil

    from meteo_bridge.era5_map_archive import Era5MapArchive

    duplicate = tmp_path / "z-copy.nc"
    shutil.copyfile(native_grid, duplicate)
    archive = Era5MapArchive([duplicate, native_grid], (-2, 2, 39, 43), max_cells=2)
    assert archive.catalog()["available_hours"] == 6
    assert archive.catalog()["duplicate_hours"] == 6
    assert np.prod(archive.shape) <= 2
    with nc.Dataset(duplicate, "a") as ds:
        ds["latitude"][:] = [43, 41]
    with pytest.raises(ValueError, match="сетка отличается"):
        Era5MapArchive([native_grid, duplicate])
    stat = native_grid.stat()
    os.utime(native_grid, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    with pytest.raises(ValueError, match="изменился"):
        archive.frame(0, 0)


def test_streamlit_real_archive_selects_gap_range(native_grid, tmp_path, monkeypatch):
    from datetime import time
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("METEOBRIDGE_HOME", str(tmp_path / "catalog"))
    at = AppTest.from_file(Path("ui/app.py").resolve(), default_timeout=60).run()
    at.sidebar.radio[0].set_value("Карта осадков").run()
    next(t for t in at.text_input if t.label == "Папка или файл NCAR ERA5 LSP").set_value(str(native_grid)).run()
    next(t for t in at.time_input if t.label == "Начальное время UTC").set_value(time(9))
    next(t for t in at.time_input if t.label == "Конечное время UTC").set_value(time(18))
    next(b for b in at.button if b.label == "Построить карту").click().run()
    assert not at.exception and not at.error
    assert at.session_state.precipitation_map[1]["selection"]["gap_hours"] == 9
    assert at.session_state.precipitation_map[1]["selection"]["available_hours"] == 0
