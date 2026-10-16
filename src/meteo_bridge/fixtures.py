"""Hand-calculated cases, independent of synthetic generator."""

from .domain import Case, Interpretation, IntervalObservation, Query, SemanticHypothesis, SeriesKey


def observation(id, a, b, lo, hi=None, **kwargs):
    return IntervalObservation(
        id=id,
        lower=str(lo),
        upper=str(lo if hi is None else hi),
        original_value=str(lo),
        interval=Interpretation(start=a * 3600, end=b * 3600),
        **kwargs,
    )


def fixture(name):
    obs = [observation("a", 0, 12, 10), observation("b", 6, 18, 12), observation("c", 6, 12, 4)]
    q = Query(start=0, end=18 * 3600)
    hs = [SemanticHypothesis(id="known")]
    complete = True
    if name in {"daily-total", "insufficient-data"}:
        obs = [observation("daily", 0, 24, 12)]
        q = Query(start=0, end=(24 if name == "daily-total" else 12) * 3600)
    elif name in {"overlap-bounded", "threshold-true", "threshold-unknown"}:
        obs = [
            observation("a", 0, 12, "9.9", "10.1"),
            observation("b", 6, 18, "11.9", "12.1"),
            observation("c", 6, 12, "3.9", "4.1"),
        ]
        if name.startswith("threshold"):
            q = q.model_copy(
                update={"objective": "threshold", "threshold": "15" if name.endswith("true") else "18"}
            )
    elif name == "conflict":
        obs = [observation("daily", 0, 24, 3), observation("half", 0, 12, 4)]
    elif name == "unbounded":
        obs = []
    elif name in {"metadata-label", "incomplete-h"}:
        obs = [observation("labelled", 0, 1, 2), observation("other", 1, 2, 5)]
        q = Query(start=0, end=3600)
        hs = [
            SemanticHypothesis(id="end", assignments={"label": "end"}),
            SemanticHypothesis(
                id="begin",
                assignments={"label": "begin"},
                intervals={
                    "labelled": Interpretation(start=3600, end=7200),
                    "other": Interpretation(start=0, end=3600),
                },
            ),
        ]
        complete = name != "incomplete-h"
        if name == "incomplete-h":
            hs = hs[:1]  # documented true begin-label branch deliberately omitted
    elif name == "cumulative":
        key = SeriesKey(product="local-cumulative-example", cycle="1970-01-01T00:00Z")
        obs = [
            observation("step1", 0, 1, 2, series=key, reset_group=key.cycle),
            observation("step2", 0, 2, 5, series=key, reset_group=key.cycle),
        ]
        for o in obs:
            o.interval = o.interval.model_copy(update={"statistic": "cumulative", "reset_start": 0})
        q = Query(series=key, start=3600, end=7200)
    elif name != "overlap-exact":
        raise ValueError(f"unknown fixture {name}")
    return Case(
        id=name,
        observations=obs,
        hypotheses=hs,
        query=q,
        h_complete=complete,
        completeness_basis="exhaustive hand-specified fixture" if complete else "top-k; truth may be omitted",
        family_id=(
            "overlap"
            if name.startswith(("overlap", "threshold"))
            else "daily"
            if name in {"daily-total", "insufficient-data", "conflict"}
            else "metadata-label"
            if name in {"metadata-label", "incomplete-h"}
            else name
        ),
    )


NAMES = [
    "overlap-exact",
    "overlap-bounded",
    "threshold-true",
    "threshold-unknown",
    "daily-total",
    "insufficient-data",
    "metadata-label",
    "conflict",
    "unbounded",
    "incomplete-h",
    "cumulative",
]
