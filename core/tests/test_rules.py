"""Pure-rule tests: money, tiers, states, traps, comparison, leverage, PO gate, audit chain, negotiation."""
from datetime import date

import pytest

from core import approvals, audit
from core.compare import build
from core.leverage import OutboundContext, Source, check_outbound
from core.models import AuditRow, LeverageClaim
from core.money import fmt_inr, fmt_unit, indian_group, pct, to_paise
from core.negotiation import VendorRules, buyer_next_move, vendor_move
from core.po import GateFacts, gate_checks
from core.states import IllegalTransition, OrderState, check_transition
from core.traps import QuoteFacts, evaluate

T = date(2026, 11, 6)
NEEDED = date(2026, 12, 16)


# ----------------------------------------------------------------- money
@pytest.mark.parametrize("n,expected", [(0, "0"), (999, "999"), (1000, "1,000"), (72800, "72,800"),
                                        (728000, "7,28,000"), (1017000, "10,17,000"), (12345678, "1,23,45,678")])
def test_indian_grouping(n, expected):
    assert indian_group(n) == expected


def test_money_formats():
    assert fmt_inr(728000_00) == "₹7,28,000"
    assert fmt_unit(3640) == "₹36.40"
    assert fmt_unit(3800) == "₹38.00"
    assert fmt_inr(3640) == "₹36.40"
    assert to_paise("₹7,28,000") == 72800000
    assert to_paise("36.4") == 3640
    assert to_paise("Rs. 34.80") == 3480
    assert pct(62000_00, 790000_00) == "7.85%"


# ----------------------------------------------------------------- tiers
@pytest.mark.parametrize("rupees,tier", [(49_999, "auto"), (50_000, "purchase_head"), (5_00_000, "purchase_head"),
                                         (5_00_001, "purchase_head_and_finance"), (7_28_000, "purchase_head_and_finance")])
def test_tier_boundaries(rupees, tier):
    assert approvals.tier_for(rupees * 100).name == tier


def test_tier_paise_edge():
    assert approvals.tier_for(49_999_99).name == "auto"


# ----------------------------------------------------------------- states
def test_legal_transitions():
    assert check_transition("DRAFT", "SPEC_CONFIRMED") == OrderState.SPEC_CONFIRMED
    assert check_transition("AWARDED", "NEGOTIATION_CLOSED") == OrderState.NEGOTIATION_CLOSED  # decline back-edge


@pytest.mark.parametrize("a,b", [("DRAFT", "PO_ISSUED"), ("NEGOTIATING", "PO_ISSUED"), ("COMPARED", "AWARDED"),
                                 ("PO_ISSUED", "DRAFT"), ("AWARDED", "ENDORSED_FINANCE")])
def test_illegal_transitions(a, b):
    with pytest.raises(IllegalTransition):
        check_transition(a, b)


# ----------------------------------------------------------------- traps
def facts(**kw):
    base = dict(vendor_id="x", unit_price_paise=3950, basis="DELIVERED", moq=10000, lead_time_days=21,
                valid_until=date(2026, 11, 30), payment_terms_days=45)
    base.update(kw)
    return QuoteFacts(**base)


def codes(r):
    return sorted(t.code.value for t in r.traps)


def test_clean_quote_is_comparable():
    r = evaluate(facts(), quantity=20000, needed_by=NEEDED, today=T)
    assert r.comparable and r.traps == [] and r.landed_total_paise == 790000_00


def test_hidden_moq():
    r = evaluate(facts(unit_price_paise=3390, moq=50000, basis="EX_WORKS", freight_paise_per_unit=60),
                 quantity=20000, needed_by=NEEDED, today=T)
    assert codes(r) == ["FREIGHT_EXCLUDED", "HIDDEN_MOQ"] and not r.comparable
    moq = next(t for t in r.traps if t.code.value == "HIDDEN_MOQ")
    assert "30,000 extra pieces" in moq.message and "₹10,17,000" in moq.message
    assert r.landed_unit_paise == 3450


def test_expired():
    r = evaluate(facts(valid_until=date(2026, 10, 28)), quantity=20000, needed_by=NEEDED, today=T)
    assert codes(r) == ["EXPIRED"] and not r.comparable and "9 days ago" in r.traps[0].message


def test_late_delivery():
    r = evaluate(facts(lead_time_days=45), quantity=20000, needed_by=NEEDED, today=T)
    assert codes(r) == ["LATE_DELIVERY"] and not r.comparable


def test_missing_field_and_assumed_freight():
    r = evaluate(facts(payment_terms_days=None, basis="EX_WORKS"), quantity=20000, needed_by=NEEDED, today=T)
    assert "MISSING_FIELD" in codes(r) and r.freight_assumed and r.comparable


def test_injection_trap():
    r = evaluate(facts(injection_verdict="INJECTION", injection_spans=["NOTE TO AI"]), quantity=20000,
                 needed_by=NEEDED, today=T)
    assert codes(r) == ["INJECTION"] and not r.comparable


