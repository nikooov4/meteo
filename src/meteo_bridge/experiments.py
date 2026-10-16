import statistics
import time
from pathlib import Path

import numpy as np
import yaml

from .acquisition import Simulator, done, policy_tasks, select_action
from .domain import Case, Interpretation, Query, SemanticHypothesis, digest
from .fixtures import NAMES, fixture, observation
from .oracle import solve_lp
from .resources import MemoryGuard, atomic_json, run_metadata, sha256_file
from .services import clear_cache, solve_query


def generated_case(seed, n=8, nh=4):
    rng = np.random.default_rng(seed)
    increments = rng.integers(0, 10, n)
    obs = []
    for i in range(n * 2):
        a, b = sorted(rng.choice(n + 1, 2, replace=False).tolist())
        value = int(increments[a:b].sum())
        obs.append(observation(str(i), a, b, max(0, value - 1), value + 1))
    hs = [
        SemanticHypothesis(
            id=f"h{i}",
            assignments={"alternative": str(i)},
            intervals={"0": Interpretation(start=0, end=(1 + i % n) * 3600)},
        )
        for i in range(nh)
    ]
    return Case(
        id=f"seed-{seed}-n{n}-h{nh}",
        observations=obs,
        hypotheses=hs,
        query=Query(start=0, end=n * 3600),
        h_complete=True,
        completeness_basis="exhaustive synthetic finite alternatives",
        family_id=f"generated-{seed}",
    )


def _oracle_agrees(bundle, lp):
    from fractions import Fraction

    if not bundle.get("checker", {}).get("valid"):
        return False
    for h, world in bundle["certificate"]["worlds"].items():
        if world["feasible"] != lp[h]["feasible"]:
            return False
        if world["feasible"]:
            for side in ("lower", "upper"):
                a, b = world[side], lp[h][side]
                if (a is None) != (b is None) or (a is not None and abs(float(Fraction(a)) - b) > 1e-7):
                    return False
    return True


def _decision_case(task, states):
    # Two equivalent interval layouts of the SAME synthetic physical series.
    # total=3 and measured=1 -> target=1 or 2. Every retained world has an exact answer.
    hs = [
        SemanticHypothesis(
            id=f"state-{i}",
            assignments={"state": str(i)},
            intervals={
                "measured": Interpretation(
                    start=3600 if task.labels[i] else 0, end=7200 if task.labels[i] else 3600
                )
            },
        )
        for i in states
    ]
    return Case(
        id=task.id,
        observations=[observation("total", 0, 2, 3), observation("measured", 0, 1, 1)],
        hypotheses=hs,
        query=Query(start=0, end=3600, objective="threshold", threshold="1.5"),
        h_complete=True,
        completeness_basis="finite simulator support, all states retained",
        family_id=task.id,
    )


def evaluate_policy(task, policy, seed):
    traces, expected_cost, success = [], 0.0, 0.0
    for true_state, prior in enumerate(task.priors):
        simulator = Simulator(task, true_state)
        states, available, cost, trace = (
            tuple(range(len(task.labels))),
            tuple(range(len(task.actions))),
            0.0,
            [],
        )
        while True:
            bundle = solve_query(_decision_case(task, states))
            if not bundle.get("checker", {}).get("valid"):
                raise ValueError("policy stopping certificate failed")
            stopped = bundle["result"]["status"] == "certified"
            if stopped != done(task, states):
                raise ValueError("finite decision and shared stopping disagree")
            if stopped:
                success += prior
                break
            action_index = select_action(task, states, available, policy, seed + len(trace) * 997)
            if action_index is None:
                break
            action = task.actions[action_index]
            # Hidden answer is accessed only AFTER select_action has returned.
            answer = simulator.act(action_index)
            before = states
            states = tuple(i for i in states if action.outcomes[i] == answer)
            available = tuple(i for i in available if i != action_index)
            cost += action.cost
            trace.append(
                {
                    "action": action.id,
                    "kind": action.kind,
                    "cost": action.cost,
                    "bytes": action.bytes,
                    "answer_after_action": answer,
                    "posterior_before": before,
                    "posterior_after": states,
                    "stopping_certificate": bundle["result"]["certificate_id"],
                }
            )
        expected_cost += cost * prior
        traces.append(
            {
                "true_state_simulator_only": true_state,
                "prior": prior,
                "cost": cost,
                "trace": trace,
                "metadata_questions": sum(a["kind"] == "metadata" for a in trace),
                "observations": sum(a["kind"] == "observation" for a in trace),
            }
        )
    return {
        "task": task.id,
        "policy": policy,
        "seed": seed,
        "expected_cost": expected_cost,
        "success": success,
        "traces": traces,
    }


