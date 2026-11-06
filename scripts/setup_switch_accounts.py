"""Create Switch accounts + per-owner registration keys through the Gateway API (idempotent).

    python scripts/setup_switch_accounts.py

Uses the admin login in .env (SWITCH_ADMIN_EMAIL / SWITCH_ADMIN_PASSWORD) to:
  1. create a registration key owned by the admin ("Mandi Exchange" — Mandi's own agents) → REGKEY_MANDI_OPS
  2. create Switch user accounts for the supplier owners (Asha, Sanjay, Karan), sign in as each, and create a
     registration key under THAT account → REGKEY_ASHA / REGKEY_SANJAY / REGKEY_KARAN.
     Switch makes the key's creator the owner of every agent registered with it, so deccan-sales is owned by
     Asha's account, not by Mandi.
Writes the keys into .env and the account logins into secrets/demo-users.local.json (both git-ignored).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import httpx  # noqa: E402
import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True)
SECRETS = Path(os.environ.get("MANDI_SECRETS_DIR", ROOT / "secrets"))
USERS = SECRETS / "demo-users.local.json"
OWNERS = {"asha": "REGKEY_ASHA", "sanjay": "REGKEY_SANJAY", "karan": "REGKEY_KARAN"}


def pw() -> str:
    a = string.ascii_letters + string.digits
    return "Mandi-" + "".join(secrets.choice(a) for _ in range(14)) + "!9"


def set_env(key: str, value: str) -> None:
    p = ROOT / ".env"
    s = p.read_text(encoding="utf-8")
    s = re.sub(rf"^{key}=.*$", f"{key}={value}", s, flags=re.M) if re.search(rf"^{key}=", s, re.M) else s + f"\n{key}={value}\n"
    p.write_text(s, encoding="utf-8")


def login(base: str, email: str, password: str) -> httpx.Client:
    c = httpx.Client(base_url=base, timeout=30)
    r = c.post("/gateway/auth/login", json={"email": email, "password": password})
    if r.status_code >= 400:
        raise SystemExit(f"login failed for {email}: {r.status_code} {r.text[:200]}")
    return c


def ensure_key(c: httpx.Client, label: str) -> str:
    r = c.post("/gateway/api-keys", json={"label": label})
    if r.status_code >= 400:
        raise SystemExit(f"create key '{label}' failed: {r.status_code} {r.text[:200]}")
    return r.json()["key"]


def main() -> int:
    base = os.environ.get("SWITCH_BASE_URL", "").rstrip("/")
    email, password = os.environ.get("SWITCH_ADMIN_EMAIL", ""), os.environ.get("SWITCH_ADMIN_PASSWORD", "")
    if not (base and email and password):
        print("Set SWITCH_BASE_URL, SWITCH_ADMIN_EMAIL, SWITCH_ADMIN_PASSWORD in .env")
        return 1
    sc = yaml.safe_load((ROOT / "config" / "scenario.yaml").read_text(encoding="utf-8"))
    store = json.loads(USERS.read_text(encoding="utf-8")) if USERS.exists() else {}
    admin = login(base, email, password)
    print(f"✓ signed in to the Gateway at {base} as the server admin")
    if not os.environ.get("REGKEY_MANDI_OPS"):
        set_env("REGKEY_MANDI_OPS", ensure_key(admin, "mandi-ops (Mandi Exchange agents)"))
        print("✓ registration key for Mandi Exchange (admin) → REGKEY_MANDI_OPS")
    else:
        print("✓ REGKEY_MANDI_OPS already set")
    for persona, env_key in OWNERS.items():
        info = sc["personas"][persona]
        rec = store.setdefault(persona, {})
        sw = rec.setdefault("switch", {"email": f"{persona}@mandi.example", "password": pw()})
        r = admin.post("/gateway/users", json={"name": info["name"], "email": sw["email"], "password": sw["password"],
                                               "role": "user"})
        if r.status_code == 409:
            status = "exists"
        elif r.status_code >= 400:
            print(f"✗ create Switch user {persona}: {r.status_code} {r.text[:200]}")
            continue
        else:
            status = "created"
            sw["id"] = r.json().get("id")
        USERS.parent.mkdir(exist_ok=True)
        USERS.write_text(json.dumps(store, indent=2), encoding="utf-8")
        if os.environ.get(env_key):
            print(f"✓ {info['name']}: Switch account {status}; {env_key} already set")
            continue
        try:
            uc = login(base, sw["email"], sw["password"])
        except SystemExit as exc:
            print(f"✗ {exc}")
            continue
        set_env(env_key, ensure_key(uc, f"{persona} — {info['title']}"))
        print(f"✓ {info['name']}: Switch account {status}; registration key created under their account → {env_key}")
    print(f"\nLogins saved in {USERS.relative_to(ROOT) if USERS.is_relative_to(ROOT) else USERS} (git-ignored).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
