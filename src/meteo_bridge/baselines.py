"""Reference behaviors, deliberately separate from acquisition policy comparisons."""

from fractions import Fraction

import pandas as pd


def typed_validator(case):
    if not case.h_complete or len(case.hypotheses) != 1:
        return {"status": "refused_unknown"}
    from .services import solve_query

    return solve_query(case)["result"]


def metadata_first(case):
    if len(case.hypotheses) != 1:
        return {"status": "requires_full_metadata"}
    from .services import solve_query

    return solve_query(case)["result"]


def manual_pandas(case):
    """Reviewed tiling pipeline for already configured, nonoverlapping amounts only."""
    if len(case.hypotheses) != 1:
        return {"status": "unsupported"}
    rows = []
    h = case.hypotheses[0]
    for o in case.observations:
        s = h.intervals.get(o.id, o.interval)
        if o.qc != "accepted" or not s or s.statistic != "amount" or s.unit != "mm" or o.lower != o.upper:
            return {"status": "unsupported"}
        if case.query.start <= s.start and s.end <= case.query.end:
            rows.append({"start": s.start, "end": s.end, "amount": Fraction(o.lower)})
    frame = pd.DataFrame(rows).sort_values("start") if rows else pd.DataFrame()
    if frame.empty or frame.iloc[0]["start"] != case.query.start or frame.iloc[-1]["end"] != case.query.end:
        return {"status": "unsupported"}
    if frame["end"].to_list()[:-1] != frame["start"].to_list()[1:]:
        return {"status": "unsupported"}
    return {
        "status": "computed",
        "amount": str(frame["amount"].sum()),
        "method": "manually configured pandas tiling",
    }
