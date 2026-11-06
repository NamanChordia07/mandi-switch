"""Replay the SM-PR-0147 scenario through Mandi Core WITHOUT Switch (no Mattermost, no LLM).

    python scripts/simulate.py [--fast] [--stop-at negotiate|approve|po]

For UI development, tests and judges who can't install Switch. Every chat line it writes into the Control Room's
feed is marked `simulated` and the UI shows a "Replay mode" banner. Approvals in replay mode are made with the gate
agents' MCP tokens — in the real demo they only happen when Meera and Vikram tap Allow in Switch.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)
from agents.common.formatting import ask_line, offer_line  # noqa: E402
from core.config import resolve_date, scenario, scenario_date  # noqa: E402
from core.money import fmt_unit, indian_group, to_paise  # noqa: E402
from core.negotiation import VendorRules, vendor_move  # noqa: E402

CORE = os.environ.get("CORE_URL", "http://127.0.0.1:8700")
T = lambda k: {"Authorization": f"Bearer {os.environ[k]}"}  # noqa: E731
AG, DESK, PO, DIR = T("CORE_TOKEN_AGENTS"), T("CORE_TOKEN_MCP_PURCHASE_DESK"), T("CORE_TOKEN_MCP_PO_ISSUER"), T("CORE_TOKEN_DIRECTOR")
PACE = 1.0
c = httpx.Client(base_url=CORE, timeout=60)
SEQ = [0]


def wait(s: float) -> None:
    time.sleep(s * PACE)


def say(room: str, who: str, kind: str, body: str, attach: str | None = None) -> None:
    SEQ[0] += 1
    item = {"event": "message", "room_id": f"sim-{room}", "room_key": room, "sequence": SEQ[0],
            "message_id": f"sim-{time.time_ns()}", "sender": who, "sender_name": who, "sender_kind": kind,
            "body": body, "addressed": body.startswith("@"), "data": {"simulated": True,
                                                                     "attachments": [{"filename": attach, "mimetype": "application/pdf"}] if attach else []}}
    c.post("/switch/feed", headers=AG, json={"items": [item]}).raise_for_status()


def ok(r: httpx.Response) -> dict:
    if r.status_code >= 400:
        raise SystemExit(f"{r.request.method} {r.request.url} -> {r.status_code} {r.text[:300]}")
    return r.json()


def main() -> None:
    global PACE
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--stop-at", choices=["negotiate", "approve", "po"], default="po")
    a = ap.parse_args()
    PACE = 0.15 if a.fast else 1.0
    sc = scenario()
    o = sc["order"]
    ok(c.post("/director/reset", headers=DIR))
    wait(1)
    say("order", "rohan", "human", f"@mandi-intake {o['raw_request_message'].strip()}")
    oid = ok(c.post("/orders", headers=AG, json={"raw_text": o["raw_request_message"], "requester": "rohan"}))["order"]["id"]
    need = resolve_date(o["needed_by"], scenario_date())
    spec = {"part_name": o["part"]["name"], "part_spec": o["part"]["spec"], "drawing_ref": o["part"]["drawing_ref"],
            "quantity": o["quantity"], "uom": "pieces", "needed_by": need.isoformat(), "delivery_terms": o["delivery"],
            "assumptions": [f"Drawing {o['part']['drawing_ref']}, as on the last purchase"]}
    wait(2)
    ok(c.post(f"/orders/{oid}/spec", headers=AG, json={"spec": spec}))
    say("order", "mandi-intake", "agent", f"📝 **Spec draft — {oid}** · {indian_group(o['quantity'])} pcs seat mounting bolt, "
        f"needed by {need:%d %b %Y}. Assumption: drawing {o['part']['drawing_ref']}. @rohan reply **yes** to confirm.")
    wait(3)
    say("order", "rohan", "human", "yes")
    ok(c.post(f"/orders/{oid}/spec/confirm", headers=AG, json={"by_user": "rohan"}))
    wait(1.5)
    rooms = {"order": "sim-order", "deccan": "sim-deccan", "ganesh": "sim-ganesh", "apex": "sim-apex"}
    ok(c.post(f"/orders/{oid}/rfq", headers=AG, json={"rooms": rooms}))
    say("order", "mandi-intake", "agent", "🔒 RFQ is open in **3 sealed Switch rooms** — Deccan Bolt Works, Shree Ganesh Fasteners, Apex Precision Components.")
    for v in ("deccan", "ganesh", "apex"):
        wait(1)
        say(v, f"mandi-negotiator-{v}", "agent", f"📨 **Request for quotation — {oid}** @{v}-sales Sahyadri Motors invites your quotation for 20,000 pcs…")
    qids = {}
    for v in ("deccan", "ganesh", "apex"):
        wait(1.5)
        pdf = ROOT / "seed" / "quotes" / f"{v}-quote.pdf"
        say(v, f"{v}-sales", "agent", f"@mandi-negotiator-{v} 📄 Please find our quotation attached.", attach=pdf.name)
        qids[v] = ok(c.post(f"/orders/{oid}/quotes", headers=AG, data={"vendor_id": v, "via": "switch_attachment"},
                            files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")}))["quote_id"]
    pdf = ROOT / "seed" / "quotes" / "konkan-quote.pdf"
    qids["konkan"] = ok(c.post(f"/orders/{oid}/quotes", headers=AG, data={"vendor_id": "konkan", "via": "email_import"},
                               files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")}))["quote_id"]
    say("order", "mandi-intake", "agent", "📧 Also found an older quote from **Konkan Fasteners** in the purchase mailbox.")
    os.environ["MANDI_OFFLINE_LLM"] = "1"
    for v, q in qids.items():
        wait(1.5)
        r = ok(c.post(f"/orders/{oid}/quotes/{q}/parse", headers=AG))
        if r["injection_verdict"] == "INJECTION":
            say("order", "mandi-quotes", "agent", "⛔ **Prompt injection blocked — Apex Precision Components**\n```\n"
                + r["injection_spans"][0][:300] + "\n```\nApex is disqualified. @meera FYI.")
            say("apex", "mandi-negotiator-apex", "agent", "⛔ @apex-sales Sahyadri Motors has **closed this RFQ for your company**.")
        else:
            say("order", "mandi-quotes", "agent", f"📄 Read **{v.title()}**'s quote: {fmt_unit(r['unit_price_paise'])}/pc, "
                + ("; ".join(t["message"] for t in r["traps"] if t["code"] != "MISSING_FIELD") or "no traps."))
    wait(2)
    cmp = ok(c.post(f"/orders/{oid}/comparison/publish", headers=AG))
    say("order", "mandi-quotes", "agent", "📊 **Quote comparison** published. " + cmp["recommendation"])
    ok(c.post(f"/orders/{oid}/negotiation/start", headers=AG))
    if a.stop_at == "negotiate":
        return
    rules = {"deccan": VendorRules(3950, [3820, 3710], 3640, 3580), "ganesh": VendorRules(3790, [3760], 3720, 3720)}
    owners = {"deccan": "asha", "ganesh": "sanjay"}
    steps = {"deccan": 0, "ganesh": 0}
    done = set()
    for _ in range(14):
        for v in ("ganesh", "deccan"):
            if v in done:
                continue
            st = ok(c.get(f"/negotiation/{oid}/{v}", headers=AG))
            if st["concluded"] or not st["move"]:
                done.add(v)
                continue
            mv = st["move"]
            wait(2)
            if mv["action"] == "requote":
                ok(c.post(f"/negotiation/{oid}/{v}/outbound", headers=AG, json={"message_text": "Please quote for 20,000 pcs delivered.", "action": "requote"}))
                say(v, f"mandi-negotiator-{v}", "agent", f"@{v}-sales Our requirement is 20,000 pcs only. Please share your best delivered price for 20,000.")
                wait(2)
                ok(c.post(f"/negotiation/{oid}/{v}/inbound", headers=AG, json={"unit_price_paise": 3790, "basis": "DELIVERED", "quantity": 20000}))
                say(v, f"{v}-sales", "agent", f"@mandi-negotiator-{v} For 20,000 only, ₹37.90/pc delivered. Take 50,000 and get ₹33.90!\n`{offer_line(3790, 20000)}`")
                continue
            if mv["action"] in ("accept", "walk_away"):
                text = "Agreed in principle, subject to internal approvals." if mv["action"] == "accept" else "We are not able to proceed at this level."
                ok(c.post(f"/negotiation/{oid}/{v}/outbound", headers=AG, json={"message_text": text, "action": mv["action"]}))
                say(v, f"mandi-negotiator-{v}", "agent", f"@{v}-sales 🤝 {text}" if mv["action"] == "accept" else f"@{v}-sales {text}")
                done.add(v)
                continue
            ask = mv["ask_paise"]
            claims = [{"unit_price_paise": mv["leverage_paise"]}] if mv["leverage_paise"] else []
            text = (f"A qualified supplier has offered {fmt_unit(mv['leverage_paise'])}/pc delivered. " if claims else "") + f"We can place the order at {fmt_unit(ask)}/pc delivered."
            ok(c.post(f"/negotiation/{oid}/{v}/outbound", headers=AG, json={"message_text": text, "action": "ask", "ask_paise": ask, "claims": claims}))
            say(v, f"mandi-negotiator-{v}", "agent", f"@{v}-sales {text}\n`{ask_line(ask, 20000)}`")
            vm = vendor_move(buyer_ask_paise=ask, steps_taken=steps[v], rules=rules[v])
            if vm.action == "need_approval":
                wait(1.5)
                say(v, f"{v}-sales", "agent", f"🔒 **Approval needed** @{owners[v]} — the buyer asks **{fmt_unit(ask)}/pc**, below our approval line. Reply approve or decline.")
                ok(c.post(f"/negotiation/{oid}/{v}/vendor-approval", headers=T(f"CORE_TOKEN_VENDOR_{v.upper()}"), json={"stage": "requested", "unit_price_paise": ask}))
                wait(3)
                say(v, owners[v], "human", "decline")
                ok(c.post(f"/negotiation/{oid}/{v}/vendor-approval", headers=T(f"CORE_TOKEN_VENDOR_{v.upper()}"),
                          json={"stage": "decided", "unit_price_paise": ask, "decision": "DECLINED", "decided_by_user": owners[v], "switch_ref": "sim"}))
                vm = vendor_move(buyer_ask_paise=ask, steps_taken=steps[v], rules=rules[v], owner_decision="DECLINED")
            if vm.action == "counter":
                steps[v] += 1
            wait(2)
            flag = "FINAL" if vm.action == "final" else ("ACCEPTED" if vm.action == "accept" else "")
            ok(c.post(f"/negotiation/{oid}/{v}/inbound", headers=AG, json={"unit_price_paise": vm.price_paise, "basis": "DELIVERED", "quantity": 20000, "is_final": vm.action in ("final", "accept")}))
            say(v, f"{v}-sales", "agent", f"@mandi-negotiator-{v} We can do {fmt_unit(vm.price_paise)}/pc delivered.\n`{offer_line(vm.price_paise, 20000, flag=flag)}`")
        if len(done) == 2:
            break
    view = ok(c.get(f"/orders/{oid}", headers=AG))
    if view["order"]["state"] != "AWARDED":
        print("not awarded:", view["order"]["state"])
        return
    say("order", "mandi-intake", "agent", "🤝 **Provisional award** — Deccan Bolt Works · ₹36.40/pc × 20,000 = **₹7,28,000**. 🔒 @meera your endorsement is needed.")
    if a.stop_at == "approve":
        return
    wait(3)
    say("order", "meera", "human", "@purchase-desk please review and endorse")
    wait(2)
    say("order", "purchase-desk", "agent", "Switch permission request: purchase-desk wants to run mandi · endorse_order. Allow once / Allow for this session / Decline")
    wait(3)
    ok(c.post(f"/orders/{oid}/endorse", headers=DESK, json={"note": "replay"}))
    say("order", "purchase-desk", "agent", "✅ Endorsed. Finance release is next (Vikram).")
    wait(3)
    say("order", "vikram", "human", "@po-issuer release the PO for SM-PR-0147")
    wait(2)
    say("order", "po-issuer", "agent", "Switch permission request: po-issuer wants to run mandi · issue_po. Allow once / Allow for this session / Decline")
    wait(3)
    po = ok(c.post(f"/orders/{oid}/issue-po", headers=PO, json={"agent_name": "po-issuer"}))
    say("order", "po-issuer", "agent", f"📄 {po['id']} issued — ₹7,28,000 (excl. GST).")
    print(f"done: {po['id']}")


if __name__ == "__main__":
    main()
