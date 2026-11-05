from __future__ import annotations

import csv
import io
from datetime import datetime
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl import Workbook
from openpyxl.writer.excel import ExcelWriter

from datagen.errors import RenderError

MAX_ROWS = 1_048_576
MAX_COLS = 16_384
MAX_CELL_CHARS = 32_767


def text_to_xlsx(
    text: str, *, delimiter: str, quoting: str, sheet_name: str, now: datetime
) -> bytes:
    """Convert delimited text to a one-sheet XLSX where every value is a text cell."""
    q = csv.QUOTE_NONE if quoting == "none" else csv.QUOTE_MINIMAL
    reader = csv.reader(io.StringIO(text), delimiter=delimiter, quoting=q)

    wb = Workbook()
    ws = wb.active
    try:
        ws.title = sheet_name
    except ValueError as exc:
        raise RenderError(f"invalid sheet name {sheet_name!r}: {exc}") from exc

    for r, row in enumerate(reader, start=1):
        if r > MAX_ROWS:
            raise RenderError(f"too many rows: XLSX allows at most {MAX_ROWS}", line=r)
        if len(row) > MAX_COLS:
            raise RenderError(
                f"too many columns ({len(row)}): XLSX allows at most {MAX_COLS}", line=r
            )
        for c, value in enumerate(row, start=1):
            if value == "":
                continue
            if len(value) > MAX_CELL_CHARS:
                raise RenderError(
                    f"value at row {r}, column {c} is {len(value)} characters; "
                    f"XLSX allows at most {MAX_CELL_CHARS}",
                    line=r,
                )
            cell = ws.cell(row=r, column=c, value=value)
            cell.data_type = "s"
            cell.number_format = "@"

    wb.properties.created = now
    wb.properties.modified = now
    buf = io.BytesIO()
    # wb.save() overwrites `modified` with the wall clock; ExcelWriter keeps it deterministic.
    with ZipFile(buf, "w", ZIP_DEFLATED, allowZip64=True) as archive:
        ExcelWriter(wb, archive).save()
    return buf.getvalue()
