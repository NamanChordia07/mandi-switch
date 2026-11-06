"""Negotiation strategy — the numbers. (LLMs only write the words around them.)

Buyer side lives here in Core. The vendor-side concession logic (`vendor_move`) is also here as a pure
function so it can be tested, but each vendor agent calls it with ITS OWN secret rules, which only that
vendor's process loads.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .money import round_down_to


@dataclass
class BuyerPolicy:
    max_rounds: int = 4
    target_discount: float = 0.08          # target <= best valid quote x (1 - 0.08)
    undercut_competing_paise: int = 50     # target <= verified competing - Rs 0.50
    opening_below_target_paise: int = 120  # opening ask = target - Rs 1.20
    concession_per_round_paise: int = 40   # concede at most Rs 0.40 per round


@dataclass
class BuyerMove:
    action: str                 # "ask" | "accept" | "walk_away" | "requote"
    round: int
    ask_paise: Optional[int] = None
    accept_offer_paise: Optional[int] = None
    leverage_paise: Optional[int] = None    # verified competing landed price to cite (anonymised)
    target_paise: Optional[int] = None
    max_acceptable_paise: Optional[int] = None
    reason: str = ""


def buyer_target(best_valid_quote_paise: Optional[int], competing_paise: Optional[int], p: BuyerPolicy) -> Optional[int]:
    candidates = []
    if competing_paise is not None:
        candidates.append(competing_paise - p.undercut_competing_paise)
    if best_valid_quote_paise is not None:
        candidates.append(int(best_valid_quote_paise * (1 - p.target_discount)))
    if not candidates:
        return None
    return round_down_to(min(candidates), 10)


def buyer_next_move(*, round_no: int, vendor_offer_paise: Optional[int], vendor_is_final: bool,
                    vendor_quote_comparable: bool, best_valid_quote_paise: Optional[int],
                    competing_paise: Optional[int], previous_ask_paise: Optional[int],
                    p: BuyerPolicy = BuyerPolicy()) -> BuyerMove:
    """Decide the buyer's next move in one sealed room.

    round_no: the round we are about to play (1-based).
    vendor_offer_paise: the vendor's latest offer AT OUR QUANTITY (landed), or None if we don't have one yet.
    competing_paise: best verified landed price from OTHER vendors (anonymised leverage), or None.
    """
    # A vendor whose quote isn't valid at our quantity (e.g. MOQ trap) must first re-quote for our lot.
    if vendor_offer_paise is None:
        return BuyerMove(action="requote", round=round_no, reason="need a price for our exact quantity")

    reference = best_valid_quote_paise if best_valid_quote_paise is not None else vendor_offer_paise
    target = buyer_target(reference, competing_paise, p)
    # The most we'd ever pay this vendor: no worse than the competing verified offer, nor the best valid quote.
    ceilings = [x for x in (competing_paise, reference) if x is not None]
    max_acceptable = min(ceilings) if ceilings else vendor_offer_paise
    if competing_paise is not None and competing_paise > vendor_offer_paise:
        max_acceptable = max(max_acceptable, vendor_offer_paise)

    if target is not None and vendor_offer_paise <= target:
        return BuyerMove(action="accept", round=round_no, accept_offer_paise=vendor_offer_paise,
                         target_paise=target, max_acceptable_paise=max_acceptable,
                         reason="offer is at or below our target")
    if vendor_is_final:
        if vendor_offer_paise <= max_acceptable and (competing_paise is None or vendor_offer_paise < competing_paise):
            return BuyerMove(action="accept", round=round_no, accept_offer_paise=vendor_offer_paise,
                             target_paise=target, max_acceptable_paise=max_acceptable,
                             reason="final offer beats every verified alternative")
        return BuyerMove(action="walk_away", round=round_no, target_paise=target,
                         max_acceptable_paise=max_acceptable,
                         reason="final offer does not beat a verified alternative")
    if round_no > p.max_rounds:
        if vendor_offer_paise <= max_acceptable and (competing_paise is None or vendor_offer_paise < competing_paise):
            return BuyerMove(action="accept", round=round_no, accept_offer_paise=vendor_offer_paise,
                             target_paise=target, max_acceptable_paise=max_acceptable, reason="round limit reached")
        return BuyerMove(action="walk_away", round=round_no, target_paise=target,
                         max_acceptable_paise=max_acceptable, reason="round limit reached")

    if previous_ask_paise is None:
        ask = (target or vendor_offer_paise) - p.opening_below_target_paise
    else:
        ask = previous_ask_paise + p.concession_per_round_paise
    if target is not None:
        ask = min(ask, target)
    ask = min(ask, vendor_offer_paise - 10)
    leverage = competing_paise if (competing_paise is not None and competing_paise < vendor_offer_paise) else None
    return BuyerMove(action="ask", round=round_no, ask_paise=ask, leverage_paise=leverage, target_paise=target,
                     max_acceptable_paise=max_acceptable, reason="counter within policy")


# ----------------------------------------------------------------------------- vendor side
@dataclass
class VendorRules:
    list_price_paise: int
    concession_schedule_paise: list[int]
    approval_line_paise: int
    floor_paise: int


@dataclass
class VendorMove:
    action: str                     # "counter" | "accept" | "need_approval" | "final"
    price_paise: int
    reason: str = ""


def vendor_move(*, buyer_ask_paise: int, steps_taken: int, rules: VendorRules,
                owner_decision: Optional[str] = None) -> VendorMove:
    """Vendor's reply to a buyer ask.

    steps_taken: how many concession-schedule steps the vendor has already offered.
    owner_decision: None (not asked yet) | "APPROVED" | "DECLINED" for this exact ask.
    """
    if buyer_ask_paise >= rules.approval_line_paise:
        return VendorMove("accept", buyer_ask_paise, "ask is at or above our approval line")
    if steps_taken < len(rules.concession_schedule_paise):
        nxt = rules.concession_schedule_paise[steps_taken]
        if nxt > rules.approval_line_paise:
            return VendorMove("counter", nxt, "next step on our concession ladder")
    # Ladder exhausted: we are at our approval line.
    if buyer_ask_paise < rules.floor_paise:
        return VendorMove("final", rules.approval_line_paise, "ask is below our absolute floor")
    if owner_decision is None:
        return VendorMove("need_approval", buyer_ask_paise, "below our approval line - owner must decide")
    if owner_decision == "APPROVED":
        return VendorMove("accept", buyer_ask_paise, "owner approved going below the line")
    return VendorMove("final", rules.approval_line_paise, "owner declined; final offer at our approval line")
