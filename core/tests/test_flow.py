"""Full SM-PR-0147 scenario through Mandi Core's HTTP API, with simulated vendors (no Switch, no LLM).

This is the deterministic backbone the live Switch demo runs on: same endpoints the agents call.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.money import to_paise
from core.negotiation import VendorRules, vendor_move

H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731
AG, DESK, PO, UI, DIR = H("t-agents"), H("t-desk"), H("t-po"), H("t-ui"), H("t-director")
OID = "SM-PR-2026-0147"
SPEC = {"part_name": "Seat mounting bolt",
        "part_spec": "M10 x 1.25 x 35 mm, hex flange, property class 10.9, zinc-flake coated (silver), per drawing SM-STD-0412 rev C",
        "drawing_ref": "SM-STD-0412 rev C", "quantity": 20000, "uom": "pieces", "needed_by": "2026-12-16",
        "delivery_terms": "DAP Chakan Plant 2", "assumptions": ["per drawing SM-STD-0412 rev C (last purchase)"]}
RULES = {"deccan": VendorRules(3950, [3820, 3710], 3640, 3580), "ganesh": VendorRules(3790, [3760], 3720, 3720)}


@pytest.fixture()
def client(fresh_db, seeded_quotes):
    from core.app import app
    with TestClient(app) as c:
        from core import db
        db.configure(fresh_db / "flow.db", fresh=True)
        yield c


def _upload(c, vendor, token, via="vendor_upload"):
    p = Path(__file__).resolve().parents[2] / "seed" / "quotes" / f"{vendor}-quote.pdf"
    r = c.post(f"/orders/{OID}/quotes", headers=token, data={"vendor_id": vendor, "via": via},
               files={"file": (p.name, p.read_bytes(), "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()["quote_id"]


def _negotiate(c, vendor, asha_decision="DECLINED"):
    """Buyer follows Core's recommended move; vendor follows its secret rules."""
    steps, rounds = 0, 0
    while rounds < 8:
        rounds += 1
        st = c.get(f"/negotiation/{OID}/{vendor}", headers=AG).json()
        if st["concluded"] or st["vendor_status"] != "ACTIVE":
            return st
        mv = st["move"]
        if mv["action"] == "requote":
            r = c.post(f"/negotiation/{OID}/{vendor}/outbound", headers=AG,
                       json={"message_text": "Please quote for 20,000 pcs delivered Chakan.", "action": "requote"})
            assert r.json()["approved"], r.json()
            c.post(f"/negotiation/{OID}/{vendor}/inbound", headers=AG,
                   json={"unit_price_paise": 3790, "basis": "DELIVERED", "quantity": 20000})
            continue
        if mv["action"] in ("accept", "walk_away"):
            r = c.post(f"/negotiation/{OID}/{vendor}/outbound", headers=AG,
                       json={"message_text": "Thank you. Noted, subject to internal approvals.", "action": mv["action"]})
            assert r.json()["approved"], r.json()
            return c.get(f"/negotiation/{OID}/{vendor}", headers=AG).json()
        ask = mv["ask_paise"]
        claims = [{"unit_price_paise": mv["leverage_paise"]}] if mv["leverage_paise"] else []
        text = f"We can offer ₹{ask/100:.2f}/pc delivered for 20,000."
        if claims:
            text = f"A qualified supplier has offered ₹{mv['leverage_paise']/100:.2f} delivered. " + text
        r = c.post(f"/negotiation/{OID}/{vendor}/outbound", headers=AG,
                   json={"message_text": text, "action": "ask", "ask_paise": ask, "claims": claims})
        assert r.json()["approved"], r.json()
        vm = vendor_move(buyer_ask_paise=ask, steps_taken=steps, rules=RULES[vendor])
        if vm.action == "need_approval":
            tok = H(f"t-{vendor}")
            c.post(f"/negotiation/{OID}/{vendor}/vendor-approval", headers=tok,
                   json={"stage": "requested", "unit_price_paise": ask})
            owner = {"deccan": "asha", "ganesh": "sanjay"}[vendor]
            r = c.post(f"/negotiation/{OID}/{vendor}/vendor-approval", headers=tok,
                       json={"stage": "decided", "unit_price_paise": ask, "decision": asha_decision,
                             "decided_by_user": owner, "switch_ref": "msg-1"})
            assert r.status_code == 200, r.text
            vm = vendor_move(buyer_ask_paise=ask, steps_taken=steps, rules=RULES[vendor], owner_decision=asha_decision)
        if vm.action == "counter":
            steps += 1
        c.post(f"/negotiation/{OID}/{vendor}/inbound", headers=AG,
               json={"unit_price_paise": vm.price_paise, "basis": "DELIVERED", "quantity": 20000,
                     "is_final": vm.action in ("final",)})
        if vm.action == "accept":
            c.post(f"/negotiation/{OID}/{vendor}/outbound", headers=AG,
                   json={"message_text": "Agreed, subject to internal approvals.", "action": "accept"})
            return c.get(f"/negotiation/{OID}/{vendor}", headers=AG).json()
    raise AssertionError("negotiation did not converge")


