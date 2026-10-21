# Progress

2026-10-19 compact viewer: fixed Plotly control auto-padding and removed
interdependent axis-domain constraints. Global map fills available width;
external compact playback/slider/reset, fullscreen and PNG; city names on hover.
Browser QA at actual widths 876/1416/492 px passed playback, repeated container
resize, zoom retention and world reset, without domain shrink or overflow.
Source and manifest hashes unchanged; saved prior HTML/metadata before replacement.
Map dataset membership in the existing scale run and calibration membership in
the realism run verified by SHA256. Precision-frontier experiments still use
separate cases. See reports/map_ui_compact.md for the exact scope and evidence.

2026-10-19 completed: acquired all 12 half-month 2023 ERA5 LSP references,
3166788003 bytes including the existing January object. Contiguous one-cycle
IO calibrated 240 training + 120 held-out cycles in 81.58 s, peak 310263808 B.
Frozen weather validation ran without tuning: mean 0.058805 vs heldout 0.059588
mm/h; v1 control 0.612368. V2 preserves spatial/temporal statistics much better
than v1; the unperturbed block bootstrap remains equally strong and is better
on most metrics. No perturbation advantage or new weather method is claimed.

New dataset: 1026890064 actual data bytes in 12 unique NetCDF shards; actual
generator stop/resume, peak 192901120 B. Full SHA256 + full normalized scan,
actual scan stop/resume; 24/24 Query certificates and generating-truth checks,
8 LP comparisons; 215.53 MB/s active scan, 208855040 B peak process-tree RSS.
10/50/200 GB v2: not_run; 200-GB dry-run disk feasible, no extrapolation.
Legacy 200 GB and user's existing HTML were preserved.

Global synthetic animation 12x180x360, standalone 9705881 B HTML; Edge verified
frame switching, zoom retention, world reset and scrollZoom; screenshot visually
inspected. Streamlit synthetic view and HTTP 200 tested, archive registered and
map opened for user. Pre-encoding-audit 154 tests passed in 52.35 s; final
UTF-8 JSON/Unicode-manifest regression passed all 154 in 41.23 s. Current
reader/checker also passed on the generated archive. Ruff/whitespace clean.
Native Windows NetCDF/HDF5 rejects Cyrillic data directories; documented
ASCII native-data path limitation, without claiming full Unicode HDF support.
See reports/weather_v2.md and its saved runs/manifests for hashes and limitations.
Scientific claims and historical negative H3 unchanged; Gate B pending.

2026-10-19: user requested more realistic synthetic weather and a worldwide,
zoomable animation. Implementing a separate monthly whole-cycle bootstrap
profile, trained only on first-ten-day ERA5 LSP cycles, with separate held-out
cycles and a small coherent intensity perturbation. Legacy v1 and its measured
200-GB archive are preserved. Public monthly reference downloads use bounded
ETag-pinned ranges after an initial long-stream network disconnect. No new
200-GB run or climate/novelty claim follows from this implementation. Actual
quality, memory, scan and browser results are recorded after execution.

2026-10-18, resumed after explicit user pause. Map implementation and saved
151-test regression were intact; completed map-context.json with source snapshot,
versions, test/XML and actual HTML/browser hashes. Four map tests plus the full
151-test run passed before pause (54.44 s, one existing TestClient warning).
Added no further scientific solver changes and did not rerun the 200-GB archive.

User asked how realistic generated data is. Audited the existing generator and
saved a small descriptive diagnostic in reports/synthetic_realism_diagnostic.json:
first 168 hours x 128 synthetic amount series, 21267 QC-valid records; three DWD
excerpts, 504 nonnegative values. Mean mm/hour 0.60113 vs 0.06190, zeros 65.87%
vs 88.49%. Deliberately not interpreted as a realism percentage: unpaired locations,
different sample sizes, three winter-station excerpts only, no climate calibration.
Report explains missing geographic/seasonal/advection dependencies and fixed
six-hour regimes. LSP not used as total-precipitation ground truth. No retuning,
new external validity, independent annotation or novelty claim follows.

2026-10-18, user requested a precipitation map/animation and a brief project
explanation. Added bounded NCAR ERA5 LSP map reader, offline Plotly 12-frame
HTML export and a small Streamlit source view. Region defaults to Europe/western
Russia; one initialization, documented previous-hour amounts, m->mm. No temporal
interpolation, daily disaggregation, spatial inference or cycle/SeriesKey fusion.
Natural Earth public-domain geometry bundled locally; dependencies unchanged.

