"""End-to-end run of Mandi's REAL agents against tests/fake_switch.py (no Docker, no LLM spend).

    python tests/run_fake_e2e.py [--chaser]

--chaser turns the sign-off chaser on with short timings and checks the reminder and escalation are posted
before the purchase head endorses.

Starts fake Switch (:8199) + Mandi Core (:8701) with temp state/secrets dirs, registers agents, bootstraps rooms,
starts all 9 custom agents, plays the humans (Rohan, Asha) through the fake server, then performs the two gate
approvals with the gate MCP tokens (Claude Code gate agents only run in real Switch Console), and checks the outcome.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
FAKE, CORE = "http://127.0.0.1:8199", "http://127.0.0.1:8701"
CHASER = "--chaser" in sys.argv


def wait_for(pred, timeout=120, every=1.0, what=""):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            v = pred()
            if v:
                return v
        except Exception:
            pass
        time.sleep(every)
    raise SystemExit(f"TIMEOUT waiting for {what}")


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mandi-e2e-"))
    (tmp / "secrets").mkdir()
    (tmp / "state").mkdir()
    from dotenv import dotenv_values
    base_env = {k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None}
    env = {**os.environ, **base_env, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(ROOT),
           "SWITCH_BASE_URL": FAKE, "CORE_URL": CORE, "MANDI_SECRETS_DIR": str(tmp / "secrets"),
           "MANDI_STATE_DIR": str(tmp / "state"), "MANDI_OFFLINE_LLM": "1", "MANDI_PACE": "0.05",
           "SWITCH_ADMIN_EMAIL": "", "SWITCH_ADMIN_PASSWORD": "", "REGKEY_MANDI_OPS": "fake-regkey"}
    logs = tmp / "logs"
    logs.mkdir()
    procs = []

    def start(name, args):
        p = subprocess.Popen([PY, *args], cwd=ROOT, env=env, stdout=open(logs / f"{name}.out", "w", encoding="utf-8"),
                             stderr=subprocess.STDOUT)
        procs.append(p)
        return p
    try:
        start("fake-switch", ["tests/fake_switch.py", "--port", "8199"])
        start("core", ["-m", "uvicorn", "core.app:app", "--host", "127.0.0.1", "--port", "8701", "--log-level", "warning"])
        wait_for(lambda: httpx.get(f"{FAKE}/health").status_code == 200, 30, what="fake switch")
        wait_for(lambda: httpx.get(f"{CORE}/health").status_code == 200, 30, what="core")
        r = subprocess.run([PY, "scripts/register_agents.py"], cwd=ROOT, env=env, capture_output=True, text=True)
        print(r.stdout[-800:], r.stderr[-800:])
        r = subprocess.run([PY, "scripts/bootstrap_switch.py", "--skip-policies"], cwd=ROOT, env=env, capture_output=True, text=True)
        print(r.stdout[-1500:], r.stderr[-1500:])
        if r.returncode != 0:
            return 1
        for name, mod in [("auditor", ["-m", "agents.auditor.agent"]), ("intake", ["-m", "agents.intake.agent"]),
                          ("quotes", ["-m", "agents.quotes.agent"]),
                          *[(f"neg-{v}", ["-m", "agents.negotiator.agent", v]) for v in ("deccan", "ganesh", "apex")],
                          *[(f"{v}-sales", ["-m", f"agents.vendors.{v}.agent"]) for v in ("deccan", "ganesh", "apex")]]:
            start(name, mod)
        time.sleep(4)
        say = lambda room, user, body: httpx.post(f"{FAKE}/test/say", json={"room": room, "user": user, "body": body})  # noqa
        flog = lambda: httpx.get(f"{FAKE}/test/log").json()["log"]  # noqa
        raw = "hey team, need seat bolts for the new rear bench line - the M10 flange ones, 10.9 grade, zinc flake like last time. about 20k pcs. need them at chakan by mid next month latest. pls arrange asap"
        say("Order room", "rohan", "@mandi-intake " + raw)
        wait_for(lambda: any("Spec draft" in m["body"] for m in flog()), 40, what="spec card")
        say("Order room", "rohan", "yes")
        H = {"Authorization": f"Bearer {env['CORE_TOKEN_UI']}"}
        cur = lambda: httpx.get(f"{CORE}/orders/current", headers=H).json()  # noqa
        wait_for(lambda: cur()["order"]["state"] in ("NEGOTIATING", "NEGOTIATION_CLOSED", "AWARDED"), 120, what="negotiation")
        print("negotiating…")
        wait_for(lambda: any("Approval needed" in m["body"] for m in flog()), 180, what="Asha's approval request")
        say("Deccan", "asha", "decline")
        wait_for(lambda: cur()["order"]["state"] == "AWARDED", 180, what="award")
        o = cur()
        offer = next(x for x in o["offers"] if x["id"] == o["order"]["awarded_offer_id"])
        print("AWARDED", o["order"]["awarded_vendor_id"], offer["unit_price_paise"])
        if CHASER:
            wait_for(lambda: any("Reminder: the **purchase head endorsement**" in m["body"] for m in flog()), 30,
                     what="chaser reminder")
            wait_for(lambda: any("Escalation: the **purchase head endorsement**" in m["body"] for m in flog()), 30,
                     what="chaser escalation")
            print("chaser: reminder + escalation posted")
        D = {"Authorization": f"Bearer {env['CORE_TOKEN_MCP_PURCHASE_DESK']}"}
        P = {"Authorization": f"Bearer {env['CORE_TOKEN_MCP_PO_ISSUER']}"}
        print(httpx.post(f"{CORE}/orders/{o['order']['id']}/endorse", headers=D, json={"note": "e2e"}).status_code)
        po = httpx.post(f"{CORE}/orders/{o['order']['id']}/issue-po", headers=P, json={"agent_name": "po-issuer"}).json()
        print("PO", po.get("id"), po.get("total_paise"))
        wait_for(lambda: any("closed —" in m["body"] for m in flog()), 60, what="outcome card")
        log = httpx.get(f"{FAKE}/test/log").json()
        print("\n=== transcript ===")
        for m in log["log"]:
            print(f"[{m['room'][:28]:<28}] {m['from']:<24} {m['body'][:150].replace(chr(10), ' ')}")
        print("\n=== rooms ===")
        print(json.dumps(log["rooms"], indent=1)[:2000])
        ok = po.get("total_paise") == 72800000
        print("\nRESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        for p in procs:
            p.terminate()
        print(f"logs: {logs}")


if __name__ == "__main__":
    raise SystemExit(main())
