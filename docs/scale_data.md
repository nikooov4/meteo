# Scale design and measurement

Realism audit, 2026-10-18: [synthetic_realism.md](../reports/synthetic_realism.md)
documents what the existing generator does and does not model. The synthetic
200-GB archive is an engineering workload, not a climate-calibrated surrogate.
A small unpaired DWD diagnostic is descriptive only and does not establish a
percentage of realism, held-out validity or scientific priority. Parameters and
the measured scale dataset were not changed in response to the comparison.

Profiles and CLI are in configs/scale and README. Default capacity: four million
distinct grid series, hourly 2023; cells have unique ids/coordinates. Each group
uses exactly one of amount/cumulative/mean-rate representations, never copies
of the same series as independent data. Wet/dry six-hour storm regimes and
nonnegative integer hundredths are deterministic in seed/id/hour. Cumulative
generation includes a cycle halo and resets at the configured 24-hour cycle
origin (default UTC midnight), not file edges. Cumulative Query reads the entire
selected cycle: later totals can bound an earlier missing subinterval.
QC codes 1/2 mark known missing/controlled rejected defects; truth can be regenerated
with amounts(seed, ids, hours), not a second full archive.

Both storage formats are real serialized arrays/tables. NetCDF default float64
precipitation and uint8 QC are uncompressed; Parquet projects columns and filters
row groups. zlib/zstd variants are supported separately and count their own actual
compressed sizes. Final excess is bounded by one shard (metadata overhead matters
for very small shards); default 512 MiB shards contain about 426 MB useful arrays
plus normal coordinates/schema. No filler/padding/sparse reservation is written.

Each completed file is atomically renamed from .partial, hashed and added to an
atomic manifest. Resume verifies completed checksums and adopts only completed
orphans with the right embedded configuration. Worker count/budget do not change
semantic data. Incomplete shard files can be regenerated; completed data remains
immutable. A worker crash exercise and coordinated interruption/resume are retained.

Disk planning reserves remaining target plus a largest temporary shard and 20%
of target, checks space before each bounded submission, and honors disk_budget.
The native NCAR loader makes bounded monthly LIST/HEAD manifests of precipitation
objects, saves size/ETag/version and streams with range + If-Match, retry/backoff,
SHA256, .partial and resume. It does not load or concatenate an archive. Full region
objects are an explicit scope, not a claim of remote spatial subsetting.

Budgets are conservative chunk/worker estimates plus sampled process-tree RSS and
batch checks, not hard kernel limits. 32 GB machine target: generator ≤2 GiB and
benchmark ≤16 GiB. Native NCAR chunks can span all twelve steps and a grid (~50 MB
float32); scan reads one initialization once rather than repeatedly decompressing
that chunk for every spatial row. Query selects one cell/cycle, never fuses cycles.
The graph is built only for a limited Query, at most 4096 observations, 1024 union
endpoints and 65536 observation/world and endpoint/world pairs. Budget exits are
incomplete_model. Shared
closure is capped at 256 endpoints; LP reference at 512 endpoints.

The benchmark validates structure, then hashes every data shard immediately before
its full normalization scan; full_verified is set only after all SHA256 match.
This reuses bounded filesystem cache on HDD instead of doing two separate whole
archive passes. Standalone verify-scale --mode full remains a separate byte pass.
Reported scan wall time/throughput includes in-pass checksum work; its time is
also recorded separately. The benchmark computes a normalization
and digest with resumable per-shard checkpoints. Separate Queries export all cases,
bounds/certificates/witnesses, logical projection bytes, cache condition, timings
and selected LP comparisons. A full scan is not a scientific solve on every row.
OS-reported process IO counters are saved (they can include cached IO); OS cache is uncontrolled and therefore
no true cold-cache performance claim is made. Allocated bytes are recorded via
Windows GetCompressedFileSizeW or POSIX st_blocks; deduplication/shared placement
is not independently audited. Sparse/compressed placement cannot silently establish
the uncompressed physical-payload acceptance criterion.

Only actual scale_report statuses count. Smoke tests create small temporary data.
Linux/WSL2 paths are portable by design, but current execution evidence is Windows.
Real-200GB acceptance requires a separate actual real-scale report.

The finalization command `scripts/finish_scale_experiment.py --acceptance-only`
reads a completed benchmark report and its matching manifest without repeating the
data scan. It checks the acceptance criteria and records header-only logical byte
accounting for all NetCDF numeric arrays, including coordinates. The benchmark's
`verification.logical_array_bytes` is specifically precipitation + QC payload;
`storage_accounting.logical_all_netcdf_arrays_bytes` includes the other arrays.
Auxiliary and remaining partial files are counted separately at finalization;
that final snapshot does not measure a historical temporary-space peak. Completed
shard scan times can span invocations. The preserved pre-pause report and current
source snapshot identify the code used on either side of a resume.

One intentional generator crash was exercised before the successful final
invocation. Its saved RSS observation is not a peak measurement. The final
successful invocation has a sampled process-tree peak and an enforced batch
budget; full-run peak/time across the deliberately killed invocation is not
recoverable and is not claimed.