Actual native source demo built: 573948 selected values (12x149x321), standalone
HTML 8392494 bytes, outputs/maps/era5_lsp_animation.html. Four targeted tests pass
(map-initial.xml); actual headless Edge render and switching to frame 5 verified,
map-render.json and local screenshot. Full regression recorded separately.
No new scientific/theoretical contribution, no Gate B change, no 200-GB rerun.

2026-10-17, substantive novelty justification after user feedback: stopped adding
solver features and separated author contribution from established global priority.
Prepared reports/novelty_justification.md (claim-level comparison, known-object
mapping, strongest standard-composition objection, limited conclusion) and
paper/novelty_statement_ru.md (usable contribution statement with supported scope).
Inspection log: reports/novelty_prior_art_check.json. Additional nearest overlaps
checked directly: Juditsky/Nemirovski finite convex unions (v5, sections 2.1/3.1-3.2),
Evans/Stark modulus formula (4.46), Donoho abstract only, McConnell et al. certifying
algorithms sections 1/2.4; revisited STN, Barber, Young/Tarjan/Orlin, Ettehad/Foucart
and determinacy passages. Did not claim full-paper/full-algorithm reproduction.
Corrected YTO final remarks/generalizations reference from section 5 to section 6.

Outcome: finite H, bounded noise, W/modulus definition, parametric paths and generic
certificate checking rejected as standalone novelty. Proposed narrow contribution
is the concrete constructive interval/H full-precision-profile method plus its
full-domain certificate and endpoint inclusion. No identical full output contract
identified in inspected passages, but general priority/nontriviality beyond known
composition unestablished. Explicitly separated prior art, correctness, expert
review and Gate B: absence of a reviewer does not forbid stating an author result;
passing Gate B does not establish priority. No new solver, tests or timings in
this documentation-only audit; historical runs, metrics and pending reviews intact.

2026-10-17, precision-frontier research extension (historical entries below retained).
User requested all feasible novelty validation work and an extensive explanation.
Closest sources read at definition/algorithm level: STN projection, Young/Tarjan/
Orlin parametric shortest paths, Ettehad/Foucart observation-error recovery. Overlap
recorded in literature_delta_2026_10_17.md; novelty/priority remains unestablished.
Implemented all-eta bounded-error precision profiles for ONE interval acquisition,
with activation, piecewise affine duals, primal endpoint/affine-ray proofs and
search-independent checker. No arbitrary daily disaggregation or series mixing.

Frozen precision-frontier-v1 completed: 36 bundles, 2880 ordered pair profiles,
2160 action/radius comparisons all pass; compiled/terminal medians
1.234/1.871/2.274; no-reuse/terminal 1.046/1.152/1.192. Peak tree RSS 98377728 bytes.
Equal-contract compiled SciPy Johnson comparator validates paths exactly with
fallback. No fallback in measured pilot; forced fallback tested separately.
Old negative H3 and all historical runs preserved. No new policy/complexity claim.
33 diagnostics pass: 2 hand, 27 existing original/controlled, 4 missing-record
derivatives; no new independent family claim, native DWD remains incomplete.

36 stored proof bundles replayed search-free; new CLI/API/Streamlit integrated;
temporary loopback server/external client verified new certificate and stopped.
Initial full regression: 146 passed, 1 failed in Git provenance metadata when a
temporary subdirectory inherited its parent repository. Source now requires .git
at the supplied project root, preventing attribution to an unrelated ancestor.
Original failed XML retained (precision-full.xml). Final: 147 passed, 1 known
TestClient deprecation warning, 47.99 seconds (precision-final.xml).

User confirmed no independent reviewer. Prepared review/proof_checklist.md and
4 development-family blind packets, zero annotations; Gate B and external proof
review pending, no one contacted. Detailed Russian explanation written in
docs/project_explained_ru.md. Scale reader untouched; no new 200-GB experiment,
real-200GB remains not_run. Final report derives metrics from saved runs.

Final artifact audit passed: all 33 diagnostic certificates replayed independently,
new Markdown local links resolve, UTF-8 checked, frozen protocol hash matches,
and the five measured scientific modules are byte-identical to the pilot source
ZIP. CLI precision/precision-verify exported and checked successfully; evidence:
reports/validation/precision-cli.json and precision-artifact-audit.json. Full
workspace Ruff passed. Final source/versions/history context retained separately;
historical failed/successful test XMLs remain intact. Preparing a normal Git
commit for the already authorized GitHub repository; no external review implied.

