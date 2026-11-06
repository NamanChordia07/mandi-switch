"""Money helpers.

All money inside Mandi is an integer number of **paise** (1 rupee = 100 paise), so
₹36.40 is stored as 3640. Floats never touch money. Formatting happens only at the edges.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

RUPEE = "₹"


def to_paise(value: str | int | float | Decimal) -> int:
    """Convert a rupee amount ("36.40", "₹7,28,000", 36.4, Decimal) to integer paise."""
    if isinstance(value, bool):
        raise ValueError("bool is not money")
    if isinstance(value, int):
        return value * 100
    if isinstance(value, float):
        value = repr(value)
    if isinstance(value, str):
        cleaned = value.replace(RUPEE, "").replace("Rs.", "").replace("Rs", "").replace("INR", "")
        cleaned = cleaned.replace(",", "").replace("/-", "").strip()
        if not cleaned:
            raise ValueError("empty amount")
        value = cleaned
    try:
        d = Decimal(value)
    except InvalidOperation as exc:  # pragma: no cover - defensive
        raise ValueError(f"not a number: {value!r}") from exc
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def indian_group(n: int) -> str:
    """Group an integer the Indian way: 728000 -> '7,28,000', 1017000 -> '10,17,000'."""
    sign = "-" if n < 0 else ""
    s = str(abs(n))
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return sign + ",".join(parts) + "," + tail


def fmt_inr(paise: int, *, decimals: bool | None = None) -> str:
    """Format paise as rupees with Indian grouping.

    decimals=None  -> show paise only when non-zero (₹7,28,000 but ₹36.40)
    decimals=True  -> always two decimals (₹36.40, ₹38.00)
    decimals=False -> whole rupees, rounded half-up
    """
    if decimals is None:
        decimals = paise % 100 != 0
    sign = "-" if paise < 0 else ""
    p = abs(paise)
    if decimals:
        return f"{sign}{RUPEE}{indian_group(p // 100)}.{p % 100:02d}"
    rupees = (p + 50) // 100
    return f"{sign}{RUPEE}{indian_group(rupees)}"


def fmt_unit(paise: int) -> str:
    """Unit prices always carry two decimals: ₹36.40, ₹38.00."""
    return fmt_inr(paise, decimals=True)


def pct(part: int, whole: int, places: int = 2) -> str:
    """Percentage string, e.g. pct(62000_00, 790000_00) -> '7.85%'."""
    if whole == 0:
        return "0%"
    q = (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return f"{q}%"


def round_down_to(paise: int, step: int = 10) -> int:
    """Round down to a multiple of `step` paise (default ₹0.10)."""
    return (paise // step) * step
