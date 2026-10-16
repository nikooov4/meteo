"""Sparse exact Bellman–Ford reference; negative cycles anywhere are conflicts."""

from fractions import Fraction as F

from .budget import checkpoint, count
from .constraints import Edge


def bellman(times, edges, source=None):
    count("bellman_ford_calls")
    dist = dict.fromkeys(times, F(0) if source is None else None)
    pred = {}
    if source is not None:
        dist[source] = F(0)
    changed = None
    for _ in times:
        checkpoint()
        count("edge_relaxation_attempts", len(edges))
        changed = None
        for e in edges:
            if dist[e.u] is not None and (dist[e.v] is None or dist[e.v] > dist[e.u] + e.w):
                dist[e.v] = dist[e.u] + e.w
                pred[e.v] = e
                changed = e.v
        if changed is None:
            return dist, pred, []
    node = changed
    for _ in times:
        node = pred[node].u
    cycle, current = [], node
    while True:
        e = pred[current]
        cycle.append(e)
        current = e.u
        if current == node:
            break
    return dist, pred, list(reversed(cycle))


def path_to(pred, source, target):
    path, current = [], target
    while current != source:
        if current not in pred or len(path) > len(pred):
            raise RuntimeError("broken shortest path")
        edge = pred[current]
        path.append(edge.id)
        current = edge.u
    return list(reversed(path))


def feasible_point(times, edges):
    dist, _, cycle = bellman(times, edges)
    if cycle:
        raise RuntimeError("infeasible augmented graph")
    gauge = dist[times[0]]
    return {str(t): str(dist[t] - gauge) for t in times}


def finish_world(times, edges, start, end, lower, upper, lower_path, upper_path):
    """Attach attaining models; an unbounded endpoint gets a feasible recession ray."""
    result = {
        "feasible": True,
        "lower": str(lower) if lower is not None else None,
        "upper": str(upper) if upper is not None else None,
        "lower_path": lower_path,
        "upper_path": upper_path,
        "point": feasible_point(times, edges),
    }
    for kind, value, u, v in (("lower", lower, end, start), ("upper", upper, start, end)):
        if value is not None:
            # Q=value is enforced by both directions; feasible iff bound is attainable.
            result[kind + "_point"] = feasible_point(
                times, edges + [Edge(start, end, value), Edge(end, start, -value)]
            )
        else:
            reach, _, _ = bellman(times, edges, u)
            result[kind + "_ray"] = {str(t): "0" if reach[t] is not None else "1" for t in times}
    return result


def solve_world(times, edges, start, end):
    _, _, cycle = bellman(times, edges)
    if cycle:
        return {"feasible": False, "negative_cycle": [e.id for e in cycle]}
    forward, fp, _ = bellman(times, edges, start)
    reverse, rp, _ = bellman(times, edges, end)
    upper = forward[end]
    lower = -reverse[start] if reverse[start] is not None else None
    return finish_world(
        times,
        edges,
        start,
        end,
        lower,
        upper,
        path_to(rp, end, start) if lower is not None else [],
        path_to(fp, start, end) if upper is not None else [],
    )
