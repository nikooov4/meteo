"""Small explicit CSV/CF-NetCDF imports; no metadata guesses."""

import csv
import io
from fractions import Fraction
from pathlib import Path

import netCDF4 as nc
import numpy as np

from .domain import (
    Case,
    Interpretation,
    IntervalObservation,
    Query,
    SemanticHypothesis,
    SeriesKey,
    utc_seconds,
)


def csv_case(text, *, name="local-csv"):
    obs = []
    for row in csv.DictReader(io.StringIO(text)):
        if len(obs) >= 4096:
            raise ValueError("CSV working model limit is 4096 rows; register a scale manifest")
        required = {
            "id",
            "start",
            "end",
            "value",
            "unit",
            "statistic",
            "location",
            "product",
            "member",
            "cycle",
        }
        if not required <= row.keys():
            raise ValueError(f"explicit CSV columns required: {sorted(required)}")
        key = SeriesKey(
            **{k: row[k] or None if k == "cycle" else row[k] for k in SeriesKey.model_fields if k in row}
        )
        start, end = utc_seconds(row["start"]), utc_seconds(row["end"])
        spec = Interpretation(
            start=start,
            end=end,
            unit=row["unit"],
            statistic=row["statistic"],
            reset_start=utc_seconds(row["reset_start"]) if row.get("reset_start") else None,
        )
        obs.append(
            IntervalObservation(
                id=row["id"],
                series=key,
                original_value=row["value"],
                original_timestamp=row["end"],
                lower=row.get("lower") or row["value"],
                upper=row.get("upper") or row["value"],
                interval=spec,
                qc=row.get("qc") or "accepted",
                reset_group=key.cycle,
            )
        )
    if not obs or any(o.series != obs[0].series for o in obs):
        raise ValueError("CSV must contain one nonempty physical series")
    return Case(
        id=name,
        observations=obs,
        hypotheses=[SemanticHypothesis(id="explicit-csv")],
        query=Query(
            series=obs[0].series,
            start=min(
                o.interval.reset_start
                if o.interval.statistic == "cumulative" and o.interval.reset_start is not None
                else o.interval.start
                for o in obs
            ),
            end=max(o.interval.end for o in obs),
        ),
        h_complete=True,
        completeness_basis="user-declared intervals, units, series and cycle; not inferred",
        family_id=name,
    )


def netcdf_case(path, *, name="local-netcdf"):
    """Small CF interval file, scalar time series only; multidimensional archives use registration."""
    with nc.Dataset(path) as ds:
        if "time" not in ds.variables:
            raise ValueError("CF time coordinate required")
        time = ds.variables["time"]
        if getattr(time, "calendar", "standard") not in {"standard", "gregorian", "proleptic_gregorian"}:
            raise ValueError("unsupported_calendar")
        bounds_name = getattr(time, "bounds", None)
        if not bounds_name or bounds_name not in ds.variables:
            raise ValueError("explicit CF time bounds required")
        candidates = [
            v
            for v in ds.variables.values()
            if v.dimensions == ("time",)
            and getattr(v, "standard_name", "")
            in {"lwe_thickness_of_precipitation_amount", "precipitation_amount"}
        ]
        if len(candidates) != 1 or len(time) > 4096:
            raise ValueError("one scalar precipitation time series, at most 4096 intervals required")
        v = candidates[0]
        for coordinate in ds.variables.values():
            if getattr(coordinate, "standard_name", "") in {
                "forecast_reference_time",
                "realization",
                "latitude",
                "longitude",
            } or getattr(coordinate, "cf_role", "") in {"timeseries_id", "trajectory_id", "profile_id"}:
                if coordinate.size > 4096:
                    raise ValueError("coordinate working-model budget exceeded")
                values = coordinate[:]
                if np.ma.is_masked(values) or np.unique(values).size != 1:
                    raise ValueError("multiple or unknown physical series/cycles in scalar CF file")
                if getattr(coordinate, "standard_name", "") == "forecast_reference_time" and not getattr(
                    ds, "cycle", ""
                ):
                    raise ValueError("forecast reference time requires an explicit SeriesKey cycle")
        if getattr(v, "cell_methods", None) != "time: sum":
            raise ValueError("supported CF import requires time: sum; instantaneous/mean needs explicit CSV")
        if any(not hasattr(ds, field) for field in ("location", "product", "member", "cycle")):
            raise ValueError("explicit global location/product/member/cycle attributes required")
        bounds = np.asarray(ds.variables[bounds_name][:])
        dates = nc.num2date(
            bounds,
            time.units,
            calendar=getattr(time, "calendar", "standard"),
            only_use_cftime_datetimes=False,
            only_use_python_datetimes=True,
        )
        key = SeriesKey(location=ds.location, product=ds.product, member=ds.member, cycle=ds.cycle or None)
        values = v[:]
        obs = []
        for i, ((a, b), value) in enumerate(zip(dates, values)):
            missing = np.ma.is_masked(value) or not np.isfinite(value)
            raw = "0" if missing else str(Fraction.from_float(float(value)))
            obs.append(
                IntervalObservation(
                    id=str(i),
                    series=key,
                    original_value=raw,
                    lower=raw,
                    upper=raw,
                    interval=Interpretation(
                        start=utc_seconds(a.isoformat() + "+00:00"),
                        end=utc_seconds(b.isoformat() + "+00:00"),
                        unit=v.units,
                    ),
                    qc="missing" if missing else "accepted",
                )
            )
    return Case(
        id=name,
        observations=obs,
        hypotheses=[SemanticHypothesis(id="CF-bounds")],
        query=Query(
            series=key, start=min(o.interval.start for o in obs), end=max(o.interval.end for o in obs)
        ),
        h_complete=True,
        completeness_basis="explicit CF bounds and user-declared SeriesKey",
        family_id=name,
    )


def import_file(path):
    path = Path(path)
    if path.suffix.lower() == ".csv":
        return csv_case(path.read_text(encoding="utf-8-sig"), name=path.stem)
    if path.suffix.lower() == ".nc":
        return netcdf_case(path, name=path.stem)
    if path.suffix.lower() in {".json", ".yaml", ".yml"}:
        from .services import load_dataset

        return load_dataset(path)
    raise ValueError("supported uploads: Case JSON/YAML, explicit interval CSV, scalar CF NetCDF")
