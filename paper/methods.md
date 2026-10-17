# Implemented methods and scope

## Additional bounded-error precision-profile operation (2026-10-17)

For one candidate interval functional m and closed, full error support |y-m|<=eta,
the worst posterior Query diameter equals the maximum q(C)-q(D) over all ordered
interpretation pairs and feasible trajectories with |m(C)-m(D)|<=2*eta. No reply
prior or simulator answer is used. The two temporal networks share only the
arbitrary cumulative origin at the action start; opposite symbolic edges of
weight rho=2*eta join their end copies. Pair feasibility starts at an explicitly
certified activation radius. The classical potential/flow dual has at most two
units, yielding at most three candidate affine bounds of slopes 0,1,2 per pair.
The global maximum may jump when a previously excluded pair activates, so the
safe precision output records whether its supremum is included. No tightness or
priority of this specialization is asserted. Full derivation: ../docs/precision_frontier.md.

The exact checker reconstructs raw constraints independently, verifies symbolic
dual paths and activation cycles, and checks full attaining potentials at each
segment endpoint. Convex interpolation proves attainment throughout bounded
segments; an affine feasible direction proves the final unbounded parameter
interval. A recession ray handles unbounded objective values. All H-pairs and
the complete parameter domain are checked; H completeness remains an input
assumption. This is a conditional proof contract, not external/formal review.

The compiled baseline operates on each full pair graph using SciPy Johnson
predecessor proposals. Raw Fraction path sums, all edge inequalities and reachability
closure are checked before use; failure invokes exact Bellman-Ford. The terminal
candidate reuses per-world paths across the action batch and operates on <=7 value
vertices, while retaining full proof construction/checking in timed work. An
ablation recomputes per-world paths per action. All four methods build all-noise
certificates; paired nonnegative-increment LP on six radii is numerical validation
only. Fixed protocol, seed, three repeats/regime and shuffled method order precede
measurements; no retuning. See ../reports/precision_frontier.md for saved results.

The new study neither replaces the original negative H3 nor compares acquisition
policies. It supports one amount Query and one interval acquisition with a supplied
deterministic error radius, bounded Case sizes, and a complete declared H for
conditional guarantees. Correlated/multiple acquisitions, noisy threshold profiles,
continuous Bayesian VOI/DRD, calibration and independently annotated external
validity are outside the implemented extension.

These are working engineering notes for the implemented fragment. They are not a
new soundness theorem, publication, or claim of method novelty. Results come from
the source snapshots attached to each saved run; later maintenance changes do not
retroactively change those measurements.

For a fixed declared interpretation, one SeriesKey identifies a nonnegative
precipitation series. The compiler collects observation and Query endpoints. With
an arbitrary cumulative origin, an amount bound on [a,b] becomes
`l <= C(b)-C(a) <= u`. Consecutive endpoint monotonicity supplies nonnegative
increments. Explicit interval mean rates are integrated over their documented
duration. Cumulative records require a documented reset origin and matching
cycle. No equality joins products, stations, ensemble members or cycles.

The graph baseline represents `C(v)-C(u) <= w` as a directed weighted edge.
Bellman–Ford tests global feasibility and provides negative cycles for conflicts.
Shortest paths bound the requested difference in each direction. Additional
equality edges construct feasible attaining potentials; an unbounded direction
has a feasible base point and recession ray. Arithmetic on this path is rational.
The independent reference instead builds a SciPy/HiGHS LP on nonnegative
elementary increments directly from the input observations. It does not use the
graph compiler. Its numerical comparisons use absolute tolerance 1e-7 and do not
alter the rational threshold decision rule.

Every declared h is evaluated. The union envelope takes the smallest feasible
lower bound and largest feasible upper bound. Amount certification at tolerance
eps requires width <= 2 eps; its point estimate is the midpoint. For sum >= tau,
the rules are L >= tau and U < tau, respectively. An incomplete H, truncated
search or exhausted working budget cannot yield a certified conclusion. Bounds
over an incomplete declared H describe that declared subset only. Completeness
and input conventions remain external assumptions.

The checker independently reconstructs inequalities and checks all hypotheses,
hashes, scopes, revisions, bound paths, negative cycles, feasible potentials and
rays. For unresolved complete models it checks witnesses that disagree on the
requested answer. A within-h range can remain after every metadata question has
been answered: acquiring additional interval observations is then a different
action from clarifying metadata. Exact proof checking is conditional on the
supported input model; passing tests is not a universal correctness proof.

The candidate solver intersects normalized edges across h, closes this common
graph once, and inserts remaining edges into bounded copies of that closure.
This uses the known incremental STN update, described in
../docs/algorithm_delta.md. It still evaluates all hypotheses and constructs
checkable extreme points. A 64-entry semantic-effect LRU on complete graphs is
the cache baseline. The shared dense closure is limited to 256 endpoints; sparse
fallback and explicit working-model limits avoid a dense archive-wide graph.
H3 in the frozen pilot is negative; this design is not presented as a new
algorithm or a proven performance advantage.

Acquisition policies are evaluated separately from solver timing. The simulator
alone holds the selected hidden state. All policies receive the same finite
public prior, likelihood support, actions and costs, and use the same checked
stopping condition. Comparators include one-step VOI, two-step VOI with terminal
error loss 10, an EC2 specialization to disjoint decision regions (DRD adaptation),
entropy, fixed, random, and an exact tiny finite decision tree. The witness
heuristic normalizes separating extreme-witness pairs by cost and falls back to
two-step VOI when immediate reduction is zero. Enumerating finite outcome support
does not solve continuous-observation DRD/HEC in general. Six constructed families
and cost sensitivity are a diagnostic pilot, not external validation.

Storage and scientific inference are different workloads. The scale scan hashes
every shard and normalizes bounded batches, recording counts and a digest. A
small, separately counted Query batch reads selected series and time ranges and
exports checked proofs, with independent LP samples. A cumulative Query reads the
entire selected cycle, including later totals that can bound an earlier missing
interval. NetCDF hyperslabs and Parquet projection/filter batches keep working
memory independent of archive size. The full scan does not certify a scientific
Query on every row. Synthetic-scale results cannot establish real-archive
external validity, and none establish new complexity, optimality or A* guarantees.

The subsequent continuous-acquisition extension evaluates a different operation:
the maximum Query separation of two feasible trajectories producing the same
single exact acquired interval amount (or deterministic metadata reply). It
enumerates all ordered interpretation pairs, without discretizing continuous
replies. A paired nonnegative-increment LP is the numerical reference; a full
pair difference graph is the exact baseline. The candidate precomputes per-world
distance closures, projects onto Query/measurement terminals, and merges only
the two endpoints of ONE measurement, giving at most six value vertices. The
four-terminal objective reduces to at most two classical unit-flow matchings.
Raw path dual bounds and full attaining potentials/rays are independently
checked; proof construction and checking remain in the timed workload. Threshold
Queries instead seek an indistinguishable pair on opposite sides of q>=tau,
with strict inequality handled exactly. The derivation and supported scope are
specified in ../docs/continuous_acquisition.md, not asserted as new STN/flow theory.

The separate acquisition-continuous-v1 development pilot uses fixed seeds, three
structural regimes and three repeats. It compares identical oracle values, not
policies: numerical paired LP, complete pair graph, cold/warm whole-batch cache,
and terminal specialization. End-to-end exact median graph/terminal ratios are
0.900, 1.251 and 1.747; numerical LP and warm cache are faster. All 576 saved
action-value comparisons agree. New policy superiority, scientific priority and
external validity do not follow from this pilot. The old negative H3 is preserved.
