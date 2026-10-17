"""All-noise precision profiles for one bounded-error interval acquisition.

rho=2*eta bounds the difference of two true amounts producing a common answer.
Classical parametric network duality yields at most three affine upper functions
per ordered interpretation pair. Full primal witnesses certify every interval,
not only a sampled grid. This is a specialization, not a priority claim.
"""

from fractions import Fraction as F
from itertools import permutations, product
from time import perf_counter

from .action_domain import validate_actions
from .budget import begin, checkpoint, end
from .constraints import Edge
from .continuous_acquisition import _linear_max, _objective, _pair_edges, _prepare, _ray
from .domain import digest
from .graph import bellman, feasible_point
from .validated_paths import compiled_paths, exact_paths


def _layout(times, action):
    left = {t: i for i, t in enumerate(times)}
    right = {t: i + len(times) for i, t in enumerate(times)}
    right[action.start] = left[action.start]
    return left, right


def _project(case, action, left, right, graphs, closures):
    terminals = {case.query.start, case.query.end, action.start, action.end}
    minimal, expansions = {}, {}
    for mapping, edges, closure in zip((left, right), graphs, closures):
        raw = {e.id: e for e in edges}
        for u in terminals:
            for v in terminals:
                if u != v and v in closure[u]:
                    weight, path = closure[u][v]
                    edge = Edge(mapping[u], mapping[v], weight)
                    minimal[edge.id] = edge
                    expansions[edge.id] = [Edge(mapping[raw[i].u], mapping[raw[i].v], raw[i].w).id for i in path]
    nodes = sorted({mapping[t] for mapping in (left, right) for t in terminals})
    return nodes, list(minimal.values()), expansions


def _affines(paths, coeff, bridges):
    supply = [v for v, c in coeff.items() for _ in range(max(0, -c))]
    demand = [v for v, c in coeff.items() for _ in range(max(0, c))]
    best = {}

    def routes(source, target):
        routes = []
        if target in paths[source]:
            value, ids = paths[source][target]
            routes.append((0, value, ids))
        for token, (u, v) in bridges.items():
            if u in paths[source] and target in paths[v]:
                a, first = paths[source][u]
                b, last = paths[v][target]
                routes.append((1, a + b, first + [token] + last))
        return routes

    for targets in sorted(set(permutations(demand))):
        for chosen in product(*(routes(s, t) for s, t in zip(supply, targets))):
            slope = sum(r[0] for r in chosen)
            intercept = sum((r[1] for r in chosen), F(0))
            dual = [{"start": s, "end": t, "edges": r[2]} for s, t, r in zip(supply, targets, chosen)]
            if slope not in best or intercept < F(best[slope]["intercept"]):
                best[slope] = {"slope": slope, "intercept": str(intercept), "paths": dual}
    return [best[k] for k in sorted(best)]


def _segments(affines, activation):
    cuts = {activation}
    for i, a in enumerate(affines):
        for b in affines[i+1:]:
            if a["slope"] != b["slope"]:
                x = (F(b["intercept"]) - F(a["intercept"])) / (a["slope"] - b["slope"])
                if x > activation:
                    cuts.add(x)
    cuts = sorted(cuts)
    segments = []
    for i, start in enumerate(cuts):
        stop = cuts[i+1] if i+1 < len(cuts) else None
        at = (start + stop) / 2 if stop is not None else start + 1
        active = min(range(len(affines)), key=lambda j: F(affines[j]["intercept"]) + affines[j]["slope"] * at)
        if segments and segments[-1]["affine"] == active:
            segments[-1]["end"] = str(stop) if stop is not None else None
        else:
            segments.append({"start": str(start), "end": str(stop) if stop is not None else None, "affine": active})
    return segments


def _attainment(nodes, base, bridges, coeff, rho, affine):
    noise = {token: Edge(u, v, rho) for token, (u, v) in bridges.items()}
    raw = {e.id: e for e in base}
    raw.update(noise)
    tight = [Edge(raw[i].v, raw[i].u, -raw[i].w) for p in affine["paths"] for i in p["edges"]]
    point = feasible_point(nodes, base + list(noise.values()) + tight)
    if sum(c * F(point[str(v)]) for v, c in coeff.items()) != F(affine["intercept"]) + affine["slope"] * rho:
        raise RuntimeError("profile witness does not attain dual bound")
    return point


