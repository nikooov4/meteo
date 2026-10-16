"""External HTTP client with local independent acquisition verification."""

import argparse
import json
from pathlib import Path

import httpx

from meteo_bridge.acquisition_checker import verify_acquisition
from meteo_bridge.action_domain import AcquisitionAction
from meteo_bridge.domain import Case
from meteo_bridge.resources import atomic_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--case", type=Path, default=Path("experiments/runs/acquisition-examples-v1/case.json"))
    parser.add_argument("--actions", type=Path, default=Path("experiments/runs/acquisition-examples-v1/actions.json"))
    parser.add_argument("--output", type=Path, default=Path("outputs/acquisition-http.json"))
    args = parser.parse_args()
    case = Case.model_validate_json(args.case.read_text(encoding="utf8"))
    actions = [AcquisitionAction.model_validate(a) for a in json.loads(args.actions.read_text(encoding="utf8"))]
    with httpx.Client(base_url=args.url, timeout=90, trust_env=False) as client:
        response = client.post("/datasets", files={"file": ("case.json", case.model_dump_json(), "application/json")})
        response.raise_for_status()
        dataset = response.json()["id"]
        response = client.post("/queries", json={"dataset_id": dataset})
        response.raise_for_status()
        qid = response.json()["id"]
        response = client.post(f"/queries/{qid}/acquisition",
                               json={"actions": [a.model_dump() for a in actions], "method": "terminal"})
        response.raise_for_status()
        bundle = response.json()
    verdict = verify_acquisition(case, actions, bundle["result"], bundle["certificate"])
    atomic_json(args.output, {"case": case.model_dump(), "actions": [a.model_dump() for a in actions],
                              "server_bundle": bundle, "local_checker": verdict})
    print(json.dumps({"local_checker": verdict, "result": bundle["result"]}, indent=2))
    if not verdict["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
