"""Frozen all-noise oracle experiment, with compiled baseline and reuse ablation."""

import json
from fractions import Fraction as F
from pathlib import Path
from random import Random
from statistics import median
from time import perf_counter

from .action_domain import AcquisitionAction as Action
from .domain import Case, Interpretation, Query, SemanticHypothesis, digest
from .fixtures import observation
from .paired_oracle import evaluate_paired_lp
from .precision_frontier import build_precision_profiles, precision_values
from .resources import MemoryGuard, atomic_json, run_metadata, sha256_file


def precision_case(seed, n, nh, na):
    rng = Random(seed)
    truth = [rng.randrange(1, 6) for _ in range(n)]
    obs = [observation("total", 0, n, sum(truth))]
    step = n//4
    for i, a in enumerate(range(0, n, step)):
        b = min(n, a+step)
        value = sum(truth[a:b])
        obs.append(observation(f"block-{i}", a, b, max(0, value-2), value+2))
    obs.append(observation("ambiguous", 0, 1, rng.randrange(1, 6)))
    starts = [0, n//2, n-1][:nh]
    hs = [SemanticHypothesis(id=f"layout-{i}", assignments={"layout": str(a)},
                             intervals={"ambiguous": Interpretation(start=a*3600, end=(a+1)*3600)})
          for i, a in enumerate(starts)]
    case = Case(id=f"precision-{seed}-n{n}-h{nh}", observations=obs, hypotheses=hs,
                query=Query(start=0, end=n//2*3600, eps="1/2"), h_complete=True,
                completeness_basis="all declared generated layouts; development synthetic scope",
                family_id=f"precision-generated-{seed}")
    pool = [(a, b) for a in range(n) for b in range(a+1, n+1)]
    rng.shuffle(pool)
    selected = [(0, n//2), (n//2, n)]
    selected += [p for p in pool if p not in selected][:na-2]
    actions = [Action(id=f"measure-{a}-{b}", start=a*3600, end=b*3600, cost=str(1+(b-a)//4)) for a, b in selected]
    return case, actions


def _agrees(values, references, tolerance):
    for row, lp in zip(values, references):
        for actual, expected in zip(row["actions"], lp["actions"]):
            if actual["width_kind"] != expected["width_kind"]:
                return False
            if actual["guarantees_resolution"] != expected["guarantees_resolution"]:
                return False
            if actual["width"] is not None and abs(float(F(actual["width"]))-expected["width"]) > tolerance:
                return False
    return True


def run_precision_pilot(config, output):
    config, output = Path(config), Path(output)
    if (output / "protocol-frozen.json").exists():
        raise FileExistsError("preserve pilot; choose a fresh output directory")
    output.mkdir(parents=True, exist_ok=True)
    protocol = json.loads(config.read_text(encoding="utf8"))
    run = {"protocol": protocol, "protocol_sha256": sha256_file(config), "metadata": run_metadata(),
           "records": [], "errors": [], "validation": [], "scope": protocol["scope"]}
    atomic_json(output / "protocol-frozen.json", run)
    # Common native initialization excluded, every measured profile is built cold.
    warm_case, warm_actions = precision_case(1, 8, 1, 2)
    for method in protocol["methods"]:
        build_precision_profiles(warm_case, warm_actions, method)
    evaluate_paired_lp(warm_case, warm_actions)
    with MemoryGuard("1GiB") as memory:
        for ri, regime in enumerate(protocol["regimes"]):
            for rep in range(protocol["replicates"]):
                seed = protocol["seed"] + 1000*ri + rep
                case, actions = precision_case(seed, regime["segments"], regime["hypotheses"], regime["actions"])
                stem = f"n{regime['segments']}-h{regime['hypotheses']}-rep{rep}"
                data = {"case": case.model_dump(), "actions": [a.model_dump() for a in actions]}
                atomic_json(output / f"{stem}-input.json", data)
                references = [evaluate_paired_lp(case, actions, error_radius=radius) for radius in protocol["radii"]]
                atomic_json(output / f"{stem}-lp-grid.json", {"radii": protocol["radii"], "results": references,
                                                            "note": "finite numerical validation grid, no all-parameter certificate"})
                methods = list(protocol["methods"])
                Random(seed).shuffle(methods)
                for method in methods:
                    try:
                        start = perf_counter()
                        bundle = build_precision_profiles(case, actions, method)
                        seconds = perf_counter()-start
                        values = precision_values(case, actions, bundle, protocol["radii"])
                        matched = _agrees(values, references, protocol["agreement_tolerance"])
                        path = output / f"{stem}-{method}.json"
                        atomic_json(path, {**bundle, "validation_values": values})
                        run["records"].append({"regime": regime, "replicate": rep, "seed": seed,
                                               "method": method, "seconds": seconds, "metrics": bundle["metrics"],
                                               "checker_valid": bundle["checker"]["valid"], "lp_agreement": matched,
                                               "input_hash": digest(data), "bundle": path.name,
                                               "sha256": sha256_file(path),
                                               "proof_bytes": len(json.dumps(bundle["certificate"]).encode("utf8"))})
                        memory.check()
                    except Exception as exc:
                        run["errors"].append({"regime": regime, "replicate": rep, "method": method, "error": repr(exc)})
                run["validation"].append({"input": f"{stem}-input.json", "sha256": sha256_file(output / f"{stem}-input.json"),
                                          "lp_grid": f"{stem}-lp-grid.json", "lp_grid_sha256": sha256_file(output / f"{stem}-lp-grid.json")})
                atomic_json(output / "run.partial.json", run)
        memory.check()
        run["peak_sampled_tree_rss_bytes"] = memory.peak
    summaries = []
    for regime in protocol["regimes"]:
        times = {m: median(r["seconds"] for r in run["records"] if r["regime"] == regime and r["method"] == m)
                 for m in protocol["methods"]
                 if any(r["regime"] == regime and r["method"] == m for r in run["records"])}
        summaries.append({"regime": regime, "median_seconds": times,
                          "terminal_below_compiled": times.get("terminal", float("inf")) < times.get("compiled", 0)})
    complete = len(run["records"]) == len(protocol["regimes"]) * protocol["replicates"] * len(protocol["methods"])
    passed = complete and not run["errors"] and all(r["checker_valid"] and r["lp_agreement"] for r in run["records"])
    run["summary"] = {"regimes": summaries, "all_checks_passed": passed,
                      "go_criterion_met": passed and sum(s["terminal_below_compiled"] for s in summaries) >= 2,
                      "method_priority": "unestablished; standard parametric graph/flow and optimal-recovery foundations",
                      "external_review": "pending; no independent human reviewers simulated"}
    atomic_json(output / "run.json", run)
    atomic_json(output / "summary.json", run["summary"])
    return run["summary"]
