"""Shared application service for CLI, SDK, UI, API and scale Query batches."""

import copy
import json
import time
from collections import OrderedDict
from fractions import Fraction as F
from pathlib import Path

import yaml

from .budget import begin, end
from .certificates import verify_certificate
from .domain import Case, digest
from .graph import solve_world
from .semantics import compile_case
from .shared import solve_shared

_CACHE = OrderedDict()


def load_dataset(path) -> Case:
    if Path(path).suffix.lower() in {".csv", ".nc"}:
        from .imports import import_file

        return import_file(path)
    raw = Path(path).read_text(encoding="utf-8-sig")
    return Case.model_validate(yaml.safe_load(raw))


def _summary(case, worlds):
    feasible = [(h, w) for h, w in worlds.items() if w["feasible"]]
    lo = (
        None
        if not feasible or any(w["lower"] is None for _, w in feasible)
        else min(F(w["lower"]) for _, w in feasible)
    )
    hi = (
        None
        if not feasible or any(w["upper"] is None for _, w in feasible)
        else max(F(w["upper"]) for _, w in feasible)
    )
    result = {
        "case_id": case.id,
        "revision": case.revision,
        "case_hash": digest(case),
        "unit": "mm",
        "lower": str(lo) if lo is not None else None,
        "upper": str(hi) if hi is not None else None,
        "bound_kind": {
            "lower": "finite" if lo is not None else "unbounded" if feasible else "empty",
            "upper": "finite" if hi is not None else "unbounded" if feasible else "empty",
        },
        "point_estimate": None,
        "decision": None,
        "reason_flags": [],
        "witnesses": [],
        "suggested_actions": [],
        "scope": [h.id for h in case.hypotheses],
        "completeness_basis": case.completeness_basis,
        "assumptions": case.assumptions,
        "h_complete": case.h_complete,
        "status": "bounded",
    }
    if not feasible:
        result["status"] = "inconsistent_model"
        result["reason_flags"] = ["conflict"]
    else:
        temporal = any(w["lower"] != w["upper"] or w["lower"] is None for _, w in feasible)
        metadata = len({(w["lower"], w["upper"]) for _, w in feasible}) > 1
        if temporal:
            result["reason_flags"].append("temporal_underdetermination")
            result["suggested_actions"].append(
                {
                    "kind": "request_observation",
                    "series": case.query.series.model_dump(),
                    "start": case.query.start,
                    "end": case.query.end,
                    "available": False,
                    "reason": "requires new interval evidence",
                }
            )
        if metadata:
            result["reason_flags"].append("metadata_ambiguity")
            attributes = sorted({a for h in case.hypotheses for a in h.assignments})
            result["suggested_actions"].extend(
                {
                    "kind": "clarify_metadata",
                    "attribute": a,
                    "options": sorted({h.assignments.get(a, "unknown") for h in case.hypotheses}),
                }
                for a in attributes
            )
        if lo is None or hi is None:
            result["reason_flags"].append("missing_bounds")
        determined = False
        if case.query.objective == "threshold":
            tau = F(case.query.threshold)
            result["decision"] = (
                True if lo is not None and lo >= tau else (False if hi is not None and hi < tau else None)
            )
            determined = result["decision"] is not None
        elif lo is not None and hi is not None and hi - lo <= 2 * F(case.query.eps):
            result["point_estimate"], determined = str((lo + hi) / 2), True
        result["status"] = (
            "certified"
            if determined
            else ("needs_evidence" if metadata else "insufficient_data" if temporal else "bounded")
        )
        if determined:
            result["suggested_actions"] = []
        if lo != hi or lo is None:
            low_h, low_w = min(
                feasible, key=lambda hw: F(hw[1]["lower"]) if hw[1]["lower"] else -float("inf")
            )
            high_h, high_w = max(
                feasible, key=lambda hw: F(hw[1]["upper"]) if hw[1]["upper"] else float("inf")
            )
            for hid, world, side in ((low_h, low_w, "lower"), (high_h, high_w, "upper")):
                point = world.get(side + "_point", world["point"])
                point = {t: F(v) for t, v in point.items()}
                if side + "_ray" in world:
                    ray = world[side + "_ray"]
                    step = (
                        abs(lo or F(0))
                        + abs(hi or F(0))
                        + F(case.query.eps) * 4
                        + 1
                        + (abs(F(case.query.threshold)) if case.query.threshold is not None else 0)
                    )
                    point = {t: v + step * F(ray[t]) for t, v in point.items()}
                result["witnesses"].append(
                    {
                        "hypothesis": hid,
                        "potentials": {t: str(v) for t, v in point.items()},
                        "q": str(point[str(case.query.end)] - point[str(case.query.start)]),
                    }
                )
    if not case.h_complete:
        result.update(status="incomplete_model", decision=None, point_estimate=None)
    return result


