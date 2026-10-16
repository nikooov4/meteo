"""Exact single-action, continuous-outcome minimax oracle.

The reductions use classical difference constraints and flow duality. Terminal
closure is a candidate implementation improvement, not a claim of a new theorem.
"""

from collections import Counter, OrderedDict
from fractions import Fraction as F
from itertools import permutations
from time import perf_counter

from .action_domain import compatible, validate_actions
from .budget import begin, checkpoint, end
from .constraints import Edge
from .domain import digest
from .graph import bellman, feasible_point, path_to
from .semantics import compile_case

_CACHE = OrderedDict()


def clear_acquisition_cache():
    _CACHE.clear()


def _prepare(case, actions):
    times, worlds = compile_case(case)
    times = sorted(set(times) | {t for a in actions if a.kind == "interval" for t in (a.start, a.end)})
    if len(times) > 128:
        raise ValueError("acquisition working-model limit: 128 endpoints including actions")
    for hid, edges in worlds.items():
        worlds[hid] = sorted(
            set(edges + [Edge(b, a, F(0)) for a, b in zip(times, times[1:])]), key=lambda e: (e.u, e.v, e.w)
        )
    return times, worlds


def _layout(times, action):
    n = len(times)
    left = {t: i for i, t in enumerate(times)}
    right = {t: i + n for i, t in enumerate(times)}
    if action.kind == "interval":
        for t in (action.start, action.end):
            right[t] = left[t]
    return left, right


def _pair_edges(left, right, le, re):
    return sorted(
        set([Edge(left[e.u], left[e.v], e.w) for e in le] + [Edge(right[e.u], right[e.v], e.w) for e in re]),
        key=lambda e: (e.u, e.v, e.w),
    )


def _objective(query, left, right):
    c = Counter()
    for v, w in (
        (left[query.end], 1),
        (left[query.start], -1),
        (right[query.start], 1),
        (right[query.end], -1),
    ):
        c[v] += w
    return {v: w for v, w in c.items() if w}


def _closure(times, edges):
    paths = {}
    for s in times:
        dist, pred, _ = bellman(times, edges, s)
        paths[s] = {t: (d, path_to(pred, s, t)) for t, d in dist.items() if d is not None}
    return paths


def _compressed(case, action, left, right, closures):
    terminals = {case.query.start, case.query.end}
    if action.kind == "interval":
        terminals.update((action.start, action.end))
    expanded = {}
    for mapping, closure in zip((left, right), closures):
        # Remapped original edge ids are stored later by the caller.
        for u in terminals:
            for v in terminals:
                if u != v and v in closure[u]:
                    w, path = closure[u][v]
                    edge = Edge(mapping[u], mapping[v], w)
                    expanded[edge.id] = path, mapping
    return expanded


def _linear_max(nodes, edges, coeff):
    """At most two units of flow: enumerate the <=2 supply-demand matchings."""
    supply = [v for v, c in coeff.items() for _ in range(max(0, -c))]
    demand = [v for v, c in coeff.items() for _ in range(max(0, c))]
    routes = {}
    for s in set(supply):
        dist, pred, _ = bellman(nodes, edges, s)
        routes[s] = {t: (d, path_to(pred, s, t)) for t, d in dist.items() if d is not None}
    best = None
    for targets in set(permutations(demand)):
        if all(t in routes[s] for s, t in zip(supply, targets)):
            value = sum((routes[s][t][0] for s, t in zip(supply, targets)), F(0))
            paths = [(s, t, routes[s][t][1]) for s, t in zip(supply, targets)]
            if best is None or value < best[0]:
                best = value, paths
    return best


def _ray(nodes, edges, coeff):
    positive = [v for v, c in coeff.items() if c > 0]
    for mask in range(1, 1 << len(positive)):
        reached = {v for i, v in enumerate(positive) if mask & (1 << i)}
        changed = True
        while changed:
            changed = False
            for e in edges:
                if e.v in reached and e.u not in reached:
                    reached.add(e.u)
                    changed = True
        if sum(c for v, c in coeff.items() if v in reached) > 0:
            return {str(v): str(int(v in reached)) for v in nodes}
    raise RuntimeError("unbounded matching without an objective-increasing predecessor cut")


def _solve_pair(case, action, times, le, re, closure_pair, method):
    left, right = _layout(times, action)
    full = _pair_edges(left, right, le, re)
    nodes = sorted(set(left.values()) | set(right.values()))
    coeff = _objective(case.query, left, right)
    threshold_edge = None
    if case.query.objective == "threshold":
        threshold_edge = Edge(left[case.query.end], left[case.query.start], -F(case.query.threshold))
        full = sorted(set(full + [threshold_edge]), key=lambda e: (e.u, e.v, e.w))
        coeff = {right[case.query.start]: 1, right[case.query.end]: -1}
    # Compression uses exact per-world closure; objective/threshold endpoints are retained.
    expanded = None
    if method == "terminal":
        raw = _compressed(case, action, left, right, closure_pair)
        by_id = {e.id: e for e in le + re}
        small = []
        expanded = {}
        for eid, (ids, mapping) in raw.items():
            path = [Edge(mapping[by_id[i].u], mapping[by_id[i].v], by_id[i].w) for i in ids]
            edge = Edge(path[0].u, path[-1].v, sum((e.w for e in path), F(0)))
            small.append(edge)
            expanded[eid] = [e.id for e in path]
        if threshold_edge:
            small.append(threshold_edge)
            expanded[threshold_edge.id] = [threshold_edge.id]
        work = sorted(set(small), key=lambda e: (e.u, e.v, e.w))
        work_nodes = sorted(set(coeff) | {v for e in work for v in (e.u, e.v)})
        # Also retain isolated objective/action terminals.
        for t in (case.query.start, case.query.end):
            work_nodes = sorted(set(work_nodes) | {left[t], right[t]})
    else:
        work, work_nodes = full, nodes

    def expand(ids):
        return [i for eid in ids for i in (expanded[eid] if expanded is not None else [eid])]

    _, _, cycle = bellman(work_nodes, work)
    if cycle:
        return {"kind": "empty", "negative_cycle": expand([e.id for e in cycle])}
    optimum = _linear_max(work_nodes, work, coeff)
    if optimum is None:
        return {"kind": "unbounded", "point": feasible_point(nodes, full), "ray": _ray(nodes, full, coeff)}
    value, routes = optimum
    paths = [{"start": s, "end": t, "edges": expand(ids)} for s, t, ids in routes]
    by_id = {e.id: e for e in full}
    tight = [Edge(by_id[eid].v, by_id[eid].u, -by_id[eid].w) for p in paths for eid in p["edges"]]
    point = feasible_point(nodes, full + tight)
    result = {"kind": "finite", "value": str(value), "dual_paths": paths, "point": point}
    if case.query.objective == "threshold":
        result["opposite_decisions"] = -value < F(case.query.threshold)
    return result


