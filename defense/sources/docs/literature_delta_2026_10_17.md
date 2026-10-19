# Focused prior-art audit: 2026-10-17

Follow-up substantive assessment, same date:
[novelty_justification.md](../reports/novelty_justification.md),
[author contribution statement](../paper/novelty_statement_ru.md),
[inspection protocol](../reports/novelty_prior_art_check.json).
Additional direct overlap checks: Juditsky/Nemirovski finite convex unions,
Evans/Stark equation (4.46) and Donoho abstract on the modulus of continuity,
McConnell et al. sections 1/2.4 on certifying algorithms. Finite H, the W formula
and a separate checker are explicitly excluded as standalone novelty claims.
No new implementation/benchmark was introduced to replace this comparison.
Reviewer availability and Gate B concern different evidence than priority.

Purpose: test an algorithmic claim, not collect impressive citations. The previous
six-terminal exact-acquisition implementation remains a specialization of known
ideas. The current extension studies a proof-carrying all-noise precision frontier
with finite semantic alternatives, activation jumps and open/closed boundaries.
Priority is **unestablished**. Not finding an identical named system in this
focused search is not proof that no predecessor exists.

## Sources actually inspected

| Primary source / inspection | Established overlap | Candidate difference and remaining risk |
|---|---|---|
| [Dechter, Meiri, Pearl, Temporal Constraint Networks, 1991](https://ftp.cs.ucla.edu/pub/stat_ser/r113-L-reprint.pdf), section 3 and minimal-network discussion | Consistency and tight difference bounds by shortest paths; graph decomposition/projection foundations | No STN novelty. Per-world closure and terminal elimination are applications of this foundation |
| [Young, Tarjan, Orlin, Faster Parametric Shortest Path and Minimum Balance Algorithms](https://arxiv.org/pdf/cs/0205041), PDF journal header: Networks 21(2), 1991; arXiv deposit 2002; section 2 and generalizations in section 6 (corrected section reference) | A parameter modifies a subset of edge costs; finite shortest-path regimes and breakpoints are already algorithmic objects | Our two opposite noise edges and at most two units of dual flow form a restricted case. A short affine list is not a new general parametric algorithm. Full semantic-union proof/frontier contract is the candidate, not parameterization itself |
| [Ettehad, Foucart, Instances of Computational Optimal Recovery: Dealing with Observation Errors](https://arxiv.org/pdf/2004.00192), definitions in section 1, section 2.1 equations 10–19/Theorem 1 and proof; Theorem 4 model checked | Bounded observation errors, local worst-case recovery, Chebyshev centers and LP-dual computational constructions for polytope models already exist | Generic noisy LP formulation and minimax error are not ours. Our finite H union, interval-network specialization and all-error certificate are narrower. The paper does not by itself establish that the specialization is unpublished |
| [MIT 6.854 duality notes](https://ocw.mit.edu/courses/6-854j-advanced-algorithms-fall-2005/99eac3e02c1e1c317f20ef3cad4f6a28_dualitynotes.pdf), shortest-path potential/flow example | Potential constraints and min-cost-flow duality are textbook material | Two path matchings and weak-duality certificates are classical tools; no new duality claim |
| [Javdani et al., Near Optimal Bayesian Active Learning for Decision Making, 2014](https://proceedings.mlr.press/v33/javdani14.html), original abstract/record; earlier review already read problem model | Decision-region identification without identifying the complete hidden state is established | No new policy or DRD guarantee follows from this oracle study; continuous priors/approximations require a separate fair experiment |
| [SciPy Johnson documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.csgraph.johnson.html), API and numerical caveats | Available compiled shortest-path implementation for directed weighted graphs | Used as a strong full-graph comparator, with rational validation/fallback before any candidate path becomes a certified bound |

Additional checked overlap anchor: [Klimm and Warode, Parametric Computation of
Minimum-Cost Flows with Piecewise Quadratic Costs](https://pubsonline.informs.org/doi/abs/10.1287/moor.2021.1151),
abstract only. It varies demands with convex costs; this is not the same model as
our affine noise-edge costs. It confirms the breadth of parametric-flow work;
we do not claim its results prove or refute our specific proposition.

Earlier context/disjunction and determinacy anchors remain in
novelty_research_proposal.md. Those have NOT suddenly become fully reproduced
implementations. This audit upgrades the noisy optimal-recovery and parametric
shortest-path comparison; it is not an exhaustive survey.

## Search log

Searches on 2026-10-17 included:

* `parametric minimum cost flow piecewise linear value function two units flow parameter edge costs`
* `optimal recovery interval sums noisy measurements polyhedral uncertainty radius information sensor accuracy`
* `simple temporal networks value of information observation precision bounded noise`
* `query determinacy noisy aggregate sum queries worst case uncertainty measurement precision`
* `parametric shortest path edge costs Young Tarjan Orlin`
* `Instances of Computational Optimal Recovery Foucart pdf`
* `optimal recovery polyhedral noise linear functional`

Only primary papers, author-hosted manuscripts and official documentation support
the comparison above. Secondary search snippets were discovery aids. Dates and
publication status follow primary records/PDF headers, not crawler timestamps.

## Claim under test

For one bounded-error interval observation and one scalar interval Query, build a
complete rational profile for each ordered semantic pair: a feasibility activation
radius, at most three candidate affine bounds (slopes 0/1/2 in rho=2*eta), primal
anchors/directions covering every parameter interval, and symbolic path/cycle
proofs. Aggregate over finite H to report an exact safe precision frontier with
endpoint inclusion. An independent checker verifies all finite eta>=0 without
running graph search or LP.

This is a **concrete implemented candidate**, with a derivation in
precision_frontier.md. The bounded affine description follows classical flow/path
reasoning; we do not present it as a new general complexity result. The diagnostic
metadata-activation jump explains why endpoint inclusion is part of the contract.
The contribution may ultimately be classified as a useful certified specialization
or tool rather than a new algorithm. A positive timing result cannot change that
classification on its own.

## Decision rules and unresolved work

The new timing protocol was frozen before measurements, includes an external
compiled SciPy full-graph comparator with exact path checks, and an ablation of
inter-action reuse. The same all-parameter proof contract is required of every
timed method. Numerical paired LP values are validation, not a secretly weaker
timed competitor. Failures and losing regimes remain in the report.

The user has no independent reviewer currently. We can prepare a proof/review
packet and blind source cases, but cannot manufacture independent review, human
labels, Gate B, or journal acceptance. No contacts are messaged. Those statuses
remain pending even when all automated checks pass. Final priority requires a
broader bibliographic comparison and independent expert assessment of the exact
delta, not a renamed method or a larger synthetic dataset.
