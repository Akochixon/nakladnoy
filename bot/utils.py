from __future__ import annotations

import datetime
import html
from decimal import Decimal
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Tashkent")


def esc(value) -> str:
    """HTML parse_mode uchun xavfsiz matn."""
    return html.escape(str(value)) if value is not None else "-"


def fmt_num(value) -> str:
    value = Decimal(str(value if value is not None else 0))
    if value == value.to_integral_value():
        s = f"{int(value):,}"
    else:
        s = f"{value:,.2f}"
    return s.replace(",", " ").replace(".", ",")


def today() -> datetime.date:
    return datetime.datetime.now(TZ).date()


def local(dt: datetime.datetime) -> datetime.datetime:
    return dt.astimezone(TZ) if dt else dt
