"""Start (and supervise) everything Mandi runs locally: Mandi Core, the custom Switch agents and the Control Room.

    python scripts/run_all.py              # Core + all agents (+ UI dev server if ui/node_modules exists)
    python scripts/run_all.py --core-only  # just Mandi Core
    python scripts/run_all.py --no-ui

Switch itself (server + Mattermost) runs in Switch Console; the two Claude Code gate agents are run by Switch
Console too. Logs: logs/<name>.log (agents write structured JSON) and logs/<name>.out (stdout).
Ctrl+C stops everything. A crashed agent is restarted with backoff.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python"))
if not Path(PY).exists():
    PY = sys.executable

PROCS = [
    ("core", [PY, "-m", "uvicorn", "core.app:app", "--host", "127.0.0.1", "--port", "8700", "--log-level", "warning"]),
    ("mandi-auditor", [PY, "-m", "agents.auditor.agent"]),
    ("mandi-intake", [PY, "-m", "agents.intake.agent"]),
    ("mandi-quotes", [PY, "-m", "agents.quotes.agent"]),
    ("mandi-negotiator-deccan", [PY, "-m", "agents.negotiator.agent", "deccan"]),
    ("mandi-negotiator-ganesh", [PY, "-m", "agents.negotiator.agent", "ganesh"]),
    ("mandi-negotiator-apex", [PY, "-m", "agents.negotiator.agent", "apex"]),
    ("deccan-sales", [PY, "-m", "agents.vendors.deccan.agent"]),
    ("ganesh-sales", [PY, "-m", "agents.vendors.ganesh.agent"]),
    ("apex-sales", [PY, "-m", "agents.vendors.apex.agent"]),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--core-only", action="store_true")
    ap.add_argument("--no-ui", action="store_true")
    a = ap.parse_args()
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(ROOT)}
    (ROOT / "logs").mkdir(exist_ok=True)
    plan = PROCS[:1] if a.core_only else list(PROCS)
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    if not a.core_only and not a.no_ui and (ROOT / "ui" / "node_modules").exists() and not (ROOT / "ui" / "dist").exists():
        plan.append(("control-room", [npm, "run", "dev", "--", "--port", "5173", "--strictPort"]))
    running: dict[str, tuple[subprocess.Popen, float, int]] = {}

    def start(name: str, cmd: list[str], restarts: int = 0) -> None:
        out = open(ROOT / "logs" / f"{name}.out", "a", encoding="utf-8")
        cwd = ROOT / "ui" if name == "control-room" else ROOT
        p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT,
                             creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        running[name] = (p, time.time(), restarts)
        print(f"  ▶ {name:<26} pid {p.pid}")

    print("Starting Mandi:")
    start(*plan[0])
    time.sleep(2.5)  # let Core come up before the agents subscribe to its event stream
    for name, cmd in plan[1:]:
        start(name, cmd)
        time.sleep(0.3)
    ui = "http://127.0.0.1:8700/" if (ROOT / "ui" / "dist").exists() else "http://127.0.0.1:5173/"
    print(f"\nControl Room: {ui}    Core API: http://127.0.0.1:8700/docs    Logs: logs/\nCtrl+C to stop.\n")
    try:
        while True:
            time.sleep(2)
            for name, cmd in plan:
                p, started, restarts = running[name]
                if p.poll() is not None:
                    if restarts >= 8:
                        print(f"  ✗ {name} keeps crashing — see logs/{name}.out")
                        continue
                    delay = min(30, 2 ** restarts)
                    print(f"  ↻ {name} exited ({p.returncode}); restarting in {delay}s (see logs/{name}.out)")
                    time.sleep(delay)
                    start(name, cmd, restarts + 1 if time.time() - started < 60 else 0)
    except KeyboardInterrupt:
        print("\nStopping…")
    finally:
        for name, (p, _, _) in running.items():
            if p.poll() is None:
                try:
                    if sys.platform == "win32":
                        p.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        p.terminate()
                except Exception:
                    p.kill()
        deadline = time.time() + 5
        for name, (p, _, _) in running.items():
            try:
                p.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
