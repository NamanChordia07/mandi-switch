"""The PO gate — Lock 3. Code, not prompts, decides whether money can move.

`gate_checks` is a pure function: given facts about an order it returns every failed check in plain English.
Even if an agent were fooled (prompt injection, social engineering) and even if a human mis-clicked,
a PO is refused unless ALL checks pass.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from .money import fmt_inr


@dataclass
class GateFacts:
    caller: str                                 # auth class of the caller
    order_state: str
    tier_name: Optional[str]
    tier_approvers: tuple[str, ...]
    endorsements: tuple[str, ...]               # approver roles already recorded as APPROVED
    awarded_offer_status: Optional[str]
    awarded_vendor_id: Optional[str]
    requested_vendor_id: Optional[str]          # vendor named in the request (None = awarded vendor)
    vendor_status: Optional[str]
    quote_valid_until: Optional[date]
    today: date
    unit_price_paise: Optional[int]
    quantity: Optional[int]
    total_paise: Optional[int]
    existing_po_id: Optional[str]


def gate_checks(f: GateFacts) -> list[str]:
    failed: list[str] = []
    if f.caller != "mcp_po_issuer":
        failed.append("Only the po-issuer agent (Vikram's) may issue purchase orders.")
    if f.existing_po_id:
        failed.append(f"A purchase order ({f.existing_po_id}) has already been issued for this order.")
    if f.awarded_vendor_id is None or f.awarded_offer_status != "ACCEPTED":
        failed.append("There is no accepted, awarded offer for this order.")
    if f.requested_vendor_id and f.awarded_vendor_id and f.requested_vendor_id != f.awarded_vendor_id:
        failed.append(f"The request names vendor '{f.requested_vendor_id}', but the award went to "
                      f"'{f.awarded_vendor_id}'.")
    if f.vendor_status == "DISQUALIFIED":
        failed.append("The vendor is disqualified.")
    if f.quote_valid_until is not None and f.quote_valid_until < f.today:
        failed.append("The vendor's quote has expired.")
    needs = set(f.tier_approvers) - {"finance"}   # finance approval is THIS call (via Switch permission)
    missing = needs - set(f.endorsements)
    if f.tier_name is None:
        failed.append("No approval tier has been computed for this order.")
    if "purchase_head" in missing:
        failed.append("The purchase head (Meera) has not endorsed this award.")
    allowed_states = {"ENDORSED_PURCHASE_HEAD", "ENDORSED_FINANCE"} if "purchase_head" in f.tier_approvers \
        else {"AWARDED", "ENDORSED_PURCHASE_HEAD", "ENDORSED_FINANCE"}
    if f.order_state not in allowed_states:
        failed.append(f"Order is in state {f.order_state}; a PO needs {' or '.join(sorted(allowed_states))}.")
    if None in (f.unit_price_paise, f.quantity, f.total_paise):
        failed.append("Price or quantity is missing from the ledger.")
    elif f.unit_price_paise * f.quantity != f.total_paise:
        failed.append(f"Total {fmt_inr(f.total_paise)} does not equal unit price x quantity.")
    return failed
