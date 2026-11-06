import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Tests never call the real LLM and use fixed tokens + a fixed scenario date.
os.environ["MANDI_OFFLINE_LLM"] = "1"
os.environ.setdefault("MANDI_SCENARIO_DATE", "2026-11-06")
for k, v in {"CORE_TOKEN_AGENTS": "t-agents", "CORE_TOKEN_VENDOR_DECCAN": "t-deccan",
             "CORE_TOKEN_VENDOR_GANESH": "t-ganesh", "CORE_TOKEN_VENDOR_APEX": "t-apex",
             "CORE_TOKEN_MCP_PURCHASE_DESK": "t-desk", "CORE_TOKEN_MCP_PO_ISSUER": "t-po",
             "CORE_TOKEN_UI": "t-ui", "CORE_TOKEN_DIRECTOR": "t-director"}.items():
    os.environ[k] = v
os.environ["MANDI_SCENARIO_DATE"] = "2026-11-06"


@pytest.fixture()
def fresh_db(tmp_path):
    from core import db
    db.configure(tmp_path / "test.db", fresh=True)
    yield tmp_path


@pytest.fixture(scope="session")
def seeded_quotes():
    """Generate the seed PDFs for the fixed scenario date into seed/quotes (idempotent)."""
    import subprocess
    out = ROOT / "seed" / "quotes"
    subprocess.run([sys.executable, str(ROOT / "seed" / "make_quotes.py"), "--date", "2026-11-06"], check=True,
                   capture_output=True, env={**os.environ, "PYTHONUTF8": "1"})
    return out
