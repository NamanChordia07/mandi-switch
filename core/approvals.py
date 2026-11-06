"""Approval tiers from config/thresholds.yaml."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import thresholds


@dataclass(frozen=True)
class Tier:
    name: str
    label: str
    approvers: tuple[str, ...]
    max_paise: int | None
    max_inclusive: bool


def tiers(cfg: dict[str, Any] | None = None) -> list[Tier]:
    cfg = cfg or thresholds()
    out = []
    for t in cfg["tiers"]:
        mv = t.get("max_value")
        out.append(Tier(name=t["name"], label=t.get("label", t["name"]), approvers=tuple(t.get("approvers", [])),
                        max_paise=None if mv is None else int(mv) * 100,
                        max_inclusive=bool(t.get("max_inclusive", False))))
    return out


def tier_for(total_paise: int, cfg: dict[str, Any] | None = None) -> Tier:
    for t in tiers(cfg):
        if t.max_paise is None:
            return t
        if total_paise < t.max_paise or (t.max_inclusive and total_paise == t.max_paise):
            return t
    raise ValueError("thresholds.yaml must end with an unbounded tier")


def tier_by_name(name: str) -> Tier:
    for t in tiers():
        if t.name == name:
            return t
    raise KeyError(name)
