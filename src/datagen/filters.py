"""Jinja filters for fixed-width and delimited output, plus `cell_text`."""
from __future__ import annotations

import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Callable

from datagen.errors import RenderError


def cell_text(v: Any) -> str:
    """Text form of a cell value: None -> "", dates ISO, bools true/false."""
    if v is None:
        return ""
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _fit(value: Any, width: int, fill: str, truncate: bool, right: bool) -> str:
    text = str(value)
    if len(text) > width:
        if not truncate:
            raise RenderError(f"value {text!r} is {len(text)} chars, wider than {width}")
        text = text[:width]
    return text.rjust(width, fill) if right else text.ljust(width, fill)


def ljust(value: Any, width: int, fill: str = " ", truncate: bool = True) -> str:
    """Truncate to `width`, then pad on the right."""
    return _fit(value, width, fill, truncate, right=False)


def rjust(value: Any, width: int, fill: str = " ", truncate: bool = True) -> str:
    """Truncate to `width`, then pad on the left."""
    return _fit(value, width, fill, truncate, right=True)


def num(value: Any, width: int) -> str:
    """Zero-pad a non-negative integer on the left to `width` digits."""
    if isinstance(value, bool):
        raise RenderError(f"num: {value!r} is not an integer")
    if isinstance(value, int):
        n = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        n = int(value)
    elif isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value():
        n = int(value)
    else:
        raise RenderError(f"num: {value!r} is not a non-negative integer")
    if n < 0:
        raise RenderError(f"num: {value!r} is negative")
    text = str(n)
    if len(text) > width:
        raise RenderError(f"num: {value!r} does not fit in {width} digits")
    return text.rjust(width, "0")


def _decimal(value: Any, name: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise RenderError(f"{name}: {value!r} is not a number") from None
    if not d.is_finite():
        raise RenderError(f"{name}: {value!r} is not a finite number")
    return d


def cents(value: Any) -> int:
    """Amount in units -> integer cents, rounded half up."""
    d = _decimal(value, "cents").quantize(Decimal("0.01"), ROUND_HALF_UP)
    return int(d * 100)


def money(value: Any, places: int = 2) -> str:
    """Format as a fixed-point decimal string, e.g. "1234.50"."""
    d = _decimal(value, "money").quantize(Decimal(1).scaleb(-places), ROUND_HALF_UP)
    return f"{d:.{places}f}"


def datefmt(value: Any, fmt: str) -> str:
    """strftime a date, datetime or ISO string."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise RenderError(f"datefmt: {value!r} is not an ISO date") from None
    if not isinstance(value, date):
        raise RenderError(f"datefmt: {value!r} is not a date")
    return value.strftime(fmt)


def digits(value: Any) -> str:
    """Keep the characters 0-9 only."""
    return "".join(c for c in str(value) if "0" <= c <= "9")


def ascii(value: Any) -> str:  # noqa: A001 - filter name is part of the template API
    """NFKD-normalise and drop non-ASCII characters."""
    return unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")


FILTERS: dict[str, Callable[..., Any]] = {
    "ljust": ljust,
    "rjust": rjust,
    "num": num,
    "cents": cents,
    "money": money,
    "datefmt": datefmt,
    "digits": digits,
    "ascii": ascii,
}
