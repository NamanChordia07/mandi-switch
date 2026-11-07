"""Sign-off chaser: when a sign-off sits unanswered, remind the approver in the order room, then escalate to a
named human. Pure functions (tested in core/tests/test_chaser.py); the intake agent runs the timer.

Switchable and OFF by default (so it can't fire mid-demo): config/scenario.yaml → signoff_chaser.enabled, or
MANDI_CHASER=1 / 0 to override (see load()). It only posts messages; it never approves, declines or changes the order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

STEP_FOR_STATE = {"AWARDED": "purchase_head", "ENDORSED_PURCHASE_HEAD": "finance"}
STEP_LABEL = {"purchase_head": "purchase head endorsement", "finance": "finance release"}
STEP_AGENT = {"purchase_head": "purchase-desk", "finance": "po-issuer"}


@dataclass(frozen=True)
class ChaserConfig:
    enabled: bool = False
    remind_after_s: int = 300
    escalate_after_s: int = 600
    escalate_to: str = "rohan"          # persona id of the named human in the order room
    poll_s: float = 5.0


def load(cfg: dict[str, Any] | None, environ: Mapping[str, str] | None = None) -> ChaserConfig:
    """Config from scenario.yaml → signoff_chaser, with env overrides: MANDI_CHASER=0|1,
    MANDI_CHASER_REMIND_S, MANDI_CHASER_ESCALATE_S, MANDI_CHASER_POLL_S (handy for rehearsals and tests)."""
    cfg, environ = cfg or {}, environ or {}
    enabled = bool(cfg.get("enabled", False))
    if environ.get("MANDI_CHASER", "").strip() in ("0", "1"):
        enabled = environ["MANDI_CHASER"].strip() == "1"
    pick = lambda k, e, d: environ.get(e, "").strip() or cfg.get(k, d)  # noqa: E731
    c = ChaserConfig(enabled=enabled, remind_after_s=int(pick("remind_after_s", "MANDI_CHASER_REMIND_S", 300)),
                     escalate_after_s=int(pick("escalate_after_s", "MANDI_CHASER_ESCALATE_S", 600)),
                     escalate_to=str(cfg.get("escalate_to", "rohan")),
                     poll_s=float(pick("poll_s", "MANDI_CHASER_POLL_S", 5.0)))
    if c.escalate_after_s <= c.remind_after_s:
        raise ValueError("signoff_chaser: escalate_after_s must be greater than remind_after_s")
    return c


def waiting_on(state: str, tier_approvers: list[str] | tuple[str, ...]) -> Optional[str]:
    """Which human sign-off the order is waiting for, or None."""
    step = STEP_FOR_STATE.get(state)
    return step if step and step in tier_approvers else None


def next_action(elapsed_s: float, done: set[str], cfg: ChaserConfig) -> Optional[str]:
    """'remind' once after remind_after_s, then 'escalate' once after escalate_after_s; otherwise None."""
    if elapsed_s >= cfg.escalate_after_s and "escalate" not in done:
        return "escalate"
    if elapsed_s >= cfg.remind_after_s and "remind" not in done and "escalate" not in done:
        return "remind"
    return None


def message(action: str, step: str, order_id: str, *, approver: str, approver_name: str, escalate_to: str,
            escalate_name: str, elapsed_s: float) -> str:
    mins = max(1, int(elapsed_s // 60))
    label, agent = STEP_LABEL[step], STEP_AGENT[step]
    if action == "remind":
        return (f"⏰ Reminder: the **{label}** for {order_id} has been waiting {mins} min. @{approver} ask "
                f"`@{agent}` when you're ready; Switch will bring you the permission request. Nothing moves "
                f"without you.")
    return (f"📣 Escalation: the **{label}** for {order_id} has been waiting {mins} min without an answer from "
            f"{approver_name}. @{escalate_to} ({escalate_name}), please follow up with {approver_name.split()[0]}. "
            f"Only {approver_name.split()[0]} can give this sign-off; this message doesn't change the order.")
