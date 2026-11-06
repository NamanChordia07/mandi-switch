"""mandi-quotes — Quote Analyst. Parses every quote that arrives (via a sealed room or the mailbox), catches
traps, blocks prompt injections, and publishes the normalised comparison in the ORDER room.

Vendor documents are untrusted data: they are parsed by Mandi Core (code + an evidence-checked LLM pass) and
never placed in this agent's instructions.
"""
from __future__ import annotations

import asyncio
from typing import Any

from agents.common.directory import Directory
from agents.common.runtime import Core, CoreHTTPError, make_switch_agent, pace, set_speed, setup_logging
from core.config import scenario
from core.money import fmt_inr, fmt_unit, indian_group

NAME = "mandi-quotes"
log = setup_logging(NAME)


class QuoteAnalyst:
    def __init__(self):
        self.dir = Directory()
        self.order_room = self.dir.room("order")
        self.sw = make_switch_agent(NAME, rooms=[self.order_room])
        self.core = Core()
        self.lock = asyncio.Lock()
        self.published: set[str] = set()

        @self.sw.on("message")
        async def _(ev):  # addressed questions: answer with the latest comparison
            if ev.room_id == self.order_room and not self.dir.is_agent(ev.sender, ev.sender_name):
                current = await self.core.current_order()
                if current:
                    await self.post_comparison(current["order"]["id"], thread_id=ev.message_id, again=True)

    async def follow_core(self) -> None:
        async for evt in self.core.events():
            try:
                await self.on_core(evt)
            except Exception:
                log.exception("core event handling failed: %s", evt.get("kind"))

    async def on_core(self, evt: dict[str, Any]) -> None:
        kind, data, oid = evt["kind"], evt.get("data", {}), evt.get("order_id")
        if kind == "director.speed":
            set_speed(data.get("speed", 1.0))
        elif kind in ("demo.reset", "director.reset"):
            self.published.clear()
        elif kind == "quote.received":
            async with self.lock:
                await self.analyse(oid, data["quote_id"], data["vendor_id"])
                await self.maybe_publish(oid)
        elif kind == "audit" and data.get("audit_kind") == "LEVERAGE_BLOCKED" and data.get("data", {}).get("redteam"):
            reasons = data.get("data", {}).get("reasons", [])
            await self.sw.post(self.order_room, "⛔ **Lock 3 held (red-team test):** Mandi Core blocked a negotiator "
                               "message before it reached the supplier's room.\n> " + (reasons[0] if reasons else ""))

    async def analyse(self, oid: str, qid: str, vendor_id: str) -> None:
        vname = scenario()["vendors"][vendor_id]["legal_name"]
        await self.sw.typing(self.order_room, True)
        try:
            q = await self.core.post(f"/orders/{oid}/quotes/{qid}/parse")
        except CoreHTTPError as exc:
            await self.sw.post(self.order_room, f"⚠️ I couldn't parse {vname}'s file — @meera please check the "
                               "upload.")
            log.error("parse failed: %s", exc)
            return
        finally:
            await self.sw.typing(self.order_room, False)
        await pace(1.0)
        if q["injection_verdict"] == "INJECTION":
            await self.injection_alert(vname, q)
            return
        traps = [t for t in q["traps"] if t["code"] != "MISSING_FIELD"]
        head = (f"📄 Read **{vname}**'s quote ({'mailbox' if q['received_via'] == 'email_import' else 'sealed room'}): "
                f"{fmt_unit(q['unit_price_paise'])}/pc {'ex-works' if q['basis'] == 'EX_WORKS' else 'delivered'}, "
                f"MOQ {indian_group(q['moq'])}, lead {q['lead_time_days']} days, payment {q['payment_terms_days']} days.")
        if not traps:
            await self.sw.post(self.order_room, head + " ✅ No traps.")
            return
        lines = [head]
        for t in traps:
            ev = t.get("evidence") or {}
            where = f" _(p.{ev['page']}: “{ev['snippet'][:90]}”)_" if ev.get("page") and ev.get("snippet") else ""
            icon = "⛔" if t["severity"] == "BLOCKER" else "⚠️"
            lines.append(f"{icon} {t['message']}{where}")
        await self.sw.post(self.order_room, "\n".join(lines))

    async def injection_alert(self, vname: str, q: dict[str, Any]) -> None:
        span = (q.get("injection_spans") or [""])[0]
        hidden = (q.get("injection_detail") or {}).get("hidden") or []
        how = f"hidden as {hidden[0]['reason']} on page {hidden[0]['page']}" if hidden else "inside the document"
        msg = (f"⛔ **Prompt injection blocked — {vname}**\n"
               f"Their quote PDF contains instructions aimed at our AI agents, {how}:\n"
               f"```\n{span[:420]}\n```\n"
               f"It tried to make an agent skip the comparison and get a PO issued without telling you. "
               f"Mandi treated it as data, **disqualified {vname}**, and is closing their room.\n"
               f"Even if an agent had been fooled: a PO needs Meera's and Vikram's approval in Switch, and Mandi's "
               f"PO rules would still refuse. @meera FYI.")
        await self.sw.post(self.order_room, msg)

    async def maybe_publish(self, oid: str) -> None:
        if oid in self.published:
            return
        view = await self.core.get(f"/orders/{oid}")
        expected = {v["vendor_id"] for v in view["vendors"]}
        parsed = {q["vendor_id"] for q in view["quotes"] if q["parsed"]}
        if not expected <= parsed:
            return
        self.published.add(oid)
        await pace(2.0)
        await self.core.post(f"/orders/{oid}/comparison/publish")
        await self.post_comparison(oid)
        await pace(2.0)
        await self.core.post(f"/orders/{oid}/negotiation/start")
        view = await self.core.get(f"/orders/{oid}")
        active = [v["legal_name"] for v in view["vendors"] if v["status"] == "ACTIVE"]
        await self.sw.post(self.order_room, f"🤝 Starting **parallel negotiations** in the sealed rooms with "
                           f"{' and '.join(active)}. Negotiators may cite only offers Mandi has verified — anonymously.")

    async def post_comparison(self, oid: str, thread_id: str | None = None, again: bool = False) -> None:
        cmp = await self.core.get(f"/orders/{oid}/comparison")
        qty = cmp["quantity"]
        lines = [f"📊 **Quote comparison — {oid}** ({indian_group(qty)} pcs, landed, excl. GST)", "",
                 "| Rank | Vendor | Unit (landed) | Total | Lead | Flags |", "|---|---|---|---|---|---|"]
        for r in cmp["rows"]:
            rank = str(r["rank"]) if r["rank"] else "–"
            if r["injection_verdict"] == "INJECTION":
                lines.append(f"| – | {r['vendor']} | — | — | — | ⛔ Prompt injection — disqualified |")
                continue
            unit = fmt_unit(r["landed_unit_paise"]) if r["landed_unit_paise"] else "—"
            if not r["comparable"]:
                unit += "*"
            total = fmt_inr(r["landed_total_paise"]) if r["landed_total_paise"] else "—"
            flags = []
            for t in r["traps"]:
                if t["code"] == "HIDDEN_MOQ":
                    flags.append(f"⚠️ MOQ {indian_group(r['moq'])}")
                elif t["code"] == "FREIGHT_EXCLUDED":
                    flags.append("⚠️ ex-works")
                elif t["code"] == "EXPIRED":
                    flags.append("⛔ " + t["message"].split(" (")[0])
                elif t["code"] == "LATE_DELIVERY":
                    flags.append("⛔ late")
            lines.append(f"| {rank} | {r['vendor']} | {unit} | {total} | {r['lead_time_days'] or '—'} d | "
                         f"{' · '.join(flags) or '—'} |")
        lines += ["", "*not comparable at our quantity as quoted.", "", cmp["recommendation"]]
        text = "\n".join(lines)
        await self.sw.post(self.order_room, text, thread_id=thread_id)
        if not again:
            try:
                doc_id = await self.sw.upsert_doc("02-quote-comparison", f"Quote comparison for {oid}",
                                                  "Normalised landed-cost comparison. Values computed by Mandi Core.",
                                                  text)
                await self.core.post(f"/orders/{oid}/docs", {"room_key": "order", "title": "02-quote-comparison",
                                                            "document_id": doc_id})
            except Exception as exc:
                log.warning("could not save comparison room document: %s", exc)

    async def run(self) -> None:
        await asyncio.gather(self.sw.run(), self.follow_core())


if __name__ == "__main__":
    asyncio.run(QuoteAnalyst().run())
