"""Rehearse the live demo end to end on the REAL Switch + Mattermost, playing the humans through their own
Mattermost test accounts (logins from secrets/demo-users.local.json, created by scripts/create_personas.py).

    python scripts/live_rehearsal.py [--until spec|negotiate|award|po] [--start request|approve]

Every human step is a real Mattermost action by that persona's account — the same thing Naman and Divya do by
hand in the recorded demo: Rohan posts and confirms, Asha declines, Meera and Vikram address their gate agents.
The script NEVER answers a Switch permission request: a real person must tap "Allow once" in Mattermost (Lock 2). Prints a timeline and exits non-zero if a stage doesn't complete.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import httpx  # noqa: E402
import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)
SECRETS = Path(os.environ.get("MANDI_SECRETS_DIR", ROOT / "secrets"))
MM = os.environ.get("MATTERMOST_URL", "http://localhost:63664").rstrip("/")
CORE = os.environ.get("CORE_URL", "http://127.0.0.1:8700")
UI = {"Authorization": f"Bearer {os.environ['CORE_TOKEN_UI']}"}
T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


class Person:
    def __init__(self, persona: str):
        rec = json.loads((SECRETS / "demo-users.local.json").read_text(encoding="utf-8"))[persona]
        self.name = persona
        self.c = httpx.Client(base_url=f"{MM}/api/v4", timeout=30)
        r = self.c.post("/users/login", json={"login_id": rec["username"], "password": rec["password"]})
        r.raise_for_status()
        self.c.headers["Authorization"] = f"Bearer {r.headers['Token']}"
        self.id = r.json()["id"]

    def channel(self, name_part: str) -> dict:
        teams = self.c.get("/users/me/teams").json()
        for t in teams:
            for ch in self.c.get(f"/users/me/teams/{t['id']}/channels").json():
                if name_part.lower() in (ch.get("display_name") or "").lower():
                    return ch
        raise SystemExit(f"{self.name} can't see a channel containing '{name_part}'")

    def say(self, channel_id: str, text: str, root_id: str = "") -> dict:
        body = {"channel_id": channel_id, "message": text}
        if root_id:
            body["root_id"] = root_id
        r = self.c.post("/posts", json=body)
        r.raise_for_status()
        log(f"{self.name:<7} ▶ {text[:90]}")
        return r.json()

    def posts(self, channel_id: str, since_ms: int = 0) -> list[dict]:
        r = self.c.get(f"/channels/{channel_id}/posts", params={"since": since_ms} if since_ms else {"per_page": 60})
        d = r.json()
        return sorted(d.get("posts", {}).values(), key=lambda p: p["create_at"])


def core_state() -> dict:
    v = httpx.get(f"{CORE}/orders/current", headers=UI, timeout=10).json()
    return v


def wait(pred, what: str, timeout: float = 240, every: float = 3.0):
    t = time.time()
    while time.time() - t < timeout:
        try:
            v = pred()
            if v:
                return v
        except Exception:
            pass
        time.sleep(every)
    raise SystemExit(f"TIMEOUT after {timeout:.0f}s waiting for: {what}")


def find_post(person: Person, ch: str, text: str, since: int, by: str | None = None) -> dict | None:
    for p in person.posts(ch, since):
        if text.lower() in (p.get("message") or "").lower() or any(text.lower() in json.dumps(a).lower()
                                                                    for a in (p.get("props") or {}).get("attachments") or []):
            return p
    return None


def approval_request(person: Person, ch: str, since: int) -> dict | None:
    """Switch's permission request: '@<person> **Permission needed** · request A1 …' with Allow/Decline buttons.
    (Not the 'Working…'/'Queued…' status cards, which only carry 'Show activity'/'Stop' actions.)"""
    for p in person.posts(ch, since):
        atts = (p.get("props") or {}).get("attachments") or []
        names = [x.get("name", "").lower() for a in atts for x in (a.get("actions") or [])]
        if "permission needed" in (p.get("message") or "").lower() and any("allow once" in n for n in names):
            return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", default="po", choices=["spec", "negotiate", "award", "po"])
    ap.add_argument("--start", default="request", choices=["request", "approve"],
                    help="approve: skip to the human approvals (order must already be AWARDED)")
    a = ap.parse_args()
    sc = yaml.safe_load((ROOT / "config" / "scenario.yaml").read_text(encoding="utf-8"))
    rohan, meera, vikram, asha = (Person(p) for p in ("rohan", "meera", "vikram", "asha"))
    order_ch = rohan.channel("Order room")["id"]
    deccan_ch = asha.channel("Deccan")["id"]
    log(f"channels: order={order_ch[:8]} deccan={deccan_ch[:8]}")
    now = int(time.time() * 1000) - 2000
    if a.start == "approve":
        return approvals(a, meera, vikram, order_ch)

    rohan.say(order_ch, "@mandi-intake " + " ".join(sc["order"]["raw_request_message"].split()))
    spec = wait(lambda: find_post(rohan, order_ch, "Spec draft", now), "intake's spec card", 120)
    log("intake  ◀ spec card posted")
    rohan.say(order_ch, "yes", root_id=spec.get("root_id") or spec["id"])
    wait(lambda: core_state()["order"]["state"] not in ("DRAFT",), "spec confirmed", 60)
    log(f"core    = {core_state()['order']['state']}")
    if a.until == "spec":
        return 0
    wait(lambda: core_state()["order"]["state"] in ("NEGOTIATING", "NEGOTIATION_CLOSED", "AWARDED"), "comparison + negotiation start", 300)
    v = core_state()
    log(f"core    = NEGOTIATING · quotes={len(v['quotes'])} · disqualified={[x['vendor_id'] for x in v['vendors'] if x['status']=='DISQUALIFIED']}")
    if a.until == "negotiate":
        return 0
    req = wait(lambda: find_post(asha, deccan_ch, "Approval needed", now), "deccan-sales asking Asha", 400)
    log("deccan  ◀ asked Asha for approval")
    asha.say(deccan_ch, "decline", root_id=req.get("root_id") or "")
    wait(lambda: core_state()["order"]["state"] == "AWARDED", "award", 400)
    v = core_state()
    off = next(x for x in v["offers"] if x["id"] == v["order"]["awarded_offer_id"])
    log(f"core    = AWARDED to {v['order']['awarded_vendor_id']} at ₹{off['unit_price_paise']/100:.2f}")
    if a.until == "award":
        return 0
    return approvals(a, meera, vikram, order_ch)


def approvals(a, meera: "Person", vikram: "Person", order_ch: str) -> int:
    """The money steps. The script never answers a Switch permission request itself: a real person (Meera, then
    Vikram) must tap **Allow once** in Mattermost. It only waits and reports — that is Lock 2."""
    state = core_state()["order"]["state"]
    if state == "AWARDED":
        if not approval_request(meera, order_ch, 0):
            t_m = int(time.time() * 1000) - 1000
            meera.say(order_ch, "@purchase-desk please review the award for SM-PR-2026-0147 and endorse it")
            req = wait(lambda: approval_request(meera, order_ch, t_m), "purchase-desk's Switch permission request", 300)
            log(f"switch  ◀ {(req.get('message') or '')[:110]!r}")
        log("WAITING for a human: log in to Mattermost as MEERA and tap “1. Allow once” on the request …")
        wait(lambda: core_state()["order"]["state"] != "AWARDED", "Meera's decision in Switch", 1800, every=4)
        if core_state()["order"]["state"] != "ENDORSED_PURCHASE_HEAD":
            log(f"core    = {core_state()['order']['state']} (declined)")
            return 0
        log("core    = ENDORSED_PURCHASE_HEAD")
    if core_state()["order"]["state"] == "ENDORSED_PURCHASE_HEAD":
        t_v = int(time.time() * 1000) - 1000
        vikram.say(order_ch, "@po-issuer release the PO for SM-PR-2026-0147")
        req = wait(lambda: approval_request(vikram, order_ch, t_v), "po-issuer's Switch permission request", 300)
        log(f"switch  ◀ {(req.get('message') or '')[:110]!r}")
        log("WAITING for a human: log in to Mattermost as VIKRAM and tap “1. Allow once” on the request …")
    wait(lambda: core_state()["order"]["state"] == "PO_ISSUED", "Vikram's decision in Switch + PO", 1800, every=4)
    out = httpx.get(f"{CORE}/orders/{core_state()['order']['id']}/outcome", headers=UI).json()
    log(f"DONE    {out['po']['id']} · {out['total']} · saved {out['saved']} ({out['saved_pct']}) · {out['elapsed_seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
