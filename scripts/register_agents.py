"""Register Mandi's custom agents with Switch (idempotent).

    python scripts/register_agents.py            # register missing agents, keep existing keys
    python scripts/register_agents.py --rotate   # re-register (overwrite) to issue fresh API keys
    python scripts/register_agents.py --only deccan-sales

Each agent is registered with its OWNER's registration key (REGKEY_<OWNER> in .env). Switch makes the key's
creator the agent's owner — that is how Deccan's sales agent ends up owned by Deccan's person, not by Mandi.
API keys are written to secrets/agent-keys.local.json (git-ignored).
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
import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)
from agents.switchclient import SwitchError, register  # noqa: E402

KEYS = Path(os.environ.get("MANDI_SECRETS_DIR", ROOT / "secrets")) / "agent-keys.local.json"


def owner_key(owner: str) -> tuple[str, str]:
    env_name = f"REGKEY_{owner.upper()}"
    val = os.environ.get(env_name, "").strip()
    if val:
        return val, owner
    fallback = os.environ.get("REGKEY_MANDI_OPS", "").strip()
    return fallback, "mandi_ops (fallback)"


async def key_works(base: str, agent_id: str, api_key: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{base}/agents/{agent_id}/ops", headers={"Authorization": f"Bearer {api_key}"})
        return r.status_code == 200


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rotate", action="store_true", help="overwrite existing registrations (new API keys)")
    ap.add_argument("--only", nargs="*", help="agent names to (re)register")
    a = ap.parse_args()
    base = os.environ.get("SWITCH_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    catalog = yaml.safe_load((ROOT / "config" / "agents.yaml").read_text(encoding="utf-8"))["agents"]
    keys = json.loads(KEYS.read_text(encoding="utf-8")) if KEYS.exists() else {}
    KEYS.parent.mkdir(exist_ok=True)
    print(f"Switch: {base}")
    rows = []
    for ag in catalog:
        name = ag["name"]
        if a.only and name not in a.only:
            continue
        regkey, owner_label = owner_key(ag["owner"])
        if not regkey:
            rows.append((name, "SKIPPED", "no registration key (set REGKEY_MANDI_OPS in .env)"))
            continue
        existing = keys.get(name)
        if existing and not a.rotate and await key_works(base, existing["id"], existing["api_key"]):
            rows.append((name, "ok (existing)", f"owner key: {existing.get('owner', '?')}"))
            continue
        try:
            res = await register(base, regkey, name=name, description=ag["description"],
                                 display_name=ag.get("display_name", ""), connection_model="always_on",
                                 overwrite=a.rotate or bool(existing))
        except SwitchError as exc:
            if exc.status == 409:
                rows.append((name, "EXISTS", "registered elsewhere — rerun with --rotate to issue a new key"))
            else:
                rows.append((name, "FAILED", str(exc)[:160]))
            continue
        keys[name] = {"id": res["id"], "api_key": res["api_key"], "owner": owner_label}
        KEYS.write_text(json.dumps(keys, indent=2), encoding="utf-8")
        rows.append((name, "registered", f"owner key: {owner_label}"))
    w = max(len(r[0]) for r in rows) if rows else 10
    for r in rows:
        print(f"  {r[0]:<{w}}  {r[1]:<14} {r[2]}")
    if any("fallback" in r[2] for r in rows):
        print("\n  NOTE: some vendor agents were registered with REGKEY_MANDI_OPS (single-owner mode). For the full\n"
              "  ownership story, create a registration key while signed in as each vendor persona and set\n"
              "  REGKEY_ASHA / REGKEY_SANJAY / REGKEY_KARAN, then run with --rotate --only <agent>.")
    print(f"\nKeys saved to {KEYS.relative_to(ROOT)} (git-ignored).")
    return 0 if all(r[1] not in ("FAILED",) for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
