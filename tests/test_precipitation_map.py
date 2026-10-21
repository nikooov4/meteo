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
    next(t for t in at.text_input if t.label == "Локальный файл NCAR ERA5 LSP").set_value(str(native_grid))
    next(b for b in at.button if b.label == "Построить карту").click().run()
    assert not at.exception and not at.error
    assert at.session_state.precipitation_map[1]["frames"] == 3
