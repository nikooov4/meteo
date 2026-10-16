import copy
from fractions import Fraction as F
from random import Random

import pytest

from meteo_bridge.acquisition_checker import verify_acquisition
from meteo_bridge.action_domain import AcquisitionAction as Action
from meteo_bridge.continuous_acquisition import clear_acquisition_cache, evaluate_actions
from meteo_bridge.domain import Case, Interpretation, Query, SemanticHypothesis, digest
from meteo_bridge.fixtures import fixture, observation
from meteo_bridge.paired_oracle import evaluate_paired_lp


def diagnostic():
    return fixture("insufficient-data"), [
        Action(id="first6", start=0, end=6 * 3600),
        Action(id="last12", start=12 * 3600, end=24 * 3600),
    ]


def agree(case, actions):
    lp = evaluate_paired_lp(case, actions)
    for method in ("graph", "terminal"):
        bundle = evaluate_actions(case, actions, method)
        assert bundle["checker"]["valid"]
        for actual, expected in zip(bundle["result"]["actions"], lp["actions"]):
            assert actual["width_kind"] == expected["width_kind"]
            assert actual["guarantees_resolution"] == expected["guarantees_resolution"]
            if expected["width"] is not None:
                assert float(F(actual["worst_remaining_width"])) == pytest.approx(expected["width"], abs=1e-7)
    return bundle


def test_diagnostic_full_continuous_worlds():
    case, actions = diagnostic()
    bundle = agree(case, actions)
    assert [x["worst_remaining_width"] for x in bundle["result"]["actions"]] == ["12", "0"]
    assert [x["guarantees_resolution"] for x in bundle["result"]["actions"]] == [False, True]


@pytest.mark.parametrize(
    "name", ["unbounded", "conflict", "overlap-exact", "overlap-bounded", "cumulative", "incomplete-h"]
)
def test_modes_and_conventions(name):
    case = fixture(name)
    agree(
        case,
        [
            Action(id="query", start=case.query.start, end=case.query.end),
            Action(id="outside", start=-7200, end=-3600),
        ],
    )


def test_metadata_does_not_reconstruct_time_detail():
    case, _ = diagnostic()
    case.hypotheses = [
        SemanticHypothesis(id="a", assignments={"label": "end"}),
        SemanticHypothesis(id="b", assignments={"label": "begin"}),
    ]
    bundle = agree(case, [Action(id="label", kind="metadata", attribute="label")])
    assert bundle["result"]["actions"][0]["worst_remaining_width"] == "12"


def test_metadata_and_response_incompatible_pairs():
    case = fixture("metadata-label")
    actions = [Action(id="label", kind="metadata", attribute="label"), Action(id="hour", start=0, end=3600)]
    bundle = agree(case, actions)
    assert all(x["guarantees_resolution"] for x in bundle["result"]["actions"])
    # Pair has disjoint measurement supports: it must be proved empty, not silently omitted.
    assert any(p["kind"] == "empty" for p in bundle["certificate"]["pairs"][1])


@pytest.mark.parametrize("tau", ["0", "6", "12", "13"])
def test_threshold_strict_boundary(tau):
    case, actions = diagnostic()
    case.query = case.query.model_copy(update={"objective": "threshold", "threshold": tau})
    bundle = agree(case, actions)
    assert bundle["result"]["actions"][1]["guarantees_resolution"]
    assert bundle["result"]["actions"][0]["guarantees_resolution"] == (tau in ("0", "13"))


def test_threshold_smaller_than_lp_tolerance_remains_exact():
    case, actions = diagnostic()
    case.query = case.query.model_copy(update={"objective": "threshold", "threshold": "1/1000000000000"})
    bundle = evaluate_actions(case, actions)
    assert not bundle["result"]["actions"][0]["guarantees_resolution"]


