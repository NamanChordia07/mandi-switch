"""Shared runtime for Mandi's custom Python agents: config, secrets, Core client, Core event stream, logging."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from agents.switchclient import SwitchAgent  # noqa: E402

SECRETS = Path(os.environ.get("MANDI_SECRETS_DIR", ROOT / "secrets"))
STATE = Path(os.environ.get("MANDI_STATE_DIR", ROOT / ".state"))
LOGS = ROOT / "logs"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def setup_logging(name: str) -> logging.Logger:
    LOGS.mkdir(parents=True, exist_ok=True)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(f"%(asctime)s {name:<26} %(levelname)-5s %(message)s", "%H:%M:%S"))
    root.addHandler(console)

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            return json.dumps({"t": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "agent": name,
                               "level": record.levelname, "logger": record.name, "msg": record.getMessage(),
                               **({"exc": self.formatException(record.exc_info)} if record.exc_info else {})},
                              ensure_ascii=False)
    fh = logging.FileHandler(LOGS / f"{name}.log", encoding="utf-8")
    fh.setFormatter(JsonFormatter())
    root.addHandler(fh)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    return logging.getLogger(name)


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def agent_keys() -> dict[str, Any]:
    return load_json(SECRETS / "agent-keys.local.json")


def switch_ids() -> dict[str, Any]:
    """Written by scripts/bootstrap_switch.py: rooms, agent ids, persona participant ids."""
    return load_json(SECRETS / "switch-ids.local.json")


def make_switch_agent(name: str, *, rooms: list[str] | None = None, scope: str = "single",
                      filter: str = "all") -> SwitchAgent:
    keys = agent_keys().get(name)
    if not keys:
        raise SystemExit(f"No API key for agent {name!r} in secrets/agent-keys.local.json. "
                         f"Run: python scripts/register_agents.py")
    base = env("SWITCH_BASE_URL", "http://127.0.0.1:8000")
    return SwitchAgent(base_url=base, agent_id=keys["id"], api_key=keys["api_key"], name=name, rooms=rooms,
                       scope=scope, filter=filter, state_dir=STATE)


class Core:
    """Async client for Mandi Core."""

    def __init__(self, token_env: str = "CORE_TOKEN_AGENTS"):
        self.base = env("CORE_URL", "http://127.0.0.1:8700")
        self.token = env(token_env)
        self.http = httpx.AsyncClient(base_url=self.base, timeout=90.0,
                                      headers={"Authorization": f"Bearer {self.token}"})

    async def get(self, path: str, **params: Any) -> Any:
        r = await self.http.get(path, params=params or None)
        return self._json(r)

    async def post(self, path: str, body: Any = None, **kw: Any) -> Any:
        r = await self.http.post(path, json=body if body is not None else {}, **kw)
        return self._json(r)

    async def post_raw(self, path: str, body: Any = None) -> httpx.Response:
        return await self.http.post(path, json=body if body is not None else {})

    async def upload_quote(self, order_id: str, vendor_id: str, filename: str, content: bytes, via: str,
                           switch_message_id: str | None = None) -> Any:
        data = {"vendor_id": vendor_id, "via": via}
        if switch_message_id:
            data["switch_message_id"] = switch_message_id
        r = await self.http.post(f"/orders/{order_id}/quotes", data=data,
                                 files={"file": (filename, content, "application/pdf")})
        return self._json(r)

    @staticmethod
    def _json(r: httpx.Response) -> Any:
        if r.status_code >= 400:
            try:
                detail = r.json()
            except ValueError:
                detail = r.text
            raise CoreHTTPError(r.status_code, detail)
        return r.json()

    async def current_order(self) -> Optional[dict[str, Any]]:
        try:
            v = await self.get("/orders/current")
            return v if v.get("order") else None
        except CoreHTTPError:
            return None

    async def events(self, since: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Follow Core's SSE stream forever (reconnects)."""
        last = since
        while True:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=60.0)) as c:
                    async with c.stream("GET", f"{self.base}/events/stream", params={"since": last},
                                        headers={"Authorization": f"Bearer {self.token}"}) as r:
                        event_name = ""
                        async for line in r.aiter_lines():
                            if line.startswith("event:"):
                                event_name = line[6:].strip()
                            elif line.startswith("data:") and event_name == "mandi":
                                evt = json.loads(line[5:].strip())
                                last = max(last, evt.get("id", last))
                                yield evt
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                logging.getLogger("core-events").warning("event stream dropped (%s); retrying", exc)
                await asyncio.sleep(2)


class CoreHTTPError(RuntimeError):
    def __init__(self, status: int, detail: Any):
        super().__init__(f"Mandi Core HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


SPEED = {"factor": 1.0}  # updated from Core "director.speed" events (2x speed -> factor 0.5)


def set_speed(speed: float) -> None:
    SPEED["factor"] = 1.0 / max(0.25, float(speed or 1.0))


async def pace(seconds: float) -> None:
    """Human-watchable pauses between agent messages. MANDI_PACE scales them (0 = no pauses, e.g. tests)."""
    try:
        base = float(env("MANDI_PACE", "1.0"))
    except ValueError:
        base = 1.0
    await asyncio.sleep(max(0.0, seconds * base * SPEED["factor"]))


def run_forever(coros: list[Callable[[], Awaitable[None]]]) -> None:
    async def main():
        await asyncio.gather(*(c() for c in coros))
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
