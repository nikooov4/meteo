from fractions import Fraction as F
from pathlib import Path

import netCDF4 as nc
import numpy as np
import pytest

from meteo_bridge.domain import Case, Query, SemanticHypothesis
from meteo_bridge.fixtures import fixture, observation
from meteo_bridge.imports import netcdf_case
from meteo_bridge.services import solve_query


def test_streamlit_archive_selection_refreshes_same_case_id(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from meteo_bridge import catalog, readers
    from meteo_bridge.resources import sha256_file

    registered = []
    for name in ("first", "second"):
        path = tmp_path / f"{name}.json"
        path.write_text(name)
        registered.append({"name": name, "path": str(path), "sha256": sha256_file(path)})
    monkeypatch.setattr(catalog, "archives", lambda: registered)

    def selected_case(path, series_id, first_hour, hours):
        case = fixture("daily-total")
        case.id = "same-id-across-selections"
        value = "12" if Path(path).stem == "first" else "20"
        case.observations[0].lower = case.observations[0].upper = value
        case.observations[0].interval.end = hours * 3600
        case.query.end = hours * 3600
        return case, 9

    monkeypatch.setattr(readers, "scale_case", selected_case)
    at = AppTest.from_file(Path("ui/app.py").resolve(), default_timeout=60).run()
    at.sidebar.radio[0].set_value("Зарегистрированный набор").run()
    assert not at.exception
    assert at.session_state.case.query.end == 6 * 3600
    next(w for w in at.sidebar.number_input if w.label == "Часов").set_value(12).run()
    assert not at.exception
    assert at.session_state.case.query.end == 12 * 3600
    at.sidebar.selectbox[0].select(registered[1]).run()
    assert not at.exception
    assert at.session_state.case.observations[0].lower == "20"
    Path(registered[1]["path"]).write_text("changed manifest")
    at.run()
    assert not at.exception
    assert any("Manifest изменился" in error.value for error in at.error)


def test_unbounded_threshold_witness_crosses_requested_threshold():
    case = fixture("unbounded")
    case.query.objective, case.query.threshold = "threshold", "1000000"
    bundle = solve_query(case)
    assert bundle["checker"]["valid"], bundle
    assert bundle["result"]["decision"] is None
    assert {F(w["q"]) >= 1000000 for w in bundle["result"]["witnesses"]} == {True, False}


def test_incomplete_H_does_not_need_invented_outside_H_witness():
    case = fixture("metadata-label")
    case.h_complete = False
    case.query.objective, case.query.threshold = "threshold", "10"
    bundle = solve_query(case)
    assert bundle["checker"]["valid"], bundle
    assert bundle["result"]["status"] == "incomplete_model"
    assert bundle["result"]["decision"] is None


def test_working_model_budget_is_incomplete_not_certified():
    case = Case(
        id="large-bounded-model",
        observations=[observation(str(i), 2 * i, 2 * i + 1, 1) for i in range(515)],
        hypotheses=[SemanticHypothesis(id="h")],
        query=Query(start=0, end=1030 * 3600),
        h_complete=True,
        completeness_basis="generated",
    )
    result = solve_query(case)
    assert result["result"]["status"] == "incomplete_model"
    assert "certificate" not in result


def cf_file(path, reference=None):
    with nc.Dataset(path, "w") as ds:
        ds.createDimension("time", 2)
        ds.createDimension("bounds", 2)
        time = ds.createVariable("time", "i8", ("time",))
        time.units, time.calendar, time.bounds = (
            "seconds since 1970-01-01",
            "proleptic_gregorian",
            "time_bounds",
        )
        time[:] = [3600, 7200]
        ds.createVariable("time_bounds", "i8", ("time", "bounds"))[:] = [[0, 3600], [3600, 7200]]
        value = ds.createVariable("rain", "f4", ("time",))
        value.units, value.standard_name, value.cell_methods = (
            "mm",
            "lwe_thickness_of_precipitation_amount",
            "time: sum",
        )
        value[:] = [0.1, 0.2]
        ds.location, ds.product, ds.member, ds.cycle = "point", "CF-example", "deterministic", ""
        if reference is not None:
            ds.cycle = "declared-cycle"
            coord = ds.createVariable("forecast_reference_time", "i8", ("time",))
            coord.standard_name = "forecast_reference_time"
            coord[:] = reference


def test_scalar_netcdf_preserves_exact_encoded_binary_value(tmp_path):
    path = tmp_path / "scalar.nc"
    cf_file(path)
    case = netcdf_case(path)
    expected = F.from_float(float(np.float32(0.1))) + F.from_float(float(np.float32(0.2)))
    bundle = solve_query(case)
    assert bundle["checker"]["valid"]
    assert F(bundle["result"]["point_estimate"]) == expected


def test_scalar_netcdf_refuses_varying_forecast_cycles(tmp_path):
    path = tmp_path / "mixed-cycles.nc"
    cf_file(path, [0, 3600])
    with pytest.raises(ValueError, match="multiple"):
        netcdf_case(path)