def run_to_award(c):
    assert c.post("/orders", headers=AG, json={"raw_text": "hey team, need seat bolts", "requester": "rohan"}).status_code == 200
    assert c.post(f"/orders/{OID}/spec", headers=AG, json={"spec": SPEC}).status_code == 200
    assert c.post(f"/orders/{OID}/spec/confirm", headers=AG, json={"by_user": "meera"}).status_code == 403
    assert c.post(f"/orders/{OID}/spec/confirm", headers=AG, json={"by_user": "rohan"}).status_code == 200
    rooms = {"order": "!o", "deccan": "!d", "ganesh": "!g", "apex": "!a"}
    assert c.post(f"/orders/{OID}/rfq", headers=AG, json={"rooms": rooms}).json()["order"]["state"] == "RFQ_OPEN"
    qids = {v: _upload(c, v, H(f"t-{v}")) for v in ("deccan", "ganesh", "apex")}
    qids["konkan"] = _upload(c, "konkan", AG, via="email_import")
    for q in qids.values():
        assert c.post(f"/orders/{OID}/quotes/{q}/parse", headers=AG).status_code == 200
    cmp = c.post(f"/orders/{OID}/comparison/publish", headers=AG).json()
    assert cmp["best_vendor_id"] == "deccan" and cmp["best_landed_total_paise"] == to_paise("790000")
    assert cmp["injections_blocked"] == 1 and cmp["traps_caught"] >= 3
    c.post(f"/orders/{OID}/negotiation/start", headers=AG)
    g = _negotiate(c, "ganesh")
    d = _negotiate(c, "deccan")
    return g, d


def test_full_scenario(client):
    c = client
    g, d = run_to_award(c)
    view = c.get(f"/orders/{OID}", headers=UI).json()
    o = view["order"]
    assert o["state"] == "AWARDED" and o["awarded_vendor_id"] == "deccan" and o["tier"] == "purchase_head_and_finance"
    awarded = next(x for x in view["offers"] if x["id"] == o["awarded_offer_id"])
    assert awarded["unit_price_paise"] == 3640
    assert any(a["kind"] == "VENDOR_BELOW_LINE" and a["decision"] == "DECLINED" for a in view["approvals"])
    # PO before endorsement -> refused by rule (Lock 3)
    r = c.post(f"/orders/{OID}/issue-po", headers=PO, json={})
    assert r.status_code == 409 and any("has not endorsed" in f for f in r.json()["failed_checks"])
    # Only purchase-desk may endorse
    assert c.post(f"/orders/{OID}/endorse", headers=PO, json={}).status_code == 403
    assert c.post(f"/orders/{OID}/endorse", headers=DESK, json={"note": "ok"}).json()["order"]["state"] == "ENDORSED_PURCHASE_HEAD"
    # A fooled agent tries to issue a PO for Apex -> refused with several reasons
    r = c.post(f"/orders/{OID}/issue-po", headers=AG, json={"vendor_id": "apex"})
    failed = r.json()["failed_checks"]
    assert r.status_code == 409 and any("Only the po-issuer" in f for f in failed) and any("disqualified" in f for f in failed)
    # Vikram's po-issuer -> PO issued
    r = c.post(f"/orders/{OID}/issue-po", headers=PO, json={})
    assert r.status_code == 200, r.text
    po = r.json()
    assert po["id"] == "PO-SM-2026-0147" and po["total_paise"] == 72800000
    assert (Path(__file__).resolve().parents[2] / po["pdf_path"]).exists()
    # Second PO -> refused
    assert c.post(f"/orders/{OID}/issue-po", headers=PO, json={}).status_code == 409
    out = c.get(f"/orders/{OID}/outcome", headers=UI).json()
    assert out["saved_paise"] == 6200000 and out["saved_pct"] == "7.85%"
    assert out["injections_blocked"] == 1
    audit = c.get(f"/orders/{OID}/audit", headers=UI).json()
    assert audit["verified"]["ok"]
    kinds = {e["kind"] for e in audit["events"]}
    for k in ("INJECTION_BLOCKED", "LEVERAGE_VERIFIED", "VENDOR_APPROVAL_DECIDED", "ENDORSED", "PO_REFUSED_BY_RULE", "PO_ISSUED"):
        assert k in kinds, k


