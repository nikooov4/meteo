import copy
from fractions import Fraction as F

import pytest

from meteo_bridge.action_domain import AcquisitionAction as Action
from meteo_bridge.domain import Case, Interpretation, Query, SemanticHypothesis, digest
from meteo_bridge.fixtures import fixture, observation
from meteo_bridge.paired_oracle import evaluate_paired_lp
from meteo_bridge.precision_checker import verify_precision_profiles
from meteo_bridge.precision_frontier import build_precision_profiles, precision_values

METHODS = ("full", "compiled", "terminal_no_reuse", "terminal")


def jump_case():
    return Case(id="noise-activates-metadata-pair",
                observations=[observation("q", 0, 1, 0), observation("m", 1, 2, 0),
                              observation("ten", 2, 3, 10), observation("two", 3, 4, 2)],
                hypotheses=[SemanticHypothesis(id="layout0"), SemanticHypothesis(id="layout1", intervals={
                    "q": Interpretation(start=7200, end=10800), "ten": Interpretation(start=0, end=3600),
                    "m": Interpretation(start=10800, end=14400), "two": Interpretation(start=3600, end=7200)})],
                query=Query(start=0, end=3600, eps="1"), h_complete=True,
                completeness_basis="two declared synthetic layouts only; not a natural-source annotation")


def compare_lp(case, actions, radii, method):
    bundle = build_precision_profiles(case, actions, method)
    assert bundle["checker"]["valid"]
    values = precision_values(case, actions, bundle, radii)
    for row in values:
        lp = evaluate_paired_lp(case, actions, error_radius=row["radius"])
        for actual, expected in zip(row["actions"], lp["actions"]):
            assert actual["width_kind"] == expected["width_kind"]
            assert actual["guarantees_resolution"] == expected["guarantees_resolution"]
            if actual["width"] is not None:
                assert float(F(actual["width"])) == pytest.approx(expected["width"], abs=1e-7)
    return bundle, values


@pytest.mark.parametrize("method", METHODS)
def test_daily_complement_precision_curve(method):
    case = fixture("insufficient-data")
    case.query.eps = "1/2"
    actions = [Action(id="complement", start=43200, end=86400), Action(id="first6", start=0, end=21600)]
    bundle, values = compare_lp(case, actions, ["0", "1/4", "1", "6", "10"], method)
    assert [r["actions"][0]["width"] for r in values] == ["0", "1/2", "2", "12", "12"]
    assert bundle["result"]["actions"][0]["radius_supremum"] == "1/2"
    assert bundle["result"]["actions"][0]["safe_at_supremum"]
    assert bundle["result"]["actions"][1]["radius_kind"] == "empty"


@pytest.mark.parametrize("method", METHODS)
def test_metadata_noise_activation_jump_and_open_boundary(method):
    case = jump_case()
    actions = [Action(id="measure-m", start=3600, end=7200)]
    bundle, values = compare_lp(case, actions, ["0", "1/2", "999/1000", "1", "2"], method)
    assert [r["actions"][0]["width"] for r in values] == ["0", "0", "0", "10", "10"]
    frontier = bundle["result"]["actions"][0]
    assert frontier["radius_supremum"] == "1" and not frontier["safe_at_supremum"]
    assert frontier["conditional_guarantee"]


@pytest.mark.parametrize("name", ["unbounded", "conflict", "cumulative", "overlap-bounded", "incomplete-h"])
def test_modes_and_existing_conventions(name):
    case = fixture(name)
    case.query.eps = "1"
    actions = [Action(id="query", start=case.query.start, end=case.query.end),
               Action(id="unrelated", start=-7200, end=-3600)]
    bundle, _ = compare_lp(case, actions, ["0", "1/2", "3"], "terminal")
    if name == "unbounded":
        assert bundle["result"]["actions"][0]["radius_supremum"] == "1"
    if not case.h_complete:
        assert bundle["result"]["status"] == "incomplete_model"
        assert not any(a["conditional_guarantee"] for a in bundle["result"]["actions"])


def test_zero_only_and_all_radii_are_distinct():
    case = fixture("insufficient-data")
    a = [Action(id="c", start=43200, end=86400)]
    result = build_precision_profiles(case, a)["result"]["actions"][0]
    assert result["radius_kind"] == "finite" and result["radius_supremum"] == "0"
    assert result["safe_at_supremum"]
    case = fixture("daily-total")
    result = build_precision_profiles(case, a)["result"]["actions"][0]
    assert result["radius_kind"] == "unbounded" and result["radius_supremum"] is None


