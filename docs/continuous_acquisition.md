# Continuous-outcome acquisition oracle

Implemented research candidate, 2026-10-16. The mathematical ingredients below
are classical. This document specifies the supported reduction and its proof
obligations; it is not a priority, new complexity, or policy-optimality claim.

## Contract

One physical SeriesKey, nonnegative interval increments, rational input bounds,
and a finite declared H. F_h is the continuous feasible set for interpretation h.
For an exact interval acquisition a=[u,v], the public response function is
g_a(h,C)=C(v)-C(u), in mm of the Query series. An action does not provide its
actual response to the oracle. A metadata action has a deterministic declared
response h.assignments[attribute] for every h. Missing assignments are rejected;
an explicitly modeled unknown response is allowed. Action costs are positive,
declared strings. The oracle evaluates actions; it does not rank cost against
benefit or execute a policy.

For an amount Query q=C(t)-C(s), compute

    W(a) = sup {q(C)-q(D): C in F_h, D in F_k,
                           h,k in H, g_a(h,C)=g_a(k,D)}.

Ordered pairs make this the worst absolute remaining diameter. The supremum is
over continuous trajectories, not sampled action outcomes. Empty sets and
infinite diameters have explicit kinds. W<=2*eps guarantees the midpoint/eps
contract after EVERY attainable response, conditional on complete H and valid
input assumptions. For incomplete H, W is for the listed model only and can
underestimate reality; guarantees_resolution is always false.

For a threshold q>=tau, amount diameter alone is insufficient. Test existence of
an indistinguishable pair with q(C)>=tau and q(D)<tau, including BOTH orders of
every h-pair. The second inequality remains strict in exact rational arithmetic.

## Pair construction: one exact measurement only

Each world is a graph of inequalities C(j)-C(i)<=w_ij, including monotonicity.
Insert all candidate action endpoints before solving. Refining monotonicity at
new endpoints preserves the original feasible projections; it does not impose
uniform precipitation between observations. Verify global consistency of each
world, including components outside the Query, before terminal projection.

Take two graph copies. Their cumulative origins are arbitrary. For one action,
translate D so that D(u)=C(u). Equality of the measured amounts then implies
D(v)=C(v). Conversely these two endpoint equalities imply equal amounts. Thus
merging the copies at u and v represents precisely this one-response equality,
up to a harmless origin translation. For a metadata action, filter h-pairs by
equal declared response and leave both graphs disjoint.

**Scope boundary:** this argument is not valid for merging every endpoint of
several disconnected measurements. Multiple simultaneous measurements, noisy
new measurements, random metadata replies, and adaptive lookahead are unsupported.
Existing observation bounds may be intervals; only the NEW acquisition is exact.

## Terminal projection and batch reuse

Precompute exact per-world shortest paths, with raw edge provenance, once per
public action batch. Retain the Query endpoints s,t and action endpoints u,v in
each copy; replace each intra-world connection by its finite shortest-path bound.
There are at most four terminals in each world. Merging u,v leaves at most six
vertices. Metadata pairs need at most four vertices. This count describes the
small VALUE subproblem; full witnesses, certificates and preprocessing still
depend on the working model. H-pairs are still explicitly enumerated.

Projection justification: any full feasible potential satisfies every path bound.
Conversely let assigned terminal potentials satisfy all shortest-path bounds.
Add an anchor with exact equalities fixing those potentials. A negative cycle
without the anchor would contradict original feasibility. A negative excursion
through the anchor would contradict a terminal shortest-path inequality. Hence
the augmented graph is feasible and the terminal assignment has a full extension.
This is ordinary elimination/projection of difference constraints.

This reuse differs from caching a solved full pair/action problem: an unseen
candidate interval uses the already computed per-world distances. The current
implementation builds its closures anew for each batch; no unbounded global
closure cache is retained. Preprocessing can cost more than it saves on small or
sparse instances. The baseline uses the same pair construction and certificates,
but Bellman-Ford on the full pair graph for every action/pair. The four-entry LRU
baseline caches whole batch results by case+action hash and checks cached proofs
again on retrieval. Cold and warm results are separate.

## Four-terminal objective and exact proofs

