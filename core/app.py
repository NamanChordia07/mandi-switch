"""Mandi Core — FastAPI service on :8700.

Run:  .venv/Scripts/python -m uvicorn core.app:app --host 127.0.0.1 --port 8700
Docs: http://127.0.0.1:8700/docs
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from . import db, director, service
from .auth import Caller, caller_dep, require, require_vendor_scope, resolve
from .config import ROOT, env, scenario, scenario_date
from .events import bus
from .states import OrderState

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(_app):
    db.configure()
    yield


app = FastAPI(title="Mandi Core", version="0.1.0", lifespan=_lifespan,
              description="Deterministic procurement rules behind Mandi's Switch agents. "
                          "Agents negotiate. Humans decide. Switch enforces.")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])

STATUS: dict[str, Any] = {"switch_live": False, "switch_live_at": None, "auditor": None}


@app.exception_handler(service.CoreError)
def _core_error(_: Request, exc: service.CoreError):
    return JSONResponse(status_code=exc.status, content={"detail": str(exc), "failed_checks": exc.details})


@app.exception_handler(ValueError)
def _value_error(_: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ----------------------------------------------------------------------------- models
class CreateOrder(BaseModel):
    raw_text: str
    requester: str
    order_id: Optional[str] = None
    switch_message_id: Optional[str] = None


class SpecIn(BaseModel):
    spec: dict[str, Any]


class ConfirmIn(BaseModel):
    by_user: str
    switch_message_id: Optional[str] = None


class RoomsIn(BaseModel):
    rooms: dict[str, str]


class OutboundIn(BaseModel):
    message_text: str
    action: str = Field(description="ask | requote | accept | walk_away | close")
    ask_paise: Optional[int] = None
    claims: list[dict[str, Any]] = Field(default_factory=list)
    redteam: bool = False


class InboundIn(BaseModel):
    unit_price_paise: int
    basis: str = "DELIVERED"
    quantity: int
    is_final: bool = False
    message_text: str = ""
    switch_message_id: Optional[str] = None
    conditions: str = ""


class VendorApprovalIn(BaseModel):
    stage: str
    unit_price_paise: int
    decision: Optional[str] = None
    decided_by_user: Optional[str] = None
    mechanism: str = "SWITCH_MESSAGE_FALLBACK"
    switch_ref: Optional[str] = None
    agent_name: str = ""


class NoteIn(BaseModel):
    note: str = ""
    agent_name: Optional[str] = None


class IssueIn(BaseModel):
    vendor_id: Optional[str] = None
    agent_name: Optional[str] = None


class DocIn(BaseModel):
    room_key: str
    title: str
    document_id: Optional[str] = None


class AuditNoteIn(BaseModel):
    kind: str
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)


class FeedIn(BaseModel):
    items: list[dict[str, Any]]


class StatusIn(BaseModel):
    agent: str
    live: bool
    detail: dict[str, Any] = Field(default_factory=dict)


class AttachIn(BaseModel):
    offer_id: str
    switch_message_id: str


# ----------------------------------------------------------------------------- health
@app.get("/health")
def health():
    return {"ok": True, "service": "mandi-core", "scenario_date": scenario_date().isoformat(),
            "current_order": service.current_order_id(), "switch": STATUS}


@app.get("/ui/config")
def ui_config(request: Request):
    """Local-only: hands the Control Room its tokens. Core binds to 127.0.0.1."""
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(403, "local only")
    return {"ui_token": env("CORE_TOKEN_UI"), "director_token": env("CORE_TOKEN_DIRECTOR"),
            "scenario": scenario()["order"] | {"vendors": scenario()["vendors"], "personas": scenario()["personas"]},
            "scenario_date": scenario_date().isoformat()}


# ----------------------------------------------------------------------------- orders
@app.get("/orders/current")
def current(caller: Caller = Depends(caller_dep)):
    oid = service.current_order_id()
    if not oid:
        return {"order": None}
    return service.order_view(oid, vendor_scope=caller.vendor_id if caller.kind == "vendor" else None)


@app.post("/orders")
def create_order(body: CreateOrder, caller: Caller = Depends(caller_dep)):
    require(caller, "agents", "director")
    return service.create_order(raw_text=body.raw_text, requester=body.requester, actor=f"{caller.label}",
                                order_id=body.order_id, switch_message_id=body.switch_message_id)


@app.get("/orders/{order_id}")
def get_order(order_id: str, caller: Caller = Depends(caller_dep)):
    return service.order_view(order_id, vendor_scope=caller.vendor_id if caller.kind == "vendor" else None)


@app.post("/orders/{order_id}/spec")
def set_spec(order_id: str, body: SpecIn, caller: Caller = Depends(caller_dep)):
    require(caller, "agents")
    return service.set_spec(order_id, body.spec, actor="agent:mandi-intake")


@app.post("/orders/{order_id}/spec/confirm")
def confirm_spec(order_id: str, body: ConfirmIn, caller: Caller = Depends(caller_dep)):
    require(caller, "agents")
    return service.confirm_spec(order_id, by_user=body.by_user, actor="agent:mandi-intake",
                                switch_message_id=body.switch_message_id)


@app.post("/orders/{order_id}/rfq")
def open_rfq(order_id: str, body: RoomsIn, caller: Caller = Depends(caller_dep)):
    require(caller, "agents")
    return service.open_rfq(order_id, rooms=body.rooms, actor="agent:mandi-intake")


@app.post("/orders/{order_id}/rooms")
def register_rooms(order_id: str, body: RoomsIn, caller: Caller = Depends(caller_dep)):
    require(caller, "agents", "director")
    service.register_rooms(order_id, body.rooms)
    return {"ok": True}


@app.post("/orders/{order_id}/quotes")
async def upload_quote(order_id: str, vendor_id: str = Form(...), via: str = Form("vendor_upload"),
                       switch_message_id: Optional[str] = Form(None), file: UploadFile = File(...),
                       caller: Caller = Depends(caller_dep)):
    require(caller, "agents", "vendor", "director")
    require_vendor_scope(caller, vendor_id)
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "Quote file too large (10 MB max).")
    if not content.startswith(b"%PDF"):
        raise HTTPException(400, "Quote must be a PDF.")
    return await asyncio.to_thread(service.add_quote, order_id, vendor_id=vendor_id, filename=file.filename or "quote.pdf",
                                   content=content, via=via, actor=caller.label,
                                   switch_message_id=switch_message_id)


@app.post("/orders/{order_id}/quotes/{quote_id}/parse")
async def parse_quote(order_id: str, quote_id: str, caller: Caller = Depends(caller_dep)):
    require(caller, "agents", "director")
    return await asyncio.to_thread(service.parse_quote, order_id, quote_id, actor="agent:mandi-quotes")


@app.get("/orders/{order_id}/comparison")
def get_comparison(order_id: str, caller: Caller = Depends(caller_dep)):
    require(caller, "agents", "mcp_purchase_desk", "mcp_po_issuer", "ui", "director")
    return service.comparison(order_id)


@app.post("/orders/{order_id}/comparison/publish")
def publish_comparison(order_id: str, caller: Caller = Depends(caller_dep)):
    require(caller, "agents")
    return service.publish_comparison(order_id, actor="agent:mandi-quotes")


@app.post("/orders/{order_id}/negotiation/start")
def start_negotiation(order_id: str, caller: Caller = Depends(caller_dep)):
    require(caller, "agents", "director")
    return service.start_negotiation(order_id, actor=caller.label)


@app.get("/negotiation/{order_id}/{vendor_id}")
def negotiation_state(order_id: str, vendor_id: str, caller: Caller = Depends(caller_dep)):
    require(caller, "agents", "ui", "director")
    return service.negotiation_state(order_id, vendor_id)


@app.post("/negotiation/{order_id}/{vendor_id}/outbound")
def outbound(order_id: str, vendor_id: str, body: OutboundIn, caller: Caller = Depends(caller_dep)):
    require(caller, "agents")
    return service.outbound(order_id, vendor_id, message_text=body.message_text, action=body.action,
                            ask_paise=body.ask_paise, claims=body.claims,
                            actor=f"agent:mandi-negotiator-{vendor_id}", redteam=body.redteam)


@app.post("/negotiation/{order_id}/{vendor_id}/attach")
def attach(order_id: str, vendor_id: str, body: AttachIn, caller: Caller = Depends(caller_dep)):
    require(caller, "agents")
    service.attach_switch_message(order_id, body.offer_id, body.switch_message_id)
    return {"ok": True}


@app.post("/negotiation/{order_id}/{vendor_id}/inbound")
def inbound(order_id: str, vendor_id: str, body: InboundIn, caller: Caller = Depends(caller_dep)):
    require(caller, "agents")
    return service.inbound(order_id, vendor_id, unit_price_paise=body.unit_price_paise, basis=body.basis,
                           quantity=body.quantity, is_final=body.is_final, message_text=body.message_text,
                           switch_message_id=body.switch_message_id, conditions=body.conditions,
                           actor=f"agent:mandi-negotiator-{vendor_id}")


@app.post("/negotiation/{order_id}/{vendor_id}/vendor-approval")
def vendor_approval(order_id: str, vendor_id: str, body: VendorApprovalIn, caller: Caller = Depends(caller_dep)):
    require(caller, "vendor", "agents")
    require_vendor_scope(caller, vendor_id)
    return service.vendor_approval(order_id, vendor_id, stage=body.stage, unit_price_paise=body.unit_price_paise,
                                   decision=body.decision, decided_by_user=body.decided_by_user,
                                   mechanism=body.mechanism, switch_ref=body.switch_ref,
                                   agent_name=body.agent_name, actor=caller.label)


@app.post("/orders/{order_id}/close-negotiation")
def close_negotiation(order_id: str, caller: Caller = Depends(caller_dep)):
    require(caller, "agents", "director")
    return service.close_negotiation(order_id, actor=caller.label)


@app.post("/orders/{order_id}/endorsement-requested")
def endorsement_requested(order_id: str, caller: Caller = Depends(caller_dep)):
    require(caller, "agents")
    service.request_endorsement(order_id, actor="agent:mandi-intake")
    return {"ok": True}


@app.post("/orders/{order_id}/endorse")
def endorse(order_id: str, body: NoteIn, caller: Caller = Depends(caller_dep)):
    require(caller, "mcp_purchase_desk")
    return service.endorse(order_id, caller_kind=caller.kind, note=body.note)


@app.post("/orders/{order_id}/endorse-declined")
def endorse_declined(order_id: str, body: NoteIn, caller: Caller = Depends(caller_dep)):
    require(caller, "mcp_purchase_desk", "director", "agents")
    return service.endorse_declined(order_id, caller_kind=caller.kind, note=body.note)


@app.post("/orders/{order_id}/issue-po")
def issue_po(order_id: str, body: IssueIn | None = None, caller: Caller = Depends(caller_dep)):
    # Deliberately NOT restricted by require(): every caller reaches the gate so refusals are audited.
    # Only the po-issuer MCP token can pass gate check #1.
    body = body or IssueIn()
    return service.issue_po(order_id, caller_kind=caller.kind,
                            agent_name=body.agent_name or ("po-issuer" if caller.kind == "mcp_po_issuer" else caller.label),
                            vendor_id=body.vendor_id)


@app.post("/orders/{order_id}/po-declined")
def po_declined(order_id: str, body: NoteIn, caller: Caller = Depends(caller_dep)):
    require(caller, "mcp_po_issuer", "director", "agents")
    return service.po_declined(order_id, caller_kind=caller.kind, note=body.note)


@app.get("/orders/{order_id}/po.pdf")
def po_pdf(order_id: str, caller: Caller = Depends(caller_dep)):
    view = service.order_view(order_id)
    if not view["po"]:
        raise HTTPException(404, "No PO issued yet.")
    return FileResponse(ROOT / view["po"]["pdf_path"], media_type="application/pdf",
                        filename=f"{view['po']['id']}.pdf")


@app.get("/orders/{order_id}/po.png")
def po_png(order_id: str, caller: Caller = Depends(caller_dep)):
    """First page of the PO as an image (for previews where a PDF viewer isn't available)."""
    import pymupdf
    from fastapi.responses import Response
    view = service.order_view(order_id)
    if not view["po"]:
        raise HTTPException(404, "No PO issued yet.")
    doc = pymupdf.open(str(ROOT / view["po"]["pdf_path"]))
    return Response(doc[0].get_pixmap(dpi=110).tobytes("png"), media_type="image/png")


@app.get("/orders/{order_id}/quotes/{quote_id}/file")
def quote_file(order_id: str, quote_id: str, caller: Caller = Depends(caller_dep)):
    require(caller, "agents", "ui", "director")
    view = service.order_view(order_id)
    q = next((q for q in view["quotes"] if q["id"] == quote_id), None)
    if not q:
        raise HTTPException(404, "Quote not found.")
    return FileResponse(ROOT / q["source_file"], media_type="application/pdf")


@app.get("/orders/{order_id}/quotes/{quote_id}/page/{page_no}.png")
def quote_page(order_id: str, quote_id: str, page_no: int, caller: Caller = Depends(caller_dep)):
    """A quote page rendered with hidden / injected text outlined (Control Room injection panel)."""
    require(caller, "agents", "ui", "director")
    from fastapi.responses import Response
    from .render import render_page
    view = service.order_view(order_id)
    q = next((q for q in view["quotes"] if q["id"] == quote_id), None)
    if not q:
        raise HTTPException(404, "Quote not found.")
    png = render_page(ROOT / q["source_file"], page_no, q.get("injection_spans") or [])
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=300"})


@app.get("/orders/{order_id}/audit")
def get_audit(order_id: str, caller: Caller = Depends(caller_dep)):
    require(caller, "agents", "mcp_purchase_desk", "mcp_po_issuer", "ui", "director")
    return service.audit_view(order_id)


@app.post("/orders/{order_id}/audit-note")
def audit_note(order_id: str, body: AuditNoteIn, caller: Caller = Depends(caller_dep)):
    require(caller, "agents", "director")
    service.note(order_id, kind=body.kind, summary=body.summary, actor=caller.label, **body.data)
    return {"ok": True}


@app.post("/orders/{order_id}/docs")
def doc_saved(order_id: str, body: DocIn, caller: Caller = Depends(caller_dep)):
    require(caller, "agents")
    service.note_doc_saved(order_id, room_key=body.room_key, title=body.title, actor=caller.label,
                           document_id=body.document_id)
    return {"ok": True}


@app.get("/orders/{order_id}/outcome")
def get_outcome(order_id: str, caller: Caller = Depends(caller_dep)):
    require(caller, "agents", "mcp_purchase_desk", "mcp_po_issuer", "ui", "director")
    return service.outcome(order_id)


# ----------------------------------------------------------------------------- switch feed + status
@app.post("/switch/feed")
def post_feed(body: FeedIn, caller: Caller = Depends(caller_dep)):
    require(caller, "agents")
    return {"added": service.feed_add(body.items)}


@app.get("/switch/feed")
def get_feed(limit: int = 300, room: Optional[str] = None, caller: Caller = Depends(caller_dep)):
    require(caller, "agents", "ui", "director")
    return {"items": service.feed(limit, room)}


@app.post("/switch/status")
def post_status(body: StatusIn, caller: Caller = Depends(caller_dep)):
    require(caller, "agents")
    from .models import now_iso
    STATUS["switch_live"] = body.live
    STATUS["switch_live_at"] = now_iso()
    STATUS["auditor"] = body.detail
    bus.publish("switch.status", None, live=body.live, detail=body.detail)
    return {"ok": True}


@app.get("/switch/rooms")
def switch_rooms(caller: Caller = Depends(caller_dep)):
    require(caller, "agents", "ui", "director")
    path = Path(os.environ.get("MANDI_SECRETS_DIR", ROOT / "secrets")) / "switch-ids.local.json"
    rooms = json.loads(path.read_text(encoding="utf-8")).get("rooms", {}) if path.exists() else {}
    return {"rooms": rooms, "live": STATUS["switch_live"]}


# ----------------------------------------------------------------------------- events
async def _event_gen(request: Request, since: int):
    q = bus.subscribe()
    try:
        for e in bus.since(since):
            yield {"id": str(e["id"]), "event": "mandi", "data": json.dumps(e, default=str)}
        while True:
            if await request.is_disconnected():
                break
            try:
                e = await asyncio.wait_for(q.get(), timeout=15)
                yield {"id": str(e["id"]), "event": "mandi", "data": json.dumps(e, default=str)}
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": "{}"}
    finally:
        bus.unsubscribe(q)


@app.get("/events/stream")
async def events_stream(request: Request, since: int = 0, caller: Caller = Depends(caller_dep)):
    return EventSourceResponse(_event_gen(request, since))


@app.websocket("/events/ws")
async def events_ws(ws: WebSocket, token: str = "", since: int = 0):
    if not resolve(token):
        await ws.close(code=4401)
        return
    await ws.accept()
    q = bus.subscribe()
    try:
        for e in bus.since(since):
            await ws.send_text(json.dumps(e, default=str))
        while True:
            e = await q.get()
            await ws.send_text(json.dumps(e, default=str))
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)


# ----------------------------------------------------------------------------- director
@app.post("/director/{action}")
async def director_action(action: str, request: Request, caller: Caller = Depends(caller_dep)):
    require(caller, "director")
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await director.handle(action, body)


# ----------------------------------------------------------------------------- UI (prod build)
UI_DIST = ROOT / "ui" / "dist"
if UI_DIST.exists():
    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
