"""Search-independent rational verifier. Does not import solvers or compiler."""

from fractions import Fraction as F

from .domain import Case, digest


def _inputs(case):
    times = {case.query.start, case.query.end}
    raw = {}
    for h in case.hypotheses:
        constraints = []
        baselines = set()
        for obs in case.observations:
            if obs.series != case.query.series:
                raise ValueError("mixed SeriesKey")
            if obs.qc != "accepted":
                continue
            s = h.intervals.get(obs.id, obs.interval)
            if s is None:
                raise ValueError("unresolved interval")
            a, b = s.start, s.end
            if s.statistic == "cumulative":
                if s.reset_start is None:
                    raise ValueError("missing reset baseline")
                if obs.series.cycle is None or obs.reset_group != obs.series.cycle:
                    raise ValueError("missing/mixed cumulative cycle")
                a = s.reset_start
                baselines.add(a)
            if s.statistic == "interval_mean_rate":
                factor = {"mm/h": F(1, 3600), "m/s": F(1000), "kg m-2 s-1": F(1)}[s.unit] * (b - a)
            elif s.statistic in ("amount", "cumulative"):
                factor = {"mm": F(1), "m": F(1000), "kg m-2": F(1)}[s.unit]
            else:
                raise ValueError("unsupported statistic")
            if b <= a:
                raise ValueError("invalid interval")
            constraints.extend([(a, b, F(obs.upper) * factor), (b, a, -F(obs.lower) * factor)])
            times.update((a, b))
        if len(baselines) > 1:
            raise ValueError("different cumulative reset baselines")
        raw[h.id] = constraints
    times = sorted(times)
    for h, triples in raw.items():
        triples += [(b, a, F(0)) for a, b in zip(times, times[1:])]
        raw[h] = {digest([a, b, str(w)])[:24]: (a, b, w) for a, b, w in triples}
    return times, raw


def _point(times, edges, point, ray=False):
    if set(point) != {str(t) for t in times}:
        raise ValueError("witness endpoint coverage")
    values = {t: F(point[str(t)]) for t in times}
    for a, b, w in edges.values():
        if values[b] - values[a] > (0 if ray else w):
            raise ValueError("infeasible witness/ray")
    return values


def _path(edges, ids, start, end, expected=None, cycle=False):
    if cycle:
        if not ids:
            raise ValueError("empty conflict certificate")
        start = edges[ids[0]][0]
        end = start
    value, node = F(0), start
    for edge_id in ids:
        a, b, w = edges[edge_id]
        if a != node:
            raise ValueError("path orientation/continuity")
        node, value = b, value + w
    if node != end or (expected is not None and value != expected):
        raise ValueError("path endpoint/weight")
    if cycle and value >= 0:
        raise ValueError("cycle is not negative")


