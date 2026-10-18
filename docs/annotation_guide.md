# Annotation guide

2026-10-19: the weather-v2 heldout is a machine-separated development weather
diagnostic. It is not an independent annotation, does not complete Gate B and
must not be counted as a new independent family merely because resampling
creates another member/file. Record LSP quantity, original reference cycle,
synthetic member, sampling support and any block boundary when reviewing it.


2026-10-17 precision extension: no independent reviewer is currently available
(user-confirmed). Status remains pending; do not replace review with generated
labels. review/annotation_blind contains four DEVELOPMENT family packets with raw
records/provenance but without our H, predictions, inferred intervals or completeness
decisions; annotation_template.csv has zero completed annotations. These already
used families are not a held-out Gate B test. See review/README.md and
review/proof_checklist.md for the actual review procedure and unanswered questions.

For bounded-error acquisitions, annotate the supplied eta meaning, closed/full
reply support, units, endpoint conventions and actual availability/cost. Separate
deterministic coarsening from instrument calibration. Controlled missing-record
cases keep their original family_id and split; restoring a removed local encoded
record does not establish a new independent source family. An open safe eta
boundary must remain open. New profiles support one interval action and amount
Query, not correlated multi-measurement noise or continuous Bayesian policies.

Unit of analysis is an original physical series/product/schema family and a
Query, not adjacent rows. Record origin as original, controlled or synthetic.
Derived/masked versions retain family_id and the same split. Hand overlap cases
and robust-threshold variants are one family; daily and half-day variants are
another. DWD variants are grouped by original station series. NCAR examples are
one product family, not independent products or observations.

For each case record: SeriesKey; raw checksum and documentation URL/version;
timestamp reference, period/bounds, calendar/zone, statistic, units, reset/cycle,
member and QC/missing conventions; exhaustive alternatives and completeness
basis; Query/eps/threshold; exact or conditional expected bounds; permitted
actions, costs/likelihood model and hidden simulation answers; evidence reviewer.

Do not infer metadata from plausible-looking values. Distinguish deterministic
representation bounds from physical measurement uncertainty and confidence
intervals. Compare equivalent certificates by validity, not a canonical path.
For an unresolved Query check the two full witnesses against every constraint.
Record both metadata ambiguity and within-h underdetermination when present.

DWD: hourly amount, mm and station-specific UTC are checked. Exact end-label for
these historical SYNOP-derived files remains a candidate annotation. Native cases
therefore have incomplete_model. Explicit assumed-end variants are controlled.
Documentation for the separate urban product is not proof for these files.
The local cumulative CSV is hand-constructed, never called a real CDS download.
NCAR LSP is reanalysis large-scale precipitation, not total precipitation or a
station observation; ERA5 hourly processing conventions differ from CERRA.

Independent human review: PENDING. A second reviewer must check the source
documents, annotate without seeing our predictions, and resolve disagreements.
Current cases are development diagnostics, not a frozen independently labeled
held-out test set. Gate B cannot pass on Codex's own annotations.

For the continuous acquisition extension, document the exact public response
function, SeriesKey, interval, availability and positive cost BEFORE obtaining
an answer. A metadata reply must be declared for every h, including modeled
unknown outcomes. Check that an exact interval acquisition is actually available;
an imagined hourly sensor reading is not an archive connector capability. Record
this as a controlled acquisition opportunity until independently verified.
Bounds/counterexamples from an oracle are not human labels. Do not infer a prior
from the simulator truth or evaluate expected VOI without specifying one.
