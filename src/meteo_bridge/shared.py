"""Known incremental STN closure, factored across declared semantic alternatives."""

from fractions import Fraction as F

from .budget import checkpoint, count
from .graph import finish_world, solve_world


def closure(times, edges):
    n = len(times)
    index = {t: i for i, t in enumerate(times)}
    dist = [[None] * n for _ in times]
    paths = [[[] for _ in times] for _ in times]
    for i in range(n):
        dist[i][i] = F(0)
    for edge in edges:
        i, j = index[edge.u], index[edge.v]
        if dist[i][j] is None or edge.w < dist[i][j]:
            dist[i][j], paths[i][j] = edge.w, [edge.id]
    for k in range(n):
        checkpoint()
        for i in range(n):
            if dist[i][k] is None:
                continue
            for j in range(n):
                if dist[k][j] is None:
                    continue
                value = dist[i][k] + dist[k][j]
                if dist[i][j] is None or value < dist[i][j]:
                    dist[i][j] = value
                    paths[i][j] = paths[i][k] + paths[k][j]
        if any(dist[i][i] < 0 for i in range(n)):
            return None, None
    return dist, paths


def solve_shared(times, worlds, start, end):
    if len(times) > 256:
        return {h: solve_world(times, es, start, end) for h, es in worlds.items()}, {"fallback": "sparse"}
    common = set.intersection(*(set(es) for es in worlds.values()))
    base, base_paths = closure(times, sorted(common, key=lambda e: e.id))
    out, index = {}, {t: i for i, t in enumerate(times)}
    if base is None:
        return {h: solve_world(times, es, start, end) for h, es in worlds.items()}, {"common_conflict": True}
    insertions = 0
    for h, edges in worlds.items():
        checkpoint()
        dist = [row.copy() for row in base]
        paths = [[p.copy() for p in row] for row in base_paths]
        conflict = False
        for edge in edges:
            checkpoint()
            if edge in common:
                continue
            insertions += 1
            count("incremental_edge_insertions")
            u, v, w = index[edge.u], index[edge.v], edge.w
            if dist[v][u] is not None and dist[v][u] + w < 0:
                conflict = True
                break
            if dist[u][v] is not None and dist[u][v] <= w:
                continue
            # Snapshot endpoints: this insertion is used at most once on a shortest path.
            left = [(dist[i][u], paths[i][u]) for i in range(len(times))]
            right = [(dist[v][j], paths[v][j]) for j in range(len(times))]
            for i, (a, ap) in enumerate(left):
                if a is None:
                    continue
                for j, (b, bp) in enumerate(right):
                    if b is not None and (dist[i][j] is None or a + w + b < dist[i][j]):
                        dist[i][j], paths[i][j] = a + w + b, ap + [edge.id] + bp
        if conflict:
            out[h] = solve_world(times, edges, start, end)
        else:
            s, t = index[start], index[end]
            lo = -dist[t][s] if dist[t][s] is not None else None
            out[h] = finish_world(times, edges, start, end, lo, dist[s][t], paths[t][s], paths[s][t])
    return out, {"common_edges": len(common), "delta_insertions": insertions, "base_closures": 1}
