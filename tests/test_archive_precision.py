import json
from fractions import Fraction as F
from pathlib import Path

import pytest

from meteo_bridge.archive_precision import (
    coarsen,
    refinements,
    replay_archive_precision,
    run_archive_precision,
)
from meteo_bridge.domain import Case, Interpretation, Query, SemanticHypothesis, SeriesKey
from meteo_bridge.fixtures import observation
from meteo_bridge.scale_data import generate_scale


@pytest.mark.parametrize("statistic", ["amount", "interval_mean_rate", "cumulative"])
def test_archive_coarsening_conventions_missing_and_nested_evidence(statistic):
    key = SeriesKey(cycle="0" if statistic == "cumulative" else None)
    obs = []
    for h in range(24):
        value = h+1 if statistic != "cumulative" else (h+1)*(h+2)//2
        item = observation(f"h{h}", h, h+1, value, series=key, reset_group=key.cycle)
        item.interval = Interpretation(start=h*3600, end=(h+1)*3600, statistic=statistic,
            unit="mm/h" if statistic == "interval_mean_rate" else "mm",
            reset_start=0 if statistic == "cumulative" else None)
        obs.append(item)
    native = Case(id="source", observations=obs, hypotheses=[SemanticHypothesis(id="known")],
                  query=Query(series=key, start=0, end=11*3600), h_complete=True,
                  completeness_basis="documented hand construction")
    case, actions, source, _ = coarsen(native, 24, 3)
    assert F(case.observations[0].lower) == 10
    assert len(actions) == 4 and len(case.hypotheses) == 3 and len(source) == 24
    assert case.origin == "controlled" and "controlled shifts" in case.completeness_basis
    assert all(o.series == key for o in case.observations)
    levels = refinements(case, source, [0, .25, .5, 1], 1e-7)
    assert levels[-1]["bundle"]["result"]["lower"] == levels[-1]["bundle"]["result"]["upper"] == "66"
    native.observations[0].qc = "missing"
    missing, _, _, _ = coarsen(native, 24, 3)
    assert missing.observations[0].qc == ("accepted" if statistic == "cumulative" else "missing")


def test_archive_experiment_resume_replay_and_source_hash(tmp_path):
    data = tmp_path / "data"
    generate_scale(target_size="110KB", output=data, series=6, series_per_shard=2,
                   shard_size="8KB", chunk_size="1MiB", missing_fraction=0, defect_fraction=0)
    m = json.loads((data / "manifest.json").read_text(encoding="utf8"))
    assert len(m["shards"]) > 1
    protocol = json.loads(Path("configs/experiments/precision-archive-200gb-v1.json").read_text(encoding="utf8"))
    protocol.update(minimum_archive_bytes=0, methods=["compiled", "terminal"], radii=["0"])
    pp = tmp_path / "protocol.json"
    pp.write_text(json.dumps(protocol), encoding="utf8")
    out = tmp_path / "run"
    assert run_archive_precision(data / "manifest.json", pp, out, dry_run=True)["status"] == "dry_run"
    first = run_archive_precision(data / "manifest.json", pp, out, stop_after_shards=1)
    assert first["status"] == "interrupted" and first["partitions"] == 1
    saved = (out / "part-000000.zip").read_bytes()
    final = run_archive_precision(data / "manifest.json", pp, out, resume=True)
    assert final["status"] == "complete" and final["data_bytes_verified"] == m["data_bytes"]
    assert saved == (out / "part-000000.zip").read_bytes()
    replay = replay_archive_precision(out / "run.json", out / "replay.json")
    assert replay["passed"] and replay["profile_bundles_checked"] == 2*len(m["shards"])
    with (data / m["shards"][0]["path"]).open("ab") as f:
        f.write(b"changed")
    with pytest.raises(ValueError, match="changed archive shard"):
        run_archive_precision(data / "manifest.json", pp, out, resume=True)


def test_real_hourly_amounts_preserve_native_binary_precision_and_are_not_deaccumulated():
    import importlib.util

    import numpy as np

    script = Path(__file__).resolve().parents[1] / "scripts/run_real_precision_experiment.py"
    spec = importlib.util.spec_from_file_location("real_precision_experiment", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    values = np.array([.002, .001]+[0]*10, dtype="float32")
    case = module.real_point_case(values, 0, 55.75, 37.5, {"sha256": "source"})
    assert F(case.observations[1].lower) == F(float(values[1]))*1000
    assert F(case.observations[1].lower) > 0
    assert case.observations[1].interval.start == 3600
    assert case.query.series.quantity == "large_scale_precipitation"
    assert all(o.series.cycle == "0" for o in case.observations)
