"""Create .env from .env.example, generating random Core tokens.

Usage:  python scripts/init_env.py            # create .env if missing, fill empty tokens
        python scripts/init_env.py --force    # regenerate all CORE_TOKEN_* values

Existing non-empty values in .env are kept, so it's safe to re-run.
"""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / ".env.example"
TARGET = ROOT / ".env"


def parse(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip()
    return values


def main() -> int:
    force = "--force" in sys.argv
    existing = parse(TARGET)
    out_lines: list[str] = []
    generated = 0
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            out_lines.append(line)
            continue
        key, default = line.split("=", 1)
        key = key.strip()
        value = existing.get(key, default.strip())
        if key.startswith("CORE_TOKEN_") and (force or not value):
            value = "mandi_" + secrets.token_urlsafe(24)
            generated += 1
        out_lines.append(f"{key}={value}")
    # keep any extra keys the user added to .env that aren't in the example
    known = {l.split("=", 1)[0].strip() for l in out_lines if "=" in l and not l.lstrip().startswith("#")}
    extras = [f"{k}={v}" for k, v in existing.items() if k not in known]
    if extras:
        out_lines += ["", "# ---------- extra (kept from previous .env) ----------", *extras]
    TARGET.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"wrote {TARGET} ({generated} token(s) generated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