def _terminal_ray(nodes, base, bridges, coeff, slope):
    if slope == 0:
        return {str(v): "0" for v in nodes}
    derivative = list(set([Edge(e.u, e.v, F(0)) for e in base] +
                          [Edge(u, v, F(1)) for u, v in bridges.values()]))
    value, paths = _linear_max(nodes, derivative, coeff)
    if value != slope:
        raise RuntimeError("profile terminal slope mismatch")
    by_id = {e.id: e for e in derivative}
    tight = [Edge(by_id[i].v, by_id[i].u, -by_id[i].w) for s, t, ids in paths for i in ids]
    return feasible_point(nodes, derivative + tight)


def _pair(case, action, times, graphs, closures, method):
    left, right = _layout(times, action)
    nodes = sorted(set(left.values()) | set(right.values()))
    base = _pair_edges(left, right, *graphs)
    coeff = _objective(case.query, left, right)
    lv, rv = left[action.end], right[action.end]
    bridges = {"noise_lr": (lv, rv), "noise_rl": (rv, lv)}
    sources = {v for v, c in coeff.items() if c < 0} | {lv, rv}
    if method.startswith("terminal"):
        small_nodes, small, expanded = _project(case, action, left, right, graphs, closures)
        paths = exact_paths(small_nodes, small, sources)
        paths = {s: {t: (w, [raw for i in ids for raw in expanded[i]]) for t, (w, ids) in row.items()}
                 for s, row in paths.items()}
    else:
        paths = (compiled_paths if method == "compiled" else exact_paths)(nodes, base, sources)
    activation, cycle = F(0), None
    for u, v, back in ((lv, rv, "noise_rl"), (rv, lv, "noise_lr")):
        if v in paths[u] and -paths[u][v][0] > activation:
            activation = -paths[u][v][0]
            cycle = paths[u][v][1] + [back]
    affines = _affines(paths, coeff, bridges)
    common = {"activation_rho": str(activation), "activation_cycle": cycle}
    at_start = base + [Edge(u, v, activation) for u, v in bridges.values()]
    if not affines:
        return {**common, "kind": "unbounded", "point": feasible_point(nodes, at_start),
                "ray": _ray(nodes, at_start, coeff)}
    segments = _segments(affines, activation)
    points = {}
    for segment in segments:
        affine = affines[segment["affine"]]
        for x in (segment["start"], segment["end"]):
            if x is not None and x not in points:
                points[x] = _attainment(nodes, base, bridges, coeff, F(x), affine)
    ray = _terminal_ray(nodes, base, bridges, coeff, affines[segments[-1]["affine"]]["slope"])
    return {**common, "kind": "finite", "affines": affines, "segments": segments,
            "points": points, "terminal_ray": ray}


def _frontier(pairs, diameter):
    failures = []
    for pair in pairs:
        if pair["kind"] == "excluded_world":
            continue
        start = F(pair["activation_rho"])
        if pair["kind"] == "unbounded":
            failures.append((start, True))
            continue
        lines = pair["affines"]
        if any(a["slope"] == 0 and F(a["intercept"]) <= diameter for a in lines):
            continue
        limits = [(diameter - F(a["intercept"])) / a["slope"] for a in lines if a["slope"]]
        cut = max([start] + limits)
        fails_at_cut = min(F(a["intercept"]) + a["slope"] * cut for a in lines) > diameter
        failures.append((cut, fails_at_cut))
    if not failures:
        return {"radius_kind": "unbounded", "radius_supremum": None, "safe_at_supremum": None}
    boundary = min(x for x, closed in failures)
    included = not any(x == boundary and closed for x, closed in failures)
    return {"radius_kind": "empty" if boundary == 0 and not included else "finite",
            "radius_supremum": str(boundary / 2), "safe_at_supremum": included}