def solve_query(case: Case, solver="graph", *, max_worlds=256, timeout=30.0):
    started = time.perf_counter()
    token, execution = begin(timeout)
    try:
        times, compiled = compile_case(case)
        if len(compiled) > max_worlds:
            return {
                "case": case.model_dump(),
                "result": {"status": "incomplete_model", "error": "world budget"},
            }
        stats, worlds = {"solver_calls": 0, "cache_hits": 0}, {}
        if solver == "shared":
            worlds, shared_stats = solve_shared(times, compiled, case.query.start, case.query.end)
            stats.update(shared_stats)
            stats["solver_calls"] = len(compiled)
        else:
            if solver not in {"graph", "cache", "lp"}:
                raise ValueError("unknown solver")
            for h, edges in compiled.items():
                key = digest([times, [[e.u, e.v, str(e.w)] for e in edges], case.query.start, case.query.end])
                if solver == "cache" and key in _CACHE:
                    worlds[h] = copy.deepcopy(_CACHE[key])
                    _CACHE.move_to_end(key)
                    stats["cache_hits"] += 1
                else:
                    worlds[h] = solve_world(times, edges, case.query.start, case.query.end)
                    stats["solver_calls"] += 1
                    if solver == "cache":
                        _CACHE[key] = copy.deepcopy(worlds[h])
                        while len(_CACHE) > 64:
                            _CACHE.popitem(last=False)
                if time.perf_counter() - started > timeout:
                    return {
                        "case": case.model_dump(),
                        "result": {"status": "incomplete_model", "error": "timeout"},
                    }
        if time.perf_counter() - started > timeout:
            return {"case": case.model_dump(), "result": {"status": "incomplete_model", "error": "timeout"}}
        if solver == "lp":
            from .oracle import solve_lp

            lp = solve_lp(case)
            for hid, w in worlds.items():
                if w["feasible"] != lp[hid]["feasible"]:
                    raise RuntimeError("LP/graph feasibility mismatch")
                if w["feasible"]:
                    for side in ("lower", "upper"):
                        a, b = w[side], lp[hid][side]
                        if (a is None) != (b is None) or (a is not None and abs(float(F(a)) - b) > 1e-7):
                            raise RuntimeError("LP/graph bound mismatch")
        result = _summary(case, worlds)
        certificate = {
            "version": "1",
            "case_hash": digest(case),
            "query_hash": digest(case.query),
            "unit": "mm",
            "scope": [h.id for h in case.hypotheses],
            "h_complete": case.h_complete,
            "revision": case.revision,
            "assumptions": case.assumptions,
            "numerical_policy": "exact-rational-v1",
            "worlds": worlds,
            "normalized_constraints": {
                hid: [edge.json() for edge in edges] for hid, edges in compiled.items()
            },
            "observation_hashes": {o.id: digest(o) for o in case.observations},
        }
        result["certificate_id"] = digest(certificate)
        verdict = verify_certificate(case, result, certificate)
        if not verdict["valid"]:
            raise RuntimeError(f"certificate rejected: {verdict}")
        return {
            "case": case.model_dump(),
            "result": result,
            "certificate": certificate,
            "checker": verdict,
            "metrics": {
                **stats,
                **execution["counts"],
                "world_evaluations": len(worlds),
                "latency_s": time.perf_counter() - started,
            },
        }
    except TimeoutError as exc:
        return {"case": case.model_dump(), "result": {"status": "incomplete_model", "error": str(exc)}}
    except (NotImplementedError, ValueError) as exc:
        return {"case": case.model_dump(), "result": {"status": "unsupported", "error": str(exc)}}
    except Exception as exc:
        return {"case": case.model_dump(), "result": {"status": "execution_failed", "error": str(exc)}}
    finally:
        end(token)


def apply_evidence(case: Case, evidence: dict) -> Case:
    raw = case.model_dump()
    if evidence.get("kind") == "clarify_metadata":
        attr, value = evidence["attribute"], evidence["value"]
        # A hypothesis with no assignment is an unknown branch and must be retained.
        raw["hypotheses"] = [h for h in raw["hypotheses"] if h["assignments"].get(attr, value) == value]
        if not raw["hypotheses"]:
            raise ValueError("evidence excludes every declared hypothesis; revise the model")
    elif evidence.get("kind") == "add_observation":
        raw["observations"].append(evidence["observation"])
    else:
        raise ValueError("unsupported evidence kind")
    raw["revision"] += 1
    raw["evidence"].append(evidence)
    return Case.model_validate(raw)


def export_bundle(bundle, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for key in ("case", "result", "certificate"):
        if key in bundle:
            (output / f"{key}.json").write_text(
                json.dumps(bundle[key], ensure_ascii=False, indent=2), encoding="utf8"
            )
    (output / "report.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf8")


def clear_cache():
    _CACHE.clear()


def suggest_action(bundle):
    return bundle["result"].get("suggested_actions", [])