def verify_certificate(case: Case, result: dict, certificate: dict) -> dict:
    """Reject forged hashes, scope, units, bounds, paths, conflicts or witnesses."""
    try:
        if certificate["version"] != "1" or certificate["numerical_policy"] != "exact-rational-v1":
            raise ValueError("unsupported checker version")
        if certificate["case_hash"] != digest(case) or certificate["query_hash"] != digest(case.query):
            raise ValueError("input/query hash mismatch")
        if result["certificate_id"] != digest(certificate):
            raise ValueError("certificate hash mismatch")
        for field, expected in (
            ("unit", "mm"),
            ("case_hash", digest(case)),
            ("h_complete", case.h_complete),
            ("revision", case.revision),
            ("scope", [h.id for h in case.hypotheses]),
            ("assumptions", case.assumptions),
        ):
            if result[field] != expected:
                raise ValueError("result identity/unit/scope mismatch")
        if certificate["scope"] != [h.id for h in case.hypotheses]:
            raise ValueError("scope H mismatch")
        if certificate["h_complete"] != case.h_complete or certificate["unit"] != "mm":
            raise ValueError("unit/completeness mismatch")
        if certificate["assumptions"] != case.assumptions or certificate["revision"] != case.revision:
            raise ValueError("assumptions/revision mismatch")
        if case.query.calendar != "proleptic_gregorian":
            raise ValueError("unsupported_calendar")
        times, models = _inputs(case)
        if "observation_hashes" in certificate and certificate["observation_hashes"] != {
            o.id: digest(o) for o in case.observations
        }:
            raise ValueError("observation checksum mismatch")
        if "normalized_constraints" in certificate:
            if set(certificate["normalized_constraints"]) != set(models):
                raise ValueError("normalized constraint scope mismatch")
            for hid, edges in models.items():
                triples = {
                    e["id"]: (e["u"], e["v"], F(e["w"])) for e in certificate["normalized_constraints"][hid]
                }
                if triples != edges:
                    raise ValueError("normalized inequality mismatch")
        if set(certificate["worlds"]) != set(models):
            raise ValueError("missing or extra hypothesis")
        feasible, s, t = [], case.query.start, case.query.end
        for hid, edges in models.items():
            world = certificate["worlds"][hid]
            if not world["feasible"]:
                _path(edges, world["negative_cycle"], None, None, cycle=True)
                continue
            feasible.append(world)
            _point(times, edges, world["point"])
            for kind, a, b, sign in (("lower", t, s, -1), ("upper", s, t, 1)):
                raw = world[kind]
                if raw is not None:
                    value = F(raw)
                    _path(edges, world[kind + "_path"], a, b, sign * value)
                    values = _point(times, edges, world[kind + "_point"])
                    if values[t] - values[s] != value:
                        raise ValueError("nonattaining extreme witness")
                else:
                    ray = _point(times, edges, world[kind + "_ray"], ray=True)
                    if sign * (ray[t] - ray[s]) <= 0:
                        raise ValueError("ray does not prove unbounded objective")
        lower = (
            None
            if not feasible or any(w["lower"] is None for w in feasible)
            else min(F(w["lower"]) for w in feasible)
        )
        upper = (
            None
            if not feasible or any(w["upper"] is None for w in feasible)
            else max(F(w["upper"]) for w in feasible)
        )
        for key, expected in (("lower", lower), ("upper", upper)):
            if result[key] != (str(expected) if expected is not None else None):
                raise ValueError("incorrect aggregate bound")
            kind = "finite" if expected is not None else ("unbounded" if feasible else "empty")
            if result["bound_kind"][key] != kind:
                raise ValueError("incorrect bound kind")
        if not case.h_complete and result["status"] != "incomplete_model":
            raise ValueError("incomplete H cannot certify")
        if not feasible and case.h_complete and result["status"] != "inconsistent_model":
            raise ValueError("empty feasible set")
        decision, estimate = None, None
        determined = False
        if feasible and case.h_complete:
            if case.query.objective == "threshold":
                tau = F(case.query.threshold)
                decision = (
                    True
                    if lower is not None and lower >= tau
                    else (False if upper is not None and upper < tau else None)
                )
                determined = decision is not None
            elif lower is not None and upper is not None and upper - lower <= 2 * F(case.query.eps):
                estimate, determined = str((lower + upper) / 2), True
        if result["decision"] != decision or result["point_estimate"] != estimate:
            raise ValueError("incorrect decision or point estimate")
        if (result["status"] == "certified") != determined:
            raise ValueError("incorrect certified status")
        for witness in result.get("witnesses", []):
            if not certificate["worlds"][witness["hypothesis"]]["feasible"]:
                raise ValueError("witness in excluded world")
            values = _point(times, models[witness["hypothesis"]], witness["potentials"])
            if F(witness["q"]) != values[t] - values[s]:
                raise ValueError("incorrect witness query value")
        witnesses = result.get("witnesses", [])
        if len(witnesses) == 2 and F(witnesses[0]["q"]) == F(witnesses[1]["q"]):
            raise ValueError("witness pair does not diverge")
        if (
            len(witnesses) == 2
            and case.h_complete
            and case.query.objective == "threshold"
            and result["decision"] is None
        ):
            if len({F(w["q"]) >= F(case.query.threshold) for w in witnesses}) != 2:
                raise ValueError("witnesses do not straddle the unresolved threshold")
        return {"valid": True, "checker_version": "1", "conditional_on_complete_H": case.h_complete}
    except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
        return {"valid": False, "checker_version": "1", "error": str(exc)}
