import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from .domain import (
    Case,
    Interpretation,
    IntervalObservation,
    Query,
    SemanticHypothesis,
    SeriesKey,
    SourceManifest,
)


def read_dwd_subset(path, start, end, *, confirmed_end_label=False):
    path = Path(path)
    provenance = next(
        m
        for m in json.loads(Path("data/manifests/dwd-subset.json").read_text(encoding="utf8"))
        if Path(m["path"]).name == path.name
    )
    key = SeriesKey(
        location="DWD:" + path.name.split("-")[0], product="DWD CDC hourly R1", version=provenance["version"]
    )
    obs = []
    with path.open(encoding="utf8") as f:
        for row in csv.DictReader(f):
            t = int(datetime.strptime(row["MESS_DATUM"], "%Y%m%d%H").replace(tzinfo=timezone.utc).timestamp())
            if not start <= t <= end:
                continue
            missing = row["R1"] == "-999"
            value = "0" if missing else row["R1"]
            obs.append(
                IntervalObservation(
                    id=row["MESS_DATUM"],
                    series=key,
                    original_value=row["R1"],
                    original_timestamp=row["MESS_DATUM"],
                    lower=value,
                    upper=value,
                    interval=Interpretation(start=t - 3600, end=t),
                    qc="missing" if missing else "accepted",
                    evidence_ids=[provenance["sha256"], "QN_8=" + row["QN_8"]],
                )
            )
    hs = [SemanticHypothesis(id="end-label", assignments={"time_label": "end"})]
    if not confirmed_end_label:
        hs.append(
            SemanticHypothesis(
                id="begin-label",
                assignments={"time_label": "begin"},
                intervals={
                    o.id: Interpretation(start=o.interval.end, end=o.interval.end + 3600) for o in obs
                },
            )
        )
    source = SourceManifest(**{k: v for k, v in provenance.items() if k in SourceManifest.model_fields})
    return Case(
        id=f"dwd-{path.stem}-{start}-{end}",
        observations=obs,
        hypotheses=hs,
        query=Query(series=key, start=start, end=end),
        h_complete=confirmed_end_label,
        completeness_basis="end-hour convention explicitly assumed by annotator"
        if confirmed_end_label
        else "period, mm and UTC verified; exact end-label not independently established for this archive",
        origin="controlled" if confirmed_end_label else "original",
        family_id=key.location,
        source_manifests=[source],
        assumptions=[
            "nonnegative precipitation increments",
            "reported R1 values used as exact serialized inputs; not a physical instrument guarantee",
        ],
    )
