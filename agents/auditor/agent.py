"""mandi-auditor — Mandi Exchange's neutral record-keeper.

* One `scope=all, filter=all` connection: receives every message, command and join in every order room it is a
  member of (order room + the three sealed rooms) and streams them into Mandi Core's /switch/feed. The Control
  Room's chat mirror is therefore fed by REAL Switch events, not by Mandi's own logs.
* A second, single-room connection to the order room is used to post the Outcome card and save the audit log as
  a room document at the end.
* It never answers messages (addressing: owner only), never negotiates, never approves.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from agents.common.directory import Directory
from agents.common.runtime import Core, CoreHTTPError, make_switch_agent, pace, set_speed, setup_logging
from agents.switchclient import Event, SwitchAgent
from core.money import fmt_inr, fmt_unit, indian_group

NAME = "mandi-auditor"
log = setup_logging(NAME)
GATES = {"purchase-desk": "purchase_head", "po-issuer": "finance"}


class Auditor:
    def __init__(self):
        self.dir = Directory()
        self.order_room = self.dir.room("order")
        self.watch = make_switch_agent(NAME, scope="all", filter="all")
        self.desk = make_switch_agent(NAME, rooms=[self.order_room])
        # the two connections must not share a connection_id
        self.desk.state_path = self.desk.state_path.with_name(f"{NAME}-order.json")
        self.desk.state = self.desk._load_state()
        import uuid
        self.desk.connection_id = self.desk.state.setdefault("connection_id", str(uuid.uuid4()))
        self.desk.cursor = self.desk.state.get("cursor")
        self.desk.generation = self.desk.state.get("generation")
        self.core = Core()
        self.buffer: list[dict[str, Any]] = []
        for sw in (self.watch, self.desk):
            sw.on("message", addressed_only=False)(self.on_event)
            sw.on("room_join")(self.on_event)
            sw.on("command")(self.on_event)
        self.watch.on_state_change = self.on_state

    async def on_state(self, live: bool, state: dict[str, Any]) -> None:
        try:
            await self.core.post("/switch/status", {"agent": NAME, "live": live,
                                                     "detail": {"rooms": state.get("rooms"), "scope": state.get("scope"),
                                                                "generation": state.get("generation"),
                                                                "server": state.get("server")}})
        except Exception as exc:
            log.warning("status update failed: %s", exc)

    async def on_event(self, ev: Event) -> None:
        p = ev.payload
        if ev.kind == "message":
            sender, name, body = ev.sender, ev.sender_name, ev.body
        elif ev.kind == "room_join":
            sender, name = p.get("member", ""), p.get("member_name", "")
            body = f"{name or sender} joined the room"
        else:
            sender, name = p.get("user_id", ""), p.get("user_name", "")
            body = f"!{p.get('command', '')} {' '.join(map(str, p.get('args') or []))}".strip()
        agent = self.dir.agent_of(sender, name)
        item = {
            "event": ev.kind, "room_id": ev.room_id, "room_key": self.dir.room_key(ev.room_id),
            "sequence": ev.sequence, "message_id": ev.payload.get("message_id") or f"{ev.kind}-{ev.sequence}",
            "thread_id": ev.payload.get("thread_id"), "sender": sender,
            "sender_name": agent or self.dir.persona_of(sender, name) or name or sender,
            "sender_kind": self.dir.kind(sender, name), "body": body[:4000], "addressed": ev.addressed,
            "data": {"attachments": ev.attachments, "display_name": name},
        }
        self.buffer.append(item)
        await self.flush()
        if ev.kind == "message":
            await self.watch_approvals(ev, agent, body)

    async def flush(self) -> None:
        if not self.buffer:
            return
        items, self.buffer = self.buffer, []
        try:
            await self.core.post("/switch/feed", {"items": items})
        except Exception as exc:
            log.warning("feed push failed (%s); will retry", exc)
            self.buffer = items + self.buffer

    async def watch_approvals(self, ev: Event, agent: str | None, body: str) -> None:
        """Record Switch's permission-request traffic around the gate agents in the audit trail."""
        if ev.room_id != self.order_room:
            return
        low = body.lower()
        oid = await self._oid()
        if not oid:
            return
        if agent in GATES and re.search(r"allow once|allow for this session|permission|wants to|approve", low):
            await self._note(oid, f"Switch posted @{agent}'s permission request in the order room.", ev, agent)
        elif self.dir.kind(ev.sender, ev.sender_name) == "switch" and re.search(r"allow|declin|approv", low):
            await self._note(oid, f"Switch recorded a permission decision: “{body[:160]}”.", ev, agent)

    async def _note(self, oid: str, summary: str, ev: Event, agent: str | None) -> None:
        try:
            await self.core.post(f"/orders/{oid}/audit-note", {"kind": "SWITCH_APPROVAL_OBSERVED", "summary": summary,
                                                               "data": {"switch_message_id": ev.message_id,
                                                                        "agent": agent, "body": ev.body[:500]}})
        except CoreHTTPError as exc:
            log.debug("note failed: %s", exc)

    async def _oid(self) -> str | None:
        cur = await self.core.current_order()
        return cur["order"]["id"] if cur else None

    # ------------------------------------------------------------------ Core events
    async def follow_core(self) -> None:
        async for evt in self.core.events():
            try:
                kind, data, oid = evt["kind"], evt.get("data", {}), evt.get("order_id")
                if kind == "director.speed":
                    set_speed(data.get("speed", 1.0))
                elif kind == "po.issued":
                    await self.outcome(oid)
            except Exception:
                log.exception("core event failed")

    async def outcome(self, oid: str) -> None:
        await pace(3.0)
        o = await self.core.get(f"/orders/{oid}/outcome")
        if not o.get("po"):
            return
        mins, secs = divmod(o.get("elapsed_seconds") or 0, 60)
        approvals = " · ".join(f"{a['name']} ({'Purchase Head' if 'PURCHASE' in a['kind'] else 'Finance'})"
                               for a in o["approvals"])
        caught = []
        for t in o["traps"]:
            code = t.split(": ")[-1]
            caught.append({"HIDDEN_MOQ": "hidden MOQ", "EXPIRED": "expired quote", "FREIGHT_EXCLUDED":
                           "freight not included", "LATE_DELIVERY": "late delivery"}.get(code, code))
        card = "\n".join([
            f"🤝 **{oid} closed — {o['po']['id']} issued to {o['vendor']}**",
            f"Unit {o['unit']} × {indian_group(o['quantity'])} = **{o['total']}** (excl. GST) · Lead "
            f"{o['lead_time_days']} days · Payment {o['payment_terms_days']} days",
            f"Saved **{o['saved']} ({o['saved_pct']})** vs best valid opening quote",
            f"Caught: {' · '.join(caught)} · {o['injections_blocked']} prompt injection blocked",
            f"Approvals: {approvals} — via Switch",
            f"Time: {mins} min {secs:02d} s (paper process: ~{o['paper_process_days']} days)",
            "📄 PO and audit log saved to this room — `!list-documents`",
        ])
        await self.desk.post(self.order_room, card)
        audit = await self.core.get(f"/orders/{oid}/audit")
        lines = [f"# Audit log — {oid}", "",
                 f"Hash chain: {'verified ✓' if audit['verified']['ok'] else 'BROKEN ✗'} "
                 f"({audit['verified']['checked']} events, head `{audit['verified'].get('head', '')[:16]}…`)", "",
                 "| # | Time (UTC) | Actor | Event | Summary |", "|---|---|---|---|---|"]
        for e in audit["events"]:
            if e["kind"] == "STATE_CHANGED":
                continue
            lines.append(f"| {e['seq']} | {e['at'][11:19]} | {e['actor']} | {e['kind']} | "
                         f"{e['summary'].replace('|', '/')[:220]} |")
        try:
            doc = await self.desk.upsert_doc("04-audit-log", f"Hash-chained audit log for {oid}",
                                             "Tamper-evident record of every step. Verify via Mandi Core /audit.",
                                             "\n".join(lines))
            await self.core.post(f"/orders/{oid}/docs", {"room_key": "order", "title": "04-audit-log", "document_id": doc})
            await self.core.post(f"/orders/{oid}/audit-note", {"kind": "OUTCOME_POSTED",
                                                               "summary": "Auditor posted the Outcome card and saved the audit log to the order room."})
        except Exception as exc:
            log.warning("audit doc failed: %s", exc)

    async def run(self) -> None:
        async def periodic_flush():
            while True:
                await asyncio.sleep(5)
                await self.flush()
        await asyncio.gather(self.watch.run(), self.desk.run(), self.follow_core(), periodic_flush())


if __name__ == "__main__":
    asyncio.run(Auditor().run())
