"""Finite public likelihood model; policy APIs cannot access the simulator's truth."""

import math
import random
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Action:
    id: str
    kind: str
    cost: float
    outcomes: tuple[str, ...]  # public predicted outcomes for every possible state
    bytes: int = 0


@dataclass(frozen=True)
class Task:
    id: str
    labels: tuple[int, ...]
    priors: tuple[float, ...]
    actions: tuple[Action, ...]


def branches(task, states, action):
    groups = {}
    for i in states:
        groups.setdefault(action.outcomes[i], []).append(i)
    total = sum(task.priors[i] for i in states)
    return [(sum(task.priors[i] for i in group) / total, tuple(group)) for group in groups.values()]


def done(task, states):
    return len({task.labels[i] for i in states}) == 1


def risk(task, states):
    mass = {}
    total = sum(task.priors[i] for i in states)
    for i in states:
        mass[task.labels[i]] = mass.get(task.labels[i], 0) + task.priors[i] / total
    return 1 - max(mass.values())


def select_action(task: Task, states: tuple[int, ...], available: tuple[int, ...], policy, seed=42):
    """Only public model/posterior/actions. No simulator, true index, or answer callback."""
    useful = [a for a in available if len({task.actions[a].outcomes[i] for i in states}) > 1]
    if not useful:
        return None
    if policy == "fixed":
        return useful[0]
    if policy == "random":
        return random.Random(seed).choice(useful)

    def voi(a):
        return (
            risk(task, states) - sum(p * risk(task, s) for p, s in branches(task, states, task.actions[a]))
        ) / task.actions[a].cost

    if policy == "voi":
        return max(useful, key=lambda a: (voi(a), -a))
    if policy == "voi2":
        # Two-step Bayes risk + acquisition costs, fixed terminal error loss=10.
        # This stronger adaptation addresses zero immediate VOI on complementary questions.
        def horizon_two(a):
            action = task.actions[a]
            loss = action.cost
            for probability, subset in branches(task, states, action):
                if done(task, subset):
                    continue
                tail = 10 * risk(task, subset)
                for b in useful:
                    if b != a:
                        tail = min(
                            tail,
                            task.actions[b].cost
                            + 10 * sum(p * risk(task, s) for p, s in branches(task, subset, task.actions[b])),
                        )
                loss += probability * tail
            return loss

        return min(useful, key=lambda a: (horizon_two(a), a))
    if policy == "entropy":
        return max(
            useful,
            key=lambda a: (
                sum(-p * math.log2(p) for p, _ in branches(task, states, task.actions[a]))
                / task.actions[a].cost,
                -a,
            ),
        )
    if policy == "drd":
        # EC2/HEC specialization to disjoint decision regions; no continuous HEC claim.
        total = sum(task.priors[i] for i in states)
        pairs = [
            (i, j, task.priors[i] * task.priors[j] / total**2)
            for i in states
            for j in states
            if i < j and task.labels[i] != task.labels[j]
        ]

        def edgecut(a):
            action = task.actions[a]
            weights = {}
            for i in states:
                weights[action.outcomes[i]] = weights.get(action.outcomes[i], 0) + task.priors[i] / total
            residual = sum(
                w * weights[action.outcomes[i]]
                for i, j, w in pairs
                if action.outcomes[i] == action.outcomes[j]
            )
            return (sum(w for _, _, w in pairs) - residual) / action.cost

        return max(useful, key=lambda a: (edgecut(a), -a))
    if policy == "optimal":

        @lru_cache(None)
        def value(subset, actions):
            if done(task, subset):
                return 0.0
            candidates = [a for a in actions if len({task.actions[a].outcomes[i] for i in subset}) > 1]
            if not candidates:
                return float("inf")
            return min(
                task.actions[a].cost
                + sum(
                    p * value(s, tuple(k for k in actions if k != a))
                    for p, s in branches(task, subset, task.actions[a])
                )
                for a in candidates
            )

        return min(
            useful,
            key=lambda a: (
                task.actions[a].cost
                + sum(
                    p * value(s, tuple(k for k in available if k != a))
                    for p, s in branches(task, states, task.actions[a])
                ),
                a,
            ),
        )
    if policy == "witness":
        low = min(states, key=lambda i: (task.labels[i], i))
        high = max(states, key=lambda i: (task.labels[i], -i))
        separating = [a for a in useful if task.actions[a].outcomes[low] != task.actions[a].outcomes[high]]
        if separating:
            return max(separating, key=lambda a: (1 / task.actions[a].cost, voi(a), -a))

        # Bounded two-step lookahead over the same public likelihood model.
        def lookahead(a):
            expected = 0.0
            for prob, subset in branches(task, states, task.actions[a]):
                next_risks = [risk(task, subset)]
                for b in useful:
                    if b != a:
                        next_risks.append(
                            sum(p * risk(task, s) for p, s in branches(task, subset, task.actions[b]))
                        )
                expected += prob * min(next_risks)
            return (risk(task, states) - expected) / task.actions[a].cost

        return max(useful, key=lambda a: (lookahead(a), -a))
    raise ValueError("unknown policy")


class Simulator:
    def __init__(self, task, true_state):
        self._task, self.__true_state = task, true_state

    def act(self, action_index):
        return self._task.actions[action_index].outcomes[self.__true_state]


def policy_tasks(fetch_multiplier=1.0):
    tasks = []
    bits = [tuple((i >> k) & 1 for k in range(3)) for i in range(8)]
    functions = [
        lambda b: b[0],
        lambda b: b[0] ^ b[1],
        lambda b: b[0] & b[1],
        lambda b: (b[0] + b[1] + b[2]) >= 2,
        lambda b: b[2],
        lambda b: b[0] ^ b[1] ^ b[2],
    ]
    for i, fn in enumerate(functions):
        labels = tuple(int(fn(b)) for b in bits)
        priors = tuple([1 / 8] * 8 if i % 2 == 0 else [0.30, 0.20, 0.15, 0.10, 0.08, 0.07, 0.06, 0.04])
        actions = [
            Action(f"metadata-bit-{k}", "metadata", (1, 1.5, 0.75)[k], tuple(str(b[k]) for b in bits))
            for k in range(3)
        ]
        actions.append(
            Action(
                "fetch-target-interval",
                "observation",
                (2.5 if i < 3 else 4) * fetch_multiplier,
                tuple(str(1 + label) for label in labels),
                bytes=128,
            )
        )
        tasks.append(Task(f"decision-family-{i}", labels, priors, tuple(actions)))
    return tasks
