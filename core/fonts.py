"""Register bundled Noto Sans fonts (SIL OFL) with ReportLab so ₹ renders in PDFs."""
from __future__ import annotations

from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_done = False

SANS = "NotoSans"
SANS_BOLD = "NotoSans-Bold"
SANS_MED = "NotoSans-Medium"
MONO = "NotoSansMono"
MONO_BOLD = "NotoSansMono-Bold"


def register() -> None:
    global _done
    if _done:
        return
    pdfmetrics.registerFont(TTFont(SANS, str(FONT_DIR / "NotoSans-Regular.ttf")))
    pdfmetrics.registerFont(TTFont(SANS_BOLD, str(FONT_DIR / "NotoSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont(SANS_MED, str(FONT_DIR / "NotoSans-Medium.ttf")))
    pdfmetrics.registerFont(TTFont(MONO, str(FONT_DIR / "NotoSansMono-Regular.ttf")))
    pdfmetrics.registerFont(TTFont(MONO_BOLD, str(FONT_DIR / "NotoSansMono-Bold.ttf")))
    pdfmetrics.registerFontFamily(SANS, normal=SANS, bold=SANS_BOLD, italic=SANS, boldItalic=SANS_BOLD)
    pdfmetrics.registerFontFamily(MONO, normal=MONO, bold=MONO_BOLD, italic=MONO, boldItalic=MONO_BOLD)
    _done = True