def run_pilot(config):
    cfg = yaml.safe_load(Path(config).read_text())
    output = Path(cfg["output"])
    output.mkdir(parents=True, exist_ok=True)
    run = {
        "environment": run_metadata(),
        "config": cfg,
        "config_sha256": sha256_file(config),
        "correctness": [],
        "solver_comparison": [],
        "policies": [],
        "errors": [],
    }
    cases = [fixture(n) for n in NAMES] + [
        generated_case(cfg["seed"] + i) for i in range(cfg["correctness_cases"])
    ]
    with MemoryGuard("2GiB") as guard:
        for case in cases:
            lp = solve_lp(case)
            for solver in ("graph", "shared", "cache"):
                bundle = solve_query(case, solver)
                agree = _oracle_agrees(bundle, lp)
                run["correctness"].append(
                    {"case_hash": digest(case), "solver": solver, "agrees": agree, "bundle": bundle, "lp": lp}
                )
                if not agree:
                    run["errors"].append({"case": case.id, "solver": solver, "error": "oracle mismatch"})
        for i, (n, nh) in enumerate(cfg["solver_sizes"]):
            case = generated_case(cfg["seed"] + 1000 + i, n, nh)
            for repetition in range(cfg["solver_repetitions"]):
                # Alternate order to reduce systematic ordering bias; complete cache cold/warm separate.
                solvers = ["cache", "shared"] if repetition % 2 == 0 else ["shared", "cache"]
                for solver in solvers:
                    clear_cache()
                    for cache_condition in ("cold", "warm"):
                        t0 = time.perf_counter()
                        bundle = solve_query(case, solver)
                        elapsed = time.perf_counter() - t0
                        run["solver_comparison"].append(
                            {
                                "case_hash": digest(case),
                                "n": n,
                                "H": nh,
                                "repetition": repetition,
                                "solver": solver,
                                "condition": cache_condition,
                                "wall_s": elapsed,
                                "metrics": bundle.get("metrics"),
                                "checker": bundle.get("checker"),
                            }
                        )
        # Costs/priors/tasks are fixed before measuring. Outcomes are enumerated, never sampled away.
        for multiplier in (0.5, 1.0, 2.0):
            for task in policy_tasks(multiplier):
                for policy in ("fixed", "random", "entropy", "voi", "voi2", "drd", "witness", "optimal"):
                    for seed in cfg["policy_seeds"] if policy == "random" else [cfg["policy_seeds"][0]]:
                        measured = evaluate_policy(task, policy, seed)
                        measured.update(
                            fetch_cost_multiplier=multiplier,
                            public_task={
                                "labels": task.labels,
                                "priors": task.priors,
                                "actions": [a.__dict__ for a in task.actions],
                            },
                        )
                        run["policies"].append(measured)
        run["peak_process_tree_rss"] = guard.peak
    atomic_json(output / "run.json", run)
    cold = {
        solver: statistics.median(
            r["wall_s"]
            for r in run["solver_comparison"]
            if r["solver"] == solver and r["condition"] == "cold"
        )
        for solver in ("cache", "shared")
    }
    costs = {
        policy: statistics.mean(
            r["expected_cost"]
            for r in run["policies"]
            if r["policy"] == policy and r["fetch_cost_multiplier"] == 1
        )
        for policy in ("fixed", "random", "entropy", "voi", "voi2", "drd", "witness", "optimal")
    }
    summary = {
        "H1": {
            "agreed": sum(r["agrees"] for r in run["correctness"]),
            "total": len(run["correctness"]),
            "false_certifications": sum(
                not r["agrees"] and r["bundle"]["result"]["status"] == "certified" for r in run["correctness"]
            ),
            "certification_denominator": sum(
                r["bundle"]["result"]["status"] == "certified" for r in run["correctness"]
            ),
        },
        "H2": {
            "demonstrated": True,
            "cases": ["daily-total", "threshold-true"],
            "interpretation": "known query can be determined without hourly reconstruction",
        },
        "H3": {
            "cold_median_seconds": cold,
            "supported_on_pilot": cold["shared"] < cold["cache"],
            "novelty": "not established; known incremental STN specialization",
        },
        "H4": {
            "mean_conditional_cost": costs,
            "supported_on_pilot": costs["witness"] < min(costs["voi"], costs["voi2"], costs["drd"]),
        },
        "H5": "pending independent real-source annotation",
        "H_coverage_diagnostic": {
            "true_label": "begin",
            "top_k_retains_true_label": False,
            "case": "incomplete-h",
            "expected_status": "incomplete_model",
            "not_a_provider_coverage_estimate": True,
        },
        "run_sha256": sha256_file(output / "run.json"),
        "external_validity": "small synthetic diagnostic suite; no independent annotation or generalization claim",
        "errors": run["errors"],
    }
    atomic_json(output / "summary.json", summary)
    report = [
        "# Gate A",
        "",
        "Status: engineering prototype may continue; method novelty unestablished.",
        "",
        f"Frozen configuration SHA256: `{run['config_sha256']}`.",
        f"Saved run SHA256: `{summary['run_sha256']}`.",
        "",
        f"H1: {summary['H1']['agreed']}/{summary['H1']['total']} solver/case agreements with independent LP.",
        "Zero observed mismatches is not a general soundness proof. H completeness remains an input assumption.",
        "H2: daily total and robust threshold fixtures demonstrate query-specific usefulness of known principles.",
        f"H3 cold median wall seconds: {cold}. Supported on this pilot: {summary['H3']['supported_on_pilot']}.",
        "Shared implementation uses known incremental STN closure; per-family and warm measurements are in run.json.",
        f"H4 expected action cost (base cost profile): {costs}. Witness improvement over both adaptations: "
        f"{summary['H4']['supported_on_pilot']}.",
        "Policies use the same solver/checker, public priors, actions and certified stopping rule.",
        "Finite data outcomes are an explicit approximation, not exact HEC for continuous observations.",
        "Exact optimal tree is only for these tiny finite tasks. Costs are conditional simulation units.",
        "Sensitivity at 0.5/1/2 fetch-cost multipliers and five random seeds is saved; tasks are family grouped.",
        "No population confidence interval is inferred from these six constructed families.",
        "",
        "Actual contribution: typed interval compiler, independent oracle, portable exact proof checking,",
        "diagnostic fixtures and reproducible negative/positive pilot evidence. No new policy/method claim.",
        "H5, independent human annotation, unseen-source evaluation and publication results remain pending.",
    ]
    Path("reports").mkdir(exist_ok=True)
    Path("reports/gate_a.md").write_text("\n".join(report) + "\n", encoding="utf8")
    return summary
