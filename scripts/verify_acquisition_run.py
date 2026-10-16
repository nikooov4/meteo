"""Replay exact proof checks and hashes in a saved pilot without running solvers."""

import argparse
import json
from pathlib import Path

from meteo_bridge.acquisition_checker import verify_acquisition
from meteo_bridge.action_domain import AcquisitionAction
from meteo_bridge.domain import Case, digest
from meteo_bridge.resources import atomic_json, sha256_file


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=Path("experiments/runs/acquisition-continuous-v1/run.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/validation/acquisition-replay.json"))
    args = parser.parse_args()
    run = json.loads(args.run.read_text(encoding="utf8"))
    results = []
    root = args.run.parent.resolve()
    for record in run["records"]:
        path = (root / record["bundle"]).resolve()
        if not path.is_relative_to(root) or sha256_file(path) != record["sha256"]:
            raise ValueError("unsafe or changed bundle")
        verdict = None
        if record["method"] != "paired_lp":
            stem = record["bundle"].removesuffix("-" + record["method"] + ".json")
            data = json.loads((root / (stem + "-input.json")).read_text(encoding="utf8"))
            case = Case.model_validate(data["case"])
            actions = [AcquisitionAction.model_validate(a) for a in data["actions"]]
            if digest([case.model_dump(), [a.model_dump() for a in actions]]) != record["input_hash"]:
                raise ValueError("input hash mismatch")
            bundle = json.loads(path.read_text(encoding="utf8"))
            verdict = verify_acquisition(case, actions, bundle["result"], bundle["certificate"])
        results.append({"bundle": record["bundle"], "hash_valid": True, "checker": verdict})
    report = {"run_sha256": sha256_file(args.run), "records": results,
              "passed": all(r["checker"] is None or r["checker"]["valid"] for r in results),
              "lp_note": "numerical LP bundle hash checked; LP not rerun and not exactly certified"}
    atomic_json(args.output, report)
    print(json.dumps({"passed": report["passed"], "bundles": len(results),
                      "exact_checks": sum(r["checker"] is not None for r in results)}))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
