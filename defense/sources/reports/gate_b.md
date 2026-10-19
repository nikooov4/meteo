# Gate B

Status: **pending**, not passed.

2026-10-19: twelve monthly 2023 NSF NCAR LSP objects now support a separate
global weather-v2 development holdout (240 train / 120 test cycles). These are
additional dates of the same product family, not independent annotation or a
passed unseen-family Gate B. See [weather report](weather_v2.md). The historical
28-case result below is preserved and was not relabelled as a new experiment.

Small DWD subset and one checked NCAR ERA5 LSP object are locally available with
provenance. 28 saved original/controlled/local-file cases passed graph proofs and
LP comparison in experiments/runs/real-subset/run.json. These include derived
cases of three DWD station families, one NCAR product family and a synthetic local
cumulative CSV. They are not 28 independent data sources.

DWD hourly/mm/UTC conventions are documented; the exact historical time-label
annotation remains incomplete. Native cases return incomplete_model. Cases with
an explicitly assumed end-label are controlled. No real CERRA/CDS acquisition,
independent human annotation, H5 transfer advantage, unseen-source study or
methodological novelty is established. The UI/API/client are useful engineering
components and can be completed while Gate B remains pending.
