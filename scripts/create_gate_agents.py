"""Create the two Claude Code gate agents (purchase-desk, po-issuer) as managed agents on this computer.

    python scripts/create_gate_agents.py [--recreate]

Equivalent to Switch Console → Your Agents → + (see docs/manual-setup.md §5), done through Switch's own
`create_agent` operation:
  1. as the server admin (Gateway API) temporarily turn ON "can manage agents" for mandi-intake,
  2. mandi-intake calls list_machines → create_agent for each gate (provider: Claude Code, directory:
     agents/gates/<name>, instructions: its CLAUDE.md, Auto mode OFF, Bypass OFF),
  3. turn "can manage agents" OFF again — no Mandi agent keeps that power.
Run scripts/setup_gates.py first (it writes each directory's .mcp.json and .claude/settings.json).
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
from agents.common.runtime import SECRETS, make_switch_agent  # noqa: E402
from agents.switchclient import SwitchError  # noqa: E402

GATES = {
    "purchase-desk": {"display_name": "Purchase Desk (Meera)",
                      "description": "Purchase Desk for Meera Joshi (Purchase Head, Sahyadri Motors). Endorses awards — "
                                     "only with Meera's approval in Switch."},
    "po-issuer": {"display_name": "PO Issuer (Vikram)",
                  "description": "PO Issuer for Vikram Shah (Finance, Sahyadri Motors). The only agent that can issue "
                                 "purchase orders — only with Vikram's approval in Switch."},
}


def gateway() -> httpx.Client:
    c = httpx.Client(base_url=os.environ["SWITCH_BASE_URL"], timeout=60)
    r = c.post("/gateway/auth/login", json={"email": os.environ["SWITCH_ADMIN_EMAIL"],
                                           "password": os.environ["SWITCH_ADMIN_PASSWORD"]})
    r.raise_for_status()
    return c


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recreate", action="store_true")
    a = ap.parse_args()
    for g in GATES:
        if not (ROOT / "agents" / "gates" / g / ".mcp.json").exists():
            print("Run scripts/setup_gates.py first.")
            return 1
    keys = json.loads((SECRETS / "agent-keys.local.json").read_text(encoding="utf-8"))
    helper_id = keys["mandi-intake"]["id"]
    gw = gateway()
    r = gw.put(f"/gateway/agents/{helper_id}/can-manage-agents", json={"enabled": True})
    print(f"• temporarily enabled 'can manage agents' on mandi-intake: HTTP {r.status_code}")
    out: dict[str, str] = {}
    try:
        sw = make_switch_agent("mandi-intake")
        machines = await sw.call("list_machines")
        print("• machines:", [(m.get("name"), m.get("kind"), m.get("state"),
                              [(p.get("provider"), p.get("auth")) for p in m.get("providers") or []]) for m in machines])
        mach = next((m for m in machines if m.get("state") == "online"
                     and any(p.get("provider") == "claude" and p.get("auth") == "ok" for p in m.get("providers") or [])), None)
        if not mach:
            print("✗ no online machine with Claude Code signed in. Open Switch Console (it runs this computer's "
                  "machine) and check Settings → Agent providers.")
            return 1
        try:
            fields = await sw.call("get_advanced_config", provider="claude")
            print("• Claude Code advanced settings available:", [f.get("key") for f in fields])
        except SwitchError as exc:
            print("  (advanced config unavailable:", exc, ")")
        existing = {x.get("name"): x for x in (await sw.call("list_agents") or [])} if True else {}
        for name, meta in GATES.items():
            if name in existing and not a.recreate:
                out[name] = existing[name].get("id")
                print(f"✓ {name} already exists ({out[name]})")
                continue
            instructions = (ROOT / "agents" / "gates" / name / "CLAUDE.md").read_text(encoding="utf-8")
            res = await sw.call("create_agent", name=name, description=meta["description"], machine=mach["id"],
                                provider="claude", instructions=instructions,
                                directory=str(ROOT / "agents" / "gates" / name),
                                auto_mode=False, auto_approve=False, display_name=meta["display_name"])
            out[name] = (res or {}).get("id") or (res or {}).get("agent", {}).get("id")
            print(f"✓ created {name}: {json.dumps(res)[:300]}")
    finally:
        r = gw.put(f"/gateway/agents/{helper_id}/can-manage-agents", json={"enabled": False})
        print(f"• turned 'can manage agents' OFF again on mandi-intake: HTTP {r.status_code}")
    (SECRETS / "gate-agents.local.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