Current status after user resume: engineering prototype completed; synthetic
200-GB acceptance PASSED, 476 files / 200040947956 bytes fully scanned and
SHA256-verified, 24 checked Query invocations in each 1/10/50/200-GB profile.
Full suite: 79 passed. External HTTP client checked the final 200-GB partition.
Final report: reports/delivery.md. Gate B / human annotation pending;
real-200GB data run not_run. History and limitations follow below.

2026-10-16: Read supplied plan v2.1 and literature review. Workspace empty;
no Git repository, AGENTS.md, user files or version-1 code existed here.
Original documents preserved under docs/input with hashes. No files removed.
Implementation order: core/oracle/checker → baselines/pilot/Gate A → source
conventions/minimal UI/API → bounded scale smoke and resource-qualified runs.

Initial disk check: NTFS D:, 453214920704 bytes free. Python initially installed:
3.14; project selects managed 3.12. uv cache and interpreter are workspace-local.
WMI hardware query denied; later measurements use psutil, not guessed hardware.

Core: independent increment LP, exact sparse Bellman–Ford, 64-entry semantic-effect
LRU, bounded incremental STN candidate, portable independent proof/witness/ray
checker and strict threshold semantics implemented. No LLM, GPU or credential
dependency. Whole-cycle future halo added for cumulative Queries with missing
early records; different cycles remain separate.

Gate A initial and final runs retained. Final H1: 213/213 agreements, observed
false certifications 0/12 certified outputs. H2 demonstrated by hand fixtures.
H3 not supported: cold medians graph+cache 0.0129344 s vs shared 0.0260376 s.
H4 base expected cost: witness 1.9533333, VOI2 2.0683333, DRD 2.1933333, tiny
optimal 1.9433333; six constructed finite families only, no policy novelty claim.
Full priors/actions/costs/stopping/traces and sensitivity profiles are saved.

DWD: three seven-day station excerpts, 168 rows each, with raw/subset checksums.
Period/mm/UTC checked; native historical end-label remains incomplete. Controlled
assumed-end cases are clearly labeled. One 269320412-byte NCAR ERA5 LSP NetCDF
downloaded and inspected: separate initialization/hour/grid axes, m, previous-hour
processing. Expected TP key absent in checked folder; no fabricated TP mirror.
Local cumulative CSV is synthetic and substitutes for CDS credentials explicitly.
28 saved real/controlled/local cases passed checker and LP. Gate B pending human review.

Interfaces: Streamlit AppTest covers exact/range/metadata views; FastAPI stores
revisions in SQLite, supports bounded uploads and registered manifest Queries.
External client actually exercised loopback HTTP for fixture and 1-GB manifest,
then checked certificates locally. Inherited proxy initially broke localhost;
reference client now disables proxy inheritance. No arbitrary server paths/code.

Validation: initial 61 core tests passed. Expanded suite first found two test
errors (AppTest relative path, Fraction-to-float conversion), fixed; 72-test full
suite passed. Later storage/halo/accounting additions receive targeted smoke
verification; see reports/validation. Native startup sometimes stalled under
concurrent HDD IO/restricted sandbox; diagnostics and unsandboxed checks retained.

Scale: initial 1-GB profile has 1278907323 data bytes, full scan/query batch and
successful coordinated generation and scan resume. Deliberate worker crash at
78910996660 bytes in the 200-GB profile preserved completed shards; resume SHA
checks passed and generation continued. Final acceptance remains pending until
reports/scale/acceptance.json explicitly says passed. HDD model verified through
Get-Partition/Get-Disk: ST1000LM048-2E7172, NTFS. Scripts/CI use small smoke only.
The large run uses four workers, 32-MiB chunks and 2-GiB generator budget.

2026-10-16, pause/resume: the explicit user pause stopped the API and scale monitor.
Pause state/processes are saved in reports/pause-state.json and reports/pause-processes.json.
Synthetic generation completed: 200040947956 useful serialized data bytes in 476 shards.
1/10/50-GB full scans and Query batches completed before pause; 200-GB checkpoint had 2 completed files.
Final validation finished before pause: 78 tests, zero failures/errors, 88.127 s (reports/validation/delivery.xml).
User resumed work. Continuing benchmark with --resume, unchanged data and shard normalization.
Command: uv run --frozen --offline meteo benchmark scale --manifest data/scale/synthetic-200gb/manifest.json --memory-limit 16GiB --output reports/scale --resume
Pre-pause report preserved in reports/scale/archive/pre-pause-scale_report.json.
200-GB acceptance remains pending until full scan, queries and acceptance checks finish.

