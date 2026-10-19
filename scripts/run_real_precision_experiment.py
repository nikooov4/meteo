"""Evaluate the unchanged precision method on real ERA5 values with controlled coarsening."""

import argparse
import json
import time
from datetime import datetime, timezone
from fractions import Fraction as F
from pathlib import Path
from random import Random

import netCDF4 as nc
import numpy as np

from meteo_bridge.archive_precision import (
    _save_bundle,
    coarsen,
    query_check,
    refinements,
    replay_archive_precision,
)
from meteo_bridge.domain import (
    Case,
    Interpretation,
    IntervalObservation,
    Query,
    SemanticHypothesis,
    SeriesKey,
    digest,
)
from meteo_bridge.paired_oracle import evaluate_paired_lp
from meteo_bridge.precision_experiment import _agrees
from meteo_bridge.precision_frontier import build_precision_profiles, precision_values
from meteo_bridge.realistic_weather import _check_source
from meteo_bridge.resources import MemoryGuard, atomic_json, run_metadata, sha256_file


def real_point_case(values_m, start, latitude, longitude, source):
    key = SeriesKey(quantity="large_scale_precipitation", location=f"ERA5:{latitude},{longitude}",
                    spatial_support="native 0.25 degree grid point", product="NCAR-ERA5-HRES-LSP",
                    member="HRES", cycle=str(start))
    obs = []
    for h, value in enumerate(values_m):
        accepted = np.isfinite(value) and value >= 0
        text = str(F(float(value))*1000) if accepted else "0"
        obs.append(IntervalObservation(id=f"native-hour-{h}", series=key, lower=text, upper=text,
            original_value=str(float(value)), qc="accepted" if accepted else "rejected",
            interval=Interpretation(start=start+h*3600, end=start+(h+1)*3600), evidence_ids=[source["sha256"]]))
    return Case(id=f"era5-{start}-{latitude}-{longitude}", observations=obs,
                hypotheses=[SemanticHypothesis(id="documented")],
                query=Query(series=key, start=start, end=start+5*3600), origin="original", h_complete=True,
                completeness_basis="documented NCAR ERA5 HRES previous-hour LSP amounts; exact encoded float m to mm",
                family_id=f"NCAR-ERA5-LSP-2023-{datetime.fromtimestamp(start,timezone.utc).month:02d}",
                assumptions=["nonnegative precipitation increments", "encoded amounts, not physical sensor accuracy",
                             "native float metres converted exactly to rational mm; no deaccumulation"])


