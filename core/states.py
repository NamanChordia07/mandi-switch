"""Order state machine. Every state change goes through `check_transition`; illegal moves raise."""
from __future__ import annotations

from enum import Enum


class OrderState(str, Enum):
    DRAFT = "DRAFT"
    SPEC_CONFIRMED = "SPEC_CONFIRMED"
    RFQ_OPEN = "RFQ_OPEN"
    QUOTES_RECEIVED = "QUOTES_RECEIVED"
    COMPARED = "COMPARED"
    NEGOTIATING = "NEGOTIATING"
    NEGOTIATION_CLOSED = "NEGOTIATION_CLOSED"
    AWARDED = "AWARDED"
    ENDORSED_PURCHASE_HEAD = "ENDORSED_PURCHASE_HEAD"
    ENDORSED_FINANCE = "ENDORSED_FINANCE"
    PO_ISSUED = "PO_ISSUED"
    CANCELLED = "CANCELLED"


S = OrderState

# Allowed transitions. Anything not listed here is refused.
TRANSITIONS: dict[OrderState, set[OrderState]] = {
    S.DRAFT: {S.SPEC_CONFIRMED, S.CANCELLED},
    S.SPEC_CONFIRMED: {S.RFQ_OPEN, S.CANCELLED},
    S.RFQ_OPEN: {S.QUOTES_RECEIVED, S.CANCELLED},
    S.QUOTES_RECEIVED: {S.COMPARED, S.CANCELLED},
    S.COMPARED: {S.NEGOTIATING, S.CANCELLED},
    S.NEGOTIATING: {S.NEGOTIATION_CLOSED, S.CANCELLED},
    S.NEGOTIATION_CLOSED: {S.AWARDED, S.CANCELLED},
    # AWARDED -> PO_ISSUED is only for the auto tier (no human approvals needed).
    # AWARDED -> NEGOTIATION_CLOSED is the back-edge when the purchase head declines.
    S.AWARDED: {S.ENDORSED_PURCHASE_HEAD, S.PO_ISSUED, S.NEGOTIATION_CLOSED, S.CANCELLED},
    # ENDORSED_PURCHASE_HEAD -> PO_ISSUED is for the purchase_head tier (finance not needed).
    S.ENDORSED_PURCHASE_HEAD: {S.ENDORSED_FINANCE, S.PO_ISSUED, S.CANCELLED},
    S.ENDORSED_FINANCE: {S.PO_ISSUED, S.CANCELLED},
    S.PO_ISSUED: set(),
    S.CANCELLED: set(),
}

# Linear order used by the UI stepper and "at least this far" checks.
ORDER = [
    S.DRAFT, S.SPEC_CONFIRMED, S.RFQ_OPEN, S.QUOTES_RECEIVED, S.COMPARED, S.NEGOTIATING,
    S.NEGOTIATION_CLOSED, S.AWARDED, S.ENDORSED_PURCHASE_HEAD, S.ENDORSED_FINANCE, S.PO_ISSUED,
]


class IllegalTransition(Exception):
    def __init__(self, current: OrderState, target: OrderState):
        super().__init__(f"Order cannot move from {current.value} to {target.value}.")
        self.current = current
        self.target = target


def check_transition(current: OrderState | str, target: OrderState | str) -> OrderState:
    cur = OrderState(current)
    tgt = OrderState(target)
    if tgt not in TRANSITIONS[cur]:
        raise IllegalTransition(cur, tgt)
    return tgt


def at_least(current: OrderState | str, milestone: OrderState) -> bool:
    cur = OrderState(current)
    if cur == S.CANCELLED:
        return False
    return ORDER.index(cur) >= ORDER.index(milestone)
