from dataclasses import dataclass
from fractions import Fraction

from .domain import digest


@dataclass(frozen=True)
class Edge:
    u: int
    v: int
    w: Fraction

    @property
    def id(self):
        return digest([self.u, self.v, str(self.w)])[:24]

    def json(self):
        return {"id": self.id, "u": self.u, "v": self.v, "w": str(self.w)}
