"""Create the demo personas as Mattermost users (idempotent) and add them to the team.

    python scripts/create_personas.py

Needs MATTERMOST_URL, MATTERMOST_ADMIN_USER, MATTERMOST_ADMIN_PASSWORD, MATTERMOST_TEAM in .env (Switch Console:
server Home → Messaging apps → Mattermost row → "Sign-in details…"). Passwords are generated once and stored in
secrets/demo-users.local.json (git-ignored) — never printed in full.

Fictional people only. Each persona later links its Mattermost account to Switch (docs/manual-setup.md).
"""
from __future__ import annotations

import json
import os
import secrets
import string
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402
import yaml  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)
OUT = ROOT / "secrets" / "demo-users.local.json"


def pw() -> str:
    alphabet = string.ascii_letters + string.digits
    return "Mandi-" + "".join(secrets.choice(alphabet) for _ in range(14)) + "!9"


def docker_exe() -> str:
    import shutil
    return shutil.which("docker") or str(Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe"))


def via_mmctl(container: str, team: str, url: str) -> int:
    """Switch Console's bundled Mattermost runs in local mode: create users with `mmctl --local` inside the
    container (no admin password needed)."""
    import subprocess
    sc = yaml.safe_load((ROOT / "config" / "scenario.yaml").read_text(encoding="utf-8"))
    store = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}

    def mm(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run([docker_exe(), "exec", container, "mmctl", "--local", *args],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
    for username, p in sc["personas"].items():
        uname = os.environ.get(f"MM_USER_{username.upper()}", username)
        first, last = p["name"].split(" ", 1)
        rec = store.setdefault(username, {})
        rec.setdefault("username", uname)
        rec.setdefault("password", pw())
        rec.setdefault("email", f"{uname}@mandi.example")
        r = mm("user", "create", "--username", uname, "--email", rec["email"], "--password", rec["password"],
               "--firstname", first, "--lastname", last, "--nickname", p["title"][:60])
        status = "created" if r.returncode == 0 else ("exists" if "already" in (r.stdout + r.stderr).lower()
                                                       or "exists" in (r.stdout + r.stderr).lower() else "FAILED")
        if status == "FAILED":
            print(f"  {uname:<8} FAILED {(r.stderr or r.stdout).strip()[:200]}")
            continue
        mm("team", "users", "add", team, uname)
        rec.update({"name": p["name"], "title": p["title"], "login_url": f"{url}/login"})
        print(f"  {uname:<8} {status:<8} {p['name']} — {p['title']}")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(store, indent=2), encoding="utf-8")
    print(f"\nLogins saved to {OUT} (git-ignored). Mattermost: {url}")
    return 0


def main() -> int:
    url = os.environ.get("MATTERMOST_URL", "http://127.0.0.1:8065").rstrip("/")
    if os.environ.get("MATTERMOST_CONTAINER"):
        return via_mmctl(os.environ["MATTERMOST_CONTAINER"], os.environ.get("MATTERMOST_TEAM", "switch"), url)
    admin, apw, team = (os.environ.get(k, "") for k in ("MATTERMOST_ADMIN_USER", "MATTERMOST_ADMIN_PASSWORD",
                                                         "MATTERMOST_TEAM"))
    if not (admin and apw and team):
        print("Set MATTERMOST_ADMIN_USER, MATTERMOST_ADMIN_PASSWORD and MATTERMOST_TEAM in .env first.")
        return 1
    sc = yaml.safe_load((ROOT / "config" / "scenario.yaml").read_text(encoding="utf-8"))
    store = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    c = httpx.Client(base_url=f"{url}/api/v4", timeout=20)
    r = c.post("/users/login", json={"login_id": admin, "password": apw})
    if r.status_code >= 400:
        print(f"Mattermost admin login failed: {r.status_code} {r.text[:200]}")
        return 1
    c.headers["Authorization"] = f"Bearer {r.headers['Token']}"
    t = c.get(f"/teams/name/{team}")
    if t.status_code >= 400:
        print(f"Team '{team}' not found: {t.text[:200]}")
        return 1
    team_id = t.json()["id"]
    for username, p in sc["personas"].items():
        uname = os.environ.get(f"MM_USER_{username.upper()}", username)
        first, last = p["name"].split(" ", 1)
        rec = store.get(username) or {"username": uname, "password": pw(), "email": f"{uname}@mandi.example"}
        got = c.get(f"/users/username/{uname}")
        if got.status_code == 200:
            uid = got.json()["id"]
            status = "exists"
        else:
            cr = c.post("/users", json={"email": rec["email"], "username": uname, "password": rec["password"],
                                        "first_name": first, "last_name": last, "nickname": p["title"][:60]})
            if cr.status_code >= 400:
                print(f"  {uname:<8} FAILED {cr.status_code} {cr.text[:160]}")
                continue
            uid = cr.json()["id"]
            status = "created"
        c.post(f"/teams/{team_id}/members", json={"team_id": team_id, "user_id": uid})
        rec.update({"id": uid, "name": p["name"], "title": p["title"], "login_url": f"{url}/login"})
        store[username] = rec
        print(f"  {uname:<8} {status:<8} {p['name']} — {p['title']}")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(store, indent=2), encoding="utf-8")
    print(f"\nLogins saved to {OUT.relative_to(ROOT)} (git-ignored). Mattermost: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