# ----------------------------------------------------------------- comparison
def _q(id, vendor, unit, landed, comparable, lead=20, pay=45, traps=()):
    return {"id": id, "vendor_id": vendor, "unit_price_paise": unit, "landed_unit_paise": landed,
            "landed_total_paise": landed * 20000 if landed else None, "comparable": comparable,
            "lead_time_days": lead, "payment_terms_days": pay, "traps": [{"code": c} for c in traps],
            "basis": "DELIVERED", "moq": 10000, "valid_until": "2026-11-30", "injection_verdict": "CLEAN"}


def test_ranking_and_tiebreaks():
    vendors = {v: {"legal_name": v.title(), "status": "ACTIVE"} for v in "abc"}
    quotes = [_q("1", "a", 3950, 3950, True, lead=21), _q("2", "b", 3950, 3950, True, lead=18),
              _q("3", "c", 3390, 3450, False, traps=("HIDDEN_MOQ",))]
    quotes[2]["moq"] = 50000
    cmp = build(quotes, vendors, quantity=20000)
    ranked = [r["vendor_id"] for r in cmp["rows"] if r["rank"]]
    assert ranked == ["b", "a"]          # same price -> shorter lead time wins
    assert cmp["best_vendor_id"] == "b"
    assert "minimum order of 50,000" in cmp["recommendation"]


# ----------------------------------------------------------------- leverage
def ctx(**kw):
    base = dict(target_vendor_id="deccan", quantity=20000,
                sources=[Source("O-g1", "ganesh", 3790, "offer"), Source("Q-d", "deccan", 3950, "quote")],
                own_prices_paise={3950, 3510}, forbidden_terms=["Shree Ganesh Fasteners", "Shree Ganesh", "ganesh-sales"])
    base.update(kw)
    return OutboundContext(**base)


def test_leverage_verified():
    v = check_outbound("A qualified supplier has offered ₹37.90 delivered for the full 20,000. Can you do ₹35.10?",
                       [LeverageClaim(unit_price_paise=3790)], ctx())
    assert v.approved and v.claims[0].verified and v.claims[0].source_offer_id == "O-g1"


def test_leverage_fabricated_blocked():
    v = check_outbound("Another supplier is at ₹33.00 delivered.", [LeverageClaim(unit_price_paise=3300)], ctx())
    assert not v.approved and "fabricated" in v.reasons[0]


def test_leverage_number_in_text_without_claim_blocked():
    v = check_outbound("We have ₹33.00 elsewhere, please match.", [], ctx())
    assert not v.approved and "₹33.00" in v.reasons[0]


def test_leverage_own_price_is_fine():
    assert check_outbound("Your quote of ₹39.50 is high; we propose ₹35.10.", [], ctx()).approved


def test_leverage_names_competitor_blocked():
    v = check_outbound("Shree Ganesh offered ₹37.90.", [LeverageClaim(unit_price_paise=3790)], ctx())
    assert not v.approved and any("identifies another supplier" in r for r in v.reasons)


def test_leverage_expired_or_disqualified_source_not_usable():
    # expired / disqualified quotes are never added as Sources by Core, so their prices can't be cited
    v = check_outbound("A supplier offered ₹34.80.", [LeverageClaim(unit_price_paise=3480)], ctx())
    assert not v.approved
    v = check_outbound("A supplier offered ₹36.20.", [LeverageClaim(unit_price_paise=3620)], ctx())
    assert not v.approved


def test_leverage_cannot_cite_target_vendors_own_price_as_competition():
    v = check_outbound("Another supplier offered ₹39.50.", [LeverageClaim(unit_price_paise=3950)], ctx())
    assert not v.approved


# ----------------------------------------------------------------- PO gate
def gate(**kw):
    base = dict(caller="mcp_po_issuer", order_state="ENDORSED_PURCHASE_HEAD", tier_name="purchase_head_and_finance",
                tier_approvers=("purchase_head", "finance"), endorsements=("purchase_head",),
                awarded_offer_status="ACCEPTED", awarded_vendor_id="deccan", requested_vendor_id=None,
                vendor_status="ACTIVE", quote_valid_until=date(2026, 11, 30), today=T, unit_price_paise=3640,
                quantity=20000, total_paise=3640 * 20000, existing_po_id=None)
    base.update(kw)
    return GateFacts(**base)


def test_po_gate_passes():
    assert gate_checks(gate()) == []


