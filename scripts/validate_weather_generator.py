"""Freeze generator first, then report held-out realism without parameter tuning."""

import argparse
import json
from pathlib import Path

from meteo_bridge.weather_validation import validate_weather

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--calibration", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("reports/weather-v2/heldout.json"))
    p.add_argument("--seed", type=int, default=20261019)
    p.add_argument("--sigma", type=float, default=.12)
    a = p.parse_args()
    r = validate_weather(a.calibration, a.output, a.seed, a.sigma)
    print(json.dumps({"status": r["status"], "heldout_cycles": r["heldout_cycles"], "metrics": r["metrics"]}))
