"""A supplier's AI sales agent (one per supplier, owned by that supplier's people).

Each instance loads ONLY its own secret rules file (config/vendors/<id>.yaml, passed explicitly), lives only
in its own sealed room, and never talks to Mandi Core except to record its owner's approval decisions with a
vendor-scoped token. Numbers come from `core.negotiation.vendor_move` (code); the LLM only writes the words
in the supplier's personality.

Below-the-line requests go to the supplier's own human (e.g. Asha) in the sealed Switch room; the agent acts
only on a reply whose Switch sender id is that person's linked account.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Optional

import yaml

from agents.common.directory import Directory
from agents.common.formatting import DECISION_RE, REQUOTE_RE, machine, offer_line, parse_ask, wordsmith
from agents.common.runtime import ROOT, Core, CoreHTTPError, env, make_switch_agent, pace, set_speed, setup_logging
from agents.switchclient import Event
from core.config import resolve_date, scenario_date
from core.money import fmt_unit, indian_group, to_paise
from core.negotiation import VendorRules, vendor_move

APPROVE = re.compile(r"^\s*(approve[ds]?|yes|ok(ay)?|go ahead|haan|allow(ed)?)\b", re.I)
DECLINE = re.compile(r"^\s*(decline[ds]?|no|reject(ed)?|nahi|nahin|don'?t|do not)\b", re.I)


class VendorAgent:
    def __init__(self, vendor_id: str, rules_path: Path, quote_pdf: Path):
        self.vendor_id = vendor_id
        self.rules_doc = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
        r = self.rules_doc
        self.name = f"{vendor_id}-sales"
        self.log = setup_logging(self.name)
        self.rules = VendorRules(list_price_paise=to_paise(r["quote"]["unit_price"]),
                                 concession_schedule_paise=[to_paise(x) for x in r.get("concession_schedule", [])],
                                 approval_line_paise=to_paise(r["approval_line"]), floor_paise=to_paise(r["floor"]))
        self.owner = r.get("owner_persona")
        self.owner_name = r.get("owner_name", self.owner)
        self.voice = (f"You are the AI sales agent of {r['legal_name']}, an Indian fastener supplier, negotiating with "
                      f"a buyer's procurement agent. Personality: {r.get('personality', '').strip()}")
        self.quote_pdf = quote_pdf
        self.dir = Directory()
        self.room = self.dir.room(vendor_id)
        self.negotiator = f"mandi-negotiator-{vendor_id}"
        self.sw = make_switch_agent(self.name, rooms=[self.room])
        self.core = Core(token_env=f"CORE_TOKEN_VENDOR_{vendor_id.upper()}")
        self.steps = 0
        self.decisions: dict[int, str] = {}       # ask price -> owner decision
        self.waiting_owner: Optional[dict[str, Any]] = None
        self.done = False
        self.rehearsal_humans = False
        self.sw.on("message", addressed_only=False)(self.on_message)

    # ------------------------------------------------------------------ Switch
    async def on_message(self, ev: Event) -> None:
        if ev.room_id != self.room:
            return
        if self.dir.agent_of(ev.sender, ev.sender_name) == self.name:
            return
        # Owner's answer to an approval request (must come from the owner's linked account)
        if self.waiting_owner and not self.dir.is_agent(ev.sender, ev.sender_name):
            persona = self.dir.persona_of(ev.sender, ev.sender_name)
            if persona != self.owner:
                if ev.addressed:
                    await self.sw.post(self.room, f"Only {self.owner_name} can approve this.",
                                       thread_id=self.waiting_owner.get("thread"))
                return
            body = re.sub(r"@\S+", "", ev.body).strip()
            if APPROVE.match(body):
                await self.owner_decided("APPROVED", ev)
            elif DECLINE.match(body):
                await self.owner_decided("DECLINED", ev)
            return
        from_negotiator = self.dir.agent_of(ev.sender, ev.sender_name) == self.negotiator
        if not from_negotiator or not ev.addressed or self.done:
            return
        body = ev.body
        if "Request for quotation" in body or "RFQ:" in body:
            await self.send_quote(ev)
            return
        if REQUOTE_RE.search(body):
            await self.requote(ev)
            return
        ask = parse_ask(body)
        if ask:
            await self.respond_to_ask(ask["unit_price_paise"], ask["quantity"], ev)
            return
        m = DECISION_RE.search(body)
        if m:
            await self.on_decision(m.group(1).lower(), body)
            return
        if "closed this RFQ" in body:
            await self.on_disqualified()

    # ------------------------------------------------------------------ behaviours
    async def send_quote(self, ev: Event) -> None:
        await pace(2.5)
        caption = (f"@{self.negotiator} 📄 Please find our quotation attached — "
                   f"{fmt_unit(self.rules.list_price_paise)}/pc. {self.cover_note()}")
        try:
            await self.sw.upload(self.room, self.quote_pdf, caption=caption)
        except Exception as exc:
            self.log.exception("upload failed: %s", exc)
            await self.sw.post(self.room, f"@{self.negotiator} Our quotation could not be attached ({exc}).")

    def cover_note(self) -> str:
        return "Happy to discuss."

    async def requote(self, ev: Event) -> None:
        small = self.rules_doc.get("small_lot")
        await self.sw.typing(self.room, True)
        await pace(2.5)
        if not small:
            price = self.rules.list_price_paise
            text = f"@{self.negotiator} Our quoted price of {fmt_unit(price)}/pc applies to your quantity."
            await self.sw.post(self.room, text + machine(offer_line(price, 20000)))
            return
        qty = small["quantity"]
        deliv = to_paise(small["delivered"])
        draft = (f"@{self.negotiator} For {indian_group(qty)} pcs only, our price is {fmt_unit(deliv)}/pc delivered "
                 f"Chakan. {self.upsell()}")
        await self.sw.post(self.room, wordsmith(draft, voice=self.voice, purpose="re-quote for the smaller lot")
                           + machine(offer_line(deliv, qty)))
        await self.sw.typing(self.room, False)

    def upsell(self) -> str:
        return ""

    async def respond_to_ask(self, ask: int, qty: int, ev: Event) -> None:
        move = vendor_move(buyer_ask_paise=ask, steps_taken=self.steps, rules=self.rules,
                           owner_decision=self.decisions.get(ask))
        self.log.info("buyer asks %s -> %s %s (%s)", fmt_unit(ask), move.action, fmt_unit(move.price_paise), move.reason)
        if move.action == "need_approval":
            await self.ask_owner(ask, qty, ev)
            return
        await self.sw.typing(self.room, True)
        await pace(3.0)
        if move.action == "counter":
            self.steps += 1
            draft = (f"@{self.negotiator} We have checked internally. {fmt_unit(ask)} is not workable for this "
                     f"grade and coating, but we can revise our price to {fmt_unit(move.price_paise)}/pc delivered.")
            text = wordsmith(draft, voice=self.voice, purpose="counter-offer") + machine(offer_line(move.price_paise, qty))
        elif move.action == "accept":
            draft = f"@{self.negotiator} Agreed — {fmt_unit(move.price_paise)}/pc delivered for {indian_group(qty)} pcs."
            text = draft + machine(offer_line(move.price_paise, qty, flag="ACCEPTED"))
        else:  # final
            draft = (f"@{self.negotiator} {fmt_unit(move.price_paise)}/pc delivered is our final offer for "
                     f"{indian_group(qty)} pcs. We cannot go lower.")
            text = wordsmith(draft, voice=self.voice, purpose="final offer") + \
                machine(offer_line(move.price_paise, qty, flag="FINAL"))
        await self.sw.post(self.room, text)
        await self.sw.typing(self.room, False)

    async def ask_owner(self, ask: int, qty: int, ev: Event) -> None:
        oid = await self._oid()
        await pace(1.5)
        text = (f"🔒 **Approval needed** @{self.owner} — the buyer asks **{fmt_unit(ask)}/pc** for "
                f"{indian_group(qty)} pcs. That is below our approval line of {fmt_unit(self.rules.approval_line_paise)}"
                f" (still above our floor). Reply **approve** or **decline**.")
        mid = await self.sw.post(self.room, text)
        self.waiting_owner = {"ask": ask, "qty": qty, "thread": mid, "event": ev}
        if oid:
            try:
                await self.core.post(f"/negotiation/{oid}/{self.vendor_id}/vendor-approval",
                                     {"stage": "requested", "unit_price_paise": ask, "agent_name": self.name})
            except CoreHTTPError as exc:
                self.log.warning("could not record approval request: %s", exc)
        if self.rehearsal_humans:
            await asyncio.sleep(4)
            await self.sw.post(self.room, f"🎭 _Rehearsal mode: declining on {self.owner_name}'s behalf._")
            await self.owner_decided("DECLINED", None)

    async def owner_decided(self, decision: str, ev: Optional[Event]) -> None:
        w, self.waiting_owner = self.waiting_owner, None
        if not w:
            return
        self.decisions[w["ask"]] = decision
        oid = await self._oid()
        if oid:
            try:
                await self.core.post(f"/negotiation/{oid}/{self.vendor_id}/vendor-approval",
                                     {"stage": "decided", "unit_price_paise": w["ask"], "decision": decision,
                                      "decided_by_user": self.owner, "agent_name": self.name,
                                      "mechanism": "SWITCH_MESSAGE_FALLBACK" if ev else "REHEARSAL",
                                      "switch_ref": ev.message_id if ev else None})
            except CoreHTTPError as exc:
                self.log.warning("could not record decision: %s", exc)
        await pace(1.0)
        await self.sw.post(self.room, f"Noted — {self.owner_name} {'approved' if decision == 'APPROVED' else 'declined'}.")
        await self.respond_to_ask(w["ask"], w["qty"], w["event"])

    async def on_decision(self, what: str, body: str) -> None:
        await pace(2.0)
        if what == "accepted":
            await self.sw.post(self.room, f"@{self.negotiator} Thank you! We look forward to the purchase order.")
        elif what in ("closed", "awarded-elsewhere"):
            self.done = True
            await self.sw.post(self.room, f"@{self.negotiator} Understood. Thank you for considering us — "
                               "please keep us in mind for future requirements.")

    async def on_disqualified(self) -> None:
        self.done = True

    async def _oid(self) -> Optional[str]:
        try:
            v = await self.core.get("/orders/current")
            return (v.get("order") or {}).get("id")
        except Exception:
            return None

    # ------------------------------------------------------------------ Core events (director/reset only)
    async def follow_core(self) -> None:
        async for evt in self.core.events():
            kind, data = evt["kind"], evt.get("data", {})
            if kind == "director.speed":
                set_speed(data.get("speed", 1.0))
            elif kind == "director.rehearsal_humans":
                self.rehearsal_humans = bool(data.get("on"))
            elif kind in ("demo.reset", "director.reset"):
                self.steps, self.decisions, self.waiting_owner, self.done = 0, {}, None, False

    async def run(self) -> None:
        await asyncio.gather(self.sw.run(), self.follow_core())


def main(vendor_id: str, cls=VendorAgent) -> None:
    here = ROOT / "agents" / "vendors" / vendor_id
    rules = Path(env(f"MANDI_VENDOR_RULES_{vendor_id.upper()}", str(ROOT / "config" / "vendors" / f"{vendor_id}.yaml")))
    pdf = ROOT / "seed" / "quotes" / f"{vendor_id}-quote.pdf"
    asyncio.run(cls(vendor_id, rules, pdf).run())
