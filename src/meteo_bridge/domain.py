"""Input contracts; no UI, graph or LP dependencies."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from fractions import Fraction
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SeriesKey(Model):
    quantity: Literal["precipitation", "large_scale_precipitation", "convective_precipitation"] = (
        "precipitation"
    )
    location: str = "fixture"
    spatial_support: str = "point"
    product: str = "hand-calculated"
    version: str = "1"
    member: str = "deterministic"
    vertical_support: str = "surface"
    cycle: str | None = None


class SourceManifest(Model):
    dataset_id: str
    provider: str
    product_kind: str
    upstream: list[str] = Field(default_factory=list)
    version: str
    request: dict = Field(default_factory=dict)
    url: str | None = None
    license: str
    downloaded_at: str | None = None
    sha256: str
    extents: dict = Field(default_factory=dict)
    documentation_version: str


class Interpretation(Model):
    start: int
    end: int
    unit: str = "mm"
    statistic: Literal["amount", "interval_mean_rate", "cumulative", "instantaneous_rate"] = "amount"
    reset_start: int | None = None

    @model_validator(mode="after")
    def interval_valid(self):
        if self.end <= self.start:
            raise ValueError("interval end must exceed start")
        return self


class IntervalObservation(Model):
    id: str
    series: SeriesKey = Field(default_factory=SeriesKey)
    original_value: str | None = None
    original_timestamp: str | None = None
    lower: str
    upper: str
    interval: Interpretation | None = None
    qc: Literal["accepted", "missing", "rejected"] = "accepted"
    reset_group: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def bounds_valid(self):
        if Fraction(self.lower) > Fraction(self.upper):
            raise ValueError("lower exceeds upper")
        return self


class SemanticHypothesis(Model):
    id: str
    assignments: dict[str, str] = Field(default_factory=dict)
    intervals: dict[str, Interpretation] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    compiler_version: str = "1"
    completeness_scope: str = "declared alternatives"


class Query(Model):
    series: SeriesKey = Field(default_factory=SeriesKey)
    start: int
    end: int
    unit: Literal["mm"] = "mm"
    timezone: str = "UTC"
    calendar: str = "proleptic_gregorian"
    objective: Literal["amount", "threshold"] = "amount"
    eps: str = "0"
    threshold: str | None = None
    permitted_assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def query_valid(self):
        if self.end <= self.start or Fraction(self.eps) < 0:
            raise ValueError("invalid interval or epsilon")
        if self.objective == "threshold" and self.threshold is None:
            raise ValueError("threshold is required")
        if self.threshold is not None:
            Fraction(self.threshold)
        ZoneInfo(self.timezone)
        return self


class Case(Model):
    id: str
    observations: list[IntervalObservation] = Field(max_length=4096)
    hypotheses: list[SemanticHypothesis] = Field(min_length=1, max_length=256)
    query: Query
    h_complete: bool
    completeness_basis: str
    assumptions: list[str] = Field(default_factory=lambda: ["nonnegative precipitation increments"])
    revision: int = 0
    evidence: list[dict] = Field(default_factory=list)
    family_id: str = "hand"
    origin: Literal["synthetic", "controlled", "original"] = "synthetic"
    source_manifests: list[SourceManifest] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self):
        for values in (self.observations, self.hypotheses):
            ids = [v.id for v in values]
            if len(set(ids)) != len(ids):
                raise ValueError("duplicate ids")
        known = {o.id for o in self.observations}
        if any(set(h.intervals) - known for h in self.hypotheses):
            raise ValueError("hypothesis references unknown observation")
        return self


def canonical(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def utc_seconds(iso: str) -> int:
    """Require an explicit offset. DST fold is resolved by the supplied offset."""
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timezone offset required; civil/solar labels cannot be guessed")
    if dt.microsecond:
        raise ValueError("subsecond timestamps unsupported")
    return int(dt.timestamp())
