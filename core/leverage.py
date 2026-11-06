"""Verified-leverage and sealed-bid checks for every outbound buyer message.

A negotiator may say "a qualified supplier has offered ₹37.90 delivered" ONLY if Core's ledger
holds a real, current, comparable offer at that price from a different, non-disqualified vendor.
It may never name a competitor or quote a number that isn't backed by the ledger.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import Basis, LeverageClaim
from .money import fmt_unit, to_paise

AMOUNT_RE = re.compile(r"(?:₹|Rs\.?|INR)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.IGNORECASE)


@dataclass
class Source:
    """A price the buyer genuinely holds: a valid comparable quote or a vendor's offer at our quantity."""
    ref: str                 # offer id or quote id (internal only)
    vendor_id: str
    landed_unit_paise: int
    kind: str                # "offer" | "quote"


@dataclass
class OutboundContext:
    target_vendor_id: str
    quantity: int
    sources: list[Source]
    # Numbers that are fine to mention in THIS room: our own asks, this vendor's own quote/offers.
    own_prices_paise: set[int] = field(default_factory=set)
    # Names/identifiers of OTHER vendors that must never appear in this room.
    forbidden_terms: list[str] = field(default_factory=list)
    tolerance_paise: int = 1


@dataclass
class OutboundVerdict:
    approved: bool
    claims: list[LeverageClaim]
    reasons: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {"approved": self.approved, "claims": [c.model_dump() for c in self.claims], "reasons": self.reasons}


def amounts_in(text: str) -> list[int]:
    out = []
    for m in AMOUNT_RE.finditer(text):
        try:
            out.append(to_paise(m.group(1)))
        except ValueError:
            continue
    return out


def verify_claim(claim: LeverageClaim, ctx: OutboundContext) -> LeverageClaim:
    c = claim.model_copy()
    candidates = [s for s in ctx.sources if s.vendor_id != ctx.target_vendor_id]
    for s in candidates:
        if abs(s.landed_unit_paise - c.unit_price_paise) <= ctx.tolerance_paise:
            c.verified = True
            c.source_offer_id = s.ref
            c.reason = f"matches a current {s.kind} in the ledger"
            return c
    c.verified = False
    if not candidates:
        c.reason = "no competing offer exists in the ledger"
    else:
        best = min(s.landed_unit_paise for s in candidates)
        if c.unit_price_paise < best:
            c.reason = (f"claimed {fmt_unit(c.unit_price_paise)} is lower than any verified competing offer "
                        f"(best is {fmt_unit(best)}) — fabricated leverage")
        else:
            c.reason = f"no verified competing offer at {fmt_unit(c.unit_price_paise)}"
    return c


def check_outbound(message_text: str, claims: list[LeverageClaim], ctx: OutboundContext) -> OutboundVerdict:
    reasons: list[str] = []
    checked = [verify_claim(c, ctx) for c in claims]
    for c in checked:
        if not c.verified:
            reasons.append(f"Unverifiable price claim: {c.reason}.")

    # Sealed-bid rule: never name or identify another vendor in this room.
    low = message_text.lower()
    for term in ctx.forbidden_terms:
        if term and term.lower() in low:
            reasons.append(f"Message identifies another supplier ('{term}'). Claims must stay anonymous.")

    # Every rupee amount in the text must be backed by the ledger.
    allowed = set(ctx.own_prices_paise) | {c.unit_price_paise for c in checked if c.verified}
    allowed_totals = {p * ctx.quantity for p in allowed}
    for amt in amounts_in(message_text):
        if any(abs(amt - a) <= ctx.tolerance_paise for a in allowed) or amt in allowed_totals:
            continue
        reasons.append(f"Message mentions {fmt_unit(amt)}, which is not a verified offer or our own ask.")

    # de-duplicate, keep order
    seen = set()
    reasons = [r for r in reasons if not (r in seen or seen.add(r))]
    return OutboundVerdict(approved=not reasons, claims=checked, reasons=reasons)


def basis_of(value: str | None) -> Basis:
    return Basis.EX_WORKS if (value or "").upper().startswith("EX") else Basis.DELIVERED
