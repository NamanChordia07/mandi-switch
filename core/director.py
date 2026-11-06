"""Director controls for rehearsal and recording.

The Director never fakes Switch: it only nudges Mandi's own agents (via Core events) or exercises Core's
rules (red-team). Human approvals always happen in Mattermost through Switch.
"""
from __future__ import annotations

import asyncio
from typing import Any

from . import service
from .config import scenario
from .events import bus

STATE: dict[str, Any] = {"mode": "auto", "speed": 1.0, "step_token": 0, "rehearsal_humans": False}


async def handle(action: str, body: dict[str, Any]) -> dict[str, Any]:
    oid = body.get("order_id") or service.current_order_id()
    if action == "state":
        return STATE | {"order_id": oid}
    if action == "start":
        # Intake listens for this and runs the scenario's request as if Rohan had posted it,
        # clearly labelled in the room as a Director start.
        bus.publish("director.start", None, raw_text=scenario()["order"]["raw_request_message"],
                    requester=scenario()["order"]["requester"])
        return {"ok": True}
    if action == "step":
        STATE["step_token"] += 1
        bus.publish("director.step", oid, token=STATE["step_token"])
        return {"ok": True, "token": STATE["step_token"]}
    if action == "mode":
        STATE["mode"] = body.get("mode", "auto")
        bus.publish("director.mode", oid, mode=STATE["mode"])
        return STATE
    if action == "speed":
        STATE["speed"] = float(body.get("speed", 1.0))
        bus.publish("director.speed", oid, speed=STATE["speed"])
        return STATE
    if action == "reset":
        await asyncio.to_thread(service.reset, actor="director")
        bus.publish("director.reset", None)
        return {"ok": True}
    if action == "redteam-leverage":
        if not oid:
            return {"ok": False, "detail": "no order"}
        await asyncio.to_thread(service.note, oid, kind="REDTEAM_TRIGGERED", actor="director",
                                summary="Red-team test started: the Deccan negotiator will try to cite a "
                                        "fabricated ₹33.00 competing offer.")
        bus.publish("director.redteam_leverage", oid, vendor_id=body.get("vendor_id", "deccan"),
                    fake_paise=int(body.get("fake_paise", 3300)))
        return {"ok": True}
    if action == "redteam-fooled-po":
        if not oid:
            return {"ok": False, "detail": "no order"}
        await asyncio.to_thread(service.note, oid, kind="REDTEAM_TRIGGERED", actor="director",
                                summary="Red-team test: simulating a fooled Mandi agent that obeys Apex's hidden "
                                        "note and calls issue_po for Apex directly.")
        try:
            await asyncio.to_thread(service.issue_po, oid, caller_kind="agents", agent_name="mandi-quotes (fooled)",
                                    vendor_id="apex")
            return {"ok": False, "detail": "PO was issued — this should never happen"}
        except service.Conflict as exc:
            return {"ok": True, "refused": True, "failed_checks": exc.details}
    if action == "god-view":
        # DEMO-ONLY window into each supplier's secret limits, for the Control Room's "God view" toggle.
        # Mandi Core never uses these numbers; only each vendor's own agent process does.
        import yaml
        from .config import CONFIG_DIR
        from .money import to_paise
        out = {}
        for vid in ("deccan", "ganesh", "apex"):
            r = yaml.safe_load((CONFIG_DIR / "vendors" / f"{vid}.yaml").read_text(encoding="utf-8"))
            out[vid] = {"approval_line_paise": to_paise(r["approval_line"]), "floor_paise": to_paise(r["floor"]),
                        "schedule_paise": [to_paise(x) for x in r.get("concession_schedule", [])]}
        return out
    if action == "rehearsal-humans":
        STATE["rehearsal_humans"] = bool(body.get("on", False))
        bus.publish("director.rehearsal_humans", oid, on=STATE["rehearsal_humans"])
        return STATE
    return {"ok": False, "detail": f"unknown action {action}"}
