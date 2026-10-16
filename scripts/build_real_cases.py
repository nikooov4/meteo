import json
from pathlib import Path

from meteo_bridge.baselines import manual_pandas
from meteo_bridge.domain import utc_seconds
from meteo_bridge.dwd import read_dwd_subset
from meteo_bridge.imports import import_file
from meteo_bridge.real_data import ncar_query_case
from meteo_bridge.resources import atomic_json, run_metadata
from meteo_bridge.services import solve_query

if __name__ == "__main__":
    root = Path("benchmark/cases")
    root.mkdir(parents=True, exist_ok=True)
    run = {"environment": run_metadata(), "cases": [], "independent_human_review": "pending"}
    for path in sorted(Path("data/real/dwd").glob("*.csv")):
        for day in range(1, 5):
            start = utc_seconds(f"2023-01-{day:02d}T01:00:00Z")
            end = start + 12 * 3600
            for confirmed in (False, True):
                case = read_dwd_subset(path, start, end, confirmed_end_label=confirmed)
                case.id += "-assumed-end" if confirmed else "-native-pending"
                bundle = solve_query(case, "lp")
                baseline = manual_pandas(case) if confirmed else None
                if baseline and baseline["status"] == "computed":
                    assert baseline["amount"] == bundle["result"]["point_estimate"]
                atomic_json(root / (case.id + ".json"), case.model_dump())
                run["cases"].append(
                    {
                        "origin": case.origin,
                        "family_id": case.family_id,
                        "manual_pandas": baseline,
                        "bundle": bundle,
                    }
                )
    local = import_file("data/fixtures/local-cumulative.csv")
    local.query.start += 3600
    run["cases"].append(
        {
            "origin": "synthetic",
            "note": "local documented file, NOT CDS data",
            "bundle": solve_query(local, "lp"),
        }
    )
    if Path("data/scale/ncar-lsp-small/manifest.json").exists():
        for index in (0, 1, 2):
            case, _ = ncar_query_case(
                "data/scale/ncar-lsp-small/manifest.json", 220 * 1440 + 52 + index, index, 6
            )
            atomic_json(root / (case.id + ".json"), case.model_dump())
            run["cases"].append(
                {"origin": "original", "family_id": case.family_id, "bundle": solve_query(case, "lp")}
            )
    atomic_json("experiments/runs/real-subset/run.json", run)
    print(
        json.dumps(
            {
                "cases": len(run["cases"]),
                "checker_valid": sum(
                    c["bundle"].get("checker", {}).get("valid", False) for c in run["cases"]
                ),
                "human_review": "pending",
            }
        )
    )
