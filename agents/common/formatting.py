"""Message wording for Mandi's agents.

Every message is first built from a deterministic template (numbers from code). If an LLM is available it
may rephrase the prose in the agent's voice, but the rephrasing is rejected unless it contains exactly the
same rupee amounts as the template. A machine-readable line (Offer:/Ask:/Decision:) is appended by code,
never by the LLM, and is what the other side parses.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from core.money import fmt_inr, fmt_unit, indian_group, to_paise

log = logging.getLogger("mandi.wording")

AMOUNT_RE = re.compile(r"(?:₹|Rs\.?|INR)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", re.I)
OFFER_RE = re.compile(r"Offer:\s*₹\s*([0-9][0-9,]*\.[0-9]{2})\s*/\s*pc\s+(delivered|ex-works)\s*·\s*([0-9,]+)\s*pcs"
                      r"(?:\s*·\s*(FINAL|ACCEPTED))?", re.I)
ASK_RE = re.compile(r"Ask:\s*₹\s*([0-9][0-9,]*\.[0-9]{2})\s*/\s*pc\s+(delivered|ex-works)\s*·\s*([0-9,]+)\s*pcs", re.I)
REQUOTE_RE = re.compile(r"Requote:\s*([0-9,]+)\s*pcs", re.I)
DECISION_RE = re.compile(r"Decision:\s*(accepted|closed|awarded-elsewhere|rfq)", re.I)
RFQ_RE = re.compile(r"RFQ:\s*([A-Z0-9-]+)", re.I)


def amounts(text: str) -> list[int]:
    out = []
    for m in AMOUNT_RE.finditer(text):
        try:
            out.append(to_paise(m.group(1)))
        except ValueError:
            pass
    return out


def parse_offer(text: str) -> Optional[dict]:
    m = OFFER_RE.search(text)
    if not m:
        return None
    flag = (m.group(4) or "").upper()
    return {"unit_price_paise": to_paise(m.group(1)),
            "basis": "EX_WORKS" if m.group(2).lower().startswith("ex") else "DELIVERED",
            "quantity": int(m.group(3).replace(",", "")), "is_final": flag in ("FINAL", "ACCEPTED"),
            "accepted": flag == "ACCEPTED"}


def parse_ask(text: str) -> Optional[dict]:
    m = ASK_RE.search(text)
    if not m:
        return None
    return {"unit_price_paise": to_paise(m.group(1)), "quantity": int(m.group(3).replace(",", ""))}


def offer_line(price: int, qty: int, basis: str = "delivered", flag: str = "") -> str:
    return f"Offer: {fmt_unit(price)}/pc {basis} · {indian_group(qty)} pcs" + (f" · {flag}" if flag else "")


def ask_line(price: int, qty: int) -> str:
    return f"Ask: {fmt_unit(price)}/pc delivered · {indian_group(qty)} pcs"


def machine(line: str) -> str:
    """Machine-readable footer, styled small in Mattermost."""
    return f"\n`{line}`"


def wordsmith(template: str, *, voice: str, purpose: str, max_sentences: int = 3) -> str:
    """Optionally rephrase `template` in the agent's voice. Falls back to the template on any doubt."""
    try:
        from common.llm import LLMUnavailable, complete_text
    except Exception:
        return template
    required = sorted(amounts(template))
    system = (f"{voice}\nRewrite the draft message below in your voice for a business chat. Keep it to at most "
              f"{max_sentences} short sentences, Indian business English, no emoji, no greeting line on its own, "
              "no sign-off. Keep every rupee amount EXACTLY as written (same digits, with the ₹ sign and two "
              "decimals). Do not add any new number, price, date, quantity or company name. Keep any @mention "
              "exactly as written at the start. Output only the message text.")
    try:
        out = complete_text(system, f"Purpose: {purpose}\n\nDraft:\n{template}", max_tokens=1500, effort="low")
    except LLMUnavailable as exc:
        log.debug("wordsmith offline: %s", exc)
        return template
    except Exception as exc:  # never let wording break the workflow
        log.warning("wordsmith failed: %s", exc)
        return template
    out = out.strip().strip('"')
    mentions = re.findall(r"@[a-z0-9][a-z0-9._-]*", template)
    if not out or sorted(amounts(out)) != required or any(m not in out for m in mentions) or len(out) > 700:
        log.info("wordsmith output rejected (numbers/mentions changed); using template")
        return template
    return out


__all__ = ["amounts", "parse_offer", "parse_ask", "offer_line", "ask_line", "machine", "wordsmith", "fmt_inr",
           "fmt_unit", "indian_group", "REQUOTE_RE", "DECISION_RE", "RFQ_RE"]