def generated_case(seed, n=8, nh=2):
    rng = Random(seed)
    truth = [rng.randrange(6) for _ in range(n)]
    obs = [observation("total", 0, n, sum(truth))]
    for k in range(n):
        a, b = sorted(rng.sample(range(n + 1), 2))
        value = sum(truth[a:b])
        obs.append(observation(str(k), a, b, max(0, value - 2), value + 2))
    hs = [
        SemanticHypothesis(
            id=f"h{i}",
            assignments={"label": str(i)},
            intervals={} if i == 0 else {"0": Interpretation(start=0, end=i * 3600)},
        )
        for i in range(nh)
    ]
    return Case(
        id=f"generated-{seed}",
        observations=obs,
        hypotheses=hs,
        query=Query(start=0, end=(n // 2) * 3600),
        h_complete=True,
        completeness_basis="finite generated alternatives; development only",
    )


@pytest.mark.parametrize("seed", range(12))
def test_generated_independent_paired_lp(seed):
    case = generated_case(seed)
    actions = [
        Action(id="a", start=3600, end=5 * 3600),
        Action(id="b", start=4 * 3600, end=8 * 3600),
        Action(id="m", kind="metadata", attribute="label"),
    ]
    agree(case, actions)
    if seed < 4:
        case.query = case.query.model_copy(update={"objective": "threshold", "threshold": "4"})
        agree(case, actions)


def test_checker_forgery_and_scope():
    case, actions = diagnostic()
    bundle = evaluate_actions(case, actions)
    bad = copy.deepcopy(bundle)
    bad["certificate"]["pairs"][0][0]["point"]["0"] = "1000"
    bad["result"]["certificate_id"] = digest(bad["certificate"])
    assert not verify_acquisition(case, actions, bad["result"], bad["certificate"])["valid"]
    bad = copy.deepcopy(bundle)
    bad["certificate"]["pairs"][0] = []
    bad["result"]["certificate_id"] = digest(bad["certificate"])
    assert not verify_acquisition(case, actions, bad["result"], bad["certificate"])["valid"]
    bad = copy.deepcopy(bundle)
    bad["result"]["actions"][0]["guarantees_resolution"] = True
    assert not verify_acquisition(case, actions, bad["result"], bad["certificate"])["valid"]
    assert not verify_acquisition(
        case.model_copy(update={"h_complete": False}), actions, bundle["result"], bundle["certificate"]
    )["valid"]
    changed = [actions[0].model_copy(update={"cost": "2"}), actions[1]]
    assert not verify_acquisition(case, changed, bundle["result"], bundle["certificate"])["valid"]


def test_incomplete_and_cache_revision():
    case, actions = diagnostic()
    clear_acquisition_cache()
    first = evaluate_actions(case, actions, "cache")
    second = evaluate_actions(case, actions, "cache")
    assert second["metrics"]["cache_hit"] and second["checker"]["valid"]
    assert first["result"] == second["result"]
    with pytest.raises(TimeoutError):
        evaluate_actions(case, actions, "cache", timeout_seconds=0)
    case = case.model_copy(update={"h_complete": False})
    third = evaluate_actions(case, actions, "cache")
    assert not third["metrics"]["cache_hit"]
    assert third["result"]["status"] == "incomplete_model"
    assert not any(x["guarantees_resolution"] for x in third["result"]["actions"])


def test_unknown_metadata_and_budget_fail_closed():
    case, actions = diagnostic()
    with pytest.raises(ValueError, match="declared for every"):
        evaluate_actions(case, [Action(id="m", kind="metadata", attribute="absent")])
    with pytest.raises(TimeoutError):
        evaluate_actions(case, actions, timeout_seconds=0)
    many = [Action(id=str(i), start=i, end=i + 1) for i in range(128)]
    with pytest.raises(ValueError, match="endpoints"):
        evaluate_actions(case, many)


def test_api_and_cli_round_trip(tmp_path, monkeypatch):
    import json

    from fastapi.testclient import TestClient
    from typer.testing import CliRunner

    from meteo_bridge.api import app
    from meteo_bridge.cli import app as cli

    monkeypatch.setenv("METEOBRIDGE_HOME", str(tmp_path / "catalog"))
    case, actions = diagnostic()
    raw_actions = [a.model_dump() for a in actions]
    with TestClient(app) as client:
        dataset = client.post(
            "/datasets", files={"file": ("case.json", case.model_dump_json(), "application/json")}
        ).json()
        qid = client.post("/queries", json={"dataset_id": dataset["id"]}).json()["id"]
        response = client.post(f"/queries/{qid}/acquisition", json={"actions": raw_actions})
        assert response.status_code == 200
        bundle = response.json()
        assert verify_acquisition(case, actions, bundle["result"], bundle["certificate"])["valid"]
        assert client.post(f"/queries/{qid}/acquisition", json={"actions": []}).status_code == 422
    (tmp_path / "case.json").write_text(case.model_dump_json(), encoding="utf8")
    (tmp_path / "actions.json").write_text(json.dumps(raw_actions), encoding="utf8")
    runner = CliRunner()
    output = tmp_path / "export"
    response = runner.invoke(
        cli,
        [
            "acquisition",
            "evaluate",
            "--case",
            str(tmp_path / "case.json"),
            "--actions",
            str(tmp_path / "actions.json"),
            "--output",
            str(output),
        ],
    )
    assert response.exit_code == 0, response.output
    response = runner.invoke(cli, ["acquisition", "verify", "--directory", str(output)])
    assert response.exit_code == 0, response.output


def test_unbounded_threshold_and_normalized_rates():
    case = fixture("unbounded")
    case.query = case.query.model_copy(update={"objective": "threshold", "threshold": "1000000"})
    result = agree(case, [Action(id="q", start=0, end=case.query.end),
                          Action(id="unrelated", start=-7200, end=-3600)])
    assert [a["guarantees_resolution"] for a in result["result"]["actions"]] == [True, False]
    case, actions = diagnostic()
    obs = case.observations[0]
    obs.interval.statistic, obs.interval.unit = "interval_mean_rate", "mm/h"
    obs.lower = obs.upper = "1/2"
    result = agree(case, actions)
    assert [a["worst_remaining_width"] for a in result["result"]["actions"]] == ["12", "0"]


def test_streamlit_acquisition(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("METEOBRIDGE_HOME", str(tmp_path))
    at = AppTest.from_file(Path("ui/app.py").resolve(), default_timeout=60).run()
    at.sidebar.selectbox[0].select("insufficient-data").run()
    _, actions = diagnostic()
    next(t for t in at.text_area if t.label.startswith("Actions JSON")).set_value(
        json.dumps([a.model_dump() for a in actions])
    )
    next(b for b in at.button if b.key == "evaluate-continuous-actions").click().run()
    assert not at.exception
    assert not at.error
    frame = at.dataframe[-1].value
    assert frame["worst_remaining_width"].tolist() == ["12", "0"]