def build_precision_profiles(case, actions, method="terminal", timeout_seconds=120):
    validate_actions(case, actions)
    if case.query.objective != "amount" or any(a.kind != "interval" for a in actions):
        raise ValueError("precision profiles support amount Query and interval actions only")
    if method not in ("full", "compiled", "terminal", "terminal_no_reuse"):
        raise ValueError("unknown precision method")
    token, execution = begin(timeout_seconds)
    started = perf_counter()
    try:
        times, graphs = _prepare(case, actions)
        worlds, closures = {}, {}
        needed = {case.query.start, case.query.end} | {t for a in actions for t in (a.start, a.end)}
        for hid, edges in graphs.items():
            _, _, cycle = bellman(times, edges)
            worlds[hid] = ({"feasible": False, "negative_cycle": [e.id for e in cycle]} if cycle else
                           {"feasible": True, "point": feasible_point(times, edges)})
            if not cycle and method == "terminal":
                closures[hid] = compiled_paths(times, edges, needed)
        records = []
        for action in actions:
            checkpoint()
            if method == "terminal_no_reuse":
                retained = {case.query.start, case.query.end, action.start, action.end}
                closures = {h: compiled_paths(times, graphs[h], retained) for h in graphs if worlds[h]["feasible"]}
            pairs = []
            for lh in case.hypotheses:
                for rh in case.hypotheses:
                    checkpoint()
                    proof = ({"kind": "excluded_world"} if not worlds[lh.id]["feasible"] or not worlds[rh.id]["feasible"] else
                             _pair(case, action, times, (graphs[lh.id], graphs[rh.id]),
                                   (closures.get(lh.id), closures.get(rh.id)), method))
                    pairs.append({"left": lh.id, "right": rh.id, **proof})
            records.append(pairs)
        feasible = any(w["feasible"] for w in worlds.values())
        certificate = {"version": "precision-1", "case_hash": digest(case),
                       "actions_hash": digest([a.model_dump() for a in actions]), "worlds": worlds, "pairs": records}
        output = []
        for action, pairs in zip(actions, records):
            frontier = (_frontier(pairs, 2 * F(case.query.eps)) if feasible else
                        {"radius_kind": "empty", "radius_supremum": None, "safe_at_supremum": False})
            output.append({"id": action.id, "cost": action.cost, **frontier,
                           "conditional_guarantee": case.h_complete and feasible and frontier["radius_kind"] != "empty"})
        result = {"status": "incomplete_model" if not case.h_complete else ("ok" if feasible else "inconsistent_model"),
                  "h_complete": case.h_complete, "eps": case.query.eps, "actions": output,
                  "certificate_id": digest(certificate)}
        from .precision_checker import verify_precision_profiles

        checker = verify_precision_profiles(case, actions, result, certificate)
        if not checker["valid"]:
            raise RuntimeError(f"precision certificate rejected: {checker}")
        checkpoint()
        return {"result": result, "certificate": certificate, "checker": checker,
                "metrics": {"seconds": perf_counter()-started, "method": method, "endpoints": len(times),
                            "pairs": sum(map(len, records)), "operations": execution["counts"]}}
    finally:
        end(token)


def precision_values(case, actions, bundle, radii):
    from .precision_checker import verify_precision_profiles

    if not 1 <= len(radii) <= 64:
        raise ValueError("need 1..64 evaluation radii")
    if not verify_precision_profiles(case, actions, bundle["result"], bundle["certificate"])["valid"]:
        raise ValueError("unverified precision bundle")
    output = []
    for eta in map(F, radii):
        if eta < 0:
            raise ValueError("negative observation error radius")
        items = []
        for action, pairs in zip(actions, bundle["certificate"]["pairs"]):
            active = [p for p in pairs if p["kind"] != "excluded_world" and F(p["activation_rho"]) <= 2 * eta]
            kind = "empty" if not active else ("unbounded" if any(p["kind"] == "unbounded" for p in active) else "finite")
            width = (max(min(F(a["intercept"]) + a["slope"] * 2 * eta for a in p["affines"]) for p in active)
                     if kind == "finite" else None)
            items.append({"id": action.id, "width_kind": kind, "width": str(width) if width is not None else None,
                          "guarantees_resolution": case.h_complete and width is not None and width <= 2 * F(case.query.eps)})
        output.append({"radius": str(eta), "actions": items})
    return output
