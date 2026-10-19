# Assumptions and supported fragment

2026-10-19 weather-v2: synthetic LSP is a monthly/phase-matched resampled
12-hour ERA5 cycle with a declared smooth intensity perturbation, not total
precipitation or a physically continuous forecast. The global 1-degree lattice
samples native points, not cell area means. No day-to-hour disaggregation.
Member and cycle remain separate SeriesKey fields. Encoded 0.0001 mm amounts
are exact only for the conditional data model. One-year first-half-month
training/development holdout does not establish climate/extreme realism.


Precision extension (2026-10-17): ONE acquired interval amount has reply y with
|y-m|<=eta, any real error in that closed interval possible. Eta>=0 is supplied,
not estimated from real sensors. No Gaussian distribution, quantization grid,
independence/calibration guarantee, bias model or multiple-acquisition gluing.
Two worlds share a possible reply iff |m(C)-m(D)|<=2*eta. Query objective is amount;
the output covers every finite eta>=0 and explicitly marks inclusion of a finite
safe supremum. A supremum alone need not be an attainable safe precision.
Incomplete H always prevents a conditional guarantee even when the modeled
frontier is nonempty. Operational action availability still requires evidence.
Limits: 128 endpoints, 16 H, 128 actions, 4096 action*ordered H-pairs. This bounded
model is separate from chunked archive reading and prior synthetic 200-GB scan.
Full mathematical contract: precision_frontier.md.

One nonnegative precipitation series per case, intervals in integer UTC seconds,
decimal rational input bounds, amount in mm/m or interval mean in mm/h, m/s,
kg m-2 s-1 (liquid-water equivalence explicitly assumed). No instantaneous rate
integration, arbitrary daily disaggregation, cross-station/product/member/cycle
equalities, or statistical interpretation of deterministic rounding bounds.

Complete H is a declaration conditional on source documentation, not a result of
ranking. Incomplete H always yields incomplete_model even for a narrow envelope.
Finite models and exact rational graph arithmetic avoid floating threshold
tolerances. LP is an independent floating-point oracle, with stated comparison
tolerance 1e-7; numerical failure is not inconsistency. JSON bounds use strings
for exact rationals and null with bound_kind=unbounded for infinity.

Calendar support is proleptic Gregorian with explicit zone/offset conversion.
360_day and local solar time are unsupported; ambiguous/nonexistent civil times
must be resolved explicitly. Query endpoints must increase. Gauge C(first)=0
fixes only an arbitrary origin. Cumulative records require an explicit reset
baseline and a cycle matching SeriesKey. Unknown reset is an alternative h,
never an invented first increment. Observations outside Query are still checked.

The certificate binds case, query, complete declared H, assumptions and revision.
An independent checker verifies every h, paths, infeasibility cycles, feasible
extremes and unbounded rays. This is conditional verification of this fragment,
not a theorem about metadata completeness or instrument accuracy.

Native/scalar NetCDF imports convert the encoded binary float exactly to a
Fraction, not a nearby decimal point bound. Synthetic v1 explicitly encodes
integer hundredths; its reader recovers that documented decimal representation.
Float64 streaming normalization is an IO operation, not certification of every
record; scientific Queries use the exact rational path.

Continuous acquisition evaluates ONE exact future interval amount in mm of the
Query SeriesKey, or a deterministic metadata reply declared for every h. It
does not assume a response distribution, sample true replies, combine stations,
or generalize endpoint gluing to several disconnected new measurements.
Existing observation bounds can be intervals. Incomplete H permits modeled-only
widths but never guarantees_resolution. Unsupported inputs, endpoint/pair limits
and deadlines fail without issuing a partial guarantee. See continuous_acquisition.md.

2026-10-19 archive viewer: a multi-day selection is navigation through distinct
12-hour synthetic episodes, never an assumption that their cumulative functions
join. Members remain separate; source hourly LSP is not total precipitation.
The 10-GB v2 scale run validates archive reads and bounded Query/checker batches;
it does not establish physical realism of every value or method novelty at scale.
Frame requests bind the manifest SHA; first shard reads verify its checksum.
The viewer trusts the declared grid/conventions of the completed v2 schema.

2026-10-19 research expansion: real ERA5 original point values are converted from
native binary floats in m to exact rational mm. This is encoded-data precision,
not a physical sensor-error guarantee. Real-study coarsening and the H2 shift are
controlled transformations; documented H1 is separate. Invalid observations are
not repaired. One place/member/cycle is retained in every case. The new 200-GB
study samples bounded controlled cases from every legacy-v1 partition; its scope
is not every possible archive Query and does not establish v1 weather realism.
