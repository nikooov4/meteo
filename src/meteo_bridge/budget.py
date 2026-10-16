"""Per-request deadlines and operation counters, isolated across threads/requests."""

import time
from contextvars import ContextVar

_STATE = ContextVar("meteo_execution", default=None)


def begin(timeout):
    state = {"deadline": time.perf_counter() + timeout, "counts": {}}
    return _STATE.set(state), state


def end(token):
    _STATE.reset(token)


def checkpoint():
    state = _STATE.get()
    if state and time.perf_counter() >= state["deadline"]:
        raise TimeoutError("solver deadline exceeded; search incomplete")


def count(name, amount=1):
    state = _STATE.get()
    if state:
        counters = state["counts"]
        counters[name] = counters.get(name, 0) + amount
