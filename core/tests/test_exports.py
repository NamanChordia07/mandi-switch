"""MOCK exports: comparative statement (CSV) and SAP-style PO (JSON/CSV)."""
import csv
import io
import json
from pathlib import Path

from .test_flow import AG, DESK, OID, PO, UI, client, run_to_award  # noqa: F401  (client is a fixture)

ROOT = Path(__file__).resolve().parents[2]


def test_comparative_statement_before_po(client):  # noqa: F811
    c = client
    run_to_award(c)
    r = c.get(f"/orders/{OID}/exports/comparative-statement.csv", headers=UI)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    text = r.text
    assert "Comparative statement (MOCK)" in text and "Not an SAP or ERP integration" in text
    rows = list(csv.reader(io.StringIO(text)))
    cols = rows.index(next(x for x in rows if x and x[0] == "rank"))
    table = [dict(zip(rows[cols], x)) for x in rows[cols + 1:] if x]
    by = {t["vendor"]: t for t in table}
    assert set(by) == {"Deccan Bolt Works", "Shree Ganesh Fasteners", "Apex Precision Components", "Konkan Fasteners"}
    d = by["Deccan Bolt Works"]
    assert d["rank"] == "1" and d["quoted_unit_price"] == "39.50" and d["landed_total"] == "790000.00"
    assert d["final_offer_unit_price"] == "36.40" and d["final_offer_total"] == "728000.00" and d["awarded"] == "YES"
    assert by["Apex Precision Components"]["status"] == "Disqualified"
    assert "Expired" in by["Konkan Fasteners"]["flags"]
    assert "MOQ" in by["Shree Ganesh Fasteners"]["flags"]
    # No PO yet -> PO export is 404, and the listing has only the statement
    assert c.get(f"/orders/{OID}/exports/po-sap-style.json", headers=UI).status_code == 404
    files = c.get(f"/orders/{OID}/exports", headers=AG).json()["files"]
    assert set(files) == {"comparative_statement_csv"}


def test_sap_style_po_export_after_issue(client):  # noqa: F811
    c = client
    run_to_award(c)
    c.post(f"/orders/{OID}/endorse", headers=DESK, json={"note": "ok"})
    assert c.post(f"/orders/{OID}/issue-po", headers=PO, json={}).status_code == 200
    exp = c.get(f"/orders/{OID}/exports/po-sap-style.json", headers=UI).json()
    assert exp["_mock"] is True and "unverified" in exp["_note"]
    h, it = exp["header"], exp["items"][0]
    assert h["po_number"] == "PO-SM-2026-0147" and h["vendor_code"] == "V100231"
    assert (h["purchasing_org"], h["purchasing_group"], h["plant"], h["currency"]) == ("SM10", "P04", "CK02", "INR")
    assert (it["item_number"], it["quantity"], it["unit"], it["net_price"], it["price_unit"]) == ("00010", 20000, "PC", "36.40", 1)
    assert it["net_value"] == "728000.00" and it["delivery_date"] == "2026-12-16"
    assert exp["_field_labels"]["po_number"]["sap_style_label_unverified"] == "EBELN"
    rows = list(csv.reader(io.StringIO(c.get(f"/orders/{OID}/exports/po-sap-style.csv", headers=UI).text)))
    assert rows[0][0].startswith("# MOCK") and rows[1][0] == "po_number" and rows[3][0] == "PO-SM-2026-0147"
    files = c.get(f"/orders/{OID}/exports", headers=AG).json()["files"]
    assert set(files) == {"comparative_statement_csv", "po_json", "po_csv"}
    assert json.loads((ROOT / files["po_json"]).read_text(encoding="utf-8"))["header"]["po_number"] == "PO-SM-2026-0147"


def test_exports_switch_off(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("MANDI_EXPORTS", "0")
    run_to_award(client)
    assert client.get(f"/orders/{OID}/exports/comparative-statement.csv", headers=UI).status_code == 404
    assert client.get(f"/orders/{OID}/exports", headers=AG).status_code == 404


def test_vendor_token_cannot_read_exports(client):  # noqa: F811
    run_to_award(client)
    r = client.get(f"/orders/{OID}/exports/comparative-statement.csv", headers={"Authorization": "Bearer t-deccan"})
    assert r.status_code == 403
