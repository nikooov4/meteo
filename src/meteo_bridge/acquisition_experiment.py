"""Separately frozen development pilot for the continuous oracle, not policies."""

import json
from fractions import Fraction as F
from pathlib import Path
from random import Random
from statistics import median
from time import perf_counter

from .action_domain import AcquisitionAction as Action
from .continuous_acquisition import clear_acquisition_cache, evaluate_actions
from .domain import Case, Interpretation, Query, SemanticHypothesis, digest
from .fixtures import fixture, observation
from .paired_oracle import evaluate_paired_lp
from .resources import MemoryGuard, atomic_json, run_metadata, sha256_file


def development_case(seed, n, nh, na):
    rng = Random(seed)
    truth = [rng.randrange(1, 7) for _ in range(n)]
    obs = [observation("total", 0, n, sum(truth))]
    for k in range(n // 3):
        a, b = sorted(rng.sample(range(n + 1), 2))
        value = sum(truth[a:b])
        obs.append(observation(f"interval-{k}", a, b, max(0, value - 3), value + 3))
    length = max(1, n // 4)
    obs.append(observation("ambiguous", 0, length, 0, 6 * length))
    hs = [
        SemanticHypothesis(
            id=f"h{i}",
            assignments={"label": str(i)},
            intervals={"ambiguous": Interpretation(start=i * 3600, end=(i + length) * 3600)},
        )
        for i in range(nh)
    ]
    case = Case(
        id=f"acquisition-{seed}-n{n}-h{nh}",
        observations=obs,
        hypotheses=hs,
        query=Query(start=0, end=(n // 2) * 3600),
        h_complete=True,
        completeness_basis="all finite generated layouts; synthetic development scope",
        family_id=f"acquisition-development-{seed}",
    )
    intervals = [(a, b) for a in range(n) for b in range(a + 1, n + 1)]
    rng.shuffle(intervals)
    chosen = [(n // 2, n)] + [x for x in intervals if x != (n // 2, n)][: na - 1]
    actions = [
        Action(id=f"measure-{a}-{b}", start=a * 3600, end=b * 3600, cost=str(1 + (b - a) // 4))
        for a, b in chosen
    ]
    return case, actions


def agrees(bundle, lp, tol):
    if not bundle.get("checker", {}).get("valid"):
        return False
    for actual, expected in zip(bundle["result"]["actions"], lp["actions"]):
        if (
            actual["width_kind"] != expected["width_kind"]
            or actual["guarantees_resolution"] != expected["guarantees_resolution"]
        ):
            return False
        if (
            expected["width"] is not None
            and abs(float(F(actual["worst_remaining_width"])) - expected["width"]) > tol
        ):
            return False
    return True


def run_acquisition_pilot(config, output):
    config, output = Path(config), Path(output)
    if (output / "run.json").exists():
        raise FileExistsError("pilot exists; use a new output directory to preserve evidence")
    output.mkdir(parents=True, exist_ok=True)
    protocol = json.loads(config.read_text(encoding="utf8"))
    run = {
        "protocol": protocol,
        "protocol_sha256": sha256_file(config),
        "metadata": run_metadata(),
        "records": [],
        "errors": [],
        "scope": "synthetic development oracle; no policy comparison",
    }
    atomic_json(output / "protocol-frozen.json", run)
    # Library startup is outside timings; every measured cold oracle builds its model/closure anew.
    warm_case = fixture("insufficient-data")
    evaluate_paired_lp(warm_case, [Action(id="warmup", start=0, end=43200)])
    with MemoryGuard("1GiB") as memory:
        for ri, regime in enumerate(protocol["regimes"]):
            for rep in range(protocol["replicates"]):
                seed = protocol["seed"] + ri * 1000 + rep
                case, actions = development_case(
                    seed, regime["segments"], regime["hypotheses"], regime["actions"]
                )
                stem = f"n{regime['segments']}-h{regime['hypotheses']}-rep{rep}"
                atomic_json(
                    output / f"{stem}-input.json",
                    {"case": case.model_dump(), "actions": [a.model_dump() for a in actions]},
                )
                clear_acquisition_cache()
                methods = list(protocol["methods"])
                Random(seed).shuffle(methods)
                # Warm must follow a matching cold cache call, without timing its priming.
                results, records = {}, []
                for method in methods:
                    try:
                        if method == "cache_warm":
                            evaluate_actions(case, actions, "cache")
                        if method == "cache_cold":
                            clear_acquisition_cache()
                        started = perf_counter()
                        bundle = (
                            evaluate_paired_lp(case, actions)
                            if method == "paired_lp"
                            else evaluate_actions(
                                case, actions, "cache" if method.startswith("cache") else method
                            )
                        )
                        elapsed = perf_counter() - started
                        memory.check()
                        path = output / f"{stem}-{method}.json"
                        atomic_json(path, bundle)
                        record = {
                            "regime": regime,
                            "replicate": rep,
                            "seed": seed,
                            "method": method,
                            "input_hash": digest([case.model_dump(), [a.model_dump() for a in actions]]),
                            "seconds": elapsed,
                            "metrics": bundle["metrics"],
                            "bundle": path.name,
                            "sha256": sha256_file(path),
                            "proof_bytes": len(json.dumps(bundle.get("certificate", {})).encode("utf8")),
                        }
                        results[method] = bundle
                        records.append(record)
                    except Exception as exc:
                        run["errors"].append(
                            {"regime": regime, "replicate": rep, "method": method, "error": repr(exc)}
                        )
                lp = results.get("paired_lp")
                for record in records:
                    record["agrees_with_lp"] = (
                        None
                        if record["method"] == "paired_lp" or lp is None
                        else agrees(results[record["method"]], lp, protocol["agreement_tolerance"])
                    )
                run["records"].extend(records)
                atomic_json(output / "run.partial.json", run)
        run["peak_sampled_tree_rss_bytes"] = memory.peak
    summaries = []
    for regime in protocol["regimes"]:
        times = {
            method: median(
                r["seconds"] for r in run["records"] if r["regime"] == regime and r["method"] == method
            )
            for method in protocol["methods"]
            if any(r["regime"] == regime and r["method"] == method for r in run["records"])
        }
        summaries.append(
            {
                "regime": regime,
                "median_seconds": times,
                "terminal_below_graph": times.get("terminal", float("inf")) < times.get("graph", 0),
            }
        )
    agreement = (
        not run["errors"]
        and all(r["agrees_with_lp"] is not False for r in run["records"])
        and len(run["records"])
        == len(protocol["regimes"]) * protocol["replicates"] * len(protocol["methods"])
    )
    run["summary"] = {
        "regimes": summaries,
        "all_agree": agreement,
        "go_criterion_met": agreement and sum(s["terminal_below_graph"] for s in summaries) >= 2,
        "method_novelty": "unestablished; classical reductions, focused prior-art review still required",
        "Gate_B": "pending independent annotation and external evaluation",
    }
    atomic_json(output / "run.json", run)
    atomic_json(output / "summary.json", run["summary"])
    return run["summary"]
