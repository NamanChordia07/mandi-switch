import pytest

from core import chaser
from core.chaser import ChaserConfig


def test_off_by_default_and_env_override():
    assert chaser.load({}).enabled is False
    assert chaser.load({"enabled": False}, {"MANDI_CHASER": "1"}).enabled is True
    assert chaser.load({"enabled": True}, {"MANDI_CHASER": "0"}).enabled is False
    assert chaser.load({"enabled": True}, {"MANDI_CHASER": ""}).enabled is True
    c = chaser.load({"remind_after_s": 300}, {"MANDI_CHASER_REMIND_S": "3", "MANDI_CHASER_ESCALATE_S": "6"})
    assert (c.remind_after_s, c.escalate_after_s) == (3, 6)
    with pytest.raises(ValueError):
        chaser.load({"remind_after_s": 600, "escalate_after_s": 300})


def test_waiting_on():
    both = ["purchase_head", "finance"]
    assert chaser.waiting_on("AWARDED", both) == "purchase_head"
    assert chaser.waiting_on("ENDORSED_PURCHASE_HEAD", both) == "finance"
    assert chaser.waiting_on("ENDORSED_PURCHASE_HEAD", ["purchase_head"]) is None   # PH tier: no finance step
    assert chaser.waiting_on("AWARDED", []) is None                                  # auto tier
    assert chaser.waiting_on("PO_ISSUED", both) is None
    assert chaser.waiting_on("NEGOTIATING", both) is None


def test_remind_then_escalate_once_each():
    cfg = ChaserConfig(enabled=True, remind_after_s=300, escalate_after_s=600)
    done: set[str] = set()
    seen = []
    for t in range(0, 1200, 5):
        a = chaser.next_action(t, done, cfg)
        if a:
            done.add(a)
            seen.append((t, a))
    assert seen == [(300, "remind"), (600, "escalate")]
    # A late start (e.g. agent restarted after 11 min) escalates directly, without a stale reminder.
    assert chaser.next_action(660, set(), cfg) == "escalate"
    assert chaser.next_action(700, {"escalate"}, cfg) is None


def test_messages_name_the_humans_and_change_nothing():
    m = chaser.message("remind", "purchase_head", "SM-PR-2026-0147", approver="meera", approver_name="Meera Joshi",
                       escalate_to="rohan", escalate_name="Rohan Kulkarni", elapsed_s=305)
    assert "@meera" in m and "`@purchase-desk`" in m and "5 min" in m
    e = chaser.message("escalate", "finance", "SM-PR-2026-0147", approver="vikram", approver_name="Vikram Shah",
                       escalate_to="rohan", escalate_name="Rohan Kulkarni", elapsed_s=610)
    assert "@rohan" in e and "Vikram Shah" in e and "finance release" in e and "doesn't change the order" in e
