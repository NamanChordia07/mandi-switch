"""Configuration loading: .env, scenario.yaml, thresholds.yaml, relative dates."""
from __future__ import annotations

import os
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = Path(os.environ.get("MANDI_STATE_DIR", ROOT / ".state"))
GENERATED_DIR = ROOT / "generated"

load_dotenv(ROOT / ".env", override=False)

_REL = re.compile(r"^T\s*([+-])\s*(\d+)\s*d$", re.IGNORECASE)


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def scenario_date() -> date:
    """The scenario's 'today' (T). MANDI_SCENARIO_DATE=YYYY-MM-DD overrides the real date."""
    raw = env("MANDI_SCENARIO_DATE").strip()
    if raw:
        return date.fromisoformat(raw)
    return date.today()


def resolve_date(value: str | date, t: date | None = None) -> date:
    """Resolve 'T+40d' / 'T-9d' / 'T' / ISO date strings against the scenario date."""
    if isinstance(value, date):
        return value
    t = t or scenario_date()
    s = str(value).strip()
    if s.upper() == "T":
        return t
    m = _REL.match(s)
    if m:
        days = int(m.group(2))
        return t + timedelta(days=days if m.group(1) == "+" else -days)
    return date.fromisoformat(s)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=1)
def scenario() -> dict[str, Any]:
    return _load_yaml(CONFIG_DIR / "scenario.yaml")


@lru_cache(maxsize=1)
def thresholds() -> dict[str, Any]:
    return _load_yaml(CONFIG_DIR / "thresholds.yaml")


def vendor_public(vendor_id: str) -> dict[str, Any]:
    """Public directory entry for a vendor (never the secret rules)."""
    return scenario()["vendors"][vendor_id]


def persona(username: str) -> dict[str, Any]:
    return scenario()["personas"].get(username, {"name": username})


def data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def generated_dir() -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    return GENERATED_DIR
