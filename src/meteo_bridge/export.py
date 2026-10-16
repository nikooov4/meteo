import csv
import io
from datetime import datetime, timezone


def interval_csv(case):
    """Only a single complete interpretation has a standalone interval CSV export."""
    if not case.h_complete or len(case.hypotheses) != 1:
        raise ValueError("CSV cannot preserve unresolved semantics; export Case JSON instead")
    fields = [
        "id",
        "start",
        "end",
        "value",
        "lower",
        "upper",
        "unit",
        "statistic",
        "quantity",
        "location",
        "spatial_support",
        "product",
        "version",
        "member",
        "vertical_support",
        "cycle",
        "reset_start",
        "qc",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fields)
    writer.writeheader()

    def iso(t):
        return datetime.fromtimestamp(t, timezone.utc).isoformat()

    for obs in case.observations:
        spec = case.hypotheses[0].intervals.get(obs.id, obs.interval)
        if spec is None:
            raise ValueError("unresolved interval")
        row = {
            "id": obs.id,
            "start": iso(spec.start),
            "end": iso(spec.end),
            "value": obs.original_value or obs.lower,
            "lower": obs.lower,
            "upper": obs.upper,
            "unit": spec.unit,
            "statistic": spec.statistic,
            "qc": obs.qc,
            "reset_start": iso(spec.reset_start) if spec.reset_start is not None else "",
        }
        row.update({k: v for k, v in obs.series.model_dump().items() if k in fields})
        writer.writerow(row)
    return output.getvalue()
