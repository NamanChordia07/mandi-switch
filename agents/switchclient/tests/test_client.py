"""switchclient against a fake Switch WebSocket server: pong timing, cursor, resume after eviction, taken_over."""
import asyncio
import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from agents.switchclient import SwitchAgent  # noqa: E402


class FakeSwitch:
    def __init__(self, script):
        self.script = script          # list of per-connection coroutines(ws, params)
        self.connections = []         # (params, pongs)
        self.server = None
        self.port = None

    async def handler(self, ws):
        q = parse_qs(urlparse(ws.request.path).query)
        params = {k: v[0] for k, v in q.items()}
        params["auth"] = ws.request.headers.get("Authorization")
        pongs = []
        self.connections.append((params, pongs))
        idx = len(self.connections) - 1
        step = self.script[min(idx, len(self.script) - 1)]

        async def reader():
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "pong":
                    pongs.append((time.monotonic(), msg.get("cursor")))
        rt = asyncio.create_task(reader())
        try:
            await step(ws, params)
        finally:
            rt.cancel()

    async def __aenter__(self):
        self.server = await websockets.serve(self.handler, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *a):
        self.server.close()
        await self.server.wait_closed()


def msg(seq, body="hi", addressed=True):
    return json.dumps({"event": "message", "id": seq, "data": {
        "type": "message", "room_id": "!r", "bridge_id": "b", "channel_type": "channel_public", "sequence": seq,
        "payload": {"addressed": addressed, "sender": "@switch-user-1:localhost", "sender_name": "Rohan",
                    "message_id": f"m{seq}", "body": body, "timestamp": 1, "thread_id": None, "attachments": []}}})


def state(gen, cursor=0):
    return json.dumps({"type": "connection_state", "connection_id": "x", "agent_id": "a", "generation": gen,
                       "scope": "single", "filter": "all", "rooms": ["!r"], "cursor": cursor,
                       "heartbeat_interval_seconds": 2})


@pytest.mark.asyncio
async def test_pong_cursor_resume_and_taken_over(tmp_path):
    got = []

    async def first(ws, params):
        await ws.send(state(7, 10))
        await ws.send(msg(11, "first"))
        await ws.send(msg(12, "chatter", addressed=False))
        await asyncio.sleep(0.05)
        t0 = time.monotonic()
        await ws.send(json.dumps({"type": "ping"}))
        await asyncio.sleep(0.2)
        first.ping_at = t0
        await ws.send(json.dumps({"type": "evicted", "code": "heartbeat_lapsed", "reason": "test"}))
        await ws.close(1000)

    async def second(ws, params):
        second.params = params
        await ws.send(state(8, 12))
        await ws.send(msg(12, "duplicate"))   # already seen -> dropped
        await ws.send(msg(13, "second"))
        await asyncio.sleep(0.1)
        await ws.send(json.dumps({"type": "evicted", "code": "taken_over", "reason": "another client"}))
        await asyncio.sleep(0.5)

    async with FakeSwitch([first, second]) as fake:
        agent = SwitchAgent(base_url=f"http://127.0.0.1:{fake.port}", agent_id="a", api_key="k", name="t",
                            rooms=["!r"], state_dir=tmp_path)

        @agent.on("message")
        async def _(ev):
            got.append(ev.body)

        # make reconnect immediate for the test
        import agents.switchclient.client as mod
        orig = mod.asyncio.sleep

        async def fast_sleep(d, *a, **k):
            return await orig(min(d, 0.01))
        mod.asyncio.sleep = fast_sleep
        try:
            await asyncio.wait_for(agent.run(), timeout=5)
        finally:
            mod.asyncio.sleep = orig

    p1, pongs1 = fake.connections[0]
    assert p1["auth"] == "Bearer k" and p1["rooms"] == "!r" and p1["connection_id"]
    assert pongs1, "client never answered the ping"
    assert pongs1[0][0] - first.ping_at < 0.5 and pongs1[0][1] == 12
    p2, _ = fake.connections[1]
    assert p2["connection_id"] == p1["connection_id"]          # same connection id on resume
    assert p2["start_from"] == "12" and p2["expected_generation"] == "7"
    assert got == ["first", "second"]                            # unaddressed + duplicate dropped
    assert agent.stopped and len(fake.connections) == 2          # taken_over is final
    saved = json.loads((tmp_path / "t.json").read_text())
    assert saved["cursor"] == 13 and saved["generation"] == 8


@pytest.mark.asyncio
async def test_handler_errors_dont_kill_worker(tmp_path):
    seen = []

    async def only(ws, params):
        await ws.send(state(1))
        await ws.send(msg(1, "boom"))
        await ws.send(msg(2, "ok"))
        await asyncio.sleep(0.2)
        await ws.send(json.dumps({"type": "evicted", "code": "taken_over"}))
        await asyncio.sleep(0.2)

    async with FakeSwitch([only]) as fake:
        agent = SwitchAgent(base_url=f"http://127.0.0.1:{fake.port}", agent_id="a", api_key="k", name="t2",
                            rooms=["!r"], state_dir=tmp_path)

        @agent.on("message")
        async def _(ev):
            if ev.body == "boom":
                raise RuntimeError("handler bug")
            seen.append(ev.body)

        await asyncio.wait_for(agent.run(), timeout=5)
    assert seen == ["ok"]
