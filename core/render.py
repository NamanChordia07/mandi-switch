"""Render a quote page as PNG with hidden / injected text revealed (for the Control Room's injection panel)."""
from __future__ import annotations

import re
from pathlib import Path

VERMILION = (0.95, 0.33, 0.36)


def render_page(pdf_path: Path, page_no: int, spans: list[str], dpi: int = 110) -> bytes:
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    if not 1 <= page_no <= len(doc):
        raise ValueError("page out of range")
    page = doc[page_no - 1]
    marks: list = []
    # 1) hidden text: tiny or white spans -> outline + make them readable in a callout
    for b in page.get_text("dict")["blocks"]:
        for line in b.get("lines", []):
            for s in line["spans"]:
                t = s["text"].strip()
                if not t:
                    continue
                if s["size"] < 3 or (s["color"] == 0xFFFFFF and not _on_dark(page, s["bbox"])):
                    marks.append(("hidden", pymupdf.Rect(s["bbox"]), t))
    # 2) visible text matching the injection spans
    for sp in spans[:4]:
        words = re.sub(r"\s+", " ", sp).strip().split(" ")
        for probe in (" ".join(words[:6]), " ".join(words[-6:])):
            if len(probe) > 12:
                for r in page.search_for(probe):
                    marks.append(("visible", r, probe))
    shape = page.new_shape()
    for kind, r, _ in marks:
        rr = pymupdf.Rect(r.x0 - 3, r.y0 - 3, r.x1 + 3, r.y1 + 3)
        shape.draw_rect(rr)
        shape.finish(color=VERMILION, fill=VERMILION, fill_opacity=0.12, width=1.4)
    shape.commit()
    hidden = [m for m in marks if m[0] == "hidden"]
    if hidden:
        r = hidden[0][1]
        text = " ".join(m[2] for m in hidden)
        top = max(40, r.y0 - 84)
        box = pymupdf.Rect(36, top, page.rect.width - 36, top + 60)
        page.draw_rect(box, color=VERMILION, fill=(1, 0.97, 0.97), width=1.2)
        page.insert_textbox(box + (8, 6, -8, -6), "Revealed by Mandi: hidden 1-pt white text at the bottom of this page:\n" + text,
                            fontsize=8.2, color=(0.6, 0.08, 0.1))
        page.draw_line(pymupdf.Point(box.x0 + 40, box.y1), pymupdf.Point(r.x0 + 20, r.y0 - 3), color=VERMILION, width=1)
    pix = page.get_pixmap(dpi=dpi)
    return pix.tobytes("png")


def _on_dark(page, bbox) -> bool:
    import pymupdf
    b = pymupdf.Rect(bbox)
    for d in page.get_drawings():
        f = d.get("fill")
        if f is not None and (0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]) < 0.6 and pymupdf.Rect(d["rect"]).intersects(b):
            return True
    return False
