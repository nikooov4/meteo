"""Search-independent verifier for the single-action oracle.

Reconstructs raw inequalities, paths and witnesses; imports no solver/compiler.
Classical weak LP duality + attaining points prove each finite pair optimum.
"""

from collections import Counter
from fractions import Fraction as F

from .action_domain import validate_actions
from .certificates import _inputs, _path, _point
from .domain import digest


def _edge_dict(triples):
    return {digest([u, v, str(w)])[:24]: (u, v, w) for u, v, w in triples}


def verify_acquisition(case, actions, result, certificate):
    try:
        validate_actions(case, actions)
        if case.query.calendar != "proleptic_gregorian":
            raise ValueError("unsupported calendar")
        if (
            certificate["version"] != "continuous-acquisition-1"
            or certificate["case_hash"] != digest(case)
            or certificate["actions_hash"] != digest([a.model_dump() for a in actions])
            or result["certificate_id"] != digest(certificate)
        ):
            raise ValueError("identity/hash mismatch")
        original_times, raw = _inputs(case)
        times = sorted(
            set(original_times) | {t for a in actions if a.kind == "interval" for t in (a.start, a.end)}
        )
        if len(times) > 128:
            raise ValueError("endpoint limit")
        models = {
            h: _edge_dict(list(edges.values()) + [(b, a, F(0)) for a, b in zip(times, times[1:])])
            for h, edges in raw.items()
        }
        worlds = certificate["worlds"]
        if set(worlds) != set(models):
            raise ValueError("world coverage")
        for hid, edges in models.items():
            if worlds[hid]["feasible"]:
                _point(times, edges, worlds[hid]["point"])
            else:
                _path(edges, worlds[hid]["negative_cycle"], None, None, cycle=True)
        if len(certificate["pairs"]) != len(actions) or len(result["actions"]) != len(actions):
            raise ValueError("action coverage")
        feasible = any(w["feasible"] for w in worlds.values())
        for action, records, item in zip(actions, certificate["pairs"], result["actions"]):
            if [(p["left"], p["right"]) for p in records] != [
                (lh.id, rh.id) for lh in case.hypotheses for rh in case.hypotheses
            ]:
                raise ValueError("ordered pair coverage")
            finite, infinite, opposite = [], False, False
            for p in records:
                lh, rh = p["left"], p["right"]
                if not worlds[lh]["feasible"] or not worlds[rh]["feasible"]:
                    if p["kind"] != "excluded_world":
                        raise ValueError("infeasible world exclusion")
                    continue
                if action.kind == "metadata":
                    hs = {h.id: h for h in case.hypotheses}
                    if hs[lh].assignments[action.attribute] != hs[rh].assignments[action.attribute]:
                        if p["kind"] != "different_response":
                            raise ValueError("metadata exclusion")
                        continue
                left = {t: i for i, t in enumerate(times)}
                right = {t: i + len(times) for i, t in enumerate(times)}
                if action.kind == "interval":
                    right[action.start], right[action.end] = left[action.start], left[action.end]
                nodes = sorted(set(left.values()) | set(right.values()))
                triples = [(left[u], left[v], w) for u, v, w in models[lh].values()]
                triples += [(right[u], right[v], w) for u, v, w in models[rh].values()]
                coeff = Counter()
                if case.query.objective == "threshold":
                    triples.append((left[case.query.end], left[case.query.start], -F(case.query.threshold)))
                    coeff[right[case.query.start]] += 1
                    coeff[right[case.query.end]] -= 1
                else:
                    for mapping, sign in ((left, 1), (right, -1)):
                        coeff[mapping[case.query.end]] += sign
                        coeff[mapping[case.query.start]] -= sign
                coeff = Counter({v: c for v, c in coeff.items() if c})
                edges = _edge_dict(triples)
                if p["kind"] == "empty":
                    _path(edges, p["negative_cycle"], None, None, cycle=True)
                    continue
                point = _point(nodes, edges, p["point"])
                if p["kind"] == "unbounded":
                    ray = _point(nodes, edges, p["ray"], ray=True)
                    if sum(c * ray[v] for v, c in coeff.items()) <= 0:
                        raise ValueError("ray objective")
                    infinite = True
                    continue
                if p["kind"] != "finite":
                    raise ValueError("invalid pair proof kind")
                balance, weight = Counter(), F(0)
                for path in p["dual_paths"]:
                    _path(edges, path["edges"], path["start"], path["end"])
                    balance[path["start"]] -= 1
                    balance[path["end"]] += 1
                    weight += sum((edges[i][2] for i in path["edges"]), F(0))
                # Counter equality includes negative values; do not use unary +.
                if dict((v, c) for v, c in balance.items() if c) != dict(coeff):
                    raise ValueError("dual objective balance")
                if weight != F(p["value"]) or sum(c * point[v] for v, c in coeff.items()) != weight:
                    raise ValueError("primal/dual gap")
                finite.append(weight)
                if case.query.objective == "threshold":
                    actual = -weight < F(case.query.threshold)
                    if p["opposite_decisions"] != actual:
                        raise ValueError("strict threshold boundary")
                    opposite |= actual
            expected = {
                "id": action.id,
                "cost": action.cost,
                "worst_remaining_width": None,
                "width_kind": "not_applicable",
                "guarantees_resolution": False,
            }
            if not feasible:
                expected["width_kind"] = "empty"
            elif case.query.objective == "amount":
                if infinite:
                    expected["width_kind"] = "unbounded"
                else:
                    width = max(finite)
                    expected.update(
                        worst_remaining_width=str(width),
                        width_kind="finite",
                        guarantees_resolution=case.h_complete and width <= 2 * F(case.query.eps),
                    )
            else:
                expected["guarantees_resolution"] = case.h_complete and not opposite and not infinite
            if item != expected:
                raise ValueError("incorrect action aggregate")
        expected_status = (
            "incomplete_model" if not case.h_complete else ("ok" if feasible else "inconsistent_model")
        )
        if result["status"] != expected_status:
            raise ValueError("incorrect completeness/conflict status")
        return {
            "valid": True,
            "checker_version": "continuous-acquisition-1",
            "conditional_on_complete_H": case.h_complete,
        }
    except (KeyError, ValueError, TypeError, ZeroDivisionError, IndexError) as exc:
        return {"valid": False, "checker_version": "continuous-acquisition-1", "error": str(exc)}
