"""Normalised quote comparison and a code-written recommendation.

Ranking: comparable quotes by landed total (ascending); ties -> shorter lead time,
then longer payment terms (better for the buyer's cash flow).
"""
from __future__ import annotations

from typing import Any

from .money import fmt_inr, fmt_unit, indian_group

FLAG_TEXT = {
    "HIDDEN_MOQ": "MOQ above our quantity",
    "EXPIRED": "Expired",
    "LATE_DELIVERY": "Late delivery",
    "FREIGHT_EXCLUDED": "Ex-works (freight extra)",
    "MISSING_FIELD": "Missing field",
    "INJECTION": "Prompt injection",
}


def rank_key(q: dict[str, Any]):
    return (q["landed_total_paise"], q.get("lead_time_days") or 10**6, -(q.get("payment_terms_days") or 0))


def build(quotes: list[dict[str, Any]], vendors: dict[str, dict[str, Any]], *, quantity: int) -> dict[str, Any]:
    """quotes: parsed QuoteRow dicts. vendors: vendor_id -> VendorRow dict."""
    comparable = sorted([q for q in quotes if q.get("comparable") and q.get("landed_total_paise") is not None],
                        key=rank_key)
    rank_of = {q["id"]: i + 1 for i, q in enumerate(comparable)}
    rows = []
    for q in sorted(quotes, key=lambda q: (rank_of.get(q["id"], 99), q.get("landed_unit_paise") or 10**9)):
        v = vendors.get(q["vendor_id"], {})
        rows.append({
            "quote_id": q["id"],
            "vendor_id": q["vendor_id"],
            "vendor": v.get("legal_name", q["vendor_id"]),
            "vendor_status": v.get("status"),
            "rank": rank_of.get(q["id"]),
            "unit_paise": q.get("unit_price_paise"),
            "basis": q.get("basis"),
            "freight_paise": q.get("freight_paise_per_unit"),
            "landed_unit_paise": q.get("landed_unit_paise"),
            "landed_total_paise": q.get("landed_total_paise") if q.get("comparable") else None,
            "moq": q.get("moq"),
            "lead_time_days": q.get("lead_time_days"),
            "valid_until": q.get("valid_until"),
            "payment_terms_days": q.get("payment_terms_days"),
            "comparable": bool(q.get("comparable")),
            "injection_verdict": q.get("injection_verdict"),
            "traps": q.get("traps", []),
            "flags": [FLAG_TEXT.get(t["code"], t["code"]) for t in q.get("traps", [])],
        })
    best = comparable[0] if comparable else None
    return {
        "quantity": quantity,
        "rows": rows,
        "best_quote_id": best["id"] if best else None,
        "best_vendor_id": best["vendor_id"] if best else None,
        "best_landed_unit_paise": best["landed_unit_paise"] if best else None,
        "best_landed_total_paise": best["landed_total_paise"] if best else None,
        "traps_caught": sum(1 for r in rows for t in r["traps"] if t["code"] in
                            ("HIDDEN_MOQ", "EXPIRED", "LATE_DELIVERY", "FREIGHT_EXCLUDED")),
        "injections_blocked": sum(1 for r in rows for t in r["traps"] if t["code"] == "INJECTION"),
        "recommendation": recommendation(rows, quantity),
    }


def _poss(name: str) -> str:
    return name + ("'" if name.endswith("s") else "'s")


def recommendation(rows: list[dict[str, Any]], quantity: int) -> str:
    """Plain-English recommendation. Every number comes from the table (never invented)."""
    ranked = [r for r in rows if r["rank"]]
    parts: list[str] = []
    if ranked:
        b = ranked[0]
        parts.append(f"Best valid quote today: {b['vendor']} at {fmt_unit(b['landed_unit_paise'])}/pc landed "
                     f"({fmt_inr(b['landed_total_paise'])} for {indian_group(quantity)} pcs).")
    live = ("ACTIVE", "CLOSED")
    renegotiable = [r for r in rows if not r["comparable"] and any(t["code"] == "HIDDEN_MOQ" for t in r["traps"])
                    and r["vendor_status"] in live]
    for r in renegotiable:
        parts.append(f"{_poss(r['vendor'])} {fmt_unit(r['unit_paise'])} is only for its minimum order of "
                     f"{indian_group(r['moq'])}; we'll ask for a {indian_group(quantity)}-piece price.")
    expired = [r for r in rows if any(t["code"] == "EXPIRED" for t in r["traps"])]
    for r in expired:
        parts.append(f"{_poss(r['vendor'])} quote has expired and is excluded.")
    injected = [r for r in rows if any(t["code"] == "INJECTION" for t in r["traps"])]
    for r in injected:
        parts.append(f"{r['vendor']} is disqualified: its document tried to instruct our agents.")
    negotiable = [r["vendor"] for r in rows if r["vendor_status"] in live and (r["rank"] or r in renegotiable)]
    if negotiable:
        parts.append("Recommendation: negotiate with " + " and ".join(negotiable) + " in parallel, in sealed rooms.")
    return " ".join(parts)
