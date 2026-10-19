# Scale report

Manifest SHA256: `07db7c2955e024911067b14b336516a4fadba77333bf846c65d982e565da0860`

No extrapolation. RSS is sampled for the process tree; OS cache is uncontrolled.

| Target bytes | Actual data bytes | Status | Scan MB/s | Peak RSS |
|---|---|---|---|---|
| 1000000000 | 1278907323 | complete | 58.35503012552088 | 199213056 |
| 10000000000 | 10231257624 | complete | 66.78704401727595 | 203649024 |
| 50000000000 | 50318700487 | complete | 64.9325818864252 | 204779520 |
| 200000000000 | 200040947956 | complete | 50.81687967627574 | 207966208 |

Synthetic acceptance: **passed**.

Hardware metadata and finalization/source lineage are in scale_report.json.
Generation resume was checked after an intentional worker crash. Real-200GB: not_run.
The killed generator invocation has no saved peak RSS; final successful invocation does.
