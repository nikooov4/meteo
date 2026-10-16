# Assumptions and supported fragment

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
