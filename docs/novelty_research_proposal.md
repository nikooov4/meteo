# Candidate research direction after the negative H3 pilot

Original status: research proposal. Implementation update, 2026-10-16: the
single-exact-action paired LP, ordinary pair graph, terminal candidate and
independent certificates are now implemented. See continuous_acquisition.md and
the separately frozen acquisition-continuous-v1 protocol/run. Existing Gate A
runs remain unchanged; algorithm_delta and claims now append this new experiment.
Neither the implementation nor a focused literature check establishes priority,
absence of prior solutions, a new complexity result or a publication guarantee.

## Recommended question

Can we compute the guaranteed remaining uncertainty after an additional interval
observation exactly over a continuous feasible set, efficiently across many
candidate observations and metadata alternatives, with independently checkable
bounds and counterexamples?

This targets a limitation of our current acquisition evaluation: the saved six
finite policy families do not establish behavior over the full continuous set of
temporally underdetermined precipitation trajectories. The current exact Query
solver already handles continuous underdetermination; its acquisition experiment
does not provide this continuous action-value oracle.

Working scope: one physical SeriesKey, finite explicitly complete H, nonnegative
amount increments, documented interval observations, deterministic known action
costs, exact additional interval measurements initially. Unknown/incomplete H
must retain incomplete_model. Measurement-error bounds can be a subsequent
extension; no unspecified distribution over trajectories is assumed.

## A concrete target, distinct from a new name

Let Omega = union_h ({h} x F_h) be the current set of feasible worlds. q(w) is
the requested amount. Each available action a has a public response function
g_a(w); its actual response is hidden until the action is executed.

