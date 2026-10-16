"""Build claim/result tables only from saved runs; never fabricate missing measurements."""

import csv
import json
import re
from pathlib import Path

from meteo_bridge.resources import atomic_json, sha256_file


def main():
    summary_path = Path("experiments/runs/gate-a-final/summary.json")
    summary = json.loads(summary_path.read_text())
    policy_costs = summary["H4"]["mean_conditional_cost"]
    lines = [
        "# Measured results (development pilot)",
        "",
        f"Input summary SHA256: `{sha256_file(summary_path)}`.",
        f"Raw run SHA256: `{summary['run_sha256']}`. Versions/source snapshot are inside that run.",
        "",
        f"H1: {summary['H1']['agreed']}/{summary['H1']['total']} oracle agreements; observed false certifications "
        f"{summary['H1']['false_certifications']}/{summary['H1']['certification_denominator']} certified outputs.",
        "Many randomized alternatives exercise conflicts; separate property tests also retain a guaranteed feasible true h.",
        "This does not establish universal soundness or empirical coverage of real metadata hypotheses.",
        f"H3: {summary['H3']['cold_median_seconds']}; supported: {summary['H3']['supported_on_pilot']}.",
        "",
        "| Policy adaptation | Mean conditional cost, six synthetic families |",
        "|---|---|",
    ]
    lines += [f"| {policy} | {cost:.6f} |" for policy, cost in policy_costs.items()]
    lines += [
        "",
        "All actions, costs, public priors and stopping are identical. Full outcome support is enumerated.",
        "VOI2 has two-step lookahead and fixed error loss 10. Optimal is an exact tiny finite tree only.",
        "Reported witness advantage is a diagnostic synthetic observation, not a new-policy or external-validity claim.",
        "H5 and independent real annotation: pending. Gate B is not passed.",
    ]
    scale = Path("reports/scale/scale_report.json")
    if scale.exists():
        measured = json.loads(scale.read_text())
        lines += [
            "",
            "## Scale",
            "",
            f"Scale report SHA256: `{sha256_file(scale)}`.",
            "",
            "| Target bytes | Actual bytes | Status | Scan MB/s | Peak RSS bytes | Query count | p50 / p95 seconds |",
            "|---|---|---|---|---|---|---|",
        ]
        for p in measured["profiles"]:
            lines.append(
                f"| {p['target_bytes']} | {p.get('data_bytes')} | {p['status']} | "
                f"{p.get('scan_throughput_MB_s')} | {p.get('peak_process_tree_rss')} | "
                f"{p.get('solver_query_count')} | {p.get('latency_p50_s')} / {p.get('latency_p95_s')} |"
            )
        lines += [
            "",
            f"Synthetic scale acceptance: **{measured.get('acceptance', {}).get('status', 'pending')}**.",
            "Repeated Queries are counted as invocations, not independent scientific cases.",
            "The full scan is IO/normalization, not solving every archive row. OS cache is uncontrolled.",
            "RSS is sampled over the Python process tree; it excludes OS filesystem cache.",
            measured.get("generation_measurement_limit", "Generation memory coverage: see manifest."),
            "A resumed scan accumulates completed-shard times across invocations; input hashes are rechecked.",
            "Real-200GB remains not_run. Hardware, hashes, source lineage and detailed IO are in scale_report.json.",
        ]
    else:
        lines += ["", "200-GB full scan and acceptance: not_run until a completed scale report is saved."]
    Path("paper/results.md").write_text("\n".join(lines) + "\n", encoding="utf8")
    scale_acceptance = measured.get("acceptance", {}).get("status", "pending") if scale.exists() else "not_run"
    claims = [
        "# Claims ledger",
        "",
        "| Claim | Status / saved evidence |",
        "|---|---|",
        "| Difference constraints, possible worlds, type checking, DRD, VOI | Known foundations, supplied review S06/S16/S19–S23 |",
        f"| H1 numerical agreement | {summary['H1']['agreed']}/{summary['H1']['total']} in gate-a-final/run.json; conditional only |",
        "| H2 query without full reconstruction | Demonstrated by hand fixtures; known general principle |",
        f"| H3 shared solver advantage | {summary['H3']['supported_on_pilot']}; cold/warm measurements saved |",
        "| H4 witness advantage | Observed only on six finite constructed families; no policy novelty claim |",
        "| H5 real external validity | Pending independent annotation/unseen-family study |",
        f"| Synthetic 200-GB scalability | {scale_acceptance}; see reports/scale/scale_report.json; no extrapolation |",
        "| Real-200GB | not_run; one 269320412-byte LSP source object checked |",
        "| New complexity, optimality, unconditional soundness, A* | NOT CLAIMED |",
        "",
        "Conditional proof checking does not establish completeness of H or correctness of input assumptions.",
        "Initial review feasibility numbers are not reused as MeteoBridge results. Method follows saved source snapshots.",
    ]
    Path("paper/claims.md").write_text("\n".join(claims) + "\n", encoding="utf8")
    review = Path("docs/input/meteo_literature_and_novelty_review.md").read_text(encoding="utf8")
    with Path("paper/related_work.csv").open("w", encoding="utf8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "supplied_record", "url", "supplied_contribution", "scope_note"])
        for line in review.splitlines():
            match = re.match(r"\| (S\d+)\. (.*?) \| (.*?) \|", line)
            if match:
                url = re.search(r"\]\((https?://[^)]+)\)", match[2])
                writer.writerow(
                    [
                        match[1],
                        match[2],
                        url[1] if url else "",
                        match[3],
                        "Imported from supplied review; publication status not independently reasserted",
                    ]
                )
    groups = {}
    for path in list(Path("data/fixtures").glob("*.json")) + list(Path("benchmark/cases").glob("*.json")):
        case = json.loads(path.read_text(encoding="utf8"))
        groups.setdefault(case["family_id"], []).append(str(path))
    atomic_json(
        "benchmark/splits/groups.json",
        {
            "development": groups,
            "test": {},
            "status": "development pilot; no independently annotated held-out test frozen",
        },
    )


if __name__ == "__main__":
    main()
