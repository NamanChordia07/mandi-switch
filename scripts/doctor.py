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


if __name__ == "__main__":
    raise SystemExit(main())
