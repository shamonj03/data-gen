"""Tests for the CSV example schemas, templates and render specs."""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from pathlib import Path

import pytest

from datagen import render, render_file

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
WITH_HEADER = EXAMPLES / "renders" / "customers_with_header.json"
NO_HEADER = EXAMPLES / "renders" / "customers_no_header.json"
HEADER_VALUES = EXAMPLES / "renders" / "transactions_header_values.json"
NOW = datetime(2026, 1, 2, 10, 0)
SEEDS = range(1, 21)

TITLES = [
    "customer_id", "First Name", "Last Name", "nickname", "ssn", "dob",
    "phone", "email", "card_number", "account_number", "branch_code", "balance",
]
DELIMITERS = [("tab", "\t"), (";", ";")]


def parse(text: str, delimiter: str = ",", quoting: int = csv.QUOTE_MINIMAL) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text), delimiter=delimiter, quoting=quoting))


def render_one(path: Path, seed: int, overrides: list[str] | None = None) -> str:
    out = render_file(path, seed=seed, now=NOW, overrides=overrides)
    assert isinstance(out, str)
    return out


@pytest.mark.parametrize("seed", SEEDS)
def test_with_header_rows(seed):
    rows = parse(render_one(WITH_HEADER, seed))
    assert rows[0] == TITLES
    assert len(rows) == 26
    assert all(len(r) == 12 for r in rows)
    body = rows[1:]
    assert body[0][0] == "00000001"
    for r in body:
        assert re.fullmatch(r"\d{8}", r[0])
        assert re.fullmatch(r"\d{4}", r[10])
        assert len(r[1]) <= 15
        assert re.fullmatch(r"[A-Za-z]{3,12}", r[3])
        assert re.fullmatch(r"\d{12}", r[9])


@pytest.mark.parametrize("seed", SEEDS)
def test_no_header_rows(seed):
    rows = parse(render_one(NO_HEADER, seed))
    assert len(rows) == 25
    assert rows[0][0] == "00000001"
    assert all(len(r) == 12 for r in rows)


@pytest.mark.parametrize("seed", SEEDS)
def test_header_values_structure(seed):
    out = render(HEADER_VALUES, seed=seed, now=NOW)
    assert list(out) == ["transactions_20260102.txt"]
    rows = parse(out["transactions_20260102.txt"], "|", csv.QUOTE_NONE)
    assert rows[0][0] == "H" and len(rows[0]) == 4
    assert rows[0][2] == "20260102"
    middle = rows[1:-1]
    assert middle
    for r in middle:
        assert r[0] == "D" and len(r) == 7
        assert len(r[3]) <= 22
    assert rows[-1] == ["T", str(len(middle))]


@pytest.mark.parametrize("name,delim", DELIMITERS)
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_delimiter_overrides_keep_field_counts(seed, name, delim):
    ov = [f"output.delimiter={name}"]
    for path, quoting in [(WITH_HEADER, csv.QUOTE_MINIMAL), (NO_HEADER, csv.QUOTE_MINIMAL)]:
        base = parse(render_one(path, seed), ",", quoting)
        alt = parse(render_one(path, seed, ov), delim, quoting)
        assert [len(r) for r in alt] == [len(r) for r in base]
    base = parse(render_one(HEADER_VALUES, seed), "|", csv.QUOTE_NONE)
    alt = parse(render_one(HEADER_VALUES, seed, ov), delim, csv.QUOTE_NONE)
    assert [len(r) for r in alt] == [len(r) for r in base]


@pytest.mark.parametrize("path", [WITH_HEADER, NO_HEADER, HEADER_VALUES])
def test_same_seed_same_text(path):
    assert render_one(path, 7) == render_one(path, 7)
