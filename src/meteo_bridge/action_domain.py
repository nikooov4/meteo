"""Public, deterministic acquisition models. No simulator answers are inputs."""

from fractions import Fraction
from typing import Literal

from pydantic import model_validator

from .domain import Model


class AcquisitionAction(Model):
    id: str
    kind: Literal["interval", "metadata"] = "interval"
    cost: str = "1"
    start: int | None = None
    end: int | None = None
    attribute: str | None = None

    @model_validator(mode="after")
    def check(self):
        if Fraction(self.cost) <= 0:
            raise ValueError("action cost must be positive")
        if self.kind == "interval":
            if self.start is None or self.end is None or self.end <= self.start or self.attribute is not None:
                raise ValueError("interval action needs start < end, in Query SeriesKey and mm")
        elif not self.attribute or self.start is not None or self.end is not None:
            raise ValueError("metadata action needs an attribute only")
        return self


def validate_actions(case, actions):
    if not actions or len(actions) > 128 or len({a.id for a in actions}) != len(actions):
        raise ValueError("need 1..128 actions with unique ids")
    if len(case.hypotheses) > 16:
        raise ValueError("acquisition working-model limit: 16 hypotheses")
    if len(actions) * len(case.hypotheses) ** 2 > 4096:
        raise ValueError("acquisition certificate budget: at most 4096 ordered action-pairs")
    for action in actions:
        if action.kind == "metadata" and any(action.attribute not in h.assignments for h in case.hypotheses):
            raise ValueError("metadata response must be declared for every h, including explicit unknown")


def compatible(action, left, right):
    return (
        action.kind == "interval" or left.assignments[action.attribute] == right.assignments[action.attribute]
    )