Resume verification: the first restricted benchmark invocation made no checkpoint
progress during native initialization. Its own process tree was stopped and the
same offline command was restarted outside the sandbox. Diagnostic metadata is
in reports/scale/sandbox-restart.json; the exact cause is not established.
The restarted invocation has advanced through 1/10-GB profiles. Full hashes are
rechecked even for already normalized shards; completed scan counters are reused.

Real subset was rerun against the current exact encoded-float import: 28/28
checker-valid outputs with independent LP comparison. Earlier results remain in
experiments/runs/real-subset/run-initial.json, current results in run.json. Native
DWD H remains incomplete; this rerun does not supply human annotation or pass Gate B.

Added paper/methods.md documenting the actual fragment and known algorithms.
Scale finalizer now supports --acceptance-only and --previous-report, preserves
source lineage, and distinguishes precipitation/QC payload, all numeric NetCDF
arrays and auxiliary/partial files. It explicitly reports the missing peak RSS
measurement of the deliberately killed generator invocation. No full crash-spanning
generation peak/time is inferred. A 200-GB real-profile LIST/HEAD dry-run is being
checked; no real-200GB download/scan is claimed.

NCAR 200-GB metadata dry-run completed: 735 LSP objects, 200208579407 selected bytes, LIST/HEAD verified; disk resource check passed. Full pinned plan in data/manifests/ncar-200gb-download-plan.json, summary in reports/ncar-profile.json. Real-200GB data download/scan remains not_run.
Header-only storage-accounting smoke passed on the existing small uncompressed dataset; reports/validation/storage-accounting-smoke.json. Whole-workspace Ruff check passed after finalizer/report/dry-run persistence changes.

Final maintenance checks: Streamlit now keys source state by full Case digest and checks registered manifest hash, fixing stale selection when duration/dataset changes under the same case ID. Targeted UI/evidence checks: 2 passed; full suite after fixes: 79 passed, zero failures/errors, 56.81 s (reports/validation/resumed-final.xml). TestClient deprecation warning retained in console log. Context/source snapshot is saved in resumed-final-context.json.
Standalone offline Plotly figures are generated by scripts/plot_results.py solely from saved runs; initial development figure excludes the unfinished 200-GB profile. No fitted scaling law or synthetic-to-real extrapolation is shown.

Completed after resume: synthetic scale acceptance PASSED (reports/scale/acceptance.json). All 476 files / 200040947956 data bytes / 22141808640 rows fully scanned and SHA256 verified. All 1/10/50/200-GB profiles complete, each with 24 checked Query invocations; largest has 8 LP checks and generating-truth inclusion 24/24.
Largest scan: 3936.506 seconds, 50.817 MB/s, 207966208 peak sampled tree RSS bytes; Query p50/p95 0.148562/0.439900 seconds.
Current 200-GB archive registered; external HTTP client queried final partition and locally verified its certificate, temporary server stopped. Full source snapshot now includes UI/tests. 79-test full suite and Ruff passed. Figures and paper tables regenerated from saved runs. Final report with commands, Gate A/B, hashes and limitations: reports/delivery.md.
Engineering synthetic-scale acceptance passed; Gate B / independent real annotation remains pending, real-200GB data run not_run. No method novelty, new complexity, unconditional soundness/optimality or A* claim. Interrupted generator peak/time and OS cache limitations remain explicit.

2026-10-16, new authorized research implementation: inspected workspace and source;
no AGENTS.md found and this is still not a Git checkout. Preserved historical
Gate A, reports, source snapshots and scale evidence. Added continuous-outcome
single-action acquisition domain, independent paired increment LP, exact full
pair graph, whole-batch LRU baseline, terminal-projection candidate and independent
path/point/ray checker. Metadata cannot resolve within-h underdetermination.
W and the projection/flow ingredients are treated as known foundations.

Pre-timing protocol: configs/experiments/acquisition-continuous-v1.json, synthetic
development regimes, no policy claim. CLI/API/Streamlit call the same oracle.
Initial core validation: 29 passed. First integration invocation retained 29 passes
and two temp-directory PermissionErrors; rerun with workspace-local basetemp:
31 passed (continuous-integration-localtmp.xml). Full new pilot is running in its
own directory; old negative H3 is not replaced. Scientific derivation and scope
limits are documented in docs/continuous_acquisition.md.

