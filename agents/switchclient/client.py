"""switchclient — a small Python client for the Switch agent protocol.

Events arrive over one WebSocket (`/agents/{id}/connection/ws`); everything the agent *does* is an HTTP
call (`/agents/{id}/ops/{op}`, `/agents/{id}/message`, media routes). Written from the public protocol
docs (docs.switchagents.ai → internals → agent protocol / connection / events).

Liveness contract we honour:
  * the server pings every ~2 s; we pong IMMEDIATELY from the reader task, before any event handling
    (handlers run on a separate worker task fed by a queue), with our cursor = highest sequence seen;
  * on `heartbeat_lapsed` / `no_stream` / `unfenced` / `connection_error` we reopen with the SAME
    connection_id, start_from=<cursor> and expected_generation=<last generation>;
  * on `taken_over` (or a permanent `closed`) we stop — never fight another client for the connection.
connection_id / cursor / generation are persisted in .state/<agent>.json so restarts resume cleanly.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlencode

import httpx
import websockets

log = logging.getLogger("switchclient")

RECONNECT_CODES = {"heartbeat_lapsed", "no_stream", "unfenced", "connection_error"}
FINAL_CODES = {"taken_over"}


class SwitchError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass
class Event:
    """A domain event (`message`, `command`, `room_join`)."""
    kind: str
    room_id: str
    sequence: int
    payload: dict[str, Any]
    bridge_id: Optional[str] = None
    channel_type: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)

    # convenience for message events
    @property
    def body(self) -> str:
        return self.payload.get("body", "") or ""

    @property
    def sender(self) -> str:
        return self.payload.get("sender", "") or ""

    @property
    def sender_name(self) -> str:
        return self.payload.get("sender_name", "") or ""

    @property
    def addressed(self) -> bool:
        return bool(self.payload.get("addressed"))

    @property
    def message_id(self) -> str:
        return self.payload.get("message_id", "") or ""

    @property
    def thread_id(self) -> Optional[str]:
        return self.payload.get("thread_id")

    @property
    def attachments(self) -> list[dict[str, Any]]:
        return self.payload.get("attachments") or []


Handler = Callable[[Event], Awaitable[None]]


class SwitchAgent:
    def __init__(self, *, base_url: str, agent_id: str, api_key: str, name: str,
                 rooms: list[str] | None = None, scope: str = "single", filter: str = "all",
                 state_dir: str | Path = ".state", client_name: str = "mandi-switchclient",
                 client_version: str = "0.1.0", heartbeat_grace: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self.agent_id = agent_id
        self.api_key = api_key
        self.name = name
        self.rooms = rooms or []
        self.scope = scope
        self.filter = filter
        self.client_name = client_name
        self.client_version = client_version
        self.state_path = Path(state_dir) / f"{name}.json"
        self.state = self._load_state()
        self.connection_id: str = self.state.setdefault("connection_id", str(uuid.uuid4()))
        self.cursor: Optional[int] = self.state.get("cursor")
        self.generation: Optional[int] = self.state.get("generation")
        self.connection_state: dict[str, Any] = {}
        self.live = asyncio.Event()
        self.stopped = False
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._handlers: dict[str, list[tuple[Handler, dict[str, Any]]]] = {}
        self._ops_cache: Optional[dict[str, Any]] = None
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=30.0,
                                       headers={"Authorization": f"Bearer {api_key}"})
        self._ws = None
        self.on_state_change: Optional[Callable[[bool, dict[str, Any]], Awaitable[None]]] = None

    # ----------------------------------------------------------------- persistence
    def _load_state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state.update({"connection_id": self.connection_id, "cursor": self.cursor,
                           "generation": self.generation})
        self.state_path.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    # ----------------------------------------------------------------- handlers
    def on(self, kind: str, *, addressed_only: bool = True, command: str | None = None):
        """Decorator: @agent.on("message") / @agent.on("command", command="reset") / @agent.on("room_join")."""
        def deco(fn: Handler) -> Handler:
            self._handlers.setdefault(kind, []).append((fn, {"addressed_only": addressed_only, "command": command}))
            return fn
        return deco

    async def _dispatch(self, ev: Event) -> None:
        for fn, opts in self._handlers.get(ev.kind, []):
            if ev.kind == "message" and opts["addressed_only"] and not ev.addressed:
                continue
            if ev.kind == "command" and opts["command"] and ev.payload.get("command") != opts["command"]:
                continue
            try:
                await fn(ev)
            except Exception:  # never let one bad handler kill the worker
                log.exception("[%s] handler %s failed on %s", self.name, getattr(fn, "__name__", fn), ev.kind)

    # ----------------------------------------------------------------- websocket
    def ws_url(self) -> str:
        scheme = "wss" if self.base_url.startswith("https") else "ws"
        host = self.base_url.split("://", 1)[1]
        params: dict[str, Any] = {"connection_id": self.connection_id, "scope": self.scope, "filter": self.filter,
                                  "client": self.client_name, "client_version": self.client_version}
        if self.rooms:
            params["rooms"] = ",".join(self.rooms)
        if self.cursor is not None:
            params["start_from"] = str(self.cursor)
        if self.generation is not None:
            params["expected_generation"] = str(self.generation)
        return f"{scheme}://{host}/agents/{self.agent_id}/connection/ws?{urlencode(params)}"

    async def run(self) -> None:
        """Connect and keep the connection alive until stop() or a final eviction."""
        worker = asyncio.create_task(self._worker(), name=f"{self.name}-worker")
        backoff = 1.0
        try:
            while not self.stopped:
                outcome = await self._connect_once()
                if outcome == "final" or self.stopped:
                    break
                await self._set_live(False)
                delay = min(backoff, 20.0) + random.uniform(0, 0.5)
                log.info("[%s] reconnecting in %.1fs", self.name, delay)
                await asyncio.sleep(delay)
                backoff = min(backoff * 2, 20.0) if outcome == "error" else 1.0
        finally:
            worker.cancel()
            await self._set_live(False)

    async def _connect_once(self) -> str:
        url = self.ws_url()
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with websockets.connect(url, additional_headers=headers, ping_interval=None,
                                          max_size=8 * 1024 * 1024, open_timeout=15) as ws:
                self._ws = ws
                async for raw in ws:
                    outcome = await self._on_frame(ws, raw)
                    if outcome:
                        return outcome
                code = ws.close_code
                return self._close_outcome(code)
        except websockets.exceptions.InvalidStatus as exc:
            status = exc.response.status_code
            log.error("[%s] websocket refused with HTTP %s", self.name, status)
            return "final" if status in (401, 403) else "error"
        except websockets.exceptions.ConnectionClosed as exc:
            return self._close_outcome(exc.rcvd.code if exc.rcvd else None)
        except (OSError, asyncio.TimeoutError) as exc:
            log.warning("[%s] connection failed: %s", self.name, exc)
            return "error"
        finally:
            self._ws = None

    def _close_outcome(self, code: Optional[int]) -> str:
        if code in (4401, 4403):
            log.error("[%s] closed %s (auth/room refused) — not retrying", self.name, code)
            return "final"
        if code == 4409:
            log.error("[%s] closed 4409 (taken over / conflict) — not retrying", self.name)
            return "final"
        return "reconnect"

    async def _on_frame(self, ws, raw: str | bytes) -> Optional[str]:
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            return None
        ftype = frame.get("type") or frame.get("event")
        # 1) liveness first — answer pings before anything else
        if ftype == "ping":
            await ws.send(json.dumps({"type": "pong", "cursor": self.cursor or 0}))
            return None
        if ftype == "connection_state":
            data = frame.get("data", frame)
            self.connection_state = data
            self.generation = data.get("generation", self.generation)
            if data.get("cursor") is not None:
                self.cursor = data["cursor"] if self.cursor is None else max(self.cursor, data["cursor"])
            self._save_state()
            await self._set_live(True)
            log.info("[%s] connected gen=%s rooms=%s cursor=%s", self.name, self.generation,
                     data.get("rooms"), self.cursor)
            return None
        if ftype == "evicted":
            data = frame.get("data", frame)
            code = data.get("code")
            log.warning("[%s] evicted: %s (%s)", self.name, code, data.get("reason"))
            if code in FINAL_CODES:
                self.stopped = True
                return "final"
            if code == "closed":
                reason = str(data.get("reason", "")).lower()
                return "final" if ("deleted" in reason or "controller" in reason) else "reconnect"
            return "reconnect"
        if ftype == "refused":
            data = frame.get("data", frame)
            log.error("[%s] refused: %s %s", self.name, data.get("status"), data.get("detail"))
            return "final" if data.get("status") in (401, 403, 409) else "error"
        if ftype == "gap":
            data = frame.get("data", frame)
            if data.get("resumed_at") is not None:
                self.cursor = data["resumed_at"]
                self._save_state()
            log.warning("[%s] gap: %s", self.name, data)
            return None
        if ftype in ("subscription_changed", "room_released"):
            log.info("[%s] %s: %s", self.name, ftype, frame.get("data", frame))
            return None
        # 2) domain events: record cursor, queue for the worker
        if frame.get("event") in ("message", "command", "room_join") or ftype in ("message", "command", "room_join"):
            data = frame.get("data", {})
            seq = frame.get("id", data.get("sequence"))
            if isinstance(seq, int):
                if self.cursor is not None and seq <= self.cursor:
                    return None  # already delivered before a reconnect
                self.cursor = seq
            ev = Event(kind=data.get("type") or frame.get("event"), room_id=data.get("room_id", ""),
                       sequence=seq if isinstance(seq, int) else -1, payload=data.get("payload", {}),
                       bridge_id=data.get("bridge_id"), channel_type=data.get("channel_type"), raw=frame)
            self._queue.put_nowait(ev)
            return None
        log.debug("[%s] unhandled frame %s", self.name, frame)
        return None

    async def _worker(self) -> None:
        while True:
            ev = await self._queue.get()
            await self._dispatch(ev)
            self._save_state()

    async def _set_live(self, live: bool) -> None:
        changed = live != self.live.is_set()
        if live:
            self.live.set()
        else:
            self.live.clear()
        if changed and self.on_state_change:
            try:
                await self.on_state_change(live, self.connection_state)
            except Exception:
                log.exception("on_state_change failed")

    async def stop(self) -> None:
        self.stopped = True
        if self._ws is not None:
            await self._ws.close()
        await self._http.aclose()

    # ----------------------------------------------------------------- HTTP: operations
    async def ops(self, refresh: bool = False) -> dict[str, Any]:
        if self._ops_cache is None or refresh:
            r = await self._http.get(f"/agents/{self.agent_id}/ops")
            self._raise(r, "list ops")
            self._ops_cache = r.json().get("operations", {})
        return self._ops_cache

    async def call(self, op: str, **kwargs: Any) -> Any:
        """Invoke an operation. kwargs are checked against the live schema first (unexpected keys are
        rejected by the server too — this just gives a clearer error)."""
        ops = await self.ops()
        if op not in ops:
            raise SwitchError(f"Unknown operation {op!r}. Available: {', '.join(sorted(ops))}")
        props = (ops[op].get("input_schema") or {}).get("properties")
        if props is not None:
            extra = set(kwargs) - set(props)
            if extra:
                raise SwitchError(f"{op}: unexpected argument(s) {sorted(extra)}; accepts {sorted(props)}")
        # The connection header binds the call to this connection's room; Switch refuses it (409) when the
        # connection isn't open, so connectionless calls (e.g. from scripts) simply omit it.
        headers = {"X-Switch-Connection-Id": self.connection_id} if self.live.is_set() else {}
        r = await self._http.post(f"/agents/{self.agent_id}/ops/{op}", json=kwargs, headers=headers)
        self._raise(r, op)
        return r.json().get("result")

    @staticmethod
    def _raise(r: httpx.Response, what: str) -> None:
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = r.text
            raise SwitchError(f"{what} failed: HTTP {r.status_code}: {body}", r.status_code, body)

    # ----------------------------------------------------------------- HTTP: helpers
    async def post(self, room_id: str, text: str, thread_id: str | None = None) -> str:
        """Post to a room. Uses post_message (thread-aware) when this connection holds the room,
        otherwise the connectionless /message route."""
        held = set(self.connection_state.get("rooms") or [])
        if room_id in held or (thread_id and room_id in held):
            res = await self.call("post_message", body=text, **({"thread_id": thread_id} if thread_id else {}))
            return (res or {}).get("event_id", "")
        r = await self._http.post(f"/agents/{self.agent_id}/message", json={"room_id": room_id, "content": text})
        self._raise(r, "post message")
        return r.json().get("event_id", "")

    async def targeted(self, names: list[str], text: str, thread_id: str | None = None,
                       roles: list[str] | None = None) -> Any:
        args: dict[str, Any] = {"body": text, "target_names": names}
        if roles:
            args["target_roles"] = roles
        if thread_id:
            args["thread_id"] = thread_id
        return await self.call("send_targeted_message", **args)

    async def read_context(self, limit: int = 50, room_id: str | None = None) -> dict[str, Any]:
        args: dict[str, Any] = {"limit": limit}
        if room_id:
            args["room_id"] = room_id
        return await self.call("read_context", **args)

    async def create_doc(self, name: str, description: str, instructions: str, content: str) -> str:
        res = await self.call("create_room_document", name=name, description=description,
                              instructions=instructions, content=content)
        return (res or {}).get("document_id", "")

    async def update_doc(self, document_id: str, **fields: Any) -> Any:
        return await self.call("update_room_document", document_id=document_id, **fields)

    async def upsert_doc(self, name: str, description: str, instructions: str, content: str) -> str:
        """Create a room document, or update the one we created earlier with the same name."""
        docs = self.state.setdefault("docs", {})
        room_key = ",".join(sorted(self.connection_state.get("rooms") or self.rooms))
        key = f"{room_key}::{name}"
        if key in docs:
            try:
                await self.update_doc(docs[key], content=content, description=description,
                                      instructions=instructions)
                return docs[key]
            except SwitchError as exc:
                log.warning("[%s] update_room_document failed (%s); creating a new one", self.name, exc)
        try:
            doc_id = await self.create_doc(name, description, instructions, content)
        except SwitchError as exc:
            if exc.status in (400, 409) and "unique" in str(exc).lower():
                doc_id = await self.create_doc(f"{name} ({len(docs) + 1})", description, instructions, content)
            else:
                raise
        docs[key] = doc_id
        self._save_state()
        return doc_id

    async def typing(self, room_id: str, on: bool = True) -> None:
        try:
            await self._http.post(f"/agents/{self.agent_id}/typing", json={"room_id": room_id, "is_typing": on})
        except httpx.HTTPError:
            pass

    async def upload(self, room_id: str, path: str | Path, caption: str = "", thread_id: str | None = None,
                     mimetype: str = "application/pdf") -> dict[str, Any]:
        p = Path(path)
        data: dict[str, Any] = {}
        if caption:
            data["caption"] = caption
        if thread_id:
            data["thread_id"] = thread_id
        r = await self._http.post(f"/agents/{self.agent_id}/rooms/{room_id}/media", data=data,
                                  files={"file": (p.name, p.read_bytes(), mimetype)}, timeout=60.0)
        self._raise(r, "upload media")
        return r.json()

    async def download(self, room_id: str, mxc: str) -> tuple[bytes, str]:
        r = await self._http.get(f"/agents/{self.agent_id}/rooms/{room_id}/media", params={"mxc": mxc}, timeout=60.0)
        self._raise(r, "download media")
        cd = r.headers.get("content-disposition", "")
        name = cd.split("filename=")[-1].strip('"; ') if "filename=" in cd else "attachment"
        return r.content, name

    async def connect_to_room(self, room_id: str) -> Any:
        return await self.call("connect_to_room", room_id=room_id)


async def health(base_url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(base_url.rstrip("/") + "/health")
        r.raise_for_status()
        return r.json()


async def register(base_url: str, registration_key: str, *, name: str, description: str, display_name: str = "",
                   connection_model: str = "always_on", overwrite: bool = False,
                   metadata: dict[str, Any] | None = None, icon_url: str | None = None) -> dict[str, Any]:
    """POST /agents with a registration key (the key's creator becomes the owner). Returns {id, api_key}."""
    body: dict[str, Any] = {
        "name": name, "description": description, "connector_type": "mandi-python",
        "integration_profile": {"connection_model": connection_model, "message_exchange": True,
                                "pre_invocation_mediation": [], "post_invocation_mediation": [],
                                "event_reporting": []},
        "overwrite": overwrite,
    }
    if display_name:
        body["display_name"] = display_name
    if metadata:
        body["metadata"] = metadata
    if icon_url:
        body["icon_url"] = icon_url
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(base_url.rstrip("/") + "/agents", json=body,
                         headers={"Authorization": f"Bearer {registration_key}"})
        if r.status_code == 409:
            raise SwitchError(f"agent {name!r} already exists", 409, r.text)
        if r.status_code >= 400:
            raise SwitchError(f"register {name} failed: HTTP {r.status_code}: {r.text}", r.status_code, r.text)
        return r.json()
