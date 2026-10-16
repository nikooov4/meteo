# Measured results (development pilot)

Input summary SHA256: `1252f17e6a88d55c5f2b3dc07900d90cb91cfc3ffb53a8ffe93b29b2193e189a`.
Raw run SHA256: `de2fbcfa958bee6c5c7f1a50560cb45ec739837f0c7c9fe8eb55fa453c3c0f2e`. Versions/source snapshot are inside that run.

H1: 213/213 oracle agreements; observed false certifications 0/12 certified outputs.
Many randomized alternatives exercise conflicts; separate property tests also retain a guaranteed feasible true h.
This does not establish universal soundness or empirical coverage of real metadata hypotheses.
H3: {'cache': 0.01293439999972179, 'shared': 0.026037600000563543}; supported: False.

| Policy adaptation | Mean conditional cost, six synthetic families |
|---|---|
| fixed | 2.435000 |
| random | 3.333333 |
| entropy | 2.318333 |
| voi | 2.583333 |
| voi2 | 2.068333 |
| drd | 2.193333 |
| witness | 1.953333 |
| optimal | 1.943333 |

All actions, costs, public priors and stopping are identical. Full outcome support is enumerated.
VOI2 has two-step lookahead and fixed error loss 10. Optimal is an exact tiny finite tree only.
Reported witness advantage is a diagnostic synthetic observation, not a new-policy or external-validity claim.
H5 and independent real annotation: pending. Gate B is not passed.

## Scale

Scale report SHA256: `97a5b0c6a6dbec7c7d6a1fae3ba771348e44f0cae22edbe80fd6e9d432be1896`.

| Target bytes | Actual bytes | Status | Scan MB/s | Peak RSS bytes | Query count | p50 / p95 seconds |
|---|---|---|---|---|---|---|
| 1000000000 | 1278907323 | complete | 58.35503012552088 | 199213056 | 24 | 0.013385800000833115 / 0.018542640000123355 |
| 10000000000 | 10231257624 | complete | 66.78704401727595 | 203649024 | 24 | 0.01320320000013453 / 0.01874787999968248 |
| 50000000000 | 50318700487 | complete | 64.9325818864252 | 204779520 | 24 | 0.017511699999886332 / 0.39514967999912187 |
| 200000000000 | 200040947956 | complete | 50.81687967627574 | 207966208 | 24 | 0.1485615500005224 / 0.4399002999994991 |

Synthetic scale acceptance: **passed**.
Repeated Queries are counted as invocations, not independent scientific cases.
The full scan is IO/normalization, not solving every archive row. OS cache is uncontrolled.
RSS is sampled over the Python process tree; it excludes OS filesystem cache.
Successful final generation invocation has sampled process-tree peak RSS. The deliberately killed invocation has only a point RSS observation, not a saved peak; no complete peak or total wall-time measurement across that crash is claimed.
A resumed scan accumulates completed-shard times across invocations; input hashes are rechecked.
Real-200GB remains not_run. Hardware, hashes, source lineage and detailed IO are in scale_report.json.
