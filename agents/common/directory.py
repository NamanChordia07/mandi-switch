"""Who is who in Switch: room ids, agent ids and persona participant ids (from secrets/switch-ids.local.json)."""
from __future__ import annotations

from typing import Any, Optional

from .runtime import switch_ids


class Directory:
    def __init__(self, data: dict[str, Any] | None = None):
        self.reload(data)

    def reload(self, data: dict[str, Any] | None = None) -> None:
        d = data if data is not None else switch_ids()
        self.rooms: dict[str, str] = d.get("rooms", {})                 # key -> room_id
        self.people: dict[str, list[str]] = {k: (v if isinstance(v, list) else [v])
                                             for k, v in d.get("people", {}).items()}  # persona -> [participant ids]
        self.agents: dict[str, dict[str, Any]] = d.get("agents", {})    # name -> {id, participant_id?}
        self.order_id: str = d.get("order_id", "")
        import os
        self.usernames: dict[str, str] = {p: os.environ.get(f"MM_USER_{p.upper()}", p).lower()
                                          for p in ("rohan", "meera", "vikram", "asha", "sanjay", "karan")}

    def room(self, key: str) -> str:
        return self.rooms.get(key, "")

    def room_key(self, room_id: str) -> str:
        for k, v in self.rooms.items():
            if v == room_id:
                return k
        return ""

    def persona_of(self, participant_id: str, sender_name: str = "") -> Optional[str]:
        """Which demo persona sent this? Matches the participant id first; otherwise Switch's sender_name, which
        for a Mattermost person is their (unique) Mattermost username as reported by Switch — not message text.
        (Live finding: list_participants returns user UUIDs, while events carry '@switch-mattermost-…' ids.)"""
        for persona, ids in self.people.items():
            if participant_id and participant_id in ids:
                return persona
        if sender_name and not self.agent_of(participant_id, sender_name):
            name = sender_name.strip().lstrip("@").lower()
            for persona in self.people or self.usernames:
                if name in (persona, self.usernames.get(persona, persona)):
                    ids = self.people.setdefault(persona, [])
                    if participant_id and participant_id not in ids:
                        ids.append(participant_id)          # learn the event-side id
                    return persona
        return None

    def agent_of(self, participant_id: str, sender_name: str = "") -> Optional[str]:
        for name, a in self.agents.items():
            if participant_id and participant_id in (a.get("participant_ids") or []):
                return name
        # Fallback: Switch shows an agent's name as its sender_name; match exactly on registered names.
        if sender_name and sender_name in self.agents:
            return sender_name
        for name, a in self.agents.items():
            if sender_name and a.get("display_name") == sender_name:
                return name
        return None

    def is_agent(self, participant_id: str, sender_name: str = "") -> bool:
        if self.agent_of(participant_id, sender_name):
            return True
        # Last resort (documented id shape, used only for display classification):
        return ":" in participant_id and participant_id.split(":")[0].startswith("@switch-agent-")

    def kind(self, participant_id: str, sender_name: str = "") -> str:
        if participant_id.split(":")[0] in ("@switch-admin", "@switch-bridge"):
            return "switch"
        if self.is_agent(participant_id, sender_name):
            return "agent"
        return "human"
