"""Partition-wide archive experiment using the existing precision oracle unchanged."""

import copy
import hashlib
import json
import shutil
import time
import zipfile
from collections import OrderedDict
from fractions import Fraction as F
from pathlib import Path
from random import Random
from statistics import median

from .action_domain import AcquisitionAction as Action
from .domain import Case, Interpretation, IntervalObservation, SemanticHypothesis, digest
from .oracle import solve_lp
from .paired_oracle import evaluate_paired_lp
from .precision_checker import verify_precision_profiles
from .precision_experiment import _agrees
from .precision_frontier import build_precision_profiles, precision_values
from .readers import scale_case
from .resources import MemoryGuard, atomic_json, run_metadata, safe_data_path, sha256_file, size_bytes
from .semantics import normalized
from .services import solve_query


def coarsen(native, hours, nh, eps="1/20"):
    """Controlled loss of resolution; no missing amount is reconstructed."""
    if hours not in (12, 24) or nh not in (2, 3):
        raise ValueError("frozen archive regimes require 12/24 hours and 2/3 hypotheses")
    start = native.query.start
    source = [o for o in native.observations if start < o.interval.end <= start+hours*3600]
    if len(source) != hours or any(o.series != native.query.series for o in source):
        raise ValueError("need one documented hourly series within one cycle")
    source.sort(key=lambda o: o.interval.end)
    if any(o.interval.end != start+(i+1)*3600 for i, o in enumerate(source)):
        raise ValueError("noncontiguous source window")
    obs, derivation = [], []
    for j in range(0, hours, 4):
        block = source[j:j+4]
        if block[-1].interval.statistic == "cumulative":
            item = block[-1].model_copy(deep=True)
            item.id = f"coarse-{j}"
            inputs = [block[-1].id]
        else:
            valid = all(o.qc == "accepted" for o in block)
            bounds = [normalized(o.interval, o.lower, o.upper)[2:] for o in block] if valid else []
            lo, hi = (sum((b[k] for b in bounds), F(0)) for k in (0, 1))
            item = IntervalObservation(id=f"coarse-{j}", series=native.query.series,
                lower=str(lo), upper=str(hi), qc="accepted" if valid else "missing",
                interval=Interpretation(start=start+j*3600, end=start+(j+4)*3600),
                evidence_ids=sorted({e for o in block for e in o.evidence_ids}))
            inputs = [o.id for o in block]
        obs.append(item)
        derivation.append({"output": item.id, "inputs": inputs, "qc": item.qc})
    anchor = obs[1]
    shifts = [0, 1] if nh == 2 else [0, 1, -1]
    hs = [SemanticHypothesis(id=f"shift-{shift}", assignments={"controlled_shift_hours": str(shift)},
          intervals={} if not shift else {anchor.id: anchor.interval.model_copy(update={
              "start": anchor.interval.start+shift*3600, "end": anchor.interval.end+shift*3600})})
          for shift in shifts]
    case = native.model_copy(deep=True)
    case.id += f"-controlled-{hours}h-h{nh}"
    case.observations, case.hypotheses, case.origin = obs, hs, "controlled"
    case.query = native.query.model_copy(update={"end": start+(hours//2-1)*3600, "eps": eps})
    case.h_complete = True
    case.completeness_basis = "exactly the declared controlled shifts; not completeness of natural archive metadata"
    case.assumptions.append("controlled coarsening and finite shifts; hypothetical bounded-error acquisitions")
    qend = case.query.end
    spans = [(start, qend), (qend, start+hours*3600),
             (start+((hours//2-1)//4)*4*3600, qend), (start, start+8*3600)]
    actions = [Action(id=f"measure-{i}", start=a, end=b, cost=str(1+(b-a)//14400))
               for i, (a, b) in enumerate(spans)]
    return case, actions, source, derivation


def query_check(case, tolerance):
    bundle, lp = solve_query(case, solver="graph"), solve_lp(case)
    feasible = [v for v in lp.values() if v["feasible"]]
    bounds = {"lower": min((v["lower"] for v in feasible), default=None),
              "upper": None if any(v["upper"] is None for v in feasible) else
              max((v["upper"] for v in feasible), default=None)}
    if not bundle["checker"]["valid"] or bool(feasible) != (bundle["result"]["status"] != "inconsistent_model"):
        raise ValueError("native/refined Query feasibility mismatch")
    for key, expected in bounds.items():
        actual = bundle["result"][key]
        if (actual is None) != (expected is None) or (actual is not None and abs(float(F(actual))-expected)>tolerance):
            raise ValueError("native/refined Query bounds disagree with independent LP")
    return bundle, lp


def refinements(case, source, fractions, tolerance):
    records, previous = [], None
    for fraction in fractions:
        count = int(len(source)*fraction)
        refined = case.model_copy(deep=True)
        refined.observations.extend(o.model_copy(deep=True) for o in source[:count])
        bundle, lp = query_check(refined, tolerance)
        lo, hi = bundle["result"]["lower"], bundle["result"]["upper"]
        if previous is not None:
            pl, pu = previous
            if ((pl is not None and (lo is None or F(lo)<F(pl)))
                    or (pu is not None and (hi is None or F(hi)>F(pu)))):
                raise ValueError("nested informative observations widened Query bounds")
        previous = lo, hi
        records.append({"native_records_added": count, "fraction": fraction,
                        "case": refined.model_dump(), "bundle": bundle, "lp": lp})
    return records


def _hash_data(path, guard):
    started, total, h = time.perf_counter(), 0, hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(8*2**20):
            h.update(block)
            total += len(block)
            guard.check()
    return h.hexdigest(), total, time.perf_counter()-started


def _save_bundle(path, content):
    partial = path.with_suffix(".partial")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in content.items():
            archive.writestr(name+".json", json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf8"))
    partial.replace(path)


def run_archive_precision(manifest, protocol, output, resume=False, dry_run=False, stop_after_shards=None):
    mp, pp, out = Path(manifest), Path(protocol), Path(output)
    m, p = (json.loads(path.read_text(encoding="utf8")) for path in (mp, pp))
    if m.get("schema") != "meteobridge-synthetic-v1" or m.get("status") != "complete":
        raise ValueError("this frozen study supports completed legacy-v1 manifests only")
    if m["data_bytes"] < p["minimum_archive_bytes"]:
        raise ValueError("insufficient prepared archive bytes for this protocol")
    budget = size_bytes(p["report_disk_budget"])
    plan = {"manifest_sha256": sha256_file(mp), "protocol_sha256": sha256_file(pp),
            "data_bytes": m["data_bytes"], "shards": len(m["shards"]),
            "report_disk_budget": budget, "free_disk_bytes": shutil.disk_usage(out.parent if out.parent.exists() else ".").free,
            "memory_limit": min(size_bytes(p["memory_limit"]),16*2**30), "workers": 1}
    if dry_run:
        return {**plan, "status": "dry_run", "disk_feasible": plan["free_disk_bytes"]>=budget}
    if plan["free_disk_bytes"] < budget:
        raise OSError("insufficient disk reserve for bounded reports")
    out.mkdir(parents=True, exist_ok=True)
    state = out / "run.json"
    if state.exists():
        if not resume:
            raise FileExistsError("preserve existing run; use --resume or a fresh output")
        run = json.loads(state.read_text(encoding="utf8"))
        if any(run["plan"][k] != plan[k] for k in ("manifest_sha256", "protocol_sha256")):
            raise ValueError("changed archive/protocol; use a new run")
        current = run_metadata()
        if any(current[k] != run["metadata"][k] for k in ("code_sha256", "uv_lock_sha256")):
            raise ValueError("changed experiment source/dependencies; use a new run")
    else:
        run = {"plan": plan, "protocol": p, "metadata": run_metadata(), "records": [], "errors": [], "invocations": []}
        atomic_json(out / "protocol-frozen.json", run)
    invocation = {"resume": resume, "started_unix": time.time(), "hashed_bytes": 0, "hash_seconds": 0., "new_shards": 0}
    run["invocations"].append(invocation)
    run["status"] = "running"
    atomic_json(state, run)
    started, cache = time.perf_counter(), OrderedDict()
    completed = {r["index"]: r for r in run["records"]}
    try:
        with MemoryGuard(plan["memory_limit"]) as guard:
            for index, shard in enumerate(m["shards"]):
                path = safe_data_path(mp.parent, shard["path"])
                actual, total, seconds = _hash_data(path, guard)
                invocation["hashed_bytes"] += total
                invocation["hash_seconds"] += seconds
                if actual != shard["sha256"] or total != shard["bytes"]:
                    raise ValueError(f"changed archive shard: {path.name}")
                if index in completed:
                    record = completed[index]
                    if sha256_file(out / record["bundle"]) != record["sha256"]:
                        raise ValueError("changed completed experiment bundle")
                    continue
                rng = Random(p["seed"]+index)
                series = rng.randrange(shard["series_start"], shard["series_end"])
                hours, nh = p["window_hours"][index%2], p["hypotheses"][index%2]
                native, logical = scale_case(mp, series, shard["first_hour"], hours)
                native.query.end = native.query.start+(hours//2-1)*3600
                native_bundle, native_lp = query_check(native, p["agreement_tolerance"])
                case, actions, source, derivation = coarsen(native, hours, nh, p["query_eps_mm"])
                inputs = {"case": case.model_dump(), "actions": [a.model_dump() for a in actions]}
                refs = [evaluate_paired_lp(case, actions, error_radius=r) for r in p["radii"]]
                content = {"input": inputs, "native": {"case": native.model_dump(), "bundle": native_bundle, "lp": native_lp},
                           "lp-grid": {"radii": p["radii"], "results": refs},
                           "refinements": refinements(case, source, p["refinement_fractions"], p["agreement_tolerance"])}
                record = {"index": index, "source_file": shard["path"], "source_sha256": actual,
                          "bytes": total, "series": series, "first_hour": shard["first_hour"],
                          "hours": hours, "H": nh, "source_logical_bytes": logical,
                          "input_hash": digest(inputs), "methods": {}, "derivation": derivation,
                          "native_lower": native_bundle["result"]["lower"], "native_upper": native_bundle["result"]["upper"],
                          "refinement_bounds": [{"added": r["native_records_added"],
                              "lower": r["bundle"]["result"]["lower"], "upper": r["bundle"]["result"]["upper"]}
                              for r in content["refinements"]],
                          "lp_calls": sum(r["metrics"]["lp_calls"] for r in refs)}
                methods = list(p["methods"])
                rng.shuffle(methods)
                reference_result = None
                for method in methods:
                    tick = time.perf_counter()
                    bundle = build_precision_profiles(case, actions, method)
                    elapsed = time.perf_counter()-tick
                    values = precision_values(case, actions, bundle, p["radii"])
                    if not _agrees(values, refs, p["agreement_tolerance"]):
                        raise ValueError(f"profile LP mismatch: {method}")
                    result = {k:v for k,v in bundle["result"].items() if k != "certificate_id"}
                    if reference_result is not None and reference_result != result:
                        raise ValueError("method frontier mismatch")
                    reference_result = result
                    content[method] = bundle
                    record["methods"][method] = {"seconds": elapsed, "checker_valid": bundle["checker"]["valid"],
                                                 "lp_agreement": True, "metrics": bundle["metrics"]}
                    guard.check()
                key = digest(inputs)
                cache[key] = content["compiled"]
                if len(cache)>4:
                    cache.popitem(last=False)
                tick = time.perf_counter()
                cached = copy.deepcopy(cache[digest(inputs)])
                checked = verify_precision_profiles(case, actions, cached["result"], cached["certificate"])
                record["methods"]["cache_warm"] = {"seconds": time.perf_counter()-tick, "checker_valid": checked["valid"]}
                if not checked["valid"]:
                    raise ValueError("cached certificate invalid")
                dest = out / f"part-{index:06d}.zip"
                _save_bundle(dest, content)
                record.update(bundle=dest.name, sha256=sha256_file(dest), bundle_bytes=dest.stat().st_size)
                run["records"].append(record)
                invocation["new_shards"] += 1
                if sum(r["bundle_bytes"] for r in run["records"])>budget:
                    raise OSError("report disk budget exceeded")
                guard.check()
                atomic_json(state, run)
                print(json.dumps({"shard": index+1, "of": len(m["shards"]), "verified_bytes": sum(r["bytes"] for r in run["records"]),
                                  "compiled_s": record["methods"]["compiled"]["seconds"],
                                  "terminal_s": record["methods"]["terminal"]["seconds"]}), flush=True)
                if stop_after_shards and invocation["new_shards"]>=stop_after_shards:
                    break
            invocation["peak_process_tree_rss"] = guard.peak
        run["status"] = "complete" if len(run["records"]) == len(m["shards"]) else "interrupted"
    except Exception as exc:
        run["status"] = "failed"
        run["errors"].append({"error": repr(exc), "after_completed_shards": len(run["records"])})
        raise
    finally:
        invocation["wall_seconds"] = time.perf_counter()-started
        atomic_json(state, run)
    run["summary"] = {"partitions": len(run["records"]), "data_bytes_verified": sum(r["bytes"] for r in run["records"]),
                      "profile_bundles": len(run["records"])*len(p["methods"]),
                      "action_radius_comparisons_per_method": len(run["records"])*4*len(p["radii"]),
                      "lp_calls": sum(r["lp_calls"] for r in run["records"]),
                      "median_seconds": {method: median(r["methods"][method]["seconds"] for r in run["records"])
                                         for method in p["methods"]+["cache_warm"]} if run["records"] else {},
                      "scope": p["scope"], "Gate_B": "pending", "priority": "unestablished"}
    atomic_json(state, run)
    return {"status": run["status"], **run["summary"]}


def replay_archive_precision(run_path, output):
    path = Path(run_path)
    run = json.loads(path.read_text(encoding="utf8"))
    checked, refinements_checked = 0, 0
    for record in run["records"]:
        bundle_path = (path.parent / record["bundle"]).resolve()
        if not bundle_path.is_relative_to(path.parent.resolve()) or sha256_file(bundle_path) != record["sha256"]:
            raise ValueError("changed/unsafe archive experiment bundle")
        with zipfile.ZipFile(bundle_path) as archive:
            def read(name):
                return json.loads(archive.read(name+".json"))
            data = read("input")
            if digest(data) != record["input_hash"]:
                raise ValueError("changed profile input")
            case = Case.model_validate(data["case"])
            actions = [Action.model_validate(a) for a in data["actions"]]
            for method in run["protocol"]["methods"]:
                bundle = read(method)
                if not verify_precision_profiles(case, actions, bundle["result"], bundle["certificate"])["valid"]:
                    raise ValueError("profile replay failed")
                checked += 1
            from .certificates import verify_certificate
            for data in [read("native"), *read("refinements")]:
                if not verify_certificate(Case.model_validate(data["case"]), data["bundle"]["result"],
                                          data["bundle"]["certificate"])["valid"]:
                    raise ValueError("Query replay failed")
                refinements_checked += 1
    result = {"run_sha256": sha256_file(path), "profile_bundles_checked": checked,
              "query_certificates_checked": refinements_checked,
              "passed": run["status"] == "complete" and not run["errors"],
              "note": "independent certificate replay; no LP or shortest-path solver called, no archive IO"}
    atomic_json(output, result)
    return result
