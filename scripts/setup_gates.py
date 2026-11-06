"""Write the per-machine files for the two Claude Code gate agents.

For agents/gates/purchase-desk and agents/gates/po-issuer this writes:
  .mcp.json              → starts mcp_server/mandi_mcp.py with this repo's Python and the right profile
  .claude/settings.json  → trust the project MCP server; read tools allowed; the gated tool ALWAYS asks;
                           built-in file/shell/web tools denied (the gates only need Mandi's tools)

Run once after cloning (paths are absolute because Switch Console starts Claude Code in that directory):
    python scripts/setup_gates.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = Path(sys.executable)
if (ROOT / ".venv").exists():
    cand = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if cand.exists():
        PY = cand

GATES = {
    "purchase-desk": ("purchase_desk", "endorse_order"),
    "po-issuer": ("po_issuer", "issue_po"),
}
READ_TOOLS = ["get_order_status", "get_comparison", "get_audit_log"]
DENY_BUILTINS = ["Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch"]


def main() -> None:
    for name, (profile, gated) in GATES.items():
        d = ROOT / "agents" / "gates" / name
        (d / ".claude").mkdir(parents=True, exist_ok=True)
        mcp = {"mcpServers": {"mandi": {
            "command": str(PY),
            "args": [str(ROOT / "mcp_server" / "mandi_mcp.py")],
            "env": {"MANDI_MCP_PROFILE": profile, "PYTHONUTF8": "1"},
        }}}
        (d / ".mcp.json").write_text(json.dumps(mcp, indent=2), encoding="utf-8")
        settings = {
            "enableAllProjectMcpServers": True,
            "enabledMcpjsonServers": ["mandi"],
            "permissions": {
                "allow": [f"mcp__mandi__{t}" for t in READ_TOOLS],
                "ask": [f"mcp__mandi__{gated}"],
                "deny": DENY_BUILTINS,
            },
        }
        (d / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
        print(f"wrote {d.relative_to(ROOT)}/.mcp.json and .claude/settings.json (gated: {gated})")


if __name__ == "__main__":
    main()