New development oracle pilot completed: 45 measured batches (9 LP, 36 exact
graph/cache/terminal), all 576 action-value comparisons agree. Zero recorded
pilot errors. Complete graph/terminal medians yield ratios 0.900/1.251/1.747;
2/3 predeclared regimes support proceeding, smallest loses. Warm cache and
numerical LP remain faster. Peak sampled process-tree RSS: 107405312 bytes.
Frozen inputs/bundles/hashes/versions/source ZIP retained in
experiments/runs/acquisition-continuous-v1. This is not a policy result, a new
complexity result, proof of priority, or Gate B pass.

Offline diagnostic and 27 original/controlled DWD/NCAR compatibility cases passed
paired LP and checker; acquisition-examples-v1. Native DWD retains incomplete_H;
new measurement availability is hypothetical, not an annotated archive action.
First full regression after integration: 110 passed, one existing TestClient
deprecation warning (continuous-full.xml). Added cached-deadline and unbounded
threshold/rate checks afterwards; final validation is running separately.

Final research validation completed: 111 passed, zero failures/errors, 34.72 s;
reports/validation/continuous-final.xml. Whole-workspace Ruff passed. Real
loopback HTTP external client exercised the new acquisition endpoint and verified
the certificate locally; temporary service stopped (acquisition-http/context.json).
CLI evaluate/export/independent verify passed. All 45 saved pilot bundle hashes
and all 36 exact certificates replayed without running a solver; acquisition-replay.json.
Validation history includes the earlier temp PermissionErrors rather than erasing
them. Context, versions, hashes and final source ZIP: continuous-final-context.json;
source SHA256 d694897b921334b9bc79c67cc50006f29620ae610ac4ca3df20580d11d41c504.

New results/commands/limitations: reports/continuous_acquisition.md; README links
the new report. Original reports/delivery.md and old Gate A runs were not edited.
Known negative results and scientific limits remain explicit: small-regime loss,
faster numerical LP and warm cache, no continuous-policy superiority, no established
priority, no independently annotated Gate B, real-200GB not_run. Existing storage
pipeline and synthetic 200-GB evidence were preserved; no new archive-wide scale
experiment is claimed for the bounded acquisition oracle.

2026-10-16, GitHub delivery requested: initialized main, checked the empty remote
https://github.com/nikooov4/meteo.git, retained existing README. Added
docs/novelty_validation_plan.md with precise prior-art/proof/strong-baseline/Gate B
requirements and explicit no-go conditions. Prepared credential/data exclusions
and byte-preserving .gitattributes because existing run/source checksums must
survive Windows/Linux clones unchanged. Bulk arrays and local environments stay
on disk outside Git; compact evidence/source snapshots are included.
Experiment metadata now detects actual Git revision/dirty state rather than
hardcoding the historical pre-Git state. Earlier saved runs are unchanged.

GitHub delivery validation: 112 tests passed, zero failures/errors, 34.59 s
(reports/validation/github-delivery.xml), whole-workspace Ruff passed. Warnings:
existing TestClient deprecation and an inaccessible optional pytest cache; test
execution completed. Credentials scan found no project credentials; the string
matches in embedded Plotly HTML were confirmed identical to the installed public
Plotly library. Added byte-identical 1/200-GB manifest provenance snapshots for
publication without raw arrays. Windows prevents changing the sandbox-owned .git
owner; a single-path safe.directory entry for this explicitly authorized workspace
allows ordinary Git under the user's account. No wildcard/global trust disable.

2026-10-19: generated a separate calibrated weather-v2 archive of 10,083,749,720
useful bytes, 118 shards, seed 42; preserved legacy-v1 200 GB and earlier v2 1 GB.
Disk plan feasible; generation 173.226 s, peak process-tree RSS 195,231,744 bytes.
Full 10-GB SHA256/streaming scan complete: 226.157 MB/s, peak 220,205,056 bytes,
24 certificate invocations (12 tasks first/repeat), eight LP validations, no errors.
New v2 50/200 GB not_run; scan resume_count=0. Runs in reports/weather-10gb/scale.
Archive map now uses the common FastAPI, one hourly field per request, four-frame
browser cache and bounded checksum-signature cache. Top-left UTC time selection,
separate members, explicit independent-cycle label, zoom retained. Native Edge
checked dates, shard/cycle/member changes, year endpoint, playback and reset.
Full regression 156 passed, 41.75 s, one existing TestClient deprecation warning.
reports/weather_10gb.md distinguishes archive IO/Query validation from bounded
precision-frontier experiments. Historical negative H3, Gate B pending and
unestablished scientific priority remain unchanged. User's original ERA5 HTML
preserved; previous main synthetic HTML backed up before promotion.