def run(calibration, protocol, output):
    out = Path(output)
    if (out / "protocol-frozen.json").exists():
        raise FileExistsError("preserve prior real study; choose a fresh output")
    out.mkdir(parents=True, exist_ok=True)
    cp, pp = Path(calibration), Path(protocol)
    m, p = (json.loads(path.read_text(encoding="utf8")) for path in (cp, pp))
    study = {"metadata": run_metadata(), "protocol": p, "protocol_sha256": sha256_file(pp),
             "calibration_manifest_sha256": sha256_file(cp), "records": [], "sources": [], "errors": [],
             "concurrent_archive_job": "separate background legacy 200GB checksum/controlled study; no significance claim",
             "status": "running", "scope": p["scope"]}
    atomic_json(out / "protocol-frozen.json", study)
    started = time.perf_counter()
    with MemoryGuard(p["memory_limit"]) as guard:
        for source in m["sources"]:
            path = Path(source["path"])
            if sha256_file(path) != source["sha256"]:
                raise ValueError("real source checksum mismatch")
            study["sources"].append(source)
            with nc.Dataset(path) as ds:
                v = _check_source(ds)
                v.set_var_chunk_cache(64*2**20,1009,.5)
                tv = ds.variables["forecast_initial_time"]
                times = nc.num2date(tv[:],tv.units,getattr(tv,"calendar","standard"))
                indices = [i for i,t in enumerate(times) if t.day == 11 and t.hour == 6]
                if len(indices) != 1:
                    raise ValueError("missing fixed day-11 06UTC real cycle")
                t = times[indices[0]]
                start = int(datetime(t.year,t.month,t.day,t.hour,tzinfo=timezone.utc).timestamp())
                lat = np.asarray(ds.variables["latitude"][:])
                lon = (np.asarray(ds.variables["longitude"][:])+180)%360-180
                native = np.asarray(np.ma.filled(v[indices[0]],np.nan),dtype="float32")
            for place in p["locations"]:
                yi, xi = int(np.argmin(abs(lat-place["latitude"]))), int(np.argmin(abs(lon-place["longitude"])))
                original = real_point_case(native[:,yi,xi],start,float(lat[yi]),float(lon[xi]),source)
                native_bundle, native_lp = query_check(original,p["agreement_tolerance"])
                for arm in p["arms"]:
                    index = len(study["records"])
                    case, actions, fine, derivation = coarsen(original,12,2,p["query_eps_mm"])
                    if arm == "documented_H1":
                        case.hypotheses = case.hypotheses[:1]
                        case.completeness_basis = original.completeness_basis
                    case.id += "-"+arm
                    inputs = {"case":case.model_dump(),"actions":[a.model_dump() for a in actions]}
                    refs = [evaluate_paired_lp(case,actions,error_radius=r) for r in p["radii"]]
                    levels = refinements(case,fine,p["refinement_fractions"],p["agreement_tolerance"])
                    content = {"input":inputs,"native":{"case":original.model_dump(),"bundle":native_bundle,"lp":native_lp},
                               "lp-grid":{"radii":p["radii"],"results":refs},"refinements":levels}
                    record = {"index":index,"arm":arm,"month":t.month,"place":place["name"],
                              "latitude":float(lat[yi]),"longitude":float(lon[xi]),"initialization":start,
                              "source_sha256":source["sha256"],"input_hash":digest(inputs),"H":len(case.hypotheses),
                              "derivation":derivation,"methods":{},
                              "reference_query_mm":native_bundle["result"]["lower"]
                                  if native_bundle["result"]["lower"]==native_bundle["result"]["upper"] else None,
                              "refinement_bounds":[{"added":r["native_records_added"],
                                  "lower":r["bundle"]["result"]["lower"],"upper":r["bundle"]["result"]["upper"]} for r in levels],
                              "lp_calls":sum(r["metrics"]["lp_calls"] for r in refs)}
                    methods = list(p["methods"])
                    Random(p["seed"]+index).shuffle(methods)
                    for method in methods:
                        tick = time.perf_counter()
                        bundle = build_precision_profiles(case,actions,method)
                        elapsed = time.perf_counter()-tick
                        if not _agrees(precision_values(case,actions,bundle,p["radii"]),refs,p["agreement_tolerance"]):
                            raise ValueError("real-value profile differs from independent LP")
                        content[method] = bundle
                        record["methods"][method] = {"seconds":elapsed,"checker_valid":bundle["checker"]["valid"],
                                                     "lp_agreement":True,"metrics":bundle["metrics"]}
                    dest = out / f"part-{index:06d}.zip"
                    _save_bundle(dest,content)
                    record.update(bundle=dest.name,sha256=sha256_file(dest),bundle_bytes=dest.stat().st_size)
                    study["records"].append(record)
                    guard.check()
                    atomic_json(out / "run.json",study)
            print(json.dumps({"month":t.month,"cases":len(study["records"])}),flush=True)
        study["peak_process_tree_rss"] = guard.peak
    study.update(status="complete",wall_seconds=time.perf_counter()-started)
    atomic_json(out / "run.json",study)
    replay = replay_archive_precision(out / "run.json",out / "replay.json")
    return {"status":study["status"],"real_point_cycles":len(study["records"])//len(p["arms"]),
            "cases":len(study["records"]),"replay":replay}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--calibration",type=Path,default=Path("data/calibration/era5-lsp-2023-v1/manifest.json"))
    p.add_argument("--protocol",type=Path,default=Path("configs/experiments/precision-real-era5-v1.json"))
    p.add_argument("--output",type=Path,default=Path("experiments/runs/precision-real-era5-v1"))
    args = p.parse_args()
    print(json.dumps(run(args.calibration,args.protocol,args.output),ensure_ascii=True))


if __name__ == "__main__":
    main()
