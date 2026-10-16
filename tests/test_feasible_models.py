from fractions import Fraction as F

from hypothesis import given, seed, settings
from hypothesis import strategies as st

from meteo_bridge.experiments import generated_case
from meteo_bridge.oracle import solve_lp
from meteo_bridge.services import solve_query


@given(st.integers(min_value=0, max_value=100000))
@settings(max_examples=40, deadline=None)
@seed(1847)
def test_guaranteed_feasible_generated_models(value):
    case = generated_case(value)
    case.hypotheses[0].intervals = {}  # preserve the actual generating interpretation
    case.query.start, case.query.end = 2 * 3600, 6 * 3600
    lp = solve_lp(case)
    assert lp[case.hypotheses[0].id]["feasible"]
    for solver in ("graph", "cache", "shared"):
        bundle = solve_query(case, solver)
        assert bundle["checker"]["valid"]
        for hid, world in bundle["certificate"]["worlds"].items():
            assert world["feasible"] == lp[hid]["feasible"]
            if world["feasible"]:
                for side in ("lower", "upper"):
                    a, b = world[side], lp[hid][side]
                    assert (a is None) == (b is None)
                    if a is not None:
                        assert abs(float(F(a)) - b) < 1e-7
