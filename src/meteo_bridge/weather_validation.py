"""Streaming development holdout diagnostic; never tunes the generator."""

import json
import time
from pathlib import Path

import netCDF4 as nc
import numpy as np

from .realistic_weather import WeatherModel
from .resources import MemoryGuard, atomic_json, run_metadata, safe_data_path, sha256_file
from .scale_data import amounts


class Statistics:
    def __init__(self, latitude, cells, sample_ids):
        self.weights = np.broadcast_to(np.cos(np.radians(latitude.astype("float64")))[:, None], cells).copy()
        self.total = self.mass = self.wet = self.zeros = 0.
        self.transitions = self.continuing = 0
        self.pairs = {k: np.zeros(6) for k in ("lag1", "longitude", "latitude")}
        self.sample_ids, self.samples = sample_ids, []
        self.blocks = []

    def add(self, x):
        wet = x >= .1
        w = self.weights[None]
        total = 12 * self.weights.sum()
        self.total += total
        self.mass += float((x*w).sum())
        self.wet += float((wet*w).sum())
        self.zeros += float(((x == 0)*w).sum())
        self.transitions += int(wet[:-1].sum())
        self.continuing += int((wet[:-1] & wet[1:]).sum())
        z = np.log1p(x)
        for key, a, b in (("lag1", z[:-1], z[1:]),
                          ("longitude", z, np.roll(z, 1, axis=2)),
                          ("latitude", z[:, :-1], z[:, 1:])):
            self.pairs[key] += [a.size, a.sum(), b.sum(), (a*a).sum(), (b*b).sum(), (a*b).sum()]
        self.samples.append(x.reshape(12, -1)[:, self.sample_ids].copy())
        self.blocks.append({"area_weighted_mean_mm_h": float((x*w).sum()/total),
                            "area_weighted_wet_fraction": float((wet*w).sum()/total)})

    def result(self):
        correlations = {}
        for key, (n, a, b, aa, bb, ab) in self.pairs.items():
            denom = (aa-a*a/n)*(bb-b*b/n)
            correlations[f"{key}_log1p_correlation"] = float((ab-a*b/n)/np.sqrt(denom)) if denom > 0 else None
        sample = np.concatenate(self.samples).ravel()
        return {"area_weighted_mean_mm_h": self.mass/self.total,
                "area_weighted_wet_fraction_ge_0_1mm": self.wet/self.total,
                "area_weighted_zero_fraction": self.zeros/self.total,
                "wet_persistence_within_cycle": self.continuing/max(1, self.transitions),
                "sample_p95_mm": float(np.quantile(sample, .95)),
                "sample_p99_mm": float(np.quantile(sample, .99)),
                "sample_values": len(sample), **correlations}


def validate_weather(calibration, output, seed=20261019, sigma=.12):
    """Compare four predeclared methods on identical geography, month and phase.

    Quantiles are fixed-cell sample estimates. Correlations are unweighted and
    use only within-cycle pairs. Mean/wet/zero use cos(latitude) area weights.
    Confidence intervals resample whole held-out cycles (development diagnostic;
    adjacent days are not independent, so not a climate significance test).
    """
    started = time.perf_counter()
    mp = Path(calibration)
    meta = json.loads(mp.read_text(encoding="utf8"))
    entry = meta["banks"]["holdout"]
    path = safe_data_path(mp.parent, entry["path"])
    if sha256_file(path) != entry["sha256"]:
        raise ValueError("held-out checksum mismatch")
    model, bootstrap = WeatherModel(mp, seed, sigma), WeatherModel(mp, seed, 0)
    try:
        with MemoryGuard("2GiB") as guard, nc.Dataset(path) as ds:
            ds.variables["lsp_mm"].set_var_chunk_cache(8*2**20, 1009, .5)
            shape = tuple(meta["grid_shape"])
            ids = np.random.default_rng(127).choice(np.prod(shape), min(512, np.prod(shape)), replace=False)
            names = ("real_heldout", "legacy_v1", "unperturbed_block_bootstrap", "weather_v2")
            stats = {name: Statistics(model.lat, shape, ids) for name in names}
            train_inits = set(model.inits.tolist())
            hold_inits = np.asarray(ds.variables["initialization"][:], dtype="int64")
            if train_inits.intersection(hold_inits.tolist()):
                raise ValueError("training/holdout cycle leakage")
            monthly = {}
            for i, initialization in enumerate(hold_inits):
                real = np.round(np.asarray(ds.variables["lsp_mm"][i], dtype="float64"), 4)
                generated, provenance = model.block(int(initialization))
                unperturbed, _ = bootstrap.block(int(initialization))
                if provenance["training_initialization"] not in train_inits:
                    raise ValueError("generator used a non-training cycle")
                h = int((initialization - min(train_inits))//3600)
                old = amounts(42, np.arange(np.prod(shape)), np.arange(h, h+12)).reshape((12,)+shape)/100
                for name, x in zip(names, (real, old, unperturbed, generated)):
                    stats[name].add(x)
                month = int(ds.variables["month"][i])
                monthly.setdefault(str(month), []).append({name: stats[name].blocks[-1] for name in names})
                guard.check()
        metrics = {name: stat.result() for name, stat in stats.items()}
        errors = {name: {key: abs(value-metrics["real_heldout"][key])
                         for key, value in values.items() if key != "sample_values" and value is not None
                         and metrics["real_heldout"][key] is not None}
                  for name, values in metrics.items() if name != "real_heldout"}
        # Fixed aggregation and cycle bootstrap, no post-hoc parameter search.
        rng = np.random.default_rng(728)
        confidence = {}
        for name in names[1:]:
            delta = np.array([b["area_weighted_mean_mm_h"]-a["area_weighted_mean_mm_h"]
                              for a, b in zip(stats["real_heldout"].blocks, stats[name].blocks)])
            draws = np.mean(delta[rng.integers(0, len(delta), (1000, len(delta)))], axis=1)
            confidence[name] = np.quantile(draws, [.025, .975]).tolist()
        result = {"status": "completed", "environment": run_metadata(), "seed": seed, "sigma": sigma,
                  "calibration_sha256": sha256_file(mp), "heldout_cycles": len(hold_inits),
                  "training_cycles": len(train_inits), "train_holdout_intersection": 0,
                  "grid_shape": list(shape), "metrics": metrics, "absolute_errors": errors,
                  "monthly_cycle_metrics": monthly, "mean_error_cycle_bootstrap_95_interval": confidence,
                  "peak_process_tree_rss": guard.peak, "seconds": time.perf_counter()-started,
                  "quantum_mm": .0001, "wet_threshold_mm": .1,
                  "definitions": {"mean_wet_zero": "cos(latitude) area weighted; global sampled points",
                                  "quantiles": "fixed 512 uniformly chosen grid cells, all holdout hours",
                                  "correlations": "unweighted log1p amounts, within 12 h cycle only",
                                  "wet_persistence": "P(next >=0.1 | current >=0.1), within cycle"},
                  "limitations": ["development holdout: same source year and first half of months",
                                  "not total precipitation, station rain, independent annotation or climate validation",
                                  "bootstrap repeats training storm footprints; extrema and diversity limited",
                                  "blocks independent across cycles; do not infer cross-cycle persistence",
                                  "unperturbed bootstrap is a strong baseline; perturbation need not improve it",
                                  "cycle bootstrap CI ignores residual dependence across adjacent days"]}
        atomic_json(output, result)
        return result
    finally:
        model.close()
        bootstrap.close()
