"""Purchase Order PDF (ReportLab). A4, clean, with the approval block and the audit hash."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from . import fonts
from .money import fmt_inr, fmt_unit, indian_group

INK = colors.HexColor("#0E1116")
MUTED = colors.HexColor("#5B6573")
HAIR = colors.HexColor("#D5DAE1")
MARIGOLD = colors.HexColor("#F2A93B")
TEAL = colors.HexColor("#1FA6A0")
MINT = colors.HexColor("#178A57")


def _styles():
    fonts.register()
    base = dict(fontName=fonts.SANS, textColor=INK, leading=13, fontSize=9.5)
    return {
        "h1": ParagraphStyle("h1", **{**base, "fontName": fonts.SANS_BOLD, "fontSize": 18, "leading": 22}),
        "h2": ParagraphStyle("h2", **{**base, "fontName": fonts.SANS_BOLD, "fontSize": 10.5, "leading": 14}),
        "body": ParagraphStyle("body", **base),
        "muted": ParagraphStyle("muted", **{**base, "textColor": MUTED, "fontSize": 8.5, "leading": 11}),
        "right": ParagraphStyle("right", **{**base, "alignment": TA_RIGHT}),
        "mono": ParagraphStyle("mono", **{**base, "fontName": fonts.MONO, "fontSize": 8, "leading": 10,
                                          "textColor": MUTED}),
        "label": ParagraphStyle("label", **{**base, "fontName": fonts.SANS_MED, "fontSize": 7.5,
                                           "textColor": MUTED, "leading": 10}),
    }


def _qr(url: str, size: float = 22 * mm) -> Drawing:
    w = QrCodeWidget(url)
    b = w.getBounds()
    d = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0, size / (b[3] - b[1]), 0, 0])
    d.add(w)
    return d


def render_po(path: str | Path, po: dict[str, Any]) -> Path:
    """po keys: po_number, date, order_id, buyer{name,address,gstin,plant}, vendor{name,address,gstin,contact},
    item{name,spec,drawing}, quantity, unit_paise, total_paise, terms{delivery,lead_time_days,payment_terms_days,
    needed_by}, approvals[{role,name,decision,at,mechanism}], audit_hash, audit_url, savings_paise"""
    st = _styles()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Purchase Order {po['po_number']}", author=po["buyer"]["name"],
                            subject=f"PO for {po['order_id']}", creator="Mandi on Switch")
    b, v = po["buyer"], po["vendor"]
    story: list[Any] = []

    header = Table([[
        Paragraph(f"<b>{b['name']}</b><br/><font size=8.5 color='#5B6573'>{b['address']}<br/>"
                  f"GSTIN {b['gstin']}</font>", st["body"]),
        Paragraph(f"<font size=18><b>PURCHASE ORDER</b></font><br/>"
                  f"<font name='{fonts.MONO}' size=10>{po['po_number']}</font>", st["right"]),
    ]], colWidths=[95 * mm, 79 * mm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LINEBELOW", (0, 0), (-1, 0), 2, MARIGOLD),
                                ("BOTTOMPADDING", (0, 0), (-1, 0), 8)]))
    story += [header, Spacer(0, 6 * mm)]

    meta = Table([
        [Paragraph("VENDOR", st["label"]), Paragraph("DELIVER TO", st["label"]), Paragraph("PO DETAILS", st["label"])],
        [Paragraph(f"<b>{v['name']}</b><br/>{v.get('address', '')}<br/>GSTIN {v.get('gstin', '—')}<br/>"
                   f"Attn: {v.get('contact', '—')}", st["body"]),
         Paragraph(f"<b>{b['plant']}</b><br/>{b['address']}<br/>Incoterm: {po['terms']['delivery']}", st["body"]),
         Paragraph(f"Date: <b>{po['date']}</b><br/>Requisition: {po['order_id']}<br/>"
                   f"Needed by: <b>{po['terms']['needed_by']}</b><br/>Currency: INR", st["body"])],
    ], colWidths=[62 * mm, 62 * mm, 50 * mm])
    meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [meta, Spacer(0, 7 * mm)]

    it = po["item"]
    lines = Table([
        ["#", "Item and specification", "Qty", "Unit price", "Amount"],
        ["1", Paragraph(f"<b>{it['name']}</b><br/><font size=8.5 color='#5B6573'>{it['spec']}</font>", st["body"]),
         f"{indian_group(po['quantity'])} pcs", fmt_unit(po["unit_paise"]), fmt_inr(po["total_paise"], decimals=True)],
        ["", Paragraph("<b>Total (excl. GST)</b>", st["body"]), "", "", fmt_inr(po["total_paise"], decimals=True)],
    ], colWidths=[8 * mm, 92 * mm, 24 * mm, 22 * mm, 28 * mm])
    lines.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), fonts.SANS_MED, 8), ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("FONT", (0, 1), (-1, -1), fonts.SANS, 9.5),
        ("FONT", (2, 1), (-1, -1), fonts.MONO, 9.5),
        ("FONT", (4, 2), (4, 2), fonts.MONO_BOLD, 10.5),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, HAIR), ("LINEABOVE", (0, 2), (-1, 2), 0.6, INK),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [lines, Spacer(0, 2 * mm),
              Paragraph("GST extra as applicable. Prices fixed for this order.", st["muted"]), Spacer(0, 6 * mm)]

    t = po["terms"]
    terms = Table([[Paragraph("TERMS", st["label"])],
                   [Paragraph(f"Delivery: {t['delivery']} within <b>{t['lead_time_days']} days</b> of PO date, "
                              f"no later than {t['needed_by']}.<br/>Payment: <b>{t['payment_terms_days']} days</b> "
                              f"from receipt of goods and invoice.<br/>Quality: per drawing {it.get('drawing', '')}; "
                              f"material test certificate with each lot.", st["body"])]], colWidths=[174 * mm])
    terms.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [terms, Spacer(0, 6 * mm)]

    appr_rows = [[Paragraph("APPROVALS", st["label"]), "", "", ""]]
    for a in po["approvals"]:
        appr_rows.append([Paragraph(f"<b>{a['role']}</b>", st["body"]), Paragraph(a["name"], st["body"]),
                          Paragraph(f"<font color='#178A57'><b>{a['decision']}</b></font> via {a['mechanism']}",
                                    st["body"]),
                          Paragraph(a["at"], st["mono"])])
    appr = Table(appr_rows, colWidths=[40 * mm, 34 * mm, 62 * mm, 38 * mm])
    appr.setStyle(TableStyle([("SPAN", (0, 0), (-1, 0)), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("LINEBELOW", (0, 1), (-1, -1), 0.4, HAIR), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story += [KeepTogether([appr]), Spacer(0, 8 * mm)]

    foot = Table([[
        Paragraph(f"<b>Audit trail</b> — every step of this order is recorded in a hash-chained log.<br/>"
                  f"Final event hash:<br/><font name='{fonts.MONO}' size=7.5>{po['audit_hash']}</font><br/><br/>"
                  f"<font color='#5B6573'>Generated by <b>Mandi</b> on <b>Switch</b>. Negotiated by AI agents in sealed "
                  f"Switch rooms; approved by people in Switch. Fictional company — demo document.</font>",
                  st["body"]),
        _qr(po.get("audit_url", "http://127.0.0.1:8700/")),
    ]], colWidths=[146 * mm, 28 * mm])
    foot.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEABOVE", (0, 0), (-1, 0), 0.6, HAIR),
                              ("TOPPADDING", (0, 0), (-1, -1), 6), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(foot)
    doc.build(story)
    return path
