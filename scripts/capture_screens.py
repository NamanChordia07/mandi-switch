"""Capture Control Room screenshots at 1920x1080 for the README and visual QA.

    python scripts/capture_screens.py [--url http://localhost:5173] [--out docs/images] [--prefix ui]

Expects Mandi Core + the Control Room running with an order in progress or finished
(e.g. after `python scripts/simulate.py --fast`).
"""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:5173")
    ap.add_argument("--out", default=str(ROOT / "docs" / "images"))
    ap.add_argument("--prefix", default="ui")
    ap.add_argument("--stages", default="1,2,3,4,6,7,8")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        await pg.goto(a.url)
        await pg.wait_for_selector("text=Live Switch feed", timeout=20000)
        await pg.wait_for_timeout(2500)
        names = {"1": "request", "2": "spec", "3": "rooms", "4": "quotes", "5": "compare", "6": "negotiate", "7": "approve", "8": "po"}
        for k in a.stages.split(","):
            await pg.keyboard.press(k)
            await pg.wait_for_timeout(1600)
            await pg.screenshot(path=str(out / f"{a.prefix}-{k}-{names[k]}.png"))
        # injection modal
        await pg.keyboard.press("4")
        await pg.wait_for_timeout(800)
        btn = pg.get_by_text("Show what was hidden")
        if await btn.count():
            await btn.first.click()
            await pg.wait_for_timeout(2500)
            await pg.screenshot(path=str(out / f"{a.prefix}-injection.png"))
            await pg.keyboard.press("Escape")
        # explain mode on negotiation
        await pg.keyboard.press("6")
        await pg.keyboard.press("e")
        await pg.wait_for_timeout(1200)
        await pg.screenshot(path=str(out / f"{a.prefix}-explain.png"))
        await pg.keyboard.press("e")
        await pg.goto(a.url + "/#/how")
        await pg.wait_for_timeout(1500)
        await pg.screenshot(path=str(out / f"{a.prefix}-how.png"), full_page=True)
        await b.close()
    print(f"screenshots in {out}")


if __name__ == "__main__":
    asyncio.run(main())
