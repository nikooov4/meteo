"""Independent LP on nonnegative interval increments, never imports graph compiler."""

import numpy as np
from scipy.optimize import linprog

from .domain import Case


def solve_lp(case: Case):
    if case.query.calendar != "proleptic_gregorian":
        raise NotImplementedError("unsupported LP calendar")
    if any(o.series != case.query.series for o in case.observations):
        raise ValueError("LP cannot combine distinct physical series")
    results = {}
    for h in case.hypotheses:
        intervals, times = [], {case.query.start, case.query.end}
        for obs in case.observations:
            if obs.qc != "accepted":
                continue
            spec = h.intervals.get(obs.id, obs.interval)
            if spec is None or spec.statistic == "instantaneous_rate":
                raise NotImplementedError("unsupported LP observation")
            a = spec.start
            if spec.statistic == "cumulative":
                if spec.reset_start is None:
                    raise NotImplementedError("LP requires reset baseline")
                a = spec.reset_start
            b = spec.end
            if spec.statistic == "interval_mean_rate":
                factor = {"mm/h": 1 / 3600, "m/s": 1000, "kg m-2 s-1": 1}[spec.unit] * (b - a)
            else:
                factor = {"mm": 1, "m": 1000, "kg m-2": 1}[spec.unit]
            # Float conversion is intentionally separate from rational compiler normalization.
            from fractions import Fraction

            lo, hi = float(Fraction(obs.lower)) * factor, float(Fraction(obs.upper)) * factor
            intervals.append((a, b, lo, hi))
            times.update((a, b))
        times = sorted(times)
        if len(times) > 512:
            raise NotImplementedError("independent dense LP reference is limited to 512 endpoints")
        matrix, rhs = [], []
        for a, b, lo, hi in intervals:
            row = np.array([float(a <= x and y <= b) for x, y in zip(times, times[1:])])
            matrix.extend((row, -row))
            rhs.extend((hi, -lo))
        q = np.array([float(case.query.start <= a and b <= case.query.end) for a, b in zip(times, times[1:])])
        kwargs = {
            "A_ub": np.array(matrix) if matrix else None,
            "b_ub": np.array(rhs) if rhs else None,
            "bounds": (0, None),
            "method": "highs",
        }
        feasible = linprog(np.zeros_like(q), **kwargs)
        if feasible.status == 2:
            results[h.id] = {"feasible": False}
            continue
        if feasible.status != 0:
            raise RuntimeError(f"LP feasibility failed: {feasible.message}")
        low, high = linprog(q, **kwargs), linprog(-q, **kwargs)
        if low.status not in (0, 3) or high.status not in (0, 3):
            raise RuntimeError(f"LP optimization failed: {low.message}; {high.message}")
        results[h.id] = {
            "feasible": True,
            "lower": float(low.fun) if low.status == 0 else None,
            "upper": float(-high.fun) if high.status == 0 else None,
            "times": times,
            "lower_increments": low.x.tolist() if low.status == 0 else None,
            "upper_increments": high.x.tolist() if high.status == 0 else None,
        }
    return results
