"""Tests for the XLSX example render specs and the multi-file bundle."""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from pathlib import Path

import openpyxl
import pytest

import datagen

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
RENDERS = EXAMPLES / "renders"
CUSTOMERS_XLSX = RENDERS / "customers_xlsx.json"
CUSTOMERS_BUNDLE = RENDERS / "customers_bundle.json"
WITH_HEADER = RENDERS / "customers_with_header.json"
NO_HEADER = RENDERS / "customers_no_header.json"
HEADER_VALUES = RENDERS / "transactions_header_values.json"
NOW = datetime(2026, 1, 2, 10, 0)
SEEDS = [1, 2, 3]


def schema_field_names() -> list[str]:
    raw = json.loads((EXAMPLES / "schemas" / "customers.json").read_text(encoding="utf-8"))
    return list(raw["data"]["customers"]["fields"])


def workbook_rows(path: Path) -> list[list[str]]:
    """Every row as strings: None becomes "", trailing empty cells are dropped."""
    wb = openpyxl.load_workbook(path)
    ws = wb.worksheets[0]
    rows = []
    for raw_row in ws.iter_rows(values_only=True):
        cells = list(raw_row)
        while cells and cells[-1] is None:
            cells.pop()
        rows.append(["" if c is None else str(c) for c in cells])
    return rows


def parse(text: str, delimiter: str = ",", quoting: int = csv.QUOTE_MINIMAL) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text), delimiter=delimiter, quoting=quoting))


def test_customers_xlsx_single_sheet(tmp_path):
    datagen.write(CUSTOMERS_XLSX, tmp_path, seed=1, now=NOW)
    path = tmp_path / "customers.xlsx"
    assert path.exists()

    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["Customers"]
    ws = wb["Customers"]

    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    assert workbook_rows(path)[0] == schema_field_names()
    assert len(rows) == 26

    for row in rows:
        for value in row:
            if value not in (None, ""):
                assert isinstance(value, str), value

    body = rows[1:]
    id_index = schema_field_names().index("customer_id")
    branch_index = schema_field_names().index("branch_code")
    assert body[0][id_index] == "00000001"
    for r in body:
        assert re.fullmatch(r"\d{8}", r[id_index]), r[id_index]
        assert re.fullmatch(r"\d{4}", r[branch_index]), r[branch_index]


@pytest.mark.parametrize("spec", [WITH_HEADER, NO_HEADER, HEADER_VALUES], ids=lambda p: p.name)
@pytest.mark.parametrize("seed", SEEDS)
def test_csv_specs_convert_row_for_row(tmp_path, spec, seed):
    fmt = spec.name
    if spec == HEADER_VALUES:
        delimiter, quoting = "|", csv.QUOTE_NONE
    else:
        delimiter, quoting = ",", csv.QUOTE_MINIMAL

    text = datagen.render_file(spec, seed=seed, now=NOW)
    assert isinstance(text, str), fmt

    xlsx_path = tmp_path / "x.xlsx"
    result = datagen.render_file(spec, seed=seed, now=NOW, out=xlsx_path)
    assert isinstance(result, bytes)
    assert xlsx_path.exists()

    expected = parse(text, delimiter, quoting)
    assert workbook_rows(xlsx_path) == expected


def test_bundle_writes_three_files_with_same_customer_ids(tmp_path):
    paths = datagen.write(CUSTOMERS_BUNDLE, tmp_path, seed=7, now=NOW)
    assert len(paths) == 3
    assert sorted(p.name for p in paths) == ["customers.csv", "customers.txt", "customers.xlsx"]
    by_name = {p.name: p for p in paths}

    csv_text = by_name["customers.csv"].read_text(encoding="utf-8")
    csv_ids = [r[0] for r in parse(csv_text)[1:]]

    txt_text = by_name["customers.txt"].read_text(encoding="utf-8")
    txt_rows = parse(txt_text, "|", csv.QUOTE_NONE)
    txt_ids = [r[0] for r in txt_rows]

    xlsx_ids = [r[0] for r in workbook_rows(by_name["customers.xlsx"])[1:]]

    assert len(csv_ids) == 25
    assert csv_ids == txt_ids == xlsx_ids
