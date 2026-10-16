import copy
import json
from fractions import Fraction as F

import numpy as np
import pytest
from hypothesis import given, seed, settings
from hypothesis import strategies as st

from meteo_bridge.certificates import verify_certificate
from meteo_bridge.domain import (
    Case,
    Interpretation,
    Query,
    SemanticHypothesis,
    SeriesKey,
    digest,
    utc_seconds,
)
from meteo_bridge.fixtures import NAMES, fixture, observation
from meteo_bridge.oracle import solve_lp
from meteo_bridge.services import apply_evidence, clear_cache, solve_query


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("solver", ["graph", "shared", "cache", "lp"])
def test_hand_cases(name, solver):
    case = fixture(name)
    bundle = solve_query(case, solver)
    assert bundle.get("checker", {}).get("valid"), bundle
    lp = solve_lp(case)
    for h, world in bundle["certificate"]["worlds"].items():
        assert world["feasible"] == lp[h]["feasible"]
        if world["feasible"]:
            for side in ("lower", "upper"):
                a, b = world[side], lp[h][side]
                assert (a is None) == (b is None)
                if a is not None:
                    assert float(F(a)) == pytest.approx(b, abs=1e-7)


def test_independent_hand_expected():
    expected = {
        "overlap-exact": ("18", "18"),
        "overlap-bounded": ("177/10", "183/10"),
        "insufficient-data": ("0", "12"),
        "cumulative": ("3", "3"),
    }
    for name, pair in expected.items():
        result = solve_query(fixture(name))["result"]
        assert (result["lower"], result["upper"]) == pair
    assert solve_query(fixture("conflict"))["result"]["status"] == "inconsistent_model"
    assert solve_query(fixture("threshold-true"))["result"]["decision"] is True
    assert solve_query(fixture("threshold-unknown"))["result"]["decision"] is None


def random_case(seed, n=8, nh=4):
    rng = np.random.default_rng(seed)
    amounts = rng.integers(0, 10, n)
    obs = []
    for i in range(n * 2):
        a, b = sorted(rng.choice(n + 1, 2, replace=False).tolist())
        value = int(amounts[a:b].sum())
        obs.append(observation(str(i), a, b, max(0, value - 1), value + 1))
    hs = [
        SemanticHypothesis(
            id=f"h{i}",
            assignments={"alternative": str(i)},
            intervals={"0": Interpretation(start=0, end=(1 + i % n) * 3600)},
        )
        for i in range(nh)
    ]
    return Case(
        id=f"random-{seed}",
        observations=obs,
        hypotheses=hs,
        query=Query(start=0, end=n * 3600),
        h_complete=True,
        completeness_basis="finite generated alternatives",
        family_id=f"seed-{seed}",
    )


@given(st.integers(min_value=0, max_value=100000))
@settings(max_examples=60, deadline=None)
@seed(42)
def test_generated_oracle_shared_cache(seed):
    case = random_case(seed)
    graph, shared = solve_query(case), solve_query(case, "shared")
    assert graph.get("checker", {}).get("valid"), graph
    assert shared.get("checker", {}).get("valid"), shared
    assert graph["result"]["lower"] == shared["result"]["lower"]
    assert graph["result"]["upper"] == shared["result"]["upper"]
    lp = solve_lp(case)
    for hid, world in graph["certificate"]["worlds"].items():
        assert world["feasible"] == lp[hid]["feasible"]
        if world["feasible"]:
            for side in ("lower", "upper"):
                v = world[side]
                assert (v is None) == (lp[hid][side] is None)
                if v is not None:
                    assert abs(float(F(v)) - lp[hid][side]) < 1e-7


@pytest.mark.parametrize(
    "mutation", ["path", "weight", "unit", "hash", "scope", "witness", "ray", "decision"]
)
def test_checker_rejects_forgery(mutation):
    case = fixture("unbounded" if mutation == "ray" else "overlap-bounded")
    bundle = solve_query(case)
    cert, result = copy.deepcopy(bundle["certificate"]), copy.deepcopy(bundle["result"])
    if mutation == "path":
        cert["worlds"]["known"]["upper_path"].reverse()
    elif mutation == "weight":
        cert["worlds"]["known"]["upper"] = "100"
    elif mutation == "unit":
        cert["unit"] = "m"
    elif mutation == "hash":
        cert["case_hash"] = "forged"
    elif mutation == "scope":
        cert["scope"] = []
    elif mutation == "witness":
        result["witnesses"][0]["potentials"]["0"] = "-10000"
    elif mutation == "ray":
        cert["worlds"]["known"]["upper_ray"] = {"0": "0", "64800": "0"}
    else:
        result["decision"] = True
    result["certificate_id"] = digest(cert)
    assert not verify_certificate(case, result, cert)["valid"]


def test_stale_cache_and_incomplete_search():
    clear_cache()
    case = fixture("metadata-label")
    before = solve_query(case, "cache")
    revised = apply_evidence(case, {"kind": "clarify_metadata", "attribute": "label", "value": "begin"})
    after = solve_query(revised, "cache")
    assert before["result"]["point_estimate"] is None
    assert after["result"]["point_estimate"] == "5"
    assert after["result"]["revision"] == 1
    assert solve_query(case, max_worlds=1)["result"]["status"] == "incomplete_model"
    assert solve_query(case, timeout=0)["result"]["status"] == "incomplete_model"
    assert solve_query(fixture("incomplete-h"))["result"]["status"] == "incomplete_model"


def test_units_permutation_duplicates_and_true_constraint():
    case = fixture("overlap-exact")
    original = solve_query(case)["result"]
    revised = case.model_copy(deep=True)
    revised.observations.reverse()
    duplicate = revised.observations[0].model_copy(update={"id": "dup"})
    revised.observations.append(duplicate)
    for obs in revised.observations:
        obs.lower, obs.upper = str(F(obs.lower) / 1000), str(F(obs.upper) / 1000)
        obs.interval.unit = "m"
    assert solve_query(revised)["result"]["point_estimate"] == original["point_estimate"]
    half = fixture("insufficient-data")
    half = apply_evidence(
        half, {"kind": "add_observation", "observation": observation("half", 0, 12, 7).model_dump()}
    )
    assert solve_query(half)["result"]["point_estimate"] == "7"


@pytest.mark.parametrize(
    "field,value", [("location", "other"), ("product", "other"), ("member", "m2"), ("cycle", "c2")]
)
def test_no_mixed_series(field, value):
    case = fixture("overlap-exact")
    case.observations[0].series = SeriesKey(**{field: value})
    assert solve_query(case)["result"]["status"] == "unsupported"


def test_rate_reset_calendar_dst_and_strict_threshold():
    case = fixture("cumulative")
    case.observations[0].interval.reset_start = None
    assert solve_query(case)["result"]["status"] == "unsupported"
    case = fixture("daily-total")
    case.observations[0].interval.statistic = "instantaneous_rate"
    assert solve_query(case)["result"]["status"] == "unsupported"
    case.query.calendar = "360_day"
    assert solve_query(case)["result"]["status"] == "unsupported"
    assert utc_seconds("2023-10-29T02:30:00+01:00") - utc_seconds("2023-10-29T02:30:00+02:00") == 3600
    with pytest.raises(ValueError):
        utc_seconds("2023-10-29T02:30:00")
    for tau, decision in [("18", True), ("18.000000000000000001", False)]:
        case = fixture("overlap-exact")
        case.query.objective, case.query.threshold = "threshold", tau
        assert solve_query(case)["result"]["decision"] is decision
    bundle = solve_query(fixture("unbounded"))
    assert "Infinity" not in json.dumps(bundle, allow_nan=False)