Define the worst remaining amount diameter

    W(a) = sup { |q(w)-q(w')| : w,w' in Omega, g_a(w)=g_a(w') }.

The equality means that these worlds could produce the same acquired answer.
For a scalar amount with the existing midpoint/eps contract, diameter <= 2 eps
would suffice after every attainable answer. If W(a) is infinite, report that;
do not replace it by zero. If Omega is empty, conflict handling precedes action
ranking. This definition is an optimal-recovery/determinacy-style construction,
not a claimed invention.

For a threshold Query, use existence of an indistinguishable pair with opposite
decisions, not amount diameter alone. Strict inequality at the threshold must
remain strict. Metadata questions partition H by their documented answers;
they do not collapse F_h within an unchanged interpretation.

For each fixed pair h,h', an exact continuous-response baseline uses two copies
of the increment LP, adds equality of the candidate measurement, and maximizes
q(w)-q(w') in both directions. Infeasible pairs are skipped, unbounded objectives
are retained. This provides a generic LP baseline without discretizing outcomes;
it is not by itself a novel algorithm. Its numerical results still require the
usual LP comparison policy or exact certificates.

Potential method delta to investigate:

* specialize this two-world oracle to interval difference networks;
* reuse computations across candidate intervals and h-pairs, beyond caching a
  previously solved whole instance;
* return attaining indistinguishable worlds and checkable upper-bound proofs;
* avoid sampling the continuous response space for this minimax criterion.

One possible derivation route is to align the arbitrary cumulative origins of
two graph copies at the start of a SINGLE measured interval. Equal interval
amounts then also align the end. This suggests a combined-network calculation
with a four-terminal objective, related to standard min-cost-flow duality.
This is a derivation idea requiring a careful proof and prior-art check, not a
new theorem. It must not be extended by simply merging all endpoints of several
disconnected measurement intervals: that can impose constraints not implied by
equal observations. Noise, several acquisitions and adaptive lookahead require
separate treatment. Even a correct reduction using standard duality may be too
routine to constitute methodological novelty.

## Diagnostic example, not an experimental novelty result

Four nonnegative increments represent consecutive six-hour periods. Their total
is 12 mm, and q=x0+x1 is precipitation in the first twelve hours.

Two convenient extreme witnesses are

    w0 = (0, 0, 12, 0), q=0
    w1 = (12, 0, 0, 0), q=12.

Measuring x0 distinguishes those two witnesses. Nevertheless the possible answer
x0=0 leaves both (0,0,12,0) and (0,12,0,0) feasible: q still ranges from 0 to 12.
Thus separating one chosen extreme pair does not establish useful worst-case
action value. Here W(measure first six hours)=12.

Measuring the last twelve hours, x2+x3=y, instead determines q=12-y for every
attainable y, so W(measure last twelve hours)=0. This only uses the known daily
total; no hourly rainfall distribution is inferred. The example motivates an
all-world oracle, not a novelty or population-performance claim.

## Closest checked foundations and overlap risks

* [Barber, Reasoning on Interval and Point-based Disjunctive Metric Constraints
  in Temporal Contexts](https://www.cs.cmu.edu/afs/cs/project/jair/pub/volume12/barber00a-html/Barber.html):
  labeled disjunctions, logical dependencies and context-dependent temporal
  constraints already exist. Opening/overview sections checked; this memo does
  not claim to reproduce its algorithms. Symbolic H or labeled paths alone is
  therefore not an adequate novelty statement.
* [Javdani et al., Near Optimal Bayesian Active Learning for Decision Making](https://proceedings.mlr.press/v33/javdani14.html):
  decision-region identification without complete hypothesis identification is
  established. DRD remains a required comparator, with the finite/continuous
  adaptation stated explicitly.
* [Zheng et al., Active Information Acquisition for Linear Optimization,
  arXiv v3](https://arxiv.org/pdf/1709.10061): problem/model and opening method
  sections checked. It acquires noisy samples of unknown LP parameters while
  seeking approximate feasibility/optimality. General active acquisition for
  optimization and focusing on relevant constraints are already known. Our
  proposed finite-H/continuous-trajectory/minimax-Query setting differs from that
  model; this difference alone does not establish novelty.
* [Segoufin and Vianu, Views and Queries: Determinacy and Rewriting](https://dbucsd.github.io/paperpdfs/2005_7.pdf):
  view determinacy already formalizes sufficient information for a Query.
  Definitions and opening sections checked. Sufficient interval observations
  must not be presented as the first information-determinacy idea.

Further focused checking is needed for optimal recovery/information-based
complexity, robust measurement design, active constraint acquisition, and
value-of-information methods for temporal/linear constraints. Search absence
is not evidence of absence. Authoritative sources above are anchors, not an
exhaustive review. No publication status beyond the source record is inferred.

## What would justify a new methodological claim

1. A precise distinction from those models, plus a nontrivial algorithm or
   structural result for the supported interval fragment. W(a) alone is not enough.
2. A proved conditional calculation/certificate contract. Neither source
   completeness nor new worst-case complexity follows from experiments.
3. Agreement with the independent paired LP, adversarial cases, unboundedness,
   conflicts and threshold-boundary checks before speed comparisons.
4. Computational comparison with paired LP and relevant temporal methods under
   the SAME action-value criterion, independently of policy quality. Report all
   candidate intervals, latency, operations, memory and proof size.
5. Policy comparison with continuous-outcome VOI/DRD adaptations on the same
   public information, actions/costs and checked stopping. Keep minimax and
   expected-cost objectives separate; disclose approximations and any priors.
   No hidden simulator response may enter ranking.
6. Independently annotated real families, family-level separation, documented
   natural ambiguity and realistic within-series acquisition opportunities.

Freeze a NEW protocol and preserve the negative old pilot. Predeclare primary
metrics, structural regimes, failure handling and go/no-go criteria before new
timings. A counterexample-driven development case is not a held-out benchmark.
If the specialization has no distinct result or advantage, retain the useful
oracle but do not relabel it as a new method or retune the evaluation indefinitely.

## Alternative data contribution

A benchmark of natural temporal/metadata ambiguity with independent annotation,
full provenance, H-coverage failures, acquisition costs and query/witness labels
could support a dataset/tool contribution. It requires substantially more than
the existing three DWD families, one NCAR family and controlled derivatives.
It would not establish a new solver algorithm or a venue/acceptance guarantee.