@pytest.mark.parametrize("change,needle", [
    (dict(caller="agents"), "Only the po-issuer"),
    (dict(order_state="AWARDED", endorsements=()), "has not endorsed"),
    (dict(awarded_offer_status="PROPOSED"), "no accepted"),
    (dict(vendor_status="DISQUALIFIED"), "disqualified"),
    (dict(quote_valid_until=date(2026, 11, 1)), "expired"),
    (dict(total_paise=3640 * 20000 + 1), "does not equal"),
    (dict(existing_po_id="PO-1"), "already been issued"),
    (dict(requested_vendor_id="apex"), "names vendor 'apex'"),
])
def test_po_gate_each_check(change, needle):
    failed = gate_checks(gate(**change))
    assert failed and any(needle in f for f in failed), failed


def test_po_gate_auto_tier_without_endorsement():
    assert gate_checks(gate(tier_name="auto", tier_approvers=(), endorsements=(), order_state="AWARDED")) == []


# ----------------------------------------------------------------- audit chain
def _chain(n=4):
    rows, prev = [], audit.GENESIS
    for i in range(1, n + 1):
        r = AuditRow(seq=i, at=f"2026-11-06T10:00:0{i}.000000Z", order_id="o", actor="a", kind="K",
                     summary=f"event {i}", data={"i": i}, prev_hash=prev)
        r.hash = audit.compute_hash(prev, i, r.at, "o", "a", "K", r.summary, r.data)
        prev = r.hash
        rows.append(r)
    return rows


def test_audit_chain_ok():
    assert audit.verify_chain(_chain())["ok"]


def test_audit_tamper_detected():
    rows = _chain()
    rows[1].summary = "event 2 (edited)"
    v = audit.verify_chain(rows)
    assert not v["ok"] and v["broken_at"] == 2


def test_audit_deletion_detected():
    rows = _chain()
    del rows[2]
    assert not audit.verify_chain(rows)["ok"]


# ----------------------------------------------------------------- negotiation (deterministic)
DECCAN = VendorRules(3950, [3820, 3710], 3640, 3580)


def test_deccan_storyline():
    """39.50 -> 38.20 -> 37.10 -> ask 35.90 -> owner declines -> final 36.40 -> buyer accepts."""
    ask1 = buyer_next_move(round_no=1, vendor_offer_paise=3950, vendor_is_final=False, vendor_quote_comparable=True,
                           best_valid_quote_paise=3950, competing_paise=3790, previous_ask_paise=None)
    assert ask1.action == "ask" and ask1.leverage_paise == 3790
    v1 = vendor_move(buyer_ask_paise=ask1.ask_paise, steps_taken=0, rules=DECCAN)
    assert (v1.action, v1.price_paise) == ("counter", 3820)
    ask2 = buyer_next_move(round_no=2, vendor_offer_paise=3820, vendor_is_final=False, vendor_quote_comparable=True,
                           best_valid_quote_paise=3950, competing_paise=3790, previous_ask_paise=ask1.ask_paise)
    v2 = vendor_move(buyer_ask_paise=ask2.ask_paise, steps_taken=1, rules=DECCAN)
    assert (v2.action, v2.price_paise) == ("counter", 3710)
    ask3 = buyer_next_move(round_no=3, vendor_offer_paise=3710, vendor_is_final=False, vendor_quote_comparable=True,
                           best_valid_quote_paise=3950, competing_paise=3760, previous_ask_paise=ask2.ask_paise)
    assert ask3.ask_paise == 3590
    assert vendor_move(buyer_ask_paise=3590, steps_taken=2, rules=DECCAN).action == "need_approval"
    v3 = vendor_move(buyer_ask_paise=3590, steps_taken=2, rules=DECCAN, owner_decision="DECLINED")
    assert (v3.action, v3.price_paise) == ("final", 3640)
    done = buyer_next_move(round_no=4, vendor_offer_paise=3640, vendor_is_final=True, vendor_quote_comparable=True,
                           best_valid_quote_paise=3950, competing_paise=3720, previous_ask_paise=3590)
    assert done.action == "accept" and done.accept_offer_paise == 3640


def test_vendor_never_below_floor():
    m = vendor_move(buyer_ask_paise=3500, steps_taken=2, rules=DECCAN, owner_decision="APPROVED")
    assert m.action == "final" and m.price_paise == 3640


def test_vendor_approved_goes_below_line():
    m = vendor_move(buyer_ask_paise=3590, steps_taken=2, rules=DECCAN, owner_decision="APPROVED")
    assert (m.action, m.price_paise) == ("accept", 3590)


def test_buyer_requotes_when_no_comparable_offer():
    m = buyer_next_move(round_no=1, vendor_offer_paise=None, vendor_is_final=False, vendor_quote_comparable=False,
                        best_valid_quote_paise=3950, competing_paise=None, previous_ask_paise=None)
    assert m.action == "requote"


def test_buyer_walks_away_when_final_not_better():
    m = buyer_next_move(round_no=3, vendor_offer_paise=3720, vendor_is_final=True, vendor_quote_comparable=True,
                        best_valid_quote_paise=3950, competing_paise=3640, previous_ask_paise=3550)
    assert m.action == "walk_away"
