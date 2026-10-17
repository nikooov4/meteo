"""Prepare an unannotated review packet; never fabricate independent reviewers."""

import argparse
import csv
from pathlib import Path

from meteo_bridge.domain import Case
from meteo_bridge.resources import atomic_json, sha256_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("review/annotation_blind"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    seen, index, private_map = set(), [], []
    for path in sorted(Path("benchmark/cases").glob("*.json")):
        case = Case.model_validate_json(path.read_text(encoding="utf8"))
        if case.family_id in seen or case.origin != "original":
            continue
        seen.add(case.family_id)
        cid = f"review-{len(index)+1:02}"
        # No predictions, H enumeration, completeness flag, candidate interval
        # annotation, Query bound or expected precision enters the blind packet.
        raw = [{"record_id": o.id, "original_value": o.original_value, "original_timestamp": o.original_timestamp,
                "qc": o.qc, "evidence_ids": o.evidence_ids} for o in case.observations]
        sources = [{k: getattr(s, k) for k in ("provider", "url", "sha256", "documentation_version", "version")}
                   for s in case.source_manifests]
        dest = args.output / (cid + ".json")
        atomic_json(dest, {"review_id": cid, "family_id": case.family_id, "series_identity": case.query.series.model_dump(),
                           "raw_records": raw, "query": case.query.model_dump(exclude={"series"}), "sources": sources,
                           "split": "development family; NOT a new held-out family"})
        index.append({"review_id": cid, "family": case.family_id, "file": dest.name, "sha256": sha256_file(dest)})
        private_map.append({"review_id": cid, "original_case": str(path), "case_file_sha256": sha256_file(path)})
    with (args.output / "annotation_template.csv").open("w", encoding="utf8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["review_id", "reviewer_id", "timestamp_convention",
            "interval_bounds", "units", "statistic", "calendar_timezone", "reset_cycle", "qc_policy",
            "candidate_interpretations_json", "h_complete", "completeness_basis", "available_actions_and_costs",
            "new_measurement_error_model", "documentation_url_page_version", "disagreement_notes"])
        writer.writeheader()
        for item in index:
            writer.writerow({"review_id": item["review_id"]})
    atomic_json(args.output / "index.json", {"cases": index, "predictions_included": False,
                                             "annotations_completed": 0, "independently_reviewed": False})
    atomic_json(".meteo/review_packet_internal_map.json", private_map)
    atomic_json("reports/review_status.json", {"status": "pending_no_independent_reviewer",
                "user_response": "no independent reviewer currently available", "annotations_completed": 0,
                "packet": args.output.as_posix(), "families": len(index), "held_out": False,
                "Gate_B": "pending; these development families alone cannot pass external validity",
                "contacts_messaged": False})
    print(f"Prepared {len(index)} unannotated development-family packets; independent review pending")


if __name__ == "__main__":
    main()
