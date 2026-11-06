"""Screenshot Mattermost as the demo personas (read-only viewing) for the README.

    python scripts/capture_mattermost.py [--out docs/images]

Logs in with each persona's test login (secrets/demo-users.local.json), opens a room's channel and saves
1600x1000 screenshots: the order room (approval requests, refusal, !roles, PO, outcome) and Deccan's sealed room.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)
MM = os.environ.get("MATTERMOST_URL", "http://localhost:63664").rstrip("/")
USERS = json.loads((ROOT / "secrets" / "demo-users.local.json").read_text(encoding="utf-8"))
SHOTS = [("meera", "Order room", "mm-order-room"), ("asha", "Deccan", "mm-deccan-sealed"),
         ("vikram", "Order room", "mm-order-approval")]


def session(persona: str) -> tuple[str, str, str]:
    """Log in through the API; return (token, user_id, channel path)."""
    c = httpx.Client(base_url=f"{MM}/api/v4", timeout=20)
    r = c.post("/users/login", json={"login_id": USERS[persona]["username"], "password": USERS[persona]["password"]})
    r.raise_for_status()
    return r.headers["Token"], r.json()["id"], c


def channel_path(c: httpx.Client, part: str) -> str:
    for t in c.get("/users/me/teams").json():
        for ch in c.get(f"/users/me/teams/{t['id']}/channels").json():
            if part.lower() in (ch.get("display_name") or "").lower():
                return f"/{t['name']}/channels/{ch['name']}"
    raise SystemExit(f"no channel {part}")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "images"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        for persona, part, name in SHOTS:
            token, uid, c = session(persona)
            c.headers["Authorization"] = f"Bearer {token}"
            path = channel_path(c, part)
            ctx = await b.new_context(viewport={"width": 1600, "height": 1000})
            host = MM.split("://", 1)[1].split(":")[0]
            await ctx.add_cookies([{"name": "MMAUTHTOKEN", "value": token, "domain": host, "path": "/", "httpOnly": True},
                                   {"name": "MMUSERID", "value": uid, "domain": host, "path": "/"},
                                   {"name": "MMCSRF", "value": "x", "domain": host, "path": "/"}])
            pg = await ctx.new_page()
            await pg.goto(MM + path)
            await pg.wait_for_timeout(2500)
            try:
                await pg.get_by_text("View in Browser").first.click(timeout=4000)
            except Exception:
                pass
            await pg.wait_for_timeout(6000)
            for sel in ("button:has-text('Skip')", "button:has-text('Not now')", "[aria-label='Close']"):
                try:
                    await pg.locator(sel).first.click(timeout=800)
                except Exception:
                    pass
            await pg.screenshot(path=str(out / f"{name}.png"))
            print("saved", out / f"{name}.png")
            await ctx.close()
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
