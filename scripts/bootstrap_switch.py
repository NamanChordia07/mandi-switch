"""Bootstrap Mandi's Switch workspace (idempotent; --dry-run prints the plan).

    python scripts/bootstrap_switch.py [--dry-run] [--skip-policies]

1. Check the Switch server (/health) and that the agent keys work.
2. Find the Mattermost bridge (list_bridges).
3. Ensure the 4 rooms exist (created by mandi-intake via `create_room`, so Switch creates the Mattermost
   channels): the order room and three sealed vendor rooms (private channels), with room instructions,
   the right agents and the right people in each.
4. Invite the two Claude Code gate agents to the order room and define the exclusive role `po-issuer`.
5. Collect participant ids and write secrets/switch-ids.local.json (rooms, agents, people).
6. Set each agent's "who can talk to me" policy through the Gateway API (admin login from .env), so e.g.
   only Meera can instruct (and therefore approve for) purchase-desk. Prints manual steps if it can't.
7. Verify sealed-ness: each vendor agent is a member of its own room only.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)
from agents.switchclient import SwitchAgent, SwitchError  # noqa: E402

SECRETS = Path(os.environ.get("MANDI_SECRETS_DIR", ROOT / "secrets"))
KEYS = SECRETS / "agent-keys.local.json"
IDS = SECRETS / "switch-ids.local.json"
SC = yaml.safe_load((ROOT / "config" / "scenario.yaml").read_text(encoding="utf-8"))
ORDER_SHORT = SC["order"]["short_id"]          # SM-PR-0147
SLUG = ORDER_SHORT.lower().replace("sm-pr-", "sm-pr-")
MM_USER = {p: os.environ.get(f"MM_USER_{p.upper()}", p) for p in SC["personas"]}   # Mattermost usernames

ROOMS = {
    "order": {"name": f"{ORDER_SHORT} · Seat bolts · Order room", "channel_type": "channel_public",
              "agents": ["mandi-intake", "mandi-quotes", "mandi-auditor"],
              "people": ["rohan", "meera", "vikram"], "instructions": "order.md",
              "description": f"Buyer-side order room for {SC['order']['order_id']}: spec, quotes, approvals, PO."},
    "deccan": {"name": f"{ORDER_SHORT} · Deccan Bolt Works · Sealed", "channel_type": "channel_private",
               "agents": ["mandi-negotiator-deccan", "deccan-sales", "mandi-auditor"], "people": ["asha"],
               "instructions": "vendor.md", "description": "Sealed negotiation room: Sahyadri Motors ↔ Deccan Bolt Works."},
    "ganesh": {"name": f"{ORDER_SHORT} · Shree Ganesh Fasteners · Sealed", "channel_type": "channel_private",
               "agents": ["mandi-negotiator-ganesh", "ganesh-sales", "mandi-auditor"], "people": ["sanjay"],
               "instructions": "vendor.md", "description": "Sealed negotiation room: Sahyadri Motors ↔ Shree Ganesh Fasteners."},
    "apex": {"name": f"{ORDER_SHORT} · Apex Precision · Sealed", "channel_type": "channel_private",
             "agents": ["mandi-negotiator-apex", "apex-sales", "mandi-auditor"], "people": ["karan"],
             "instructions": "vendor.md", "description": "Sealed negotiation room: Sahyadri Motors ↔ Apex Precision Components."},
}
GATES = ["purchase-desk", "po-issuer"]
ROLE_INSTRUCTIONS = (ROOT / "agents" / "gates" / "po-issuer" / "CLAUDE.md").read_text(encoding="utf-8")


def log(msg: str) -> None:
    print(msg, flush=True)


def keys() -> dict[str, Any]:
    return json.loads(KEYS.read_text(encoding="utf-8")) if KEYS.exists() else {}


def agent(name: str, rooms: list[str] | None = None, scope: str = "single") -> SwitchAgent:
    k = keys()[name]
    sw = SwitchAgent(base_url=os.environ.get("SWITCH_BASE_URL", "http://127.0.0.1:8000"), agent_id=k["id"],
                     api_key=k["api_key"], name=f"bootstrap-{name}", rooms=rooms, scope=scope,
                     state_dir=Path(os.environ.get("MANDI_STATE_DIR", ROOT / ".state")) / "bootstrap")
    return sw


async def with_connection(sw: SwitchAgent, fn):
    """Run fn while sw holds a live connection (ops that act in a room need one)."""
    task = asyncio.create_task(sw.run())
    try:
        await asyncio.wait_for(sw.live.wait(), timeout=20)
        return await fn()
    finally:
        sw.stopped = True
        if sw._ws is not None:
            await sw._ws.close()
        task.cancel()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-policies", action="store_true")
    a = ap.parse_args()
    base = os.environ.get("SWITCH_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    async with httpx.AsyncClient(timeout=10) as c:
        h = await c.get(f"{base}/health")
        log(f"✓ Switch at {base} → /health {h.status_code} {h.text[:80]}")
    k = keys()
    missing = [n for r in ROOMS.values() for n in r["agents"] if n not in k]
    if missing:
        log(f"✗ missing agent keys: {sorted(set(missing))} — run scripts/register_agents.py first")
        return 1
    ids: dict[str, Any] = json.loads(IDS.read_text(encoding="utf-8")) if IDS.exists() else {}
    ids.setdefault("rooms", {})
    ids["order_id"] = SC["order"]["order_id"]

    intake = agent("mandi-intake")
    bridges = await intake.call("list_bridges")
    mm = next((b for b in bridges if b.get("type", "").lower().startswith("mattermost") and b.get("status") == "active"),
              next((b for b in bridges if b.get("is_default")), None))
    log(f"✓ bridges: {[(b.get('type'), b.get('display_name'), b.get('status')) for b in bridges]}")
    if not mm:
        log("✗ no active Mattermost bridge — connect Mattermost in Switch Console first (docs/manual-setup.md)")
        return 1
    existing = await intake.call("list_rooms")
    by_name = {r.get("name"): r for r in existing or []}

    # ---------------------------------------------------------------- rooms
    for key, spec in ROOMS.items():
        rid = ids["rooms"].get(key)
        if not rid and spec["name"] in by_name:
            rid = by_name[spec["name"]].get("id") or by_name[spec["name"]].get("room_id")
        if rid:
            log(f"✓ room {key}: exists ({rid})")
            ids["rooms"][key] = rid
            continue
        instr = (ROOT / "config" / "room-instructions" / spec["instructions"]).read_text(encoding="utf-8")
        args = dict(name=spec["name"], description=spec["description"], agent_names=spec["agents"],
                    user_names=[MM_USER[p] for p in spec["people"]], channel_type=spec["channel_type"],
                    bridge_id=mm["id"], instructions=instr,
                    read_visibility="private" if key != "order" else "public",
                    write_visibility="private" if key != "order" else "public")
        if a.dry_run:
            log(f"• would create room {key}: {json.dumps({k2: v for k2, v in args.items() if k2 != 'instructions'})}")
            continue
        try:
            res = await intake.call("create_room", **args)
        except SwitchError as exc:
            log(f"  create_room with users failed ({exc}); retrying without user_names")
            args.pop("user_names")
            res = await intake.call("create_room", **args)
        rid = res.get("room_id") or res.get("id")
        ids["rooms"][key] = rid
        log(f"✓ room {key}: created {rid} ({res.get('channel') or res.get('channel_name') or ''})")
        IDS.write_text(json.dumps(ids, indent=2), encoding="utf-8")

    if a.dry_run:
        return 0
    order = ids["rooms"]["order"]

    # ---------------------------------------------------------------- order room: gates + role + participants
    async def order_room_setup():
        sw = intake_conn
        out: dict[str, Any] = {}
        for g in GATES:
            try:
                await sw.call("invite_agent_to_room", room_id=order, agent_name=g)
                log(f"✓ invited {g} to the order room")
            except SwitchError as exc:
                log(f"! could not invite {g} ({exc.status}): create it in Switch Console first (manual-setup §6)")
        try:
            roles = await sw.call("list_roles")
            if not any((r.get("name") == "po-issuer") for r in roles or []):
                await sw.call("define_role", name="po-issuer", instructions=ROLE_INSTRUCTIONS, exclusive=True)
                log("✓ defined exclusive role po-issuer")
            else:
                log("✓ role po-issuer exists")
        except SwitchError as exc:
            log(f"! define_role failed: {exc}")
        out["participants"] = await sw.call("list_participants")
        return out

    intake_conn = agent("mandi-intake", rooms=[order])
    order_info = await with_connection(intake_conn, order_room_setup)
    participants = {"order": order_info["participants"]}
    for v in ("deccan", "ganesh", "apex"):
        rid = ids["rooms"].get(v)
        if not rid:
            continue
        neg = agent(f"mandi-negotiator-{v}", rooms=[rid])
        participants[v] = await with_connection(neg, lambda neg=neg: neg.call("list_participants"))

    # ---------------------------------------------------------------- ids: people + agents
    people: dict[str, list[str]] = {}
    agents_out: dict[str, Any] = {}
    names_to_persona = {}
    for p, info in SC["personas"].items():
        names_to_persona[p] = p
        names_to_persona[MM_USER[p].lower()] = p
        names_to_persona[info["name"].lower()] = p
    for room_key, plist in participants.items():
        for prt in plist or []:
            nm = (prt.get("name") or "").strip()
            if prt.get("type") == "agent":
                a_ent = agents_out.setdefault(nm, {"participant_ids": []})
                if prt["id"] not in a_ent["participant_ids"]:
                    a_ent["participant_ids"].append(prt["id"])
            else:
                persona = names_to_persona.get(nm.lower()) or names_to_persona.get(nm.lower().lstrip("@"))
                if persona:
                    people.setdefault(persona, [])
                    if prt["id"] not in people[persona]:
                        people[persona].append(prt["id"])
    for n, kk in k.items():
        agents_out.setdefault(n, {"participant_ids": []})["id"] = kk["id"]
    try:  # the Claude Code gate agents are registered by Switch Console; find their ids
        listed = await intake.call("list_agents")
        for ag in (listed.get("agents") if isinstance(listed, dict) else listed) or []:
            nm = ag.get("name")
            if nm in GATES:
                agents_out.setdefault(nm, {"participant_ids": []})["id"] = ag.get("id") or ag.get("agent_id")
    except SwitchError as exc:
        log(f"! list_agents failed: {exc}")
    ids["people"], ids["agents"] = people, agents_out
    IDS.write_text(json.dumps(ids, indent=2), encoding="utf-8")
    log(f"✓ people found: { {p: len(v) for p, v in people.items()} }")
    if len(people) < 4:
        log("! some personas were not found in the rooms — create/link their Mattermost accounts "
            "(scripts/create_personas.py) and rerun bootstrap")

    # ---------------------------------------------------------------- sealed-ness check
    sealed_ok = True
    for v in ("deccan", "ganesh", "apex"):
        names = {p.get("name") for p in participants.get(v, [])}
        others = {f"{o}-sales" for o in ("deccan", "ganesh", "apex") if o != v}
        if names & others:
            sealed_ok = False
            log(f"✗ room {v} contains another vendor's agent: {names & others}")
    log("✓ sealed rooms: each vendor agent is only in its own room" if sealed_ok else "✗ sealed check failed")

    # ---------------------------------------------------------------- addressing policies (Gateway, admin)
    if not a.skip_policies:
        await set_policies(base, ids)
    log(f"\nWrote {IDS}")
    return 0


def policy_plan(ids: dict[str, Any]) -> dict[str, dict[str, Any]]:
    R, P, A = ids["rooms"], ids.get("people", {}), ids.get("agents", {})
    pid = lambda *ps: [x for p in ps for x in P.get(p, [])]  # noqa: E731
    aid = lambda *ns: [A[n]["id"] for n in ns if n in A and A[n].get("id")]  # noqa: E731
    mandi = ["mandi-intake", "mandi-quotes", "mandi-auditor"]
    plan = {
        "mandi-intake": {"rules": [{"rooms": [R["order"]], "users": pid("rohan", "meera", "vikram"),
                                    "agents": aid(*mandi, "purchase-desk", "po-issuer"), "owner": True}]},
        "mandi-quotes": {"rules": [{"rooms": [R["order"]], "users": pid("rohan", "meera", "vikram"),
                                    "agents": aid(*mandi), "owner": True}]},
        "mandi-auditor": {"rules": [{"rooms": "*", "users": [], "agents": [], "owner": True}]},
        # The gates answer exactly ONE human and no agent — so only that human can approve their requests.
        "purchase-desk": {"rules": [{"rooms": [R["order"]], "users": pid("meera"), "agents": [], "owner": False}]},
        "po-issuer": {"rules": [{"rooms": [R["order"]], "users": pid("vikram"), "agents": [], "owner": False}]},
    }
    for v, person in (("deccan", "asha"), ("ganesh", "sanjay"), ("apex", "karan")):
        if v not in R:
            continue
        plan[f"mandi-negotiator-{v}"] = {"rules": [{"rooms": [R[v]], "users": pid(person),
                                                   "agents": aid(f"{v}-sales", *mandi), "owner": True}]}
        # The vendor's agent answers its own person and the buyer's negotiator in its sealed room — not the
        # buyer's other agents, not the platform operator.
        plan[f"{v}-sales"] = {"rules": [{"rooms": [R[v]], "users": pid(person),
                                         "agents": aid(f"mandi-negotiator-{v}"), "owner": True}]}
    for p in plan.values():
        for r in p["rules"]:
            r.setdefault("room_groups", "*")
    return plan


async def set_policies(base: str, ids: dict[str, Any]) -> None:
    email, pw = os.environ.get("SWITCH_ADMIN_EMAIL", ""), os.environ.get("SWITCH_ADMIN_PASSWORD", "")
    plan = policy_plan(ids)
    (SECRETS / "addressing-plan.local.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    if not (email and pw):
        log("! SWITCH_ADMIN_EMAIL/PASSWORD not set — addressing policies NOT applied. Apply them in Switch Console\n"
            "  (agent → General → Who can talk to your agent → Custom rules) per docs/manual-setup.md §8, or set the\n"
            "  admin login in .env and rerun. Plan written to secrets/addressing-plan.local.json")
        return
    async with httpx.AsyncClient(base_url=base, timeout=20) as c:
        r = await c.post("/gateway/auth/login", json={"email": email, "password": pw})
        if r.status_code >= 400:
            log(f"! Gateway login failed ({r.status_code}); policies not applied")
            return
        for name, policy in plan.items():
            aid_ = ids["agents"].get(name, {}).get("id")
            if not aid_:
                log(f"! {name}: agent id unknown (gate agents: create them in Console, then rerun)")
                continue
            r = await c.put(f"/gateway/agents/{aid_}/addressing-policy", json={"policy": policy})
            log(f"{'✓' if r.status_code < 400 else '✗'} policy {name}: HTTP {r.status_code}"
                + ("" if r.status_code < 400 else f" {r.text[:160]}"))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
