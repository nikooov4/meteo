"""Offline hand diagnostic and compatibility checks on existing source cases.

This does not claim that the hypothetical acquisition is available in an archive.
No downloaded source or old evidence is modified.
"""

import argparse
import json
from pathlib import Path

from meteo_bridge.acquisition_experiment import agrees
from meteo_bridge.action_domain import AcquisitionAction as Action
from meteo_bridge.continuous_acquisition import evaluate_actions
from meteo_bridge.domain import Case, digest
from meteo_bridge.fixtures import fixture, observation
from meteo_bridge.paired_oracle import evaluate_paired_lp
from meteo_bridge.resources import atomic_json, run_metadata, sha256_file
from meteo_bridge.services import apply_evidence, solve_query


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("experiments/runs/acquisition-examples-v1"))
    args = parser.parse_args()
    if (args.output / "run.json").exists():
        raise FileExistsError("preserve existing run; choose another --output")
    args.output.mkdir(parents=True, exist_ok=True)
    case = fixture("insufficient-data")
    case.hypotheses[0].assignments = {"label": "end"}
    choices = [Action(id="first6", start=0, end=21600),
               Action(id="last12", start=43200, end=86400),
               Action(id="label", kind="metadata", attribute="label")]
    diagnostic = evaluate_actions(case, choices)
    atomic_json(args.output / "case.json", case.model_dump())
    atomic_json(args.output / "actions.json", [a.model_dump() for a in choices])
    atomic_json(args.output / "bundle.json", diagnostic)
    # Actual responses used only here, AFTER public action evaluation. These are
    # illustrative attainable answers, not policy performance or hidden priors.
    responses = {}
    for action, value, start, end in (("first6", 0, 0, 6), ("last12", 5, 12, 24)):
        posterior = apply_evidence(case, {"kind": "add_observation",
                                         "observation": observation(action, start, end, value).model_dump(),
                                         "origin": "controlled hand diagnostic"})
        responses[action] = solve_query(posterior)
    atomic_json(args.output / "after-actions.json", responses)
    run = {"metadata": run_metadata(), "diagnostic": diagnostic["result"], "records": [], "errors": [],
           "scope": "compatibility diagnostics; hypothetical exact acquisitions, not independently verified availability",
           "Gate_B": "pending independent human review; no external-validity claim"}
    for path in sorted(Path("benchmark/cases").glob("*.json")):
        try:
            model = Case.model_validate_json(path.read_text(encoding="utf8"))
            q = model.query
            middle = (q.start + q.end) // 2
            actions = [Action(id="measure-query", start=q.start, end=q.end),
                       Action(id="measure-half", start=q.start, end=middle)]
            attrs = set.intersection(*(set(h.assignments) for h in model.hypotheses))
            actions += [Action(id="metadata-" + a, kind="metadata", attribute=a) for a in sorted(attrs)]
            bundle = evaluate_actions(model, actions)
            lp = evaluate_paired_lp(model, actions)
            dest = args.output / (path.stem + ".json")
            atomic_json(dest, {"case_hash": digest(model), "actions": [a.model_dump() for a in actions],
                               "bundle": bundle, "paired_lp": lp})
            run["records"].append({"input": str(path), "input_sha256": sha256_file(path),
                                   "family": model.family_id, "origin": model.origin,
                                   "h_complete": model.h_complete, "status": bundle["result"]["status"],
                                   "checker_valid": bundle["checker"]["valid"],
                                   "agrees_with_lp": agrees(bundle, lp, 1e-7),
                                   "output": dest.name, "sha256": sha256_file(dest)})
        except Exception as exc:
            run["errors"].append({"input": str(path), "error": repr(exc)})
    run["passed"] = (bool(run["records"]) and not run["errors"] and
                     all(r["checker_valid"] and r["agrees_with_lp"] for r in run["records"]))
    atomic_json(args.output / "run.json", run)
    print(json.dumps({"passed": run["passed"], "cases": len(run["records"]), "errors": run["errors"],
                      "diagnostic": diagnostic["result"]}, indent=2))
    if not run["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
