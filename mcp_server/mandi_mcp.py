"""Mandi MCP server for the two Claude Code gate agents (run by Switch Console / its agent controller).

Profiles (env MANDI_MCP_PROFILE):
  purchase_desk → get_order_status, get_comparison, get_audit_log, endorse_order        (Meera's agent)
  po_issuer     → get_order_status, get_comparison, get_audit_log, issue_po             (Vikram's agent)

The ONLY way these agents can change anything is the one gated tool of their profile. Claude Code asks before
running it, Switch turns that into a permission request in the room, and only the agent's single permitted
human (Meera / Vikram) can answer it. Mandi Core then re-checks everything in code (Lock 3).

Run (stdio): python mcp_server/mandi_mcp.py      — normally started by Claude Code from the agent's .mcp.json
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from mcp.server import MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

PROFILE = os.environ.get("MANDI_MCP_PROFILE", "purchase_desk")
TOKEN = os.environ.get("CORE_TOKEN_MCP_PURCHASE_DESK" if PROFILE == "purchase_desk" else "CORE_TOKEN_MCP_PO_ISSUER", "")
CORE = os.environ.get("CORE_URL", "http://127.0.0.1:8700")
AGENT = "purchase-desk" if PROFILE == "purchase_desk" else "po-issuer"

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
GATED = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)

mcp = MCPServer(
    name="mandi",
    instructions=(f"Mandi procurement tools for the {AGENT} agent of Sahyadri Motors. Read tools are safe. "
                  + ("endorse_order records the Purchase Head's endorsement and always needs Meera's approval."
                     if PROFILE == "purchase_desk" else
                     "issue_po issues a legally binding purchase order and always needs Vikram's approval.")),
)


def _client() -> httpx.Client:
    return httpx.Client(base_url=CORE, timeout=60.0, headers={"Authorization": f"Bearer {TOKEN}"})


def _rupees(paise: int | None) -> str:
    if paise is None:
        return "—"
    from core.money import fmt_inr
    return fmt_inr(paise, decimals=True)


def _current(c: httpx.Client) -> str:
    r = c.get("/orders/current")
    r.raise_for_status()
    o = (r.json() or {}).get("order")
    if not o:
        raise ValueError("There is no active order in Mandi.")
    return o["id"]


@mcp.tool(annotations=READ)
def get_order_status(order_id: str = "") -> dict[str, Any]:
    """Current state of a purchase order request: award, approval tier, endorsements, disqualified vendors.
    Leave order_id empty for the active order."""
    with _client() as c:
        oid = order_id or _current(c)
        r = c.get(f"/orders/{oid}")
        r.raise_for_status()
        v = r.json()
    o = v["order"]
    offer = next((x for x in v["offers"] if x["id"] == o.get("awarded_offer_id")), None)
    vendors = {x["vendor_id"]: x for x in v["vendors"]}
    endorsed = [a for a in v["approvals"] if a["kind"] == "PURCHASE_HEAD_ENDORSEMENT" and a["decision"] == "APPROVED"]
    return {
        "order_id": oid, "state": o["state"], "part": o["spec"].get("part_name"), "quantity": o["spec"].get("quantity"),
        "awarded_vendor": vendors[o["awarded_vendor_id"]]["legal_name"] if o.get("awarded_vendor_id") else None,
        "awarded_vendor_status": vendors[o["awarded_vendor_id"]]["status"] if o.get("awarded_vendor_id") else None,
        "unit_price": _rupees(offer["unit_price_paise"]) if offer else None,
        "total_excl_gst": _rupees(offer["unit_price_paise"] * offer["quantity"]) if offer else None,
        "approval_tier": (v.get("tier") or {}).get("label"),
        "approvers_required": (v.get("tier") or {}).get("approvers"),
        "purchase_head_endorsed": bool(endorsed),
        "disqualified_vendors": [x["legal_name"] for x in v["vendors"] if x["status"] == "DISQUALIFIED"],
        "po_issued": (v.get("po") or {}).get("id"),
    }


@mcp.tool(annotations=READ)
def get_comparison(order_id: str = "") -> dict[str, Any]:
    """The normalised quote comparison (landed cost, traps found) and the savings so far."""
    with _client() as c:
        oid = order_id or _current(c)
        r = c.get(f"/orders/{oid}/comparison")
        r.raise_for_status()
        cmp = r.json()
    rows = [{"vendor": x["vendor"], "rank": x["rank"], "landed_unit": _rupees(x["landed_unit_paise"]),
             "landed_total": _rupees(x["landed_total_paise"]), "flags": x["flags"]} for x in cmp["rows"]]
    return {"order_id": oid, "rows": rows, "best_valid_opening_total": _rupees(cmp["best_landed_total_paise"]),
            "traps_caught": cmp["traps_caught"], "injections_blocked": cmp["injections_blocked"]}


@mcp.tool(annotations=READ)
def get_audit_log(order_id: str = "", last: int = 12) -> dict[str, Any]:
    """The most recent entries of the order's hash-chained audit log, and whether the chain verifies."""
    with _client() as c:
        oid = order_id or _current(c)
        r = c.get(f"/orders/{oid}/audit")
        r.raise_for_status()
        a = r.json()
    ev = [e for e in a["events"] if e["kind"] != "STATE_CHANGED"][-max(1, min(last, 40)):]
    return {"order_id": oid, "chain_verified": a["verified"]["ok"],
            "events": [{"seq": e["seq"], "kind": e["kind"], "summary": e["summary"]} for e in ev]}


if PROFILE == "purchase_desk":
    @mcp.tool(annotations=GATED)
    def endorse_order(order_id: str, note: str = "") -> dict[str, Any]:
        """Record the Purchase Head's endorsement of the provisional award. This changes the order and is
        allowed only after Meera approves this exact action in Switch."""
        with _client() as c:
            r = c.post(f"/orders/{order_id}/endorse", json={"note": note})
        if r.status_code >= 400:
            return {"ok": False, "status": r.status_code, "refused": r.json()}
        o = r.json()["order"]
        return {"ok": True, "order_id": order_id, "state": o["state"],
                "message": "Endorsement recorded. Finance release is next (Vikram, via the po-issuer agent)."}

if PROFILE == "po_issuer":
    @mcp.tool(annotations=GATED)
    def issue_po(order_id: str) -> dict[str, Any]:
        """Issue the legally binding purchase order for the endorsed award. Allowed only after Vikram approves
        this exact action in Switch. Mandi re-checks every rule and refuses (409) if anything is wrong."""
        with _client() as c:
            r = c.post(f"/orders/{order_id}/issue-po", json={"agent_name": "po-issuer"})
        if r.status_code == 409:
            body = r.json()
            return {"ok": False, "refused_by_mandi": True, "reasons": body.get("failed_checks") or [body.get("detail")]}
        if r.status_code >= 400:
            return {"ok": False, "status": r.status_code, "detail": r.text[:500]}
        po = r.json()
        return {"ok": True, "po_number": po["id"], "vendor_id": po["vendor_id"], "total_excl_gst": _rupees(po["total_paise"]),
                "unit_price": _rupees(po["unit_price_paise"]), "quantity": po["quantity"],
                "pdf": f"{CORE}/orders/{order_id}/po.pdf",
                "note": "The PO PDF is posted to the order room by Mandi automatically."}


if __name__ == "__main__":
    mcp.run("stdio")
