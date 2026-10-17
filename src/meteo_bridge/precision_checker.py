"""Search-independent all-parameter proof verifier; no solver/compiler imports.

Endpoint attainment + convex interpolation verifies every bounded segment. An
affine feasible ray verifies the final unbounded parameter interval. Symbolic
dual paths bound each interval; an affine negative cycle excludes pre-activation.
"""

from collections import Counter
from fractions import Fraction as F

from .action_domain import validate_actions
from .certificates import _inputs, _path, _point
from .domain import digest


def _edges(triples):
    return {digest([u, v, str(w)])[:24]: (u, v, w) for u, v, w in triples}


def _walk(raw, bridges, tokens, start=None, end=None, cycle=False):
    if cycle:
        if not tokens:
            raise ValueError("empty activation cycle")
        start = (bridges[tokens[0]][0] if tokens[0] in bridges else raw[tokens[0]][0])
        end = start
    current, intercept, slope = start, F(0), 0
    for token in tokens:
        if token in bridges:
            u, v = bridges[token]
            weight, derivative = F(0), 1
        else:
            u, v, weight = raw[token]
            derivative = 0
        if u != current:
            raise ValueError("symbolic path discontinuity")
        current, intercept, slope = v, intercept + weight, slope + derivative
    if current != end:
        raise ValueError("symbolic path endpoint")
    return intercept, slope


def _first_failure(pair, diameter):
    start = F(pair["activation_rho"])
    if pair["kind"] == "unbounded":
        return start, True
    for segment in pair["segments"]:
        a = pair["affines"][segment["affine"]]
        lo, hi = F(segment["start"]), None if segment["end"] is None else F(segment["end"])
        b, k = F(a["intercept"]), a["slope"]
        if b + k * lo > diameter:
            return lo, True
        if k:
            crossing = (diameter - b) / k
            if crossing >= lo and (hi is None or crossing < hi):
                return crossing, False
    return None


