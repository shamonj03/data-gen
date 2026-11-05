from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from datagen.errors import RenderError
from datagen.filters import (
    FILTERS,
    ascii,
    cell_text,
    cents,
    datefmt,
    digits,
    ljust,
    money,
    num,
    rjust,
)


def test_registry_names() -> None:
    assert set(FILTERS) == {"ljust", "rjust", "num", "cents", "money", "datefmt", "digits", "ascii"}


def test_ljust_pads_and_truncates() -> None:
    assert ljust("ab", 5) == "ab   "
    assert ljust("abcdef", 3) == "abc"
    assert ljust(7, 4, "0") == "7000"
    assert ljust("", 3) == "   "


def test_rjust_pads_and_truncates() -> None:
    assert rjust("ab", 5) == "   ab"
    assert rjust("abcdef", 3) == "abc"  # keeps the first characters
    assert rjust(7, 4, "0") == "0007"


def test_just_overflow_without_truncate() -> None:
    with pytest.raises(RenderError):
        ljust("abcdef", 3, truncate=False)
    with pytest.raises(RenderError):
        rjust("abcdef", 3, truncate=False)
    assert ljust("abc", 3, truncate=False) == "abc"


def test_num_accepts_int_digit_string_and_integral_decimal() -> None:
    assert num(42, 5) == "00042"
    assert num("42", 5) == "00042"
    assert num(Decimal("42"), 5) == "00042"
    assert num(Decimal("42.00"), 5) == "00042"
    assert num(0, 3) == "000"
    assert num(12345, 5) == "12345"


@pytest.mark.parametrize("value", [123456, "123456"])
def test_num_overflow(value: object) -> None:
    with pytest.raises(RenderError):
        num(value, 5)


@pytest.mark.parametrize("value", [-1, "-1", Decimal("1.5"), 1.5, "abc", "", None, True])
def test_num_rejects(value: object) -> None:
    with pytest.raises(RenderError):
        num(value, 5)


def test_cents() -> None:
    assert cents(Decimal("12.34")) == 1234
    assert cents("12.345") == 1235  # half up
    assert cents(12) == 1200
    assert cents(0.1) == 10
    assert cents("-1.005") == -101
    assert isinstance(cents("1.00"), int)


def test_cents_rejects_garbage() -> None:
    with pytest.raises(RenderError):
        cents("abc")


def test_money() -> None:
    assert money(Decimal("1234.5")) == "1234.50"
    assert money(1234) == "1234.00"
    assert money("1.005") == "1.01"
    assert money(Decimal("1.2"), 0) == "1"
    assert money(Decimal("1.23456"), 4) == "1.2346"


def test_datefmt() -> None:
    assert datefmt(date(2026, 11, 5), "%y%m%d") == "261105"
    assert datefmt(datetime(2026, 11, 5, 13, 7), "%y%m%d%H%M") == "2611051307"
    assert datefmt("2026-11-05", "%d/%m/%Y") == "05/11/2026"
    assert datefmt("2026-11-05T13:07:00", "%H:%M") == "13:07"


def test_datefmt_rejects() -> None:
    with pytest.raises(RenderError):
        datefmt("not a date", "%y")
    with pytest.raises(RenderError):
        datefmt(5, "%y")


def test_digits() -> None:
    assert digits("(555) 123-4567") == "5551234567"
    assert digits(1234) == "1234"
    assert digits("abc") == ""


def test_ascii() -> None:
    assert ascii("José Müller") == "Jose Muller"
    assert ascii("naïve café") == "naive cafe"
    assert ascii("日本") == ""


def test_cell_text() -> None:
    assert cell_text(None) == ""
    assert cell_text(date(2026, 11, 5)) == "2026-11-05"
    assert cell_text(datetime(2026, 11, 5, 1, 2, 3)) == "2026-11-05T01:02:03"
    assert cell_text(True) == "true"
    assert cell_text(False) == "false"
    assert cell_text(0) == "0"
    assert cell_text(Decimal("1.50")) == "1.50"
