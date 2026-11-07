"""Sealed-room rules, shared by scripts/bootstrap_switch.py (which creates the rooms) and scripts/doctor.py
(which checks them). Pure functions: no network, so every rule is unit-tested (tests/test_sealed.py).

A supplier's room is "sealed" when:
  1. it is created as a PRIVATE Mattermost channel with private read and write visibility in Switch;
  2. the only supplier-side agent in it is that supplier's own sales agent;
  3. the only supplier-side person in it is that supplier's own contact;
  4. no buyer-side human is a member (the buyer speaks through its negotiator agent);
  5. the supplier's agent may be addressed only in its own room (addressing policy).
"""
from __future__ import annotations

from typing import Any, Iterable


def vendor_keys(rooms: dict[str, dict[str, Any]]) -> list[str]:
    return [k for k in rooms if k != "order"]


def config_problems(rooms: dict[str, dict[str, Any]], personas: dict[str, dict[str, Any]],
                    vendors: dict[str, dict[str, Any]]) -> list[str]:
    """Check the room plan (bootstrap_switch.ROOMS) before anything is created. Empty list = sealed."""
    problems: list[str] = []
    vkeys = vendor_keys(rooms)
    sales = {v: (vendors.get(v) or {}).get("agent") or f"{v}-sales" for v in vkeys}
    contact = {v: (vendors.get(v) or {}).get("contact_persona") for v in vkeys}
    buyer_people = {p for p, info in personas.items() if info.get("company") == "buyer"}
    for v in vkeys:
        spec = rooms[v]
        if spec.get("channel_type") != "channel_private":
            problems.append(f"room {v}: channel_type is {spec.get('channel_type')!r}, must be 'channel_private'")
        for field in ("read_visibility", "write_visibility"):
            if spec.get(field, "private") != "private":
                problems.append(f"room {v}: {field} is {spec.get(field)!r}, must be 'private'")
        foreign_agents = {sales[o] for o in vkeys if o != v} & set(spec.get("agents", []))
        if foreign_agents:
            problems.append(f"room {v}: contains another supplier's agent {sorted(foreign_agents)}")
        people = set(spec.get("people", []))
        foreign_people = {contact[o] for o in vkeys if o != v and contact[o]} & people
        if foreign_people:
            problems.append(f"room {v}: contains another supplier's person {sorted(foreign_people)}")
        if people & buyer_people:
            problems.append(f"room {v}: buyer-side people {sorted(people & buyer_people)} should not be members")
    return problems


def participant_problems(room_key: str, participants: Iterable[dict[str, Any]], *, all_vendor_keys: list[str],
                         persona_names: dict[str, str], vendors: dict[str, dict[str, Any]],
                         personas: dict[str, dict[str, Any]]) -> list[str]:
    """Check a LIVE vendor room's members (Switch list_participants). persona_names maps lower-cased display or
    user names to persona ids."""
    problems: list[str] = []
    sales = {v: (vendors.get(v) or {}).get("agent") or f"{v}-sales" for v in all_vendor_keys}
    for prt in participants:
        name = (prt.get("name") or "").strip()
        if prt.get("type") == "agent":
            other = [v for v, a in sales.items() if a == name and v != room_key]
            if other:
                problems.append(f"room {room_key}: {other[0]}'s agent {name} is a member")
            continue
        p = persona_names.get(name.lower()) or persona_names.get(name.lower().lstrip("@"))
        if not p:
            continue
        company = personas.get(p, {}).get("company")
        if company == "buyer":
            problems.append(f"room {room_key}: buyer-side person {p} is a member")
        elif company and company != room_key:
            problems.append(f"room {room_key}: {company}'s person {p} is a member")
    return problems


def policy_problems(plan: dict[str, dict[str, Any]], room_ids: dict[str, str]) -> list[str]:
    """Check the addressing-policy plan: each supplier agent may be addressed only in its own room."""
    problems: list[str] = []
    for v in room_ids:
        if v == "order":
            continue
        name = f"{v}-sales"
        pol = plan.get(name)
        if not pol:
            problems.append(f"{name}: no addressing policy planned")
            continue
        for rule in pol.get("rules", []):
            rooms = rule.get("rooms")
            if rooms == "*" or set(rooms or []) != {room_ids[v]}:
                problems.append(f"{name}: addressing rule covers rooms {rooms!r}, must be only its sealed room")
    return problems


def mattermost_channel_problems(channels: list[dict[str, Any]], expected_names: dict[str, str]) -> list[str]:
    """channels: Mattermost channel objects (mmctl --json). expected_names: room key -> display name.
    Mattermost channel type 'P' = private, 'O' = open (public)."""
    problems: list[str] = []
    by_display = {c.get("display_name"): c for c in channels}
    for key, display in expected_names.items():
        ch = by_display.get(display)
        if ch is None:
            problems.append(f"room {key}: no Mattermost channel named {display!r} found")
        elif ch.get("type") != "P":
            problems.append(f"room {key}: Mattermost channel {ch.get('name')!r} is type {ch.get('type')!r}, "
                            f"not private ('P')")
    return problems
