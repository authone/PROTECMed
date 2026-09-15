"""Run and local-party state machines (blueprint 4.7).

Transitions are explicit and one-way: there is no path back into a completed phase and
no path out of a terminal state. `transition` is a compare-and-set helper; the durable
transaction that persists it belongs to the service layer (M4).
"""
from __future__ import annotations
from .errors import ProtocolError

RUN_TERMINAL = frozenset({"REVEALED", "CLOSED", "REJECTED", "EXPIRED", "ABORTED",
                          "INTEGRITY_HOLD"})

# Any non-terminal run state may fail into one of these.
_RUN_FAILURES = ("REJECTED", "EXPIRED", "ABORTED", "INTEGRITY_HOLD")

RUN_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "DRAFT": ("PLAN_ACCEPTED", *_RUN_FAILURES),
    "PLAN_ACCEPTED": ("CONTEXT_READY", *_RUN_FAILURES),
    "CONTEXT_READY": ("KEYGEN", *_RUN_FAILURES),
    "KEYGEN": ("EPOCH_CONFIRMED", *_RUN_FAILURES),
    "EPOCH_CONFIRMED": ("COLLECTING", *_RUN_FAILURES),
    "COLLECTING": ("INPUTS_LOCKED", *_RUN_FAILURES),
    "INPUTS_LOCKED": ("EVALUATED", *_RUN_FAILURES),
    "EVALUATED": ("APPROVAL_PENDING", *_RUN_FAILURES),
    "APPROVAL_PENDING": ("PARTIALS_IN_PROGRESS", *_RUN_FAILURES),
    "PARTIALS_IN_PROGRESS": ("REVEALED", *_RUN_FAILURES),
    "REVEALED": ("CLOSED",),
    "CLOSED": (),
    "REJECTED": (),
    "EXPIRED": (),
    "ABORTED": (),
    "INTEGRITY_HOLD": (),
}

PARTY_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "IMPORTED": ("PLAN_ACCEPTED", "CLOSED"),
    "PLAN_ACCEPTED": ("SHARE_CREATED", "CLOSED"),
    "SHARE_CREATED": ("EPOCH_CONFIRMED", "CLOSED"),
    "EPOCH_CONFIRMED": ("SUBMITTED", "CLOSED"),
    "SUBMITTED": ("REQUEST_VERIFIED", "CLOSED"),
    "REQUEST_VERIFIED": ("PARTIAL_RESERVED", "CLOSED"),
    "PARTIAL_RESERVED": ("PARTIAL_COMMITTED", "CLOSED"),
    "PARTIAL_COMMITTED": ("PARTIAL_SENT", "CLOSED"),
    "PARTIAL_SENT": ("CLOSED",),
    "CLOSED": (),
}


class StateMachine:
    def __init__(self, transitions: dict[str, tuple[str, ...]], state: str) -> None:
        if state not in transitions:
            raise ProtocolError("UNKNOWN_STATE")
        self._transitions = transitions
        self.state = state

    def can(self, target: str) -> bool:
        return target in self._transitions.get(self.state, ())

    def transition(self, target: str) -> str:
        if target not in self._transitions:
            raise ProtocolError("UNKNOWN_STATE", {"target": target})
        if not self.can(target):
            raise ProtocolError("ILLEGAL_TRANSITION", {"from": self.state, "to": target})
        self.state = target
        return self.state

    def require(self, *expected: str) -> None:
        if self.state not in expected:
            raise ProtocolError("WRONG_STATE", {"state": self.state,
                                                "expected": list(expected)})


def run_machine(state: str = "DRAFT") -> StateMachine:
    return StateMachine(RUN_TRANSITIONS, state)


def party_machine(state: str = "IMPORTED") -> StateMachine:
    return StateMachine(PARTY_TRANSITIONS, state)
