"""A tiny in-memory stand-in for the Switch agent protocol — FOR TESTS ONLY.

It implements just enough of the documented surface (registration, WebSocket events with ping/pong, operations,
connectionless messages, media upload/download) to run Mandi's real agents end to end without Docker. It is never
used by the demo and never presented as Switch: the real demo runs on Switch + Mattermost.

    python tests/fake_switch.py --port 8199
Humans speak through:  POST /test/say {"room": "<room key or id>", "user": "rohan", "body": "..."}
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import re
import time
import uuid
from collections import defaultdict
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

app = FastAPI(title="fake-switch (tests only)")
AGENTS: dict[str, dict[str, Any]] = {}          # id -> {name, api_key}
KEYS: dict[str, str] = {}                        # api_key -> agent id
ROOMS: dict[str, dict[str, Any]] = {}            # room_id -> {name, agents:set, users:set, docs, roles, instructions}
QUEUES: dict[str, list[asyncio.Queue]] = defaultdict(list)   # agent id -> live sockets' queues
SEQ: dict[str, itertools.count] = defaultdict(lambda: itertools.count(1))
MEDIA: dict[str, tuple[bytes, str, str]] = {}
LOG: list[dict[str, Any]] = []
OPS = {
    "list_bridges": [], "list_rooms": ["include_archived"], "create_room": ["name", "description", "agent_names", "user_names",
    "channel_type", "bridge_id", "instructions", "read_visibility", "write_visibility"], "list_participants": [],
    "invite_agent_to_room": ["room_id", "agent_name", "include_subagents"], "define_role": ["name", "instructions", "exclusive"],
    "list_roles": [], "create_room_document": ["name", "description", "instructions", "content"],
    "update_room_document": ["document_id", "name", "description", "instructions", "content"],
    "post_message": ["body", "thread_id"], "send_targeted_message": ["body", "target_names", "target_roles", "thread_id"],
    "read_context": ["limit", "since", "before", "room_id"], "list_agents": [], "connect_to_room": ["room_id"],
    "update_agent_detail": ["agent_id", "addressing"],
}
CONN_ROOM: dict[str, str] = {}                   # connection id -> claimed room (single scope)


def pid_agent(name: str) -> str:
    return f"@switch-agent-{name}:fake"


def pid_user(name: str) -> str:
    return f"@switch-user-{name}:fake"


def auth(authorization: str) -> str:
    key = authorization.removeprefix("Bearer ").strip()
    if key not in KEYS:
        raise HTTPException(401, "bad key")
    return KEYS[key]


@app.get("/health")
def health():
    return {"status": "ok", "fake": True}


@app.post("/agents")
async def register(req: Request, authorization: str = Header("")):
    body = await req.json()
    name = body["name"]
    existing = next((a for a in AGENTS.values() if a["name"] == name), None)
    if existing and not body.get("overwrite"):
        raise HTTPException(409, "exists")
    aid = existing["id"] if existing else f"agent-{name}"
    key = f"key-{name}-{uuid.uuid4().hex[:6]}"
    AGENTS[aid] = {"id": aid, "name": name}
    KEYS[key] = aid
    return {"id": aid, "api_key": key}


def broadcast(room_id: str, sender_pid: str, sender_name: str, body: str, attachments=None, kind="message"):
    room = ROOMS[room_id]
    mid = f"msg-{uuid.uuid4().hex[:8]}"
    LOG.append({"room": room["name"], "from": sender_name, "body": body, "t": time.time()})
    for aid in list(room["agents"]):
        name = AGENTS[aid]["name"]
        addressed = bool(re.search(rf"@{re.escape(name)}\b", body, re.I))
        seq = next(SEQ[aid])
        frame = {"event": kind, "id": seq, "data": {"type": kind, "room_id": room_id, "bridge_id": "mm",
                 "channel_type": "channel_public", "sequence": seq,
                 "payload": {"addressed": addressed, "sender": sender_pid, "sender_name": sender_name, "message_id": mid,
                             "body": body, "timestamp": int(time.time() * 1000), "thread_id": None,
                             "attachments": attachments or []}}}
        for q in QUEUES[aid]:
            q.put_nowait(frame)
    return mid


def room_of_conn(conn: str) -> str:
    if conn not in CONN_ROOM:
        raise HTTPException(409, "no connected room")
    return CONN_ROOM[conn]


@app.get("/agents/{agent_id}/ops")
def list_ops(agent_id: str, authorization: str = Header("")):
    auth(authorization)
    return {"operations": {k: {"description": k, "input_schema": {"type": "object", "properties": {p: {} for p in v}}}
                           for k, v in OPS.items()}}


@app.post("/agents/{agent_id}/ops/{op}")
async def call_op(agent_id: str, op: str, req: Request, authorization: str = Header(""),
                  x_switch_connection_id: str = Header("")):
    aid = auth(authorization)
    a = await req.json()
    me = AGENTS[aid]["name"]
    if op == "list_bridges":
        return {"result": [{"id": "mm", "type": "mattermost", "display_name": "Fake MM", "status": "active",
                            "is_default": True, "can_create_channels": True}]}
    if op == "list_rooms":
        return {"result": [{"id": rid, "name": r["name"]} for rid, r in ROOMS.items() if aid in r["agents"]]}
    if op == "create_room":
        rid = f"room-{len(ROOMS) + 1}"
        ids = {x["id"] for x in AGENTS.values() if x["name"] in a.get("agent_names", [])}
        ROOMS[rid] = {"name": a["name"], "agents": ids, "users": set(a.get("user_names") or []), "docs": {},
                      "roles": {}, "instructions": a.get("instructions", "")}
        return {"result": {"room_id": rid, "caller_is_member": aid in ids}}
    if op == "list_agents":
        return {"result": [{"id": x["id"], "name": x["name"]} for x in AGENTS.values()]}
    if op == "update_agent_detail":
        return {"result": {"ok": True}}
    if op == "invite_agent_to_room":
        tgt = next((x["id"] for x in AGENTS.values() if x["name"] == a["agent_name"]), None)
        if not tgt:
            raise HTTPException(404, "no such agent")
        ROOMS[a["room_id"]]["agents"].add(tgt)
        return {"result": {"ok": True}}
    if op == "connect_to_room":
        CONN_ROOM[x_switch_connection_id] = a["room_id"]
        return {"result": {"room_id": a["room_id"]}}
    rid = room_of_conn(x_switch_connection_id)
    room = ROOMS[rid]
    if op == "list_participants":
        return {"result": [{"id": pid_agent(AGENTS[x]["name"]), "name": AGENTS[x]["name"], "type": "agent"} for x in room["agents"]]
                + [{"id": pid_user(u), "name": u, "type": "user"} for u in room["users"]]}
    if op == "define_role":
        room["roles"][a["name"]] = {"exclusive": a.get("exclusive", False)}
        return {"result": {"status": "defined", "name": a["name"]}}
    if op == "list_roles":
        return {"result": [{"name": k, **v} for k, v in room["roles"].items()]}
    if op == "create_room_document":
        did = f"doc-{uuid.uuid4().hex[:6]}"
        room["docs"][did] = a
        return {"result": {"document_id": did}}
    if op == "update_room_document":
        room["docs"].setdefault(a["document_id"], {}).update(a)
        return {"result": {"document_id": a["document_id"], "status": "ok"}}
    if op == "post_message":
        return {"result": {"event_id": broadcast(rid, pid_agent(me), me, a["body"])}}
    if op == "send_targeted_message":
        body = " ".join(f"@{n}" for n in a.get("target_names") or []) + " " + a["body"]
        return {"result": {"event_id": broadcast(rid, pid_agent(me), me, body)}}
    if op == "read_context":
        return {"result": {"threads": [], "truncated": False}}
    raise HTTPException(404, f"unknown op {op}")


@app.post("/agents/{agent_id}/message")
async def message(agent_id: str, req: Request, authorization: str = Header("")):
    aid = auth(authorization)
    b = await req.json()
    return {"ok": True, "event_id": broadcast(b["room_id"], pid_agent(AGENTS[aid]["name"]), AGENTS[aid]["name"], b["content"])}


@app.post("/agents/{agent_id}/typing")
def typing(agent_id: str):
    return {"ok": True}


@app.post("/agents/{agent_id}/rooms/{room_id}/media")
async def upload(agent_id: str, room_id: str, authorization: str = Header(""), file: UploadFile = File(...),
                 caption: str | None = Form(None)):
    aid = auth(authorization)
    data = await file.read()
    mxc = f"mxc://fake/{uuid.uuid4().hex}"
    MEDIA[mxc] = (data, file.content_type or "application/pdf", file.filename or "file")
    att = [{"filename": file.filename, "mimetype": file.content_type or "application/pdf", "size": len(data),
            "mxc": mxc, "msgtype": "m.file"}]
    broadcast(room_id, pid_agent(AGENTS[aid]["name"]), AGENTS[aid]["name"], caption or "", attachments=att)
    return {"ok": True}


@app.get("/agents/{agent_id}/rooms/{room_id}/media")
def download(agent_id: str, room_id: str, mxc: str, authorization: str = Header("")):
    auth(authorization)
    data, ctype, name = MEDIA[mxc]
    return Response(data, media_type=ctype, headers={"Content-Disposition": f'inline; filename="{name}"'})


@app.websocket("/agents/{agent_id}/connection/ws")
async def ws(sock: WebSocket, agent_id: str):
    key = (sock.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    if key not in KEYS:
        await sock.close(code=4401)
        return
    await sock.accept()
    aid = KEYS[key]
    conn = sock.query_params.get("connection_id", "")
    rooms = [r for r in (sock.query_params.get("rooms") or "").split(",") if r]
    if rooms:
        CONN_ROOM[conn] = rooms[0]
    q: asyncio.Queue = asyncio.Queue()
    QUEUES[aid].append(q)
    await sock.send_text(json.dumps({"type": "connection_state", "connection_id": conn, "agent_id": aid,
                                     "generation": 1, "scope": sock.query_params.get("scope", "single"),
                                     "rooms": rooms, "cursor": 0, "heartbeat_interval_seconds": 2}))

    async def pinger():
        while True:
            await asyncio.sleep(2)
            await sock.send_text(json.dumps({"type": "ping"}))

    async def reader():
        async for _ in sock.iter_text():
            pass
    pt, rt = asyncio.create_task(pinger()), asyncio.create_task(reader())
    try:
        while True:
            frame = await q.get()
            if sock.query_params.get("scope") != "all" and rooms and frame["data"]["room_id"] not in rooms:
                continue
            await sock.send_text(json.dumps(frame))
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        pt.cancel()
        rt.cancel()
        QUEUES[aid].remove(q)


@app.post("/test/say")
async def say(req: Request):
    b = await req.json()
    rid = b["room"] if b["room"] in ROOMS else next(r for r, v in ROOMS.items() if b["room"].lower() in v["name"].lower())
    return {"message_id": broadcast(rid, pid_user(b["user"]), b["user"], b["body"])}


@app.get("/test/log")
def log():
    return {"log": LOG, "rooms": {rid: {"name": r["name"], "agents": sorted(AGENTS[a]["name"] for a in r["agents"]),
                                        "users": sorted(r["users"]), "docs": [d.get("name") for d in r["docs"].values()]}
                                  for rid, r in ROOMS.items()}}


if __name__ == "__main__":
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8199)
    uvicorn.run(app, host="127.0.0.1", port=ap.parse_args().port, log_level="warning")
