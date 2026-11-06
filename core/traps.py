"""Quote validation: the procurement traps a tired human misses.

Pure functions — no database, no network — so every rule is unit-tested.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .models import Basis, Evidence, InjectionVerdict, Severity, Trap, TrapCode
from .money import fmt_inr, fmt_unit, indian_group

REQUIRED_FIELDS = ["unit_price_paise", "basis", "moq", "lead_time_days", "valid_until", "payment_terms_days"]
FIELD_LABELS = {
    "unit_price_paise": "unit price",
    "basis": "price basis (delivered / ex-works)",
    "moq": "minimum order quantity",
    "lead_time_days": "lead time",
    "valid_until": "validity date",
    "payment_terms_days": "payment terms",
}
# Used only when an ex-works quote gives no freight figure. Clearly labelled as an estimate.
DEFAULT_FREIGHT_ESTIMATE_PAISE = 60


@dataclass
class QuoteFacts:
    vendor_id: str
    unit_price_paise: int | None = None
    basis: str | None = None
    freight_paise_per_unit: int | None = None
    moq: int | None = None
    lead_time_days: int | None = None
    valid_until: date | None = None
    payment_terms_days: int | None = None
    injection_verdict: str = InjectionVerdict.CLEAN.value
    injection_spans: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)  # field -> {"page": int, "snippet": str}


@dataclass
class TrapResult:
    traps: list[Trap]
    comparable: bool
    landed_unit_paise: int | None
    landed_total_paise: int | None
    freight_assumed: bool = False


def _ev(facts: QuoteFacts, key: str) -> Evidence:
    e = facts.evidence.get(key) or {}
    return Evidence(page=e.get("page"), snippet=e.get("snippet", ""))


def _fmt_date(d: date) -> str:
    return d.strftime("%d %b %Y").lstrip("0")


def evaluate(facts: QuoteFacts, *, quantity: int, needed_by: date, today: date) -> TrapResult:
    traps: list[Trap] = []
    blocked = False

    # 1. Missing fields
    missing = [f for f in REQUIRED_FIELDS if getattr(facts, f) in (None, "")]
    for f in missing:
        traps.append(Trap(code=TrapCode.MISSING_FIELD, severity=Severity.WARNING,
                          message=f"The quote does not state the {FIELD_LABELS[f]}."))
    if facts.unit_price_paise is None:
        blocked = True

    # 2. Expired validity
    if facts.valid_until is not None and facts.valid_until < today:
        days = (today - facts.valid_until).days
        traps.append(Trap(code=TrapCode.EXPIRED, severity=Severity.BLOCKER,
                          message=f"Quote expired {days} day{'s' if days != 1 else ''} ago "
                                  f"(valid until {_fmt_date(facts.valid_until)}). The price can't be relied on.",
                          evidence=_ev(facts, "valid_until")))
        blocked = True

    # 3. MOQ larger than our quantity
    if facts.moq is not None and facts.moq > quantity:
        extra = facts.moq - quantity
        extra_value = extra * (facts.unit_price_paise or 0)
        traps.append(Trap(code=TrapCode.HIDDEN_MOQ, severity=Severity.BLOCKER,
                          message=f"Minimum order is {indian_group(facts.moq)}; we need {indian_group(quantity)}. "
                                  f"Buying at this price means {indian_group(extra)} extra pieces "
                                  f"({fmt_inr(extra_value, decimals=False)} of unwanted stock).",
                          evidence=_ev(facts, "moq")))
        blocked = True

    # 4. Late delivery
    if facts.lead_time_days is not None:
        arrives = date.fromordinal(today.toordinal() + facts.lead_time_days)
        if arrives > needed_by:
            late = (arrives - needed_by).days
            traps.append(Trap(code=TrapCode.LATE_DELIVERY, severity=Severity.BLOCKER,
                              message=f"Lead time {facts.lead_time_days} days means delivery on {_fmt_date(arrives)}, "
                                      f"{late} day{'s' if late != 1 else ''} after the needed-by date "
                                      f"({_fmt_date(needed_by)}).",
                              evidence=_ev(facts, "lead_time_days")))
            blocked = True

    # 5. Freight not included -> landed cost
    landed_unit = facts.unit_price_paise
    freight_assumed = False
    if facts.basis == Basis.EX_WORKS.value and facts.unit_price_paise is not None:
        freight = facts.freight_paise_per_unit
        if freight is None:
            freight = DEFAULT_FREIGHT_ESTIMATE_PAISE
            freight_assumed = True
        landed_unit = facts.unit_price_paise + freight
        traps.append(Trap(code=TrapCode.FREIGHT_EXCLUDED, severity=Severity.WARNING,
                          message=f"Price is ex-works: freight is extra (+{fmt_unit(freight)}/pc "
                                  f"{'assumed' if freight_assumed else 'estimated'}). "
                                  f"Landed cost {fmt_unit(landed_unit)}/pc.",
                          evidence=_ev(facts, "basis")))

    # 6. Prompt injection
    if facts.injection_verdict == InjectionVerdict.INJECTION.value:
        snippet = facts.injection_spans[0] if facts.injection_spans else ""
        traps.append(Trap(code=TrapCode.INJECTION, severity=Severity.BLOCKER,
                          message="The document contains hidden instructions aimed at our AI agents. "
                                  "Vendor disqualified.",
                          evidence=Evidence(snippet=snippet[:400])))
        blocked = True

    landed_total = landed_unit * quantity if landed_unit is not None else None
    return TrapResult(traps=traps, comparable=not blocked, landed_unit_paise=landed_unit,
                      landed_total_paise=landed_total, freight_assumed=freight_assumed)
