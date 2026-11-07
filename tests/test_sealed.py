"""Sealed supplier rooms: the plan bootstrap uses must be private, and doctor must catch leaks."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import yaml

from common import sealed

ROOT = Path(__file__).resolve().parents[1]
SC = yaml.safe_load((ROOT / "config" / "scenario.yaml").read_text(encoding="utf-8"))


def _bootstrap():
    spec = importlib.util.spec_from_file_location("bootstrap_switch", ROOT / "scripts" / "bootstrap_switch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_real_room_plan_is_sealed():
    bs = _bootstrap()
    assert sealed.config_problems(bs.ROOMS, SC["personas"], SC["vendors"]) == []
    for v in sealed.vendor_keys(bs.ROOMS):
        assert bs.ROOMS[v]["channel_type"] == "channel_private"
        assert bs.ROOMS[v]["read_visibility"] == bs.ROOMS[v]["write_visibility"] == "private"


def test_public_or_leaky_room_plan_fails():
    rooms = copy.deepcopy(_bootstrap().ROOMS)
    rooms["deccan"]["channel_type"] = "channel_public"
    rooms["ganesh"]["read_visibility"] = "public"
    rooms["apex"]["agents"].append("deccan-sales")
    rooms["apex"]["people"].append("meera")
    problems = " | ".join(sealed.config_problems(rooms, SC["personas"], SC["vendors"]))
    assert "room deccan: channel_type" in problems
    assert "room ganesh: read_visibility" in problems
    assert "another supplier's agent ['deccan-sales']" in problems
    assert "buyer-side people ['meera']" in problems


def test_live_participants():
    names = {p: p for p in SC["personas"]} | {i["name"].lower(): p for p, i in SC["personas"].items()}
    ok = [{"type": "agent", "name": "deccan-sales"}, {"type": "agent", "name": "mandi-negotiator-deccan"},
          {"type": "user", "name": "Asha Rao"}, {"type": "user", "name": "switch-admin"}]
    kw = dict(all_vendor_keys=["deccan", "ganesh", "apex"], persona_names=names, vendors=SC["vendors"],
              personas=SC["personas"])
    assert sealed.participant_problems("deccan", ok, **kw) == []
    bad = ok + [{"type": "agent", "name": "apex-sales"}, {"type": "user", "name": "@sanjay"},
                {"type": "user", "name": "Rohan Kulkarni"}]
    problems = " | ".join(sealed.participant_problems("deccan", bad, **kw))
    assert "apex's agent apex-sales" in problems
    assert "ganesh's person sanjay" in problems
    assert "buyer-side person rohan" in problems


def test_policy_plan_scoped_to_own_room():
    bs = _bootstrap()
    ids = {"rooms": {"order": "r0", "deccan": "r1", "ganesh": "r2", "apex": "r3"},
           "people": {"asha": ["u1"], "sanjay": ["u2"], "karan": ["u3"]},
           "agents": {n: {"id": f"a-{n}"} for n in ("deccan-sales", "ganesh-sales", "apex-sales",
                                                     "mandi-negotiator-deccan", "mandi-negotiator-ganesh",
                                                     "mandi-negotiator-apex")}}
    plan = bs.policy_plan(ids)
    assert sealed.policy_problems(plan, ids["rooms"]) == []
    plan["apex-sales"]["rules"][0]["rooms"] = "*"
    assert sealed.policy_problems(plan, ids["rooms"]) == [
        "apex-sales: addressing rule covers rooms '*', must be only its sealed room"]


def test_mattermost_channel_types():
    expected = {"deccan": "D", "ganesh": "G"}
    chans = [{"display_name": "D", "name": "d", "type": "P"}, {"display_name": "G", "name": "g", "type": "O"}]
    assert sealed.mattermost_channel_problems(chans, expected) == [
        "room ganesh: Mattermost channel 'g' is type 'O', not private ('P')"]
    assert "no Mattermost channel" in sealed.mattermost_channel_problems([], {"apex": "A"})[0]
