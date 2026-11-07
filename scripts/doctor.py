"""mandi doctor — check every dependency and connection, with a fix hint for each failure.

    python scripts/doctor.py
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

results: list[tuple[bool, str, str]] = []


def check(ok: bool, what: str, fix: str = "") -> bool:
    results.append((ok, what, fix))
    print(f"  {'✅' if ok else '❌'} {what}" + ("" if ok or not fix else f"\n      ↳ {fix}"))
    return ok


def warn(what: str, hint: str = "") -> None:
    """Shown but not counted: something doctor could not verify on this machine."""
    print(f"  ⚠️  {what}" + (f"\n      ↳ {hint}" if hint else ""))


def http_get(url: str, headers: dict | None = None, timeout: float = 4.0):
    import httpx
    try:
        return httpx.get(url, headers=headers or {}, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return exc


def port_open(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.8)
        return s.connect_ex((host, port)) == 0


def main() -> int:
    print("\nMandi doctor\n")
    print("Tools")
    check(sys.version_info >= (3, 11), f"Python {sys.version.split()[0]}", "Install Python 3.11+")
    check((ROOT / ".venv").exists(), ".venv exists", "python -m venv .venv && .venv/Scripts/pip install -e .[dev]")
    node = shutil.which("node")
    nv = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip() if node else ""
    check(bool(node), f"Node {nv or 'missing'}", "Install Node 20+ (winget install OpenJS.NodeJS.LTS)")
    docker = shutil.which("docker")
    check(bool(docker), "Docker CLI", "Install Docker Desktop (needed for Switch's bundled Mattermost)")
    if docker:
        r = subprocess.run([docker, "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True)
        check(r.returncode == 0, f"Docker engine running {r.stdout.strip()}", "Start Docker Desktop")

    print("\nConfiguration")
    env_ok = (ROOT / ".env").exists()
    check(env_ok, ".env present", "python scripts/init_env.py")
    check(bool(os.environ.get("OPENAI_API_KEY")) or os.environ.get("MANDI_OFFLINE_LLM") == "1",
          f"OPENAI_API_KEY set (model {os.environ.get('MANDI_OPENAI_MODEL', 'gpt-4o-mini')}) or MANDI_OFFLINE_LLM=1",
          "Paste your key into .env")
    try:
        from common.llm import spend
        sp = spend()
        check(True, f"LLM spend so far: ~${sp['usd']} over {sp['calls']} calls (logs/llm-usage.jsonl)")
    except Exception:
        pass
    toks = [k for k in os.environ if k.startswith("CORE_TOKEN_")]
    check(len(toks) >= 8 and all(os.environ[k] for k in toks), "Mandi Core tokens generated", "python scripts/init_env.py")
    pdfs = [ROOT / "seed" / "quotes" / f"{v}-quote.pdf" for v in ("deccan", "ganesh", "apex", "konkan")]
    check(all(p.exists() for p in pdfs), "seed quote PDFs", "python seed/make_quotes.py")
    gates_ok = all((ROOT / "agents" / "gates" / g / ".mcp.json").exists() for g in ("purchase-desk", "po-issuer"))
    check(gates_ok, "gate agents' .mcp.json", "python scripts/setup_gates.py")

    print("\nSwitch")
    base = os.environ.get("SWITCH_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    r = http_get(f"{base}/health")
    sw_ok = check(not isinstance(r, Exception) and r.status_code == 200, f"Switch server {base}/health",
                  "Open Switch Console (server must be running); set SWITCH_BASE_URL in .env")
    keys_path = ROOT / "secrets" / "agent-keys.local.json"
    keys = json.loads(keys_path.read_text(encoding="utf-8")) if keys_path.exists() else {}
    check(len(keys) >= 9, f"agent keys ({len(keys)}/9)", "python scripts/register_agents.py")
    if sw_ok and keys:
        bad = []
        for name, k in keys.items():
            rr = http_get(f"{base}/agents/{k['id']}/ops", {"Authorization": f"Bearer {k['api_key']}"})
            if isinstance(rr, Exception) or rr.status_code != 200:
                bad.append(name)
        check(not bad, "agent keys accepted by Switch" + (f" (bad: {bad})" if bad else ""),
              "python scripts/register_agents.py --rotate --only " + " ".join(bad))
    ids_path = ROOT / "secrets" / "switch-ids.local.json"
    ids = json.loads(ids_path.read_text(encoding="utf-8")) if ids_path.exists() else {}
    check(len(ids.get("rooms", {})) >= 4, f"rooms recorded ({len(ids.get('rooms', {}))}/4)",
          "python scripts/bootstrap_switch.py")
    check(len(ids.get("people", {})) >= 6, f"persona accounts found in rooms ({len(ids.get('people', {}))}/6)",
          "python scripts/create_personas.py, link accounts (manual-setup §5), rerun bootstrap")
    gates = [g for g in ("purchase-desk", "po-issuer") if ids.get("agents", {}).get(g, {}).get("id")]
    check(len(gates) == 2, f"Claude Code gate agents registered ({gates})", "Create them in Switch Console (manual-setup §6)")
    mm = os.environ.get("MATTERMOST_URL", "http://127.0.0.1:8065")
    r = http_get(f"{mm.rstrip('/')}/api/v4/system/ping")
    check(not isinstance(r, Exception) and r.status_code == 200, f"Mattermost {mm}", "Set MATTERMOST_URL from Console")

    sealed_rooms(sw_ok, keys, ids)

    print("\nMandi")
    core = os.environ.get("CORE_URL", "http://127.0.0.1:8700")
    r = http_get(f"{core}/health")
    if not isinstance(r, Exception) and r.status_code == 200:
        h = r.json()
        check(True, f"Mandi Core {core} (order: {h.get('current_order')})")
        check(bool(h.get("switch", {}).get("switch_live")), "auditor connected to Switch (LIVE dot)",
              "python scripts/run_all.py — check logs/mandi-auditor.log")
    else:
        check(False, f"Mandi Core {core}", "python scripts/run_all.py")
    check((ROOT / "ui" / "node_modules").exists() or (ROOT / "ui" / "dist").exists(), "Control Room built/installed",
          "cd ui && npm install && npm run build")

    failed = [r for r in results if not r[0]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed.")
    return 0 if not failed else 1


def sealed_rooms(sw_ok: bool, keys: dict, ids: dict) -> None:
    """Supplier rooms must be private. Fails on the room plan, the addressing plan, live membership in Switch, and
    the Mattermost channel type, as far as this machine can verify each."""
    import asyncio

    import yaml
    from common import sealed
    print("\nSealed supplier rooms")
    import importlib.util
    spec = importlib.util.spec_from_file_location("bootstrap_switch", ROOT / "scripts" / "bootstrap_switch.py")
    bs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bs)  # only reads config at import time; main() is not run
    sc = yaml.safe_load((ROOT / "config" / "scenario.yaml").read_text(encoding="utf-8"))
    problems = sealed.config_problems(bs.ROOMS, sc["personas"], sc["vendors"])
    check(not problems, "room plan: supplier rooms are private channels, private read/write visibility, "
          "one supplier each" + ("" if not problems else f" ({'; '.join(problems)})"),
          "fix ROOMS in scripts/bootstrap_switch.py")
    plan_path = ROOT / "secrets" / "addressing-plan.local.json"
    if plan_path.exists() and ids.get("rooms"):
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        problems = sealed.policy_problems(plan, ids["rooms"])
        check(not problems, "addressing plan: each supplier agent can be addressed only in its own room"
              + ("" if not problems else f" ({'; '.join(problems)})"), "python scripts/bootstrap_switch.py")
    else:
        warn("addressing plan not written yet", "python scripts/bootstrap_switch.py")
    vkeys = [v for v in sealed.vendor_keys(bs.ROOMS) if v in ids.get("rooms", {})]
    if sw_ok and keys and vkeys:
        names = {}
        for p_, info in sc["personas"].items():
            names[p_] = p_
            names[bs.MM_USER[p_].lower()] = p_
            names[info["name"].lower()] = p_

        async def live() -> list[str]:
            out: list[str] = []
            for v in vkeys:
                neg = bs.agent(f"mandi-negotiator-{v}", rooms=[ids["rooms"][v]])
                prts = await bs.with_connection(neg, lambda neg=neg: neg.call("list_participants"))
                out += sealed.participant_problems(v, prts or [], all_vendor_keys=sealed.vendor_keys(bs.ROOMS),
                                                   persona_names=names, vendors=sc["vendors"],
                                                   personas=sc["personas"])
            return out
        try:
            problems = asyncio.run(live())
            check(not problems, f"live membership in Switch: no outsider in {len(vkeys)} supplier rooms"
                  + ("" if not problems else f" ({'; '.join(problems)})"),
                  "remove the outsider from the room (Switch Console → Rooms), then rerun doctor")
        except Exception as exc:  # noqa: BLE001
            warn(f"could not list live room members ({exc})",
                 "check the negotiator keys: python scripts/register_agents.py")
    else:
        warn("live room membership not checked (Switch or rooms not set up yet)")
    container = os.environ.get("MATTERMOST_CONTAINER", "")
    docker = shutil.which("docker")
    if container and docker:
        team = os.environ.get("MATTERMOST_TEAM", "switch") or "switch"
        r = subprocess.run([docker, "exec", container, "mmctl", "--local", "channel", "list", team, "--json"],
                           capture_output=True, text=True, timeout=30)
        channels = _json_objects(r.stdout) if r.returncode == 0 else []
        if channels:
            expected = {v: bs.ROOMS[v]["name"] for v in vkeys or sealed.vendor_keys(bs.ROOMS)}
            problems = sealed.mattermost_channel_problems(channels, expected)
            check(not problems, "Mattermost: supplier channels are private (type P)"
                  + ("" if not problems else f" ({'; '.join(problems)})"),
                  "convert the channel to private in Mattermost (channel menu → Convert to Private Channel)")
        else:
            warn("could not read Mattermost channel types via mmctl", (r.stderr or r.stdout).strip()[:160])
    else:
        warn("Mattermost channel types not checked (MATTERMOST_CONTAINER not set)")


def _json_objects(text: str) -> list[dict]:
    """mmctl --json prints either one JSON array or one object per line."""
    text = text.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        return [d for d in (data if isinstance(data, list) else [data]) if isinstance(d, dict)]
    except json.JSONDecodeError:
        out = []
        for line in text.splitlines():
            try:
                d = json.loads(line)
                out += d if isinstance(d, list) else [d]
            except json.JSONDecodeError:
                continue
        return [d for d in out if isinstance(d, dict)]


if __name__ == "__main__":
    raise SystemExit(main())
