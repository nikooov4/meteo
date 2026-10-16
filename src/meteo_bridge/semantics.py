from fractions import Fraction as F

from .budget import checkpoint
from .domain import Case, Interpretation


def normalized(interval: Interpretation, lower: str, upper: str):
    if interval.statistic == "instantaneous_rate":
        raise NotImplementedError("instantaneous rate cannot determine an interval amount")
    start = interval.start
    if interval.statistic == "cumulative":
        if interval.reset_start is None:
            raise NotImplementedError("cumulative requires documented reset baseline")
        start = interval.reset_start
        if start >= interval.end:
            raise ValueError("invalid reset baseline")
    if interval.statistic == "interval_mean_rate":
        rates = {"mm/h": F(1, 3600), "m/s": F(1000), "kg m-2 s-1": F(1)}
        if interval.unit not in rates:
            raise NotImplementedError("unsupported mean-rate unit")
        factor = rates[interval.unit] * (interval.end - start)
    else:
        if interval.unit not in {"mm", "m", "kg m-2"}:
            raise NotImplementedError("unsupported amount unit")
        factor = F(1000) if interval.unit == "m" else F(1)
    return start, interval.end, F(lower) * factor, F(upper) * factor


def validate_case(case: Case):
    if case.query.calendar != "proleptic_gregorian":
        raise NotImplementedError("unsupported_calendar")
    if len(case.observations) > 4096:
        raise NotImplementedError("working model exceeds 4096 observations; narrow the Query")
    for obs in case.observations:
        if obs.series != case.query.series:
            raise ValueError("mixed SeriesKey: select one station/product/member/cycle")
        if obs.reset_group is not None and obs.reset_group != obs.series.cycle:
            raise ValueError("reset group must match SeriesKey cycle")
    for h in case.hypotheses:
        checkpoint()
        baselines = set()
        for obs in case.observations:
            if obs.qc != "accepted":
                continue
            spec = h.intervals.get(obs.id, obs.interval)
            if spec is None:
                raise NotImplementedError(
                    "unknown interval requires explicit alternatives or incomplete model"
                )
            if spec.statistic == "cumulative":
                if obs.series.cycle is None or obs.reset_group != obs.series.cycle:
                    raise ValueError(
                        "cumulative observations require explicit SeriesKey cycle and reset_group"
                    )
                baselines.add(spec.reset_start)
            normalized(spec, obs.lower, obs.upper)
        if len(baselines) > 1:
            raise ValueError("different cumulative reset baselines cannot be one SeriesKey cycle")


def compile_case(case: Case):
    """Compile each h separately; retain all alternatives including conflicts."""
    from .constraints import Edge

    if len(case.hypotheses) * len(case.observations) > 65536:
        raise TimeoutError("working-model observation/world budget exceeded")
    validate_case(case)
    worlds = {}
    times = {case.query.start, case.query.end}
    for h in case.hypotheses:
        checkpoint()
        edges = []
        for obs in case.observations:
            if obs.qc != "accepted":
                continue
            a, b, lo, hi = normalized(h.intervals.get(obs.id, obs.interval), obs.lower, obs.upper)
            times.update((a, b))
            edges.extend([Edge(a, b, hi), Edge(b, a, -lo)])
        worlds[h.id] = edges
    times = sorted(times)
    if len(times) > 1024 or len(times) * len(worlds) > 65536:
        raise TimeoutError("working-model endpoint/world budget exceeded; narrow the Query or H")
    monotone = [Edge(b, a, F(0)) for a, b in zip(times, times[1:])]
    for h, edges in worlds.items():
        checkpoint()
        worlds[h] = sorted(set(edges + monotone), key=lambda e: (e.u, e.v, e.w))
    return times, worlds
