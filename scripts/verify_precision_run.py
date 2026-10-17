"""Replay hashes and all-noise certificates without running a search/LP solver."""

import argparse
import json
from pathlib import Path

from meteo_bridge.action_domain import AcquisitionAction
from meteo_bridge.domain import Case, digest
from meteo_bridge.precision_checker import verify_precision_profiles
from meteo_bridge.resources import atomic_json, sha256_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=Path("experiments/runs/precision-frontier-v1/run.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/validation/precision-replay.json"))
    args = parser.parse_args()
    run = json.loads(args.run.read_text(encoding="utf8"))
    root = args.run.parent.resolve()
    records = []
    for record in run["records"]:
        dest = (root / record["bundle"]).resolve()
        if not dest.is_relative_to(root) or sha256_file(dest) != record["sha256"]:
            raise ValueError("unsafe or changed profile bundle")
        stem = record["bundle"].removesuffix("-" + record["method"] + ".json")
        data = json.loads((root / (stem + "-input.json")).read_text(encoding="utf8"))
        if digest(data) != record["input_hash"]:
            raise ValueError("changed profile input")
        case = Case.model_validate(data["case"])
        actions = [AcquisitionAction.model_validate(a) for a in data["actions"]]
        bundle = json.loads(dest.read_text(encoding="utf8"))
        check = verify_precision_profiles(case, actions, bundle["result"], bundle["certificate"])
        records.append({"bundle": dest.name, "checker": check, "hash_valid": True})
    for validation in run["validation"]:
        for field, checksum in (("input", "sha256"), ("lp_grid", "lp_grid_sha256")):
            if sha256_file(root / validation[field]) != validation[checksum]:
                raise ValueError("validation file changed")
    report = {"run_sha256": sha256_file(args.run), "records": records,
              "passed": bool(records) and all(r["checker"]["valid"] for r in records),
              "note": "LP reference hashes verified; no numerical LP/search executed by replay"}
    atomic_json(args.output, report)
    print(json.dumps({"passed": report["passed"], "profiles_checked": len(records)}))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
