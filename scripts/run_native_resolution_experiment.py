"""Real native-hourly data queried below their temporal resolution, without masking."""

import argparse
import json
import time
import zipfile
from fractions import Fraction as F
from pathlib import Path

from meteo_bridge.action_domain import AcquisitionAction as Action
from meteo_bridge.archive_precision import _save_bundle, query_check, replay_archive_precision
from meteo_bridge.domain import Case, digest
from meteo_bridge.paired_oracle import evaluate_paired_lp
from meteo_bridge.precision_frontier import build_precision_profiles, precision_values
from meteo_bridge.resources import MemoryGuard, atomic_json, run_metadata, sha256_file


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path("experiments/runs/precision-real-native-resolution-v1"))
    args=parser.parse_args()
    pp=Path("configs/experiments/precision-real-native-resolution-v1.json")
    p=json.loads(pp.read_text(encoding="utf8"))
    source=Path(p["source_run"])
    prior=json.loads(source.read_text(encoding="utf8"))
    out=args.output
    if (out / "protocol-frozen.json").exists():
        raise FileExistsError("preserve native diagnostic; choose a new version for another run")
    out.mkdir(parents=True,exist_ok=True)
    run={"protocol":p,"protocol_sha256":sha256_file(pp),"source_run_sha256":sha256_file(source),
         "metadata":run_metadata(),"records":[],"errors":[],"numerical_decision_differences":[],"status":"running"}
    atomic_json(out / "protocol-frozen.json",run)
    started=time.perf_counter()
    with MemoryGuard("1GiB") as guard:
        for record in prior["records"]:
            if record["arm"]!="documented_H1":
                continue
            path=source.parent / record["bundle"]
            if sha256_file(path)!=record["sha256"]:
                raise ValueError("changed real source bundle")
            with zipfile.ZipFile(path) as z:
                original=json.loads(z.read("native.json"))["case"]
            case=Case.model_validate(original)
            observations_hash=digest(original["observations"])
            start=case.query.start
            case.id+="-native-first-half-hour"
            case.query=case.query.model_copy(update={"end":start+1800,"eps":"0"})
            assert digest([o.model_dump() for o in case.observations])==observations_hash
            actions=[Action(id=f"refetch-{h}h",start=start,end=start+h*3600) for h in (1,4,6,12)]
            inputs={"case":case.model_dump(),"actions":[a.model_dump() for a in actions]}
            native,lp=query_check(case,p["agreement_tolerance"])
            refs=[evaluate_paired_lp(case,actions,error_radius=r) for r in p["radii"]]
            content={"input":inputs,"native":{"case":case.model_dump(),"bundle":native,"lp":lp},
                     "lp-grid":{"radii":p["radii"],"results":refs},"refinements":[]}
            row={"index":len(run["records"]),"month":record["month"],"place":record["place"],
                 "observations_sha256_unchanged":observations_hash,"original_observation_count":len(case.observations),
                 "input_hash":digest(inputs),"lower":native["result"]["lower"],"upper":native["result"]["upper"],
                 "source_sha256":record["source_sha256"],"methods":{}}
            for method in p["methods"]:
                b=build_precision_profiles(case,actions,method)
                values=precision_values(case,actions,b,p["radii"])
                for actual,expected in zip(values,refs):
                    for a,e in zip(actual["actions"],expected["actions"]):
                        if a["width_kind"]!=e["width_kind"] or (a["width"] is not None and
                                abs(float(F(a["width"]))-e["width"])>p["agreement_tolerance"]):
                            raise ValueError("native-resolution paired LP bounds mismatch")
                        if a["guarantees_resolution"]!=e["guarantees_resolution"]:
                            run["numerical_decision_differences"].append({"case":case.id,"method":method,
                                "radius":actual["radius"],"action":a["id"],"exact":a,"numerical":e})
                row["methods"][method]={"checker_valid":b["checker"]["valid"],"lp_width_agreement":True}
                content[method]=b
            row["exact_answer"]=native["result"]["lower"]==native["result"]["upper"]
            row["none_of_available_actions_resolves"]=all(a["radius_kind"]=="empty" for a in content["terminal"]["result"]["actions"])
            dest=out / f"part-{row['index']:06d}.zip"
            _save_bundle(dest,content)
            row.update(bundle=dest.name,sha256=sha256_file(dest),bundle_bytes=dest.stat().st_size)
            run["records"].append(row)
            guard.check()
        run["peak_process_tree_rss"]=guard.peak
    run.update(status="complete",wall_seconds=time.perf_counter()-started)
    atomic_json(out / "run.json",run)
    replay=replay_archive_precision(out / "run.json",out / "replay.json")
    print(json.dumps({"cases":len(run["records"]),"exact":sum(r["exact_answer"] for r in run["records"]),
                      "unresolved_by_available_actions":sum(r["none_of_available_actions_resolves"] for r in run["records"]),
                      "numerical_decision_differences":len(run["numerical_decision_differences"]),"replay":replay}))


if __name__=="__main__":
    main()