def verify_precision_profiles(case, actions, result, certificate):
    try:
        validate_actions(case, actions)
        if case.query.objective != "amount" or any(a.kind != "interval" for a in actions):
            raise ValueError("unsupported precision contract")
        if case.query.calendar != "proleptic_gregorian":
            raise ValueError("unsupported calendar")
        if (certificate["version"] != "precision-1" or certificate["case_hash"] != digest(case) or
                certificate["actions_hash"] != digest([a.model_dump() for a in actions]) or
                result["certificate_id"] != digest(certificate)):
            raise ValueError("profile identity/hash mismatch")
        original, models = _inputs(case)
        times = sorted(set(original) | {t for a in actions for t in (a.start, a.end)})
        if len(times) > 128:
            raise ValueError("endpoint limit")
        models = {h: _edges(list(raw.values()) + [(b, a, F(0)) for a, b in zip(times, times[1:])])
                  for h, raw in models.items()}
        worlds = certificate["worlds"]
        if set(models) != set(worlds):
            raise ValueError("world coverage")
        for h, raw in models.items():
            if worlds[h]["feasible"]:
                _point(times, raw, worlds[h]["point"])
            else:
                _path(raw, worlds[h]["negative_cycle"], None, None, cycle=True)
        if len(certificate["pairs"]) != len(actions) or len(result["actions"]) != len(actions):
            raise ValueError("action coverage")
        any_feasible = any(w["feasible"] for w in worlds.values())
        for action, pairs, item in zip(actions, certificate["pairs"], result["actions"]):
            expected_pairs = [(h.id, k.id) for h in case.hypotheses for k in case.hypotheses]
            if [(p["left"], p["right"]) for p in pairs] != expected_pairs:
                raise ValueError("ordered pair coverage")
            failures = []
            for pair in pairs:
                lh, rh = pair["left"], pair["right"]
                if not worlds[lh]["feasible"] or not worlds[rh]["feasible"]:
                    if pair["kind"] != "excluded_world":
                        raise ValueError("world exclusion")
                    continue
                left = {t: i for i, t in enumerate(times)}
                right = {t: i+len(times) for i, t in enumerate(times)}
                right[action.start] = left[action.start]
                nodes = sorted(set(left.values()) | set(right.values()))
                base = _edges([(mapping[u], mapping[v], w) for mapping, h in ((left, lh), (right, rh))
                               for u, v, w in models[h].values()])
                bridges = {"noise_lr": (left[action.end], right[action.end]),
                           "noise_rl": (right[action.end], left[action.end])}
                coeff = Counter()
                for mapping, sign in ((left, 1), (right, -1)):
                    coeff[mapping[case.query.end]] += sign
                    coeff[mapping[case.query.start]] -= sign
                coeff = {v: c for v, c in coeff.items() if c}
                activation = F(pair["activation_rho"])
                if activation < 0:
                    raise ValueError("negative activation")
                if activation:
                    b, k = _walk(base, bridges, pair["activation_cycle"], cycle=True)
                    if k <= 0 or b + k * activation != 0:
                        raise ValueError("activation exclusion proof")

                def raw_at(rho):
                    return {**base, **{token: (u, v, rho) for token, (u, v) in bridges.items()}}

                if pair["kind"] == "unbounded":
                    _point(nodes, raw_at(activation), pair["point"])
                    ray = _point(nodes, raw_at(F(0)), pair["ray"], ray=True)
                    if sum(c*ray[v] for v, c in coeff.items()) <= 0:
                        raise ValueError("unbounded ray objective")
                elif pair["kind"] == "finite":
                    affines, segments = pair["affines"], pair["segments"]
                    if not 1 <= len(affines) <= 3 or len({a["slope"] for a in affines}) != len(affines):
                        raise ValueError("affine coverage/count")
                    for a in affines:
                        if type(a["slope"]) is not int or a["slope"] not in (0, 1, 2):
                            raise ValueError("invalid affine slope")
                        balance, b, k = Counter(), F(0), 0
                        for path in a["paths"]:
                            weight, count = _walk(base, bridges, path["edges"], path["start"], path["end"])
                            balance[path["start"]] -= 1
                            balance[path["end"]] += 1
                            b, k = b+weight, k+count
                        if {v: c for v, c in balance.items() if c} != coeff:
                            raise ValueError("dual coefficient balance")
                        if b != F(a["intercept"]) or k != a["slope"]:
                            raise ValueError("symbolic dual weight")
                    if not 1 <= len(segments) <= 3:
                        raise ValueError("segment count")
                    expected_start = activation
                    anchors = set()
                    for i, segment in enumerate(segments):
                        start = F(segment["start"])
                        stop = None if segment["end"] is None else F(segment["end"])
                        if start != expected_start or (stop is not None and stop <= start):
                            raise ValueError("profile parameter gap/overlap")
                        if (stop is None) != (i == len(segments)-1):
                            raise ValueError("infinite parameter coverage")
                        ai = segment["affine"]
                        if type(ai) is not int or not 0 <= ai < len(affines):
                            raise ValueError("affine reference")
                        a = affines[ai]
                        for at in (start, stop):
                            if at is not None:
                                anchors.add(str(at))
                                point = _point(nodes, raw_at(at), pair["points"][str(at)])
                                if sum(c*point[v] for v, c in coeff.items()) != F(a["intercept"]) + a["slope"]*at:
                                    raise ValueError("nonattaining profile anchor")
                        expected_start = stop
                    if set(pair["points"]) != anchors:
                        raise ValueError("anchor coverage")
                    derivative = {i: (u, v, F(0)) for i, (u, v, w) in base.items()}
                    derivative.update({i: (u, v, F(1)) for i, (u, v) in bridges.items()})
                    ray = _point(nodes, derivative, pair["terminal_ray"])
                    last = affines[segments[-1]["affine"]]
                    if sum(c*ray[v] for v, c in coeff.items()) != last["slope"]:
                        raise ValueError("terminal affine ray objective")
                else:
                    raise ValueError("invalid precision pair kind")
                failure = _first_failure(pair, 2*F(case.query.eps))
                if failure is not None:
                    failures.append(failure)
            if not any_feasible:
                frontier = {"radius_kind": "empty", "radius_supremum": None, "safe_at_supremum": False}
            elif not failures:
                frontier = {"radius_kind": "unbounded", "radius_supremum": None, "safe_at_supremum": None}
            else:
                boundary = min(at for at, included in failures)
                safe = not any(at == boundary and included for at, included in failures)
                frontier = {"radius_kind": "empty" if boundary == 0 and not safe else "finite",
                            "radius_supremum": str(boundary/2), "safe_at_supremum": safe}
            expected = {"id": action.id, "cost": action.cost, **frontier,
                        "conditional_guarantee": case.h_complete and any_feasible and frontier["radius_kind"] != "empty"}
            if item != expected:
                raise ValueError("incorrect precision frontier")
        status = "incomplete_model" if not case.h_complete else ("ok" if any_feasible else "inconsistent_model")
        if result["status"] != status or result["h_complete"] != case.h_complete or result["eps"] != case.query.eps:
            raise ValueError("incorrect scope/status")
        return {"valid": True, "checker_version": "precision-1", "verified_domain": "all finite eta >= 0",
                "conditional_on_complete_H": case.h_complete}
    except (ValueError, KeyError, TypeError, IndexError, ZeroDivisionError) as exc:
        return {"valid": False, "checker_version": "precision-1", "error": str(exc)}