2026-10-19 defense/research expansion requested: prepared defense/ with Russian
project report, demo/map script, dataset sizes, novelty/delta, Q&A, copied older
materials and actual input examples. Historic precision inputs measured: nine
JSONs, 75,356 bytes; whole old pilot 15,840,022 bytes. Kept separate from large IO.
New frozen real ERA5 study completed: 12 verified source files (3,166,788,003 bytes),
72 native point/cycles, 144 documented-H1/controlled-H2 cases, 576 all-noise bundles,
1728 distinct action/radius comparisons per method, 4968 paired LP calls. Replay
checks 576 profile and 720 native/refinement bundles without LP/search. In H1,
35/72 bounds shrink, 37 already exact; full exact graph is faster than terminal
in that small regime. Sources are real reanalysis values, transformations controlled,
not independent annotation. Wall 170.579 s, peak RSS 330,211,328 bytes. New full
regression 161 passed, 219.81 s under concurrent IO, one existing warning.
Partition-wide 200-GB legacy precision run started separately with seed/protocol,
full SHA256 reads, checkpoints, identical oracle contracts and separate warm cache.
Report builder retains its actual running/complete status, historical scan remains
unchanged. Gate B/priority remain pending/unestablished; no weather forecast claim.

Additional posthoc native-resolution ERA5 diagnostic completed: 72 unchanged
12-hour point/cycles, Query first half-hour with eps=0. All original observation
hashes retained; no coarsening/removal/metadata shift. 41 exact, 31 uncertain and
unresolvable by available whole-hour amount refetches; at eps=0.05 mm only eight
have excessive width. 288 profile + 72 Query certificates replayed, paired LP
widths agree, zero numerical decision differences. Wall 16.889 s, peak RSS
145,743,872 bytes. Actual half-hour truth is unavailable and not invented.

Final archive experiment completed: all 476 shards / 200,040,947,956 bytes SHA256
verified; 1904 profile bundles, 5712 distinct action/radius comparisons per method,
40698 paired LP calls, zero recorded errors. Source metadata/versions/snapshots and
stop/resume history retained. Last complete invocation 2731.235 s, SHA read time
2312.106 s, peak tree RSS 170,975,232 bytes. Replay: 1904 profiles and 2380 Query
certificates checked without LP/search. Initial controlled exact cases 86; after
native refinement 453 exact, 22 still unbounded and one finite uncertain. Warm
cache is faster; cold compiled/terminal median ratio about 1.222, descriptive only.
Full final regression through ordinary pytest entry point: 161 passed, 108.78 s,
one existing warning. Earlier test import-path failure preserved separately and
fixed; no solver change. Defense evidence copies retain all compact bundles,
not bulk weather arrays. Gate A history and Gate B pending remain unchanged.

2026-10-22: added a plain Russian teaching/demo walkthrough, with translations of
all 11 fixture names, exact expected outcomes, UI click sequence, adding interval
evidence, metadata clarification, query tolerance, two contrasting measurement
actions and a glossary of input/output/proof/archive JSON fields. Clarified that
the UI plots cumulative witness trajectories rather than the internal constraint
graph. Executed all 11 fixtures and four evidence/tolerance derivatives; all
certificate checks passed. The unchanged native half-hour real example was also
checked, for 16 Query scenarios in total. The evening/repeat-day all-noise profile
and four eta values were checked separately. Detailed validation is recorded in
reports/validation/demo-walkthrough-2026-10-22.json. No solver changes, new browser
validation, fresh large-data runs or new novelty claims were made for this guide.

2026-10-22: reproduced the new-PC calibration failure on Windows/netCDF4 1.7.5:
Python existence/hash checks pass for a copied file under a Cyrillic directory,
while native Dataset(absolute_path) raises FileNotFoundError; an ASCII relative
path from the same Unicode current directory opens successfully. Tiny payload
and actual diagnostic are retained under outputs/path-diagnostics-2026-10-22/.
Weather generation now distinguishes absent training payload from existing-file
native Unicode errors and gives an ASCII-path workaround. Dry-run opens the
training bank header before reporting disk readiness, explicitly deferring full
SHA256 until generation. Added missing-bank/native-error regressions and copying
instructions; existing datasets, manifests and user changes are preserved.
Targeted weather/map regression: 11 passed in 15.11 s, one existing TestClient
deprecation warning; Ruff and git diff whitespace checks passed. Full regression
and large-data generation were not rerun for this path diagnostic change.
