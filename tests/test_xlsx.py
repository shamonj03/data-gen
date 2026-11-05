from __future__ import annotations

from datetime import datetime
from io import BytesIO

import pytest
from openpyxl import load_workbook

from datagen.errors import RenderError
from datagen.xlsx import text_to_xlsx

NOW = datetime(2026, 1, 2, 3, 4, 5)


def conv(text, *, delimiter=",", quoting="minimal", sheet_name="Sheet1"):
    return text_to_xlsx(
        text, delimiter=delimiter, quoting=quoting, sheet_name=sheet_name, now=NOW
    )


def load(b):
    return load_workbook(BytesIO(b))


def rows(ws):
    return [[c.value for c in row] for row in ws.iter_rows()]


def test_one_sheet_with_title():
    wb = load(conv("a,b\n", sheet_name="Payments"))
    assert wb.sheetnames == ["Payments"]


def test_comma_quoted_value_is_one_cell():
    ws = load(conv('a,"b,c",d\n')).active
    assert rows(ws) == [["a", "b,c", "d"]]


def test_pipe_quoting_none():
    ws = load(conv('a|"b|c\n1|2\n', delimiter="|", quoting="none")).active
    assert ws.cell(row=1, column=2).value == '"b'
    assert [ws.cell(row=1, column=c).value for c in (1, 3)] == ["a", "c"]
    assert [ws.cell(row=2, column=c).value for c in (1, 2, 3)] == ["1", "2", None]


def test_tab():
    ws = load(conv("a\tb\tc\n1\t2\t3\n", delimiter="\t")).active
    assert rows(ws) == [["a", "b", "c"], ["1", "2", "3"]]


def test_ragged_rows_keep_lengths():
    ws = load(conv("a,b,c,d\n1,2,3,4,5,6,7\nx,y\n")).active
    assert ws.max_column == 7
    assert [ws.cell(row=1, column=c).value for c in range(1, 8)] == [
        "a", "b", "c", "d", None, None, None,
    ]
    assert [ws.cell(row=2, column=c).value for c in range(1, 8)] == list("1234567")
    assert [ws.cell(row=3, column=c).value for c in range(1, 8)] == [
        "x", "y", None, None, None, None, None,
    ]


@pytest.mark.parametrize(
    "value", ["011000015", "00000001", "4111111111111111", "2026-01-02"]
)
def test_values_stay_text(value):
    cell = load(conv(f"{value},x\n")).active["A1"]
    assert cell.value == value
    assert isinstance(cell.value, str)
    assert cell.number_format == "@"
    assert cell.data_type == "s"


def test_formula_like_value_is_text():
    cell = load(conv("=1+1,b\n")).active["A1"]
    assert cell.value == "=1+1"
    assert cell.data_type == "s"


def test_empty_value_is_empty_cell():
    ws = load(conv("a,,c\n")).active
    assert ws["B1"].value is None
    assert ws["A1"].value == "a"
    assert ws["C1"].value == "c"


def test_too_long_value_names_row_and_column():
    with pytest.raises(RenderError) as ei:
        conv("a,b\nc," + "x" * 32_768 + "\n")
    msg = str(ei.value)
    assert "row 2" in msg and "column 2" in msg


def test_max_length_value_ok():
    cell = load(conv("x" * 32_767 + "\n")).active["A1"]
    assert len(cell.value) == 32_767


def test_too_many_columns():
    with pytest.raises(RenderError):
        conv(",".join(["a"] * 16_385) + "\n")


def test_created_and_modified():
    wb = load(conv("a\n"))
    assert wb.properties.created == NOW
    assert wb.properties.modified == NOW