The pair objective is c^T z=q(C)-q(D). After cancellation, c has total positive
mass at most 2, total negative mass at most 2, and zero sum. The classical dual
of maximizing c^T z under difference bounds is an uncapacitated min-cost flow
with supply at negative coefficient vertices and demand at positive ones.
In a feasible difference network there are no negative cycles. An optimal
integral flow decomposes into unit paths, with no advantageous cycle. Therefore
at most two source-target matchings need checking (including cancellations or
repeated sources/targets). The minimum sum of their shortest-path lengths gives
the finite optimum. This is a small specialization of standard LP/flow duality,
not a newly discovered duality or matching algorithm.

For each finite pair the exported proof contains expanded RAW edge paths. Their
incidence balances equal c and their weights sum to the claimed upper bound.
The solver enforces tightness on the used paths and obtains a full feasible
attaining potential. The checker directly verifies all raw inequalities and
equality of objective and bound. Thus it checks weak duality plus attainment,
without trusting shortest-path search, flow optimality, or terminal projection.
An empty pair needs an expanded negative cycle. A globally excluded world needs
its own negative cycle. No h-pair may be silently skipped.

If no supply-demand matching is reachable, a deficient demand subset gives a
predecessor-closed vertex set with more positive than negative objective mass.
Its 0/1 indicator is a feasible recession ray: no edge enters a 1 vertex from a
0 vertex, and c^T ray>0. With at most two positive terminals the implementation
enumerates their nonempty subsets. The checker verifies the full recession
inequalities, an ordinary feasible point, and strict objective improvement.
This uses the usual flow reachability/Hall argument. Unbounded values stay
unbounded; they are not converted to useful actions.

For a threshold, add q(C)>=tau to the pair graph and minimize q(D). An empty
graph excludes that order. Otherwise a finite attained minimum strictly below
tau supplies the opposite-decision pair; a reverse path proving q(D)>=tau
excludes it. The code implements this as maximizing -q(D), using the same dual
and witness checker. Equality at tau is NOT a counterexample. The independent
floating LP uses 1e-9 near this boundary and is not an exact threshold authority.

## Independent implementation and limits

`paired_oracle.py` builds TWO sets of nonnegative elementary increments directly
from raw units/statistics, adds equality of interval sums, and invokes SciPy
HiGHS. It imports neither the difference-graph compiler nor the graph solver nor
the certificate checker. Numerical comparison tolerance: 1e-7; LP outputs have
no exact certificate. Graph and terminal methods use Fraction arithmetic.

`acquisition_checker.py` reconstructs inequalities through the existing independent
raw parser in certificates.py, not semantics.py; reconstructs pair node maps;
checks all ordered pairs, hashes, paths, feasible worlds, rays, strict threshold
decisions and action aggregates. It imports no search implementation. Certificate
validity remains conditional on H and assumptions, not meteorological truth.

Working model limits: 128 endpoints INCLUDING all action endpoints, 16 hypotheses,
128 actions, 4096 ordered action-pairs. Large storage still uses existing bounded,
partitioned readers. This module does not load or scan the 200-GB archive.
Deadline/unsupported input produces an exception (HTTP 503/422); no partial
certificate or action guarantee is returned. The batch cache retains at most
four bounded results. Limits are rejection boundaries, not truncation of H.

## Foundations checked and remaining priority risk

Shortest-path temporal consistency and minimal networks are established in
[Dechter, Meiri and Pearl, Temporal Constraint Networks (1991), section 3](https://ftp.cs.ucla.edu/pub/stat_ser/r113-L-reprint.pdf).
Potential/flow LP duality is textbook material; see the
[MIT 6.854 duality notes, shortest-path example](https://ocw.mit.edu/courses/6-854j-advanced-algorithms-fall-2005/99eac3e02c1e1c317f20ef3cad4f6a28_dualitynotes.pdf).
Worst-case recovery of linear quantities has extensive prior work, e.g.
[Foucart and Paouris, abstract (2023)](https://arxiv.org/abs/2301.07228).
Our finite union of interval models and exact-response batch implementation is
a concrete research candidate; those differences do not prove priority.
Further anchors and overlap risks are in novelty_research_proposal.md. No claim
of inventing W, query determinacy, STNs, VOI, DRD, or continuous feasible worlds.

Policy quality is a separate experiment. This pilot measures an oracle under a
single minimax criterion; it has no prior and is NOT a new VOI/DRD policy study.
The old fair finite-policy study and negative H3 remain untouched. A future
continuous policy study requires stated priors/integrations or approximations,
strong VOI/DRD adaptations, identical actions/costs/information/stopping and
hidden-answer isolation. No superiority claim is made before that study.
