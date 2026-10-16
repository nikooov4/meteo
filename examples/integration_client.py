"""External client: provider-agnostic Query plus local certificate verification."""

import argparse
import json

import httpx

from meteo_bridge.certificates import verify_certificate
from meteo_bridge.domain import Case

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case", nargs="?", help="Case JSON or supported explicit CSV/CF NetCDF")
    parser.add_argument("--dataset-id", help="manifest hash returned by meteo data register")
    parser.add_argument("--series-id", default=0, type=int)
    parser.add_argument("--first-hour", default=1, type=int)
    parser.add_argument("--hours", default=6, type=int)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    # The local reference client must not send loopback requests to an inherited HTTP proxy.
    with httpx.Client(base_url=args.url, timeout=60, trust_env=False) as client:
        if args.dataset_id:
            payload = {
                "dataset_id": args.dataset_id,
                "selection": {
                    "series_id": args.series_id,
                    "first_hour": args.first_hour,
                    "hours": args.hours,
                },
            }
        else:
            if not args.case:
                parser.error("case or --dataset-id required")
            with open(args.case, "rb") as f:
                response = client.post("/datasets", files={"file": (args.case, f)})
            response.raise_for_status()
            dataset = response.json()
            payload = {"dataset_id": dataset["id"], "query": dataset["query"]}
        response = client.post("/queries", json=payload)
        response.raise_for_status()
        bundle = response.json()
        verdict = verify_certificate(
            Case.model_validate(bundle["case"]), bundle["result"], bundle["certificate"]
        )
        if not verdict["valid"]:
            raise RuntimeError(verdict)
        print(json.dumps({"result": bundle["result"], "local_checker": verdict}, indent=2))
