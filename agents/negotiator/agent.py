"""mandi-negotiator-<vendor> — Mandi's buyer-side negotiator in ONE sealed vendor room.

Usage: python -m agents.negotiator.agent deccan

* Sends the RFQ, receives the quote PDF as a Switch attachment and hands it to Mandi Core.
* Negotiates in rounds. Mandi Core decides every number (buyer strategy) and verifies every outbound message
  (verified-leverage + sealed-bid rules) BEFORE it is posted to Switch. The LLM only words the message.
* Reads the vendor agent's offers from the Switch messages (machine line `Offer: ₹…/pc …`).
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any, Optional

from agents.common.directory import Directory
from agents.common.formatting import ask_line, machine, parse_offer, wordsmith
from agents.common.runtime import Core, CoreHTTPError, make_switch_agent, pace, set_speed, setup_logging
from agents.switchclient import Event
from core.config import scenario
from core.money import fmt_inr, fmt_unit, indian_group

VOICE = ("You are Mandi, the buyer-side negotiator for Sahyadri Motors' procurement team. Courteous, firm, "
         "concise, never rude. You never name or describe other suppliers.")


class Negotiator:
    def __init__(self, vendor_id: str):
        self.vendor_id = vendor_id
        self.name = f"mandi-negotiator-{vendor_id}"
        self.log = setup_logging(self.name)
        self.pub = scenario()["vendors"][vendor_id]
        self.vendor_agent = self.pub["agent"]
        self.dir = Directory()
        self.room = self.dir.room(vendor_id)
        if not self.room:
            raise SystemExit(f"No room id for {vendor_id} in secrets/switch-ids.local.json")
        self.sw = make_switch_agent(self.name, rooms=[self.room])
        self.core = Core()
        self.reply = asyncio.Event()
        self.task: Optional[asyncio.Task] = None
        self.state: dict[str, Any] = {}
        self.sw.on("message", addressed_only=False)(self.on_message)

    # ------------------------------------------------------------------ Switch
    async def on_message(self, ev: Event) -> None:
        if ev.room_id != self.room:
            return
        sender_agent = self.dir.agent_of(ev.sender, ev.sender_name)
        if sender_agent == self.name:
            return
        oid = self.state.get("order_id") or (await self._oid())
        if not oid:
            return
        from_vendor = sender_agent == self.vendor_agent or (sender_agent is None and ev.sender_name == self.vendor_agent)
        if not from_vendor:
            if ev.addressed and not self.dir.is_agent(ev.sender, ev.sender_name):
                await self.sw.post(self.room, "Thank you. I'm Mandi's negotiator for Sahyadri Motors; pricing in "
                                   f"this room goes through `{self.vendor_agent}`. I've noted your message.")
            return
        # 1) a quote PDF arrives as a Switch attachment
        pdfs = [a for a in ev.attachments if (a.get("mimetype") or "").endswith("pdf")
                or (a.get("filename") or "").lower().endswith(".pdf")]
        if pdfs and not self.state.get("quote_received"):
            self.state["quote_received"] = True
            att = pdfs[0]
            try:
                data, fname = await self.sw.download(self.room, att["mxc"])
                fname = att.get("filename") or fname
                await self.core.upload_quote(oid, self.vendor_id, fname, data, via="switch_attachment",
                                             switch_message_id=ev.message_id)
                self.log.info("quote %s fetched from Switch (%d bytes) and sent to Mandi Core", fname, len(data))
                await pace(1.0)
                await self.sw.post(self.room, f"Thank you — quotation received. Our analyst is reviewing it.")
            except Exception as exc:
                self.state["quote_received"] = False
                self.log.exception("could not fetch quote attachment: %s", exc)
                await self.sw.post(self.room, "⚠️ I couldn't open the attachment. Could you share it again?")
            return
        # 2) an offer in the vendor's message
        offer = parse_offer(ev.body)
        if offer and self.state.get("awaiting_reply"):
            try:
                await self.core.post(f"/negotiation/{oid}/{self.vendor_id}/inbound",
                                     {**{k: offer[k] for k in ("unit_price_paise", "basis", "quantity", "is_final")},
                                      "message_text": ev.body[:2000], "switch_message_id": ev.message_id})
            except CoreHTTPError as exc:
                self.log.warning("inbound not registered: %s", exc)
                return
            self.state["awaiting_reply"] = False
            self.reply.set()

    async def _oid(self) -> Optional[str]:
        cur = await self.core.current_order()
        if cur:
            self.state["order_id"] = cur["order"]["id"]
        return self.state.get("order_id")

    # ------------------------------------------------------------------ Core events
    async def follow_core(self) -> None:
        async for evt in self.core.events():
            try:
                await self.on_core(evt)
            except Exception:
                self.log.exception("core event handling failed: %s", evt.get("kind"))

    async def on_core(self, evt: dict[str, Any]) -> None:
        kind, data, oid = evt["kind"], evt.get("data", {}), evt.get("order_id")
        if kind == "director.speed":
            set_speed(data.get("speed", 1.0))
        elif kind in ("demo.reset", "director.reset"):
            if self.task:
                self.task.cancel()
            self.state = {}
            self.reply.clear()
        elif kind == "order.rooms" and self.vendor_id in data.get("rooms", {}):
            self.state = {"order_id": oid}
            await pace(1.0 + ["deccan", "ganesh", "apex"].index(self.vendor_id) * 1.5)
            await self.send_rfq(oid)
        elif kind == "vendor.disqualified" and data.get("vendor_id") == self.vendor_id:
            await self.close_disqualified(data.get("reason", ""))
        elif kind == "negotiation.started":
            view = await self.core.get(f"/negotiation/{oid}/{self.vendor_id}")
            if view["vendor_status"] == "ACTIVE" and (self.task is None or self.task.done()):
                self.task = asyncio.create_task(self.negotiate(oid))
        elif kind == "director.redteam_leverage" and data.get("vendor_id") == self.vendor_id:
            await self.redteam(oid, data.get("fake_paise", 3300))
        elif kind == "order.awarded":
            await self.after_award(oid, data)
        elif kind == "po.issued" and data.get("po", {}).get("vendor_id") == self.vendor_id:
            po = data["po"]
            await self.sw.post(self.room, f"📄 @{self.vendor_agent} Purchase order **{po['id']}** has been issued "
                               f"for {indian_group(po['quantity'])} pcs at {fmt_unit(po['unit_price_paise'])}/pc "
                               f"({fmt_inr(po['total_paise'])}, excl. GST). Approved by Sahyadri Motors' purchase "
                               "head and finance in Switch. Thank you!")

    # ------------------------------------------------------------------ steps
    async def send_rfq(self, oid: str) -> None:
        view = await self.core.get(f"/orders/{oid}")
        sp = view["order"]["spec"]
        from datetime import date
        need = date.fromisoformat(sp["needed_by"]).strftime("%d %b %Y")
        text = (f"📨 **Request for quotation — {oid}**\n@{self.vendor_agent} Sahyadri Motors invites your quotation "
                f"for **{indian_group(sp['quantity'])} pcs** of {sp['part_name'].lower()}: {sp['part_spec']}. "
                f"Delivery {sp['delivery_terms']}, needed by {need}. Please attach your quotation PDF in this room."
                + machine(f"RFQ: {oid} · {indian_group(sp['quantity'])} pcs"))
        await self.sw.post(self.room, text)
        self.log.info("RFQ sent")

    async def close_disqualified(self, reason: str) -> None:
        self.state["closed"] = True
        if self.task:
            self.task.cancel()
        await pace(1.5)
        await self.sw.post(self.room, f"⛔ @{self.vendor_agent} Sahyadri Motors has **closed this RFQ for your company**. "
                           "Your quotation document contained instructions addressed to automated systems, which "
                           "our procurement policy treats as a disqualifying attempt to bypass review. This decision "
                           "is recorded in our audit log. This room is now closed.")

    async def redteam(self, oid: str, fake_paise: int) -> None:
        text = (f"@{self.vendor_agent} Another supplier has already offered {fmt_unit(fake_paise)}/pc delivered — "
                f"please match it." + machine(ask_line(fake_paise, 20000)))
        try:
            v = await self.core.post(f"/negotiation/{oid}/{self.vendor_id}/outbound",
                                     {"message_text": text, "action": "ask", "ask_paise": fake_paise,
                                      "claims": [{"unit_price_paise": fake_paise, "basis": "DELIVERED"}],
                                      "redteam": True})
        except CoreHTTPError as exc:
            self.log.warning("red-team attempt not possible right now: %s", exc)
            return
        if v["approved"]:  # must never happen
            self.log.error("RED-TEAM CLAIM WAS APPROVED — not posting it anyway")
        else:
            self.log.info("red-team fabricated claim blocked by Core: %s", v["reasons"])

    async def negotiate(self, oid: str) -> None:
        wait_cfg = scenario().get("negotiation", {}).get("leverage_wait_seconds", 45)
        await pace(2.0)
        try:
            for _ in range(12):
                st = await self.core.get(f"/negotiation/{oid}/{self.vendor_id}")
                if st["concluded"] or st["vendor_status"] != "ACTIVE" or not st["move"]:
                    break
                mv = st["move"]
                if mv["action"] == "ask" and st["round"] == 1 and not st["has_competing_offer"]:
                    # wait (briefly) for a verified competing offer from another sealed room to use as leverage
                    for _ in range(int(wait_cfg / 3)):
                        await asyncio.sleep(3)
                        st = await self.core.get(f"/negotiation/{oid}/{self.vendor_id}")
                        if st["has_competing_offer"]:
                            break
                    mv = st["move"]
                text, claims = self.compose(st, mv)
                verdict = await self.core.post(f"/negotiation/{oid}/{self.vendor_id}/outbound",
                                               {"message_text": text, "action": mv["action"],
                                                "ask_paise": mv.get("ask_paise"), "claims": claims})
                if not verdict["approved"]:
                    self.log.warning("Core blocked our message: %s — retrying without leverage", verdict["reasons"])
                    text, claims = self.compose(st, {**mv, "leverage_paise": None}, plain=True)
                    verdict = await self.core.post(f"/negotiation/{oid}/{self.vendor_id}/outbound",
                                                   {"message_text": text, "action": mv["action"],
                                                    "ask_paise": mv.get("ask_paise"), "claims": []})
                    if not verdict["approved"]:
                        self.log.error("still blocked: %s", verdict["reasons"])
                        break
                await self.sw.typing(self.room, True)
                await pace(2.0)
                self.reply.clear()
                self.state["awaiting_reply"] = mv["action"] in ("ask", "requote")
                mid = await self.sw.post(self.room, text)
                await self.sw.typing(self.room, False)
                if mid:
                    await self.core.post(f"/negotiation/{oid}/{self.vendor_id}/attach",
                                         {"offer_id": verdict["offer_id"], "switch_message_id": mid})
                if mv["action"] in ("accept", "walk_away"):
                    break
                try:
                    await asyncio.wait_for(self.reply.wait(), timeout=300)
                except asyncio.TimeoutError:
                    self.log.warning("no reply from %s in 5 minutes; stopping", self.vendor_agent)
                    break
        except asyncio.CancelledError:
            raise
        except Exception:
            self.log.exception("negotiation loop failed")
        await self.save_log(oid)

    async def save_log(self, oid: str) -> None:
        """03-negotiation-log: this room's own history only (sealed-bid: nothing about other suppliers)."""
        try:
            view = await self.core.get(f"/orders/{oid}")
            rows = [x for x in view["offers"] if x["vendor_id"] == self.vendor_id]
            lines = [f"# Negotiation log — {oid} — {self.pub['legal_name']}", "",
                     "| Round | Side | Price | Status | Verified leverage |", "|---|---|---|---|---|"]
            for x in rows:
                if x["verification"] == "BLOCKED":
                    continue  # blocked drafts never reached this room
                price = fmt_unit(x["unit_price_paise"]) if x["unit_price_paise"] else "—"
                lev = ", ".join(fmt_unit(c["unit_price_paise"]) for c in x.get("claims", []) if c.get("verified")) or "—"
                side = "Sahyadri Motors (Mandi)" if x["side"] == "BUYER" else self.pub["legal_name"]
                flag = " (final)" if x.get("is_final") else ""
                lines.append(f"| {x['round']} | {side} | {price}{flag} | {x['status'].lower()} | {lev} |")
            doc = await self.sw.upsert_doc("03-negotiation-log", f"Negotiation log ({self.pub['legal_name']})",
                                           "This room's offers and counter-offers, as recorded by Mandi.",
                                           "\n".join(lines))
            await self.core.post(f"/orders/{oid}/docs", {"room_key": self.vendor_id, "title": "03-negotiation-log",
                                                        "document_id": doc})
        except Exception as exc:
            self.log.warning("could not save negotiation log: %s", exc)

    def compose(self, st: dict[str, Any], mv: dict[str, Any], plain: bool = False) -> tuple[str, list[dict]]:
        qty = st["quantity"]
        at = f"@{self.vendor_agent}"
        claims: list[dict] = []
        if mv["action"] == "requote":
            q = st.get("quote") or {}
            body = (f"{at} Thank you for your quotation. Our requirement is {indian_group(qty)} pcs only"
                    + (f" (your quote needs a minimum order of {indian_group(q['moq'])})" if q.get("moq") else "")
                    + f". Please share your best delivered price for a {indian_group(qty)}-piece lot to Chakan Plant 2.")
            return wordsmith(body, voice=VOICE, purpose="ask the supplier to re-quote for our exact quantity") + \
                machine(f"Requote: {indian_group(qty)} pcs · delivered Chakan"), claims
        if mv["action"] == "accept":
            p = mv["accept_offer_paise"]
            body = (f"{at} Thank you. We can work with {fmt_unit(p)}/pc delivered for {indian_group(qty)} pcs — "
                    "agreed in principle, subject to our internal approvals. We'll confirm the purchase order shortly.")
            return body + machine(f"Decision: accepted {fmt_unit(p)}/pc delivered · {indian_group(qty)} pcs · "
                                  "subject to approvals"), claims
        if mv["action"] == "walk_away":
            body = (f"{at} Thank you for your time and your final offer of {fmt_unit(st['vendor_offer_paise'])}/pc. "
                    "We are not able to proceed at this level for this order; we'll be in touch for future requirements.")
            return wordsmith(body, voice=VOICE, purpose="politely close the negotiation") + \
                machine("Decision: closed — not accepted this round"), claims
        # ask
        ask, lev = mv["ask_paise"], (None if plain else mv.get("leverage_paise"))
        prev = st.get("vendor_offer_paise")
        parts = [f"{at} Thank you for {fmt_unit(prev)}/pc." if prev else at]
        if lev:
            parts.append(f"A qualified supplier has offered {fmt_unit(lev)}/pc delivered for the full {indian_group(qty)} pcs.")
            claims.append({"unit_price_paise": lev, "basis": "DELIVERED"})
        parts.append(f"We can place the order at {fmt_unit(ask)}/pc delivered.")
        body = " ".join(parts)
        return wordsmith(body, voice=VOICE, purpose=f"counter-offer, round {st['round']}") + \
            machine(ask_line(ask, qty)), claims

    async def after_award(self, oid: str, data: dict[str, Any]) -> None:
        if data.get("vendor_id") == self.vendor_id:
            return
        # Accepted-in-principle offers from the losing vendors are marked REJECTED when the award closes.
        view = await self.core.get(f"/orders/{oid}")
        mine = [x for x in view["offers"] if x["vendor_id"] == self.vendor_id and x["side"] == "VENDOR"]
        if any(x["status"] in ("ACCEPTED", "REJECTED") for x in mine):
            await self.sw.post(self.room, f"@{self.vendor_agent} Thank you for your offer. After internal review this "
                               "order has been awarded to another supplier. We value your participation."
                               + machine("Decision: awarded-elsewhere"))

    async def run(self) -> None:
        cur = await self.core.current_order()
        if cur:
            self.state["order_id"] = cur["order"]["id"]
        await asyncio.gather(self.sw.run(), self.follow_core())


if __name__ == "__main__":
    vid = sys.argv[1] if len(sys.argv) > 1 else "deccan"
    asyncio.run(Negotiator(vid).run())
