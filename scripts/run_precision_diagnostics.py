"""Save hand diagnostics and controlled existing-source precision examples."""

import argparse
import json
from fractions import Fraction as F
from pathlib import Path

from meteo_bridge.action_domain import AcquisitionAction as Action
from meteo_bridge.domain import Case, Interpretation, Query, SemanticHypothesis, digest
from meteo_bridge.fixtures import fixture, observation
from meteo_bridge.paired_oracle import evaluate_paired_lp
from meteo_bridge.precision_experiment import _agrees
from meteo_bridge.precision_frontier import build_precision_profiles, precision_values
from meteo_bridge.resources import atomic_json, run_metadata, sha256_file


def hand_cases():
    daily = fixture("insufficient-data")
    daily.query.eps = "1/2"
    yield "daily", daily, [Action(id="complement", start=43200, end=86400),
                           Action(id="first6", start=0, end=21600)]
    jump = Case(id="metadata-activation-jump", observations=[observation("q", 0, 1, 0),
                observation("m", 1, 2, 0), observation("ten", 2, 3, 10), observation("two", 3, 4, 2)],
                hypotheses=[SemanticHypothesis(id="h0"), SemanticHypothesis(id="h1", intervals={
                    "q": Interpretation(start=7200, end=10800), "ten": Interpretation(start=0, end=3600),
                    "m": Interpretation(start=10800, end=14400), "two": Interpretation(start=3600, end=7200)})],
                query=Query(start=0, end=3600, eps="1"), h_complete=True,
                completeness_basis="two explicitly declared synthetic layouts; hand diagnostic",
                family_id="precision-metadata-jump")
    yield "jump", jump, [Action(id="measure-m", start=3600, end=7200)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("experiments/runs/precision-diagnostics-v1"))
    args = parser.parse_args()
    if (args.output / "run.json").exists():
        raise FileExistsError("preserve diagnostic run; use another --output")
    args.output.mkdir(parents=True, exist_ok=True)
    radii = ["0", "1/10", "1/2", "999/1000", "1", "2", "10"]
    run = {"metadata": run_metadata(), "records": [], "errors": [], "Gate_B": "pending; controlled/development only"}
    selected = [(name, c, a, {"origin": "hand", "family": c.family_id}) for name, c, a in hand_cases()]
    for path in sorted(Path("benchmark/cases").glob("*.json")):
        case = Case.model_validate_json(path.read_text(encoding="utf8"))
        q = case.query
        actions = [Action(id="measure-query", start=q.start, end=q.end),
                   Action(id="measure-first-half", start=q.start, end=(q.start+q.end)//2)]
        selected.append((path.stem, case, actions, {"origin": case.origin, "family": case.family_id,
                                                  "input": str(path), "input_sha256": sha256_file(path)}))
    # One missing-record derivative per original family. Its action is a refetch
    # of an existing encoded interval; eta>0 is a CONTROLLED coarsening model.
    families = set()
    for path in sorted(Path("benchmark/cases").glob("*.json")):
        case = Case.model_validate_json(path.read_text(encoding="utf8"))
        if case.family_id in families or "assumed-end" in path.stem:
            continue
        candidate = next((o for o in case.observations if o.qc == "accepted" and o.interval is not None and
                          o.interval.start >= case.query.start and o.interval.end <= case.query.end), None)
        if candidate is None:
            continue
        families.add(case.family_id)
        controlled = case.model_copy(deep=True)
        controlled.id += "-controlled-missing-record"
        controlled.origin = "controlled"
        controlled.observations = [o for o in controlled.observations if o.id != candidate.id]
        for h in controlled.hypotheses:
            h.intervals.pop(candidate.id, None)
        controlled.query.eps = "1/2"
        controlled.assumptions.append("controlled record removal and bounded coarsening; not device calibration")
        selected.append((controlled.id, controlled, [Action(id="refetch-removed", start=candidate.interval.start,
                         end=candidate.interval.end)], {"origin": "controlled", "family": case.family_id,
                         "input": str(path), "input_sha256": sha256_file(path),
                         "action_availability": "encoded original interval exists locally; conventions conditional as in original",
                         "coarsening": "eta is hypothetical bounded reply error, not measured instrument precision"}))
    for name, case, actions, provenance in selected:
        try:
            bundle = build_precision_profiles(case, actions)
            values = precision_values(case, actions, bundle, radii)
            refs = [evaluate_paired_lp(case, actions, error_radius=r) for r in radii]
            matched = _agrees(values, refs, 1e-7)
            dest = args.output / (name + ".json")
            atomic_json(dest, {"case": case.model_dump(), "actions": [a.model_dump() for a in actions],
                               "bundle": bundle, "values": values, "lp": refs, "provenance": provenance})
            if name in ("daily", "jump"):
                subdir = args.output / name
                atomic_json(subdir / "case.json", case.model_dump())
                atomic_json(subdir / "actions.json", [a.model_dump() for a in actions])
                atomic_json(subdir / "bundle.json", bundle)
            run["records"].append({"id": name, "case_hash": digest(case), "h_complete": case.h_complete,
                                   "checker_valid": bundle["checker"]["valid"], "lp_agreement": matched,
                                   "output": dest.name, "sha256": sha256_file(dest), **provenance})
        except Exception as exc:
            run["errors"].append({"id": name, "error": repr(exc)})
    run["passed"] = not run["errors"] and all(r["checker_valid"] and r["lp_agreement"] for r in run["records"])
    # Hand checks are separate from LP tolerance at the open endpoint.
    jump = json.loads((args.output / "jump/bundle.json").read_text(encoding="utf8"))["result"]["actions"][0]
    daily = json.loads((args.output / "daily/bundle.json").read_text(encoding="utf8"))["result"]["actions"][0]
    assert F(jump["radius_supremum"]) == 1 and not jump["safe_at_supremum"]
    assert F(daily["radius_supremum"]) == F(1, 2) and daily["safe_at_supremum"]
    atomic_json(args.output / "run.json", run)
    print(json.dumps({"passed": run["passed"], "cases": len(run["records"]), "controlled_families": len(families),
                      "errors": run["errors"]}))
    if not run["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
