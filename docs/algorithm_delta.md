# Algorithm delta, frozen before pilot

2026-10-19 implementation extension: global monthly block-bootstrap LSP
surrogates and zoomable animation are engineering/benchmark support. They add
no solver algorithm_delta, theoretical complexity or new priority claim.
Whole-cycle resampling and spatial dependence are known weather-generator
ideas; docs/weather_generator_v2.md gives scope, references and limitations.
The historical negative H3 and precision-frontier evidence remain unchanged.


## Latest extension: all-error precision frontier (2026-10-17)

The historical candidates and their saved results below remain unchanged.
The new operation returns the ENTIRE precision profile for one bounded-error
interval acquisition, not only an exact-response action value. Neither interval
uncertainty, parametric shortest paths nor optimal recovery with observation
errors is new. See precision_frontier.md and literature_delta_2026_10_17.md.

Concrete change against enumeration+graph+simple cache: retain every ordered
H-pair, align only its arbitrary origin at the measurement start, keep its end
copies separate, and add opposite edges with symbolic weight rho=2*eta.
Precompute certified per-world paths once per action batch, project each pair to
<=7 value vertices, enumerate the <=2-unit flow matchings and their zero/one-noise
edge paths, retaining at most one affine bound for each slope 0/1/2. Derive pair
activation and all breakpoints; expand raw dual paths, full attaining points and
the final affine ray. Compute the safe eta interval with explicit open/closed end.
No H pruning, hidden-answer access, archive-wide closure or new complexity claim.

All-noise independent checker verifies symbolic paths/activation cycles plus
attainment on complete parameter intervals. Its proof does not depend on SciPy
or the profile-construction search. Conditional on H and bounded-error assumptions.

Equal-contract baselines: full exact pair graph; full graph with compiled SciPy
Johnson proposals validated in Fraction (exact fallback on rejection). Projection
without inter-action reuse is the ablation. A whole-result cache only helps a
repeated identical batch; it does not compute profiles for new actions. Prior
warm-cache benefits remain acknowledged. Independent paired LP on six radii
validates implementation numerically and is not a whole-profile time comparator.

Frozen precision-frontier-v1: terminal/compiled improvement in all three small
development regimes (compiled/terminal 1.234/1.871/2.274); no-reuse/terminal
1.046/1.152/1.192. 2160 action/radius comparisons and 36 all-parameter certificates
pass. This supports computational utility, not priority, a policy claim or a
general speed law. Detailed run/protocol/source hashes: reports/precision_frontier.md.

Possible narrow contribution for external examination: the proof-carrying batch
precision frontier over a finite union of interval temporal models, with pair
activation and strict precision limits. Priority UNESTABLISHED. If this follows
directly from the closest published specialization, classify as implementation
and reproducible application rather than inventing a new general algorithm.

Baseline: enumerate every declared h, compile its complete graph, Bellman–Ford
feasibility plus two single-source shortest paths. A bounded LRU caches complete
canonical graph/query effects (not case ids). Warm caches are measured separately.

Candidate: intersect the normalized directed edges of all hypotheses, compute a
shared exact rational all-pairs closure once, then copy that bounded closure and
insert the few remaining edges for each h. Inserting (u,v,w) updates each pair
using d(i,u)+w+d(v,j); a negative return path detects inconsistency. Store actual
edge chains and check all resulting certificates. No hypothesis is pruned.
The common graph includes the union of endpoints, hence identical monotonicity
edges. Conflicts anywhere in the graph remain relevant.

This is an application of known incremental STN closure, with canonical semantic
factoring and proof reuse. It is a concrete implementation difference from a
whole-graph cache, NOT an established new algorithm, complexity result or novelty
claim. It can lose to sparse Bellman–Ford and to a warm complete-graph cache.
The dense closure is limited to 256 endpoints and 256 hypotheses; larger inputs
use the sparse baseline with explicit limits. Cache entries are bounded and
content addressed; evidence creates a new case digest.

Policy candidate: choose a cost-normalized action separating extreme feasible
decision witnesses, with two-step VOI fallback when immediate reduction is zero.
Compare against finite decision-region edge cutting (DRD adaptation), exact
one-step expected decision-risk reduction (structured VOI adaptation), entropy,
fixed, random, and a tiny exact optimal decision tree. No claim of a new policy
unless the independently frozen pilot supports it. All use identical public
outcome likelihoods, costs, actions and stopping; only the simulator holds truth.

Primary H3 measure: cold wall time against graph+LRU at identical H/Q, also calls
and warm time. H4: expected conditional action cost at equal success over the
entire finite prior support, multiple random seeds. Do not retune after pilot.

## Separate continuous-acquisition candidate (2026-10-16)

The preceding frozen candidate and its negative H3 remain historical evidence.
New code evaluates a DIFFERENT operation: worst remaining Query uncertainty
after one exact interval observation, over all continuous feasible trajectories.
Enumeration of H-pairs is retained. The full-pair graph baseline and four-entry
whole-batch cache compute the SAME value/proof contract as the new candidate.

Concrete delta: precompute each world's exact distance closure with provenance;
project each action pair to Query+measurement terminals; glue its two measurement
endpoints, giving <=6 value vertices; evaluate the four-terminal objective through
<=2 classical flow matchings; expand proofs and construct full attaining worlds.
Witness construction and checking remain full-model work and are timed. No new
complexity or theorem priority is claimed. Derivation, limitations and independent
paired-increment LP: [continuous_acquisition.md](continuous_acquisition.md).

Protocol frozen before new timings:
configs/experiments/acquisition-continuous-v1.json. All output goes to a NEW run
directory. Main comparison: complete cold graph/terminal batch including exact
proofs/checks. Warm cache reported separately; numerical LP has a weaker proof
contract. No policy cost result or Gate B follows from this oracle experiment.

Saved result: all comparisons passed; graph/terminal median ratios
0.900, 1.251, 1.747 across the three predeclared regimes. The smallest regime
loses, numerical LP and warm cache are faster. Research go criterion met (2/3
regimes); priority remains unestablished. See reports/continuous_acquisition.md.