@pytest.mark.parametrize("mutation", ["activation", "point", "dual", "ray", "boundary", "scope", "coverage"])
def test_profile_checker_rejects_forged_all_parameter_proof(mutation):
    case = jump_case() if mutation in ("activation", "boundary") else fixture("unbounded")
    case.query.eps = "1"
    actions = [Action(id="m", start=case.query.start, end=case.query.end)]
    if mutation in ("activation", "boundary"):
        actions = [Action(id="m", start=3600, end=7200)]
    bundle = build_precision_profiles(case, actions)
    cert, result = copy.deepcopy(bundle["certificate"]), copy.deepcopy(bundle["result"])
    pair = next(p for p in cert["pairs"][0] if p["kind"] == "finite")
    if mutation == "activation":
        pair = next(p for p in cert["pairs"][0] if F(p["activation_rho"]) > 0)
        pair["activation_cycle"] = []
    elif mutation == "point":
        first = next(iter(pair["points"].values()))
        first[next(iter(first))] = "999"
    elif mutation == "dual":
        pair["affines"][0]["intercept"] = "999"
    elif mutation == "ray":
        pair["terminal_ray"] = {k: "0" for k in pair["terminal_ray"]}
    elif mutation == "boundary":
        result["actions"][0]["safe_at_supremum"] = True
    elif mutation == "scope":
        result["h_complete"] = False
    else:
        cert["pairs"][0] = []
    result["certificate_id"] = digest(cert)
    assert not verify_precision_profiles(case, actions, result, cert)["valid"]


def test_rejects_unsupported_and_deadline():
    case = fixture("threshold-unknown")
    actions = [Action(id="q", start=0, end=case.query.end)]
    with pytest.raises(ValueError, match="amount Query"):
        build_precision_profiles(case, actions)
    case = fixture("daily-total")
    with pytest.raises(TimeoutError):
        build_precision_profiles(case, actions, timeout_seconds=0)


def test_compiled_paths_are_proposals_not_float_bounds(monkeypatch):
    import numpy as np
    import scipy.sparse.csgraph as cg

    from meteo_bridge.constraints import Edge
    from meteo_bridge.validated_paths import compiled_paths

    edges = [Edge(0, 1, F(1)), Edge(1, 2, F(-1, 10**20)), Edge(0, 2, F(1))]
    monkeypatch.setattr(cg, "johnson", lambda *a, **kw: (np.array([[0., 1., 1.]]),
                                                        np.array([[-9999, 0, 0]])))
    result = compiled_paths([0, 1, 2], edges, [0])
    assert result[0][2][0] == 1-F(1, 10**20)


@pytest.mark.parametrize("seed", range(10))
def test_generated_whole_profiles_against_independent_lp(seed):
    from meteo_bridge.precision_experiment import precision_case

    case, actions = precision_case(seed, 8, 2, 4)
    terminal, _ = compare_lp(case, actions, ["0", "1/3", "2", "10"], "terminal")
    full = build_precision_profiles(case, actions, "compiled")
    assert full["result"]["actions"] == terminal["result"]["actions"]


def test_precision_cli_api_roundtrip(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient
    from typer.testing import CliRunner

    from meteo_bridge.api import app
    from meteo_bridge.cli import app as cli

    case = fixture("insufficient-data")
    case.query.eps = "1/2"
    actions = [Action(id="complement", start=43200, end=86400)]
    raw = [a.model_dump() for a in actions]
    monkeypatch.setenv("METEOBRIDGE_HOME", str(tmp_path / "catalog"))
    with TestClient(app) as client:
        data = client.post("/datasets", files={"file": ("case.json", case.model_dump_json(), "application/json")}).json()
        qid = client.post("/queries", json={"dataset_id": data["id"]}).json()["id"]
        response = client.post(f"/queries/{qid}/precision", json={"actions": raw})
        assert response.status_code == 200
        bundle = response.json()
        assert verify_precision_profiles(case, actions, bundle["result"], bundle["certificate"])["valid"]
        assert client.post(f"/queries/{qid}/precision", json={"actions": raw, "radii": ["-1"]}).status_code == 422
    (tmp_path / "case.json").write_text(case.model_dump_json(), encoding="utf8")
    (tmp_path / "actions.json").write_text(json.dumps(raw), encoding="utf8")
    runner = CliRunner()
    target = tmp_path / "export"
    result = runner.invoke(cli, ["acquisition", "precision", "--case", str(tmp_path / "case.json"),
                                 "--actions", str(tmp_path / "actions.json"), "--output", str(target)])
    assert result.exit_code == 0, result.output
    result = runner.invoke(cli, ["acquisition", "precision-verify", "--directory", str(target)])
    assert result.exit_code == 0, result.output


def test_streamlit_precision_frontier(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("METEOBRIDGE_HOME", str(tmp_path))
    at = AppTest.from_file(Path("ui/app.py").resolve(), default_timeout=60).run()
    at.sidebar.selectbox[0].select("insufficient-data").run()
    next(t for t in at.text_area if t.label.startswith("Actions JSON")).set_value(
        json.dumps([Action(id="c", start=43200, end=86400).model_dump()]))
    next(b for b in at.button if b.key == "evaluate-precision-profile").click().run()
    assert not at.exception and not at.error
    assert at.dataframe[-1].value["radius_supremum"].tolist() == ["0"]