def summarize(case, actions, worlds, records):
    feasible = any(w["feasible"] for w in worlds.values())
    output = []
    for action, pairs in zip(actions, records):
        item = {
            "id": action.id,
            "cost": action.cost,
            "worst_remaining_width": None,
            "width_kind": "not_applicable",
            "guarantees_resolution": False,
        }
        if not feasible:
            item["width_kind"] = "empty"
        elif case.query.objective == "amount":
            active = [p for p in pairs if p["kind"] in ("finite", "unbounded")]
            if any(p["kind"] == "unbounded" for p in active):
                item["width_kind"] = "unbounded"
            else:
                width = max(F(p["value"]) for p in active)
                item.update(
                    worst_remaining_width=str(width),
                    width_kind="finite",
                    guarantees_resolution=case.h_complete and width <= 2 * F(case.query.eps),
                )
        else:
            item["guarantees_resolution"] = case.h_complete and not any(
                p.get("opposite_decisions", False) or p["kind"] == "unbounded" for p in pairs
            )
        output.append(item)
    return {
        "status": "incomplete_model" if not case.h_complete else ("ok" if feasible else "inconsistent_model"),
        "actions": output,
    }


def evaluate_actions(case, actions, method="terminal", timeout_seconds=60):
    """One-step minimax oracle; does not select/execute an action or assume a prior."""
    if method not in ("terminal", "graph", "cache"):
        raise ValueError("method must be terminal, graph or cache")
    validate_actions(case, actions)
    token, execution = begin(timeout_seconds)
    started = perf_counter()
    key = digest([case.model_dump(), [a.model_dump() for a in actions]])
    try:
        checkpoint()
        if method == "cache" and key in _CACHE:
            import copy

            from .acquisition_checker import verify_acquisition

            bundle = copy.deepcopy(_CACHE[key])
            _CACHE.move_to_end(key)
            bundle["checker"] = verify_acquisition(case, actions, bundle["result"], bundle["certificate"])
            if not bundle["checker"]["valid"]:
                raise RuntimeError("cached certificate rejected")
            checkpoint()
            bundle["metrics"] = {"seconds": perf_counter() - started, "method": method, "cache_hit": True}
            return bundle
        times, graphs = _prepare(case, actions)
        worlds, closures = {}, {}
        for h, edges in graphs.items():
            _, _, cycle = bellman(times, edges)
            worlds[h] = (
                {"feasible": False, "negative_cycle": [e.id for e in cycle]}
                if cycle
                else {"feasible": True, "point": feasible_point(times, edges)}
            )
            if not cycle and method == "terminal":
                closures[h] = _closure(times, edges)
        records = []
        for action in actions:
            pairs = []
            for lh in case.hypotheses:
                for rh in case.hypotheses:
                    checkpoint()
                    if not worlds[lh.id]["feasible"] or not worlds[rh.id]["feasible"]:
                        proof = {"kind": "excluded_world"}
                    elif not compatible(action, lh, rh):
                        proof = {"kind": "different_response"}
                    else:
                        proof = _solve_pair(
                            case,
                            action,
                            times,
                            graphs[lh.id],
                            graphs[rh.id],
                            (closures.get(lh.id), closures.get(rh.id)),
                            method,
                        )
                    pairs.append({"left": lh.id, "right": rh.id, **proof})
            records.append(pairs)
        certificate = {
            "version": "continuous-acquisition-1",
            "case_hash": digest(case),
            "actions_hash": digest([a.model_dump() for a in actions]),
            "worlds": worlds,
            "pairs": records,
        }
        result = summarize(case, actions, worlds, records)
        result["certificate_id"] = digest(certificate)
        from .acquisition_checker import verify_acquisition

        verdict = verify_acquisition(case, actions, result, certificate)
        if not verdict["valid"]:
            raise RuntimeError(f"acquisition certificate rejected: {verdict}")
        checkpoint()
        bundle = {
            "result": result,
            "certificate": certificate,
            "checker": verdict,
            "metrics": {
                "seconds": perf_counter() - started,
                "method": method,
                "cache_hit": False,
                "endpoints": len(times),
                "hypotheses": len(worlds),
                "pairs": sum(map(len, records)),
                "operations": execution["counts"],
            },
        }
        if method == "cache":
            import copy

            _CACHE[key] = copy.deepcopy(bundle)
            while len(_CACHE) > 4:
                _CACHE.popitem(last=False)
        return bundle
    finally:
        end(token)
