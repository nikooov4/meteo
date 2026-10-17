"""Compiled SciPy Johnson baseline, accepting paths only after rational checking."""

import math

from .budget import checkpoint, count
from .graph import bellman, path_to


def exact_paths(nodes, edges, sources):
    output = {}
    for source in sorted(set(sources)):
        dist, pred, cycle = bellman(nodes, edges, source)
        if cycle:
            raise ValueError("negative cycle in path preprocessing")
        output[source] = {t: (v, path_to(pred, source, t)) for t, v in dist.items() if v is not None}
    return output


def compiled_paths(nodes, edges, sources):
    """Numerical paths are proposals. Exact paths + edge inequalities certify SSSP.

    Parallel edges are minimized, never summed by CSR conversion. Explicit zero
    edges remain in the sparse matrix. Any numerical/path failure falls back to
    rational Bellman-Ford and is counted. No approximate distance becomes a bound.
    """
    import numpy as np
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import NegativeCycleError, johnson

    checkpoint()
    sources = sorted(set(sources))
    index = {v: i for i, v in enumerate(nodes)}
    minimal = {}
    for e in edges:
        if (e.u, e.v) not in minimal or e.w < minimal[e.u, e.v].w:
            minimal[e.u, e.v] = e
    try:
        pairs = list(minimal)
        matrix = csr_matrix(([float(minimal[p].w) for p in pairs],
                             ([index[u] for u, v in pairs], [index[v] for u, v in pairs])),
                            shape=(len(nodes), len(nodes)))
        count("compiled_johnson_calls")
        distances, predecessors = johnson(matrix, directed=True,
                                           indices=np.array([index[s] for s in sources]),
                                           return_predecessors=True)
        output = {}
        for row, source in enumerate(sources):
            checkpoint()
            found = {}
            for target in nodes:
                if not math.isfinite(distances[row, index[target]]):
                    continue
                path, current = [], target
                while current != source:
                    pred = int(predecessors[row, index[current]])
                    if pred < 0 or len(path) >= len(nodes):
                        raise ValueError("broken compiled path")
                    edge = minimal[nodes[pred], current]
                    path.append(edge)
                    current = edge.u
                path.reverse()
                found[target] = sum((e.w for e in path), 0), [e.id for e in path]
            if source not in found or found[source][0] != 0:
                raise ValueError("missing compiled origin")
            for e in edges:
                if e.u in found and (e.v not in found or found[e.v][0] > found[e.u][0] + e.w):
                    raise ValueError("compiled distances fail exact edge inequalities")
            output[source] = found
        return output
    except (ValueError, KeyError, OverflowError, NegativeCycleError):
        count("compiled_exact_fallbacks")
        return exact_paths(nodes, edges, sources)
