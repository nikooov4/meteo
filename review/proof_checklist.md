# Proof review checklist (PENDING)

Claim candidate: see ../docs/precision_frontier.md. Prior-art overlap:
../docs/literature_delta_2026_10_17.md. This document is a review request, not a
review result. No reviewer is assigned or simulated.

1. Check that one scalar bounded-error response has a common possible answer iff
   true interval sums differ by at most 2*eta; list required noise-support assumptions.
2. Check gauge alignment at u, retaining separate v vertices and two rho edges;
   identify why merging disconnected measurements is unsupported.
3. Verify whole-world consistency before projection, new-endpoint monotonicity,
   and exact extension of terminal potentials to the full difference graph.
4. Verify activation rho bound, treatment of missing paths, negative-cycle proof
   below activation and a feasible point at the endpoint.
5. Check the at-most-two-unit dual and path enumeration. Distinguish the upper
   bound of three candidate affine slopes from an unproved tightness claim.
6. Check that interpolation of attaining full potentials proves every finite
   segment, and the terminal derivative/ray proves every larger finite rho.
7. Check the separate proofs for globally excluded worlds and unbounded objectives.
8. Verify aggregation over ALL ordered h-pairs, negative pair objectives, semantic
   activation jumps, open/closed precision boundaries and the eta=0-only case.
9. Inspect independent checker dependencies and raw input normalization; validate
   forged certificates, path/ray/scope/endpoint failures, exact threshold scope
   rejection and failure on time/resource limits.
10. Inspect compiled shortest paths: numerical proposals require exact edge/path
    validation and fallback. Report whether fair timing includes this cost.
11. Assess prior-art delta independently: which statements are direct corollaries
    of STN projection, flow duality, parametric paths and optimal recovery?
12. State scope of any correctness finding. H completeness, provider conventions,
    calibration, new policy optimality and scientific priority are separate claims.

Reviewer / date: UNASSIGNED. Findings: PENDING. Counterexamples: not yet solicited.
