"""Independent numerical paired increment LP; no graph/compiler/checker imports."""

from fractions import Fraction
from time import perf_counter

import numpy as np
from scipy.optimize import linprog

from .action_domain import validate_actions


def evaluate_paired_lp(case, actions):
    validate_actions(case, actions)
    started = perf_counter()
    if case.query.calendar != "proleptic_gregorian":
        raise ValueError("unsupported calendar")
    times = {case.query.start, case.query.end}
    times.update(t for a in actions if a.kind == "interval" for t in (a.start, a.end))
    intervals = {}
    for h in case.hypotheses:
        rows, baselines = [], set()
        for o in case.observations:
            if o.series != case.query.series:
                raise ValueError("mixed physical series")
            if o.qc != "accepted":
                continue
            s = h.intervals.get(o.id, o.interval)
            if s is None:
                raise ValueError("unresolved interval")
            a, b = s.start, s.end
            if s.statistic == "cumulative":
                if s.reset_start is None or o.series.cycle is None or o.reset_group != o.series.cycle:
                    raise ValueError("missing cumulative cycle/reset")
                a = s.reset_start
                baselines.add(a)
            if b <= a:
                raise ValueError("invalid interval")
            if s.statistic == "interval_mean_rate":
                factor = {"mm/h": 1 / 3600, "m/s": 1000, "kg m-2 s-1": 1}[s.unit] * (b - a)
            elif s.statistic in ("amount", "cumulative"):
                factor = {"mm": 1, "m": 1000, "kg m-2": 1}[s.unit]
            else:
                raise ValueError("unsupported statistic")
            rows.append((a, b, float(Fraction(o.lower)) * factor, float(Fraction(o.upper)) * factor))
            times.update((a, b))
        if len(baselines) > 1:
            raise ValueError("mixed cumulative reset baselines")
        intervals[h.id] = rows
    times = sorted(times)
    if len(times) > 128:
        raise ValueError("working-model endpoint limit")
    n = len(times) - 1

    def vector(a, b):
        return np.array([float(a <= x and y <= b) for x, y in zip(times, times[1:])])

    q = vector(case.query.start, case.query.end)
    models, feasible = {}, {}
    calls = 0

    def run(c, a, b, eq=None):
        nonlocal calls
        calls += 1
        result = linprog(
            c,
            A_ub=np.array(a) if len(a) else None,
            b_ub=np.array(b) if len(b) else None,
            A_eq=eq[None, :] if eq is not None else None,
            b_eq=np.zeros(1) if eq is not None else None,
            bounds=(0, None),
            method="highs",
        )
        if result.status not in (0, 2, 3):
            raise RuntimeError(result.message)
        return result

    for hid, rows in intervals.items():
        a, b = [], []
        for start, stop, lo, hi in rows:
            row = vector(start, stop)
            a.extend((row, -row))
            b.extend((hi, -lo))
        models[hid] = a, b
        feasible[hid] = run(np.zeros(n), a, b).status == 0
    output = []
    for action in actions:
        values, unbounded, opposite = [], False, False
        for lh in case.hypotheses:
            for rh in case.hypotheses:
                if not feasible[lh.id] or not feasible[rh.id]:
                    continue
                if (
                    action.kind == "metadata"
                    and lh.assignments[action.attribute] != rh.assignments[action.attribute]
                ):
                    continue
                la, lb = models[lh.id]
                ra, rb = models[rh.id]
                a = [np.r_[row, np.zeros(n)] for row in la] + [np.r_[np.zeros(n), row] for row in ra]
                b = list(lb) + list(rb)
                eq = None
                if action.kind == "interval":
                    m = vector(action.start, action.end)
                    eq = np.r_[m, -m]
                if case.query.objective == "threshold":
                    a.append(np.r_[-q, np.zeros(n)])
                    b.append(-float(Fraction(case.query.threshold)))
                    c = np.r_[np.zeros(n), q]
                else:
                    c = np.r_[-q, q]
                pair = run(c, a, b, eq)
                if pair.status == 2:
                    continue
                if pair.status == 3:
                    unbounded = True
                elif case.query.objective == "threshold":
                    opposite |= pair.fun < float(Fraction(case.query.threshold)) - 1e-9
                else:
                    values.append(float(-pair.fun))
        item = {
            "id": action.id,
            "width": None,
            "width_kind": "not_applicable",
            "guarantees_resolution": False,
        }
        if not any(feasible.values()):
            item["width_kind"] = "empty"
        elif case.query.objective == "threshold":
            item["guarantees_resolution"] = case.h_complete and not opposite and not unbounded
        elif unbounded:
            item["width_kind"] = "unbounded"
        else:
            item.update(
                width=max(values),
                width_kind="finite",
                guarantees_resolution=case.h_complete
                and max(values) <= 2 * float(Fraction(case.query.eps)) + 1e-9,
            )
        output.append(item)
    return {
        "actions": output,
        "numerical_only": True,
        "threshold_tolerance": 1e-9,
        "metrics": {"seconds": perf_counter() - started, "lp_calls": calls},
    }
