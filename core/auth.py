"""Caller classes for Mandi Core. Static bearer tokens from .env, one per class.

| class               | who                                  | can                                             |
|---------------------|--------------------------------------|-------------------------------------------------|
| agents              | Mandi's own buyer agents             | run the order (spec, RFQ, quotes, negotiation)  |
| vendor:<id>         | one vendor's sales agent             | upload ITS quote, record ITS approvals          |
| mcp_purchase_desk   | Meera's Purchase Desk (Claude Code)  | read + endorse                                  |
| mcp_po_issuer       | Vikram's PO Issuer (Claude Code)     | read + issue PO                                 |
| ui                  | Control Room                         | read-only                                       |
| director            | Control Room director drawer         | start / reset / red-team                        |
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, Query, Request

from .config import env

VENDOR_IDS = ("deccan", "ganesh", "apex")


@dataclass(frozen=True)
class Caller:
    kind: str                        # agents | vendor | mcp_purchase_desk | mcp_po_issuer | ui | director
    vendor_id: Optional[str] = None

    @property
    def label(self) -> str:
        return f"vendor:{self.vendor_id}" if self.kind == "vendor" else self.kind


def _token_table() -> dict[str, Caller]:
    table: dict[str, Caller] = {}
    pairs = [("CORE_TOKEN_AGENTS", Caller("agents")),
             ("CORE_TOKEN_MCP_PURCHASE_DESK", Caller("mcp_purchase_desk")),
             ("CORE_TOKEN_MCP_PO_ISSUER", Caller("mcp_po_issuer")),
             ("CORE_TOKEN_UI", Caller("ui")),
             ("CORE_TOKEN_DIRECTOR", Caller("director"))]
    pairs += [(f"CORE_TOKEN_VENDOR_{v.upper()}", Caller("vendor", v)) for v in VENDOR_IDS]
    for var, caller in pairs:
        tok = env(var)
        if tok:
            table[tok] = caller
    return table


def resolve(token: str) -> Optional[Caller]:
    for known, caller in _token_table().items():
        if hmac.compare_digest(known, token):
            return caller
    return None


def caller_dep(request: Request, authorization: str = Header(default=""),
               token: str = Query(default="", include_in_schema=False)) -> Caller:
    raw = authorization.removeprefix("Bearer ").strip() if authorization else token
    caller = resolve(raw) if raw else None
    if caller is None:
        raise HTTPException(status_code=401, detail="Missing or unknown Mandi Core token.")
    return caller


def require(caller: Caller, *kinds: str) -> None:
    if caller.kind not in kinds:
        raise HTTPException(status_code=403,
                            detail=f"{caller.label} is not allowed to do this (needs {' or '.join(kinds)}).")


def require_vendor_scope(caller: Caller, vendor_id: str) -> None:
    """Vendor tokens only ever touch their own vendor's data."""
    if caller.kind == "vendor" and caller.vendor_id != vendor_id:
        raise HTTPException(status_code=403, detail="Vendor tokens can only access their own vendor's data.")