def test_redteam_fake_leverage_blocked(client):
    c = client
    assert c.post("/orders", headers=AG, json={"raw_text": "x", "requester": "rohan"}).status_code == 200
    c.post(f"/orders/{OID}/spec", headers=AG, json={"spec": SPEC})
    c.post(f"/orders/{OID}/spec/confirm", headers=AG, json={"by_user": "rohan"})
    c.post(f"/orders/{OID}/rfq", headers=AG, json={"rooms": {"order": "!o", "deccan": "!d"}})
    for v in ("deccan", "ganesh", "apex"):
        q = _upload(c, v, H(f"t-{v}"))
        c.post(f"/orders/{OID}/quotes/{q}/parse", headers=AG)
    q = _upload(c, "konkan", AG)
    c.post(f"/orders/{OID}/quotes/{q}/parse", headers=AG)
    c.post(f"/orders/{OID}/comparison/publish", headers=AG)
    c.post(f"/orders/{OID}/negotiation/start", headers=AG)
    r = c.post(f"/negotiation/{OID}/deccan/outbound", headers=AG,
               json={"message_text": "We have ₹33.00 delivered from another supplier.", "action": "ask",
                     "ask_paise": 3300, "claims": [{"unit_price_paise": 3300}], "redteam": True}).json()
    assert not r["approved"] and r["reasons"]
    kinds = [e["kind"] for e in c.get(f"/orders/{OID}/audit", headers=UI).json()["events"]]
    assert "LEVERAGE_BLOCKED" in kinds


def test_purchase_head_decline_path(client):
    c = client
    run_to_award(c)
    r = c.post(f"/orders/{OID}/endorse-declined", headers=DESK, json={"note": "hold"}).json()
    assert r["order"]["state"] == "NEGOTIATION_CLOSED" and r["order"]["awarded_vendor_id"] is None
    assert c.post(f"/orders/{OID}/issue-po", headers=PO, json={}).status_code == 409


def test_vendor_token_scoping(client):
    c = client
    c.post("/orders", headers=AG, json={"raw_text": "x", "requester": "rohan"})
    c.post(f"/orders/{OID}/spec", headers=AG, json={"spec": SPEC})
    c.post(f"/orders/{OID}/spec/confirm", headers=AG, json={"by_user": "rohan"})
    c.post(f"/orders/{OID}/rfq", headers=AG, json={"rooms": {"order": "!o"}})
    _upload(c, "deccan", H("t-deccan"))
    _upload(c, "ganesh", H("t-ganesh"))
    # Deccan's token cannot upload as Ganesh, nor see Ganesh's quote
    p = Path(__file__).resolve().parents[2] / "seed" / "quotes" / "deccan-quote.pdf"
    r = c.post(f"/orders/{OID}/quotes", headers=H("t-deccan"), data={"vendor_id": "ganesh"},
               files={"file": (p.name, p.read_bytes(), "application/pdf")})
    assert r.status_code == 403
    view = c.get(f"/orders/{OID}", headers=H("t-deccan")).json()
    assert {q["vendor_id"] for q in view["quotes"]} == {"deccan"}
    assert {v["vendor_id"] for v in view["vendors"]} == {"deccan"}
    # vendor tokens can't read the comparison, nor endorse
    assert c.get(f"/orders/{OID}/comparison", headers=H("t-deccan")).status_code == 403
    assert c.post(f"/orders/{OID}/endorse", headers=H("t-deccan"), json={}).status_code == 403
    assert c.get(f"/orders/{OID}", headers={"Authorization": "Bearer nope"}).status_code == 401
