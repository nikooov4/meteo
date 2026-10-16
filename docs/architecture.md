# Architecture

CSV/Case JSON/scalar CF NetCDF → typed Case → per-h semantic intervals → exact
difference graphs → result + proof → independent checker. SciPy oracle separately
builds a dense interval-incidence LP on nonnegative increments for small cases.
The LP does not import semantics.py, graph.py or normalized edge assembly.

The graph uses sparse Bellman–Ford for global consistency and two query bounds.
Attaining models are found with equality edges; unreachable objectives use
recession rays. Shared candidate intersects common directed effects, closes the
bounded common graph and inserts deltas using known incremental STN arithmetic.
Full-effect LRU holds at most 64 worlds; query/evidence changes alter keys.
Budget context variables isolate counters and deadlines across requests.
The compiler caps the union at 1024 endpoints, 65536 observation/world pairs
and 65536 endpoint/world pairs before building repeated monotonicity structures.
Budget exits return incomplete_model, never a certificate from a partial search.

Certificates bind the complete raw Case/query (including source checksums and
assumptions), all H and revision. The checker reconstructs inequalities itself,
checks paths/cycles/feasible extremes/rays with Fractions, and recalculates bounds
and strict threshold decisions. It performs no search. It verifies a conditional
mathematical argument, not authenticity of the provider or completeness of H.

Storage: synthetic NetCDF shards partition by series group and time; each group
has one representation. A cycle never resets at a shard/chunk boundary. NetCDF
uses bounded hyperslabs/cache; Parquet uses projection, row-group predicates and
record batches. Manifest is small; archive registration stores its path/hash in
SQLite. UI/API only import bounded cases. Query reads one series and limited
hours, and cumulative Queries select a single cycle. Scan streams normalization
separately from solver batches. No dense graph is built for the whole archive.

Policy experiments use a public finite predictive model and priors. The simulator
owns only the true-state index and reveals an outcome after an action. All methods
use exactly the same service/checker stopping condition. Continuous observations
are not modeled as exact finite HEC. UI suggestions are conservative cause-based
actions; experimental ranking is not advertised as validated on real users.

SQLite persists dataset cases, query revisions and evidence. Uploads are capped at
20 MiB, filenames are replaced with temporary server-generated names, archives
are rejected, SQL is parameterized, and no endpoint accepts server file paths.
The local service binds loopback by default; authentication/multi-user deployment
is outside this prototype.
