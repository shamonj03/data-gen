"""Independent NACHA file checker for the ACH examples.

Written from the NACHA record layouts. It deliberately does not import ``datagen.formats.ach``, so a bug in
the helpers cannot hide itself. Field positions below are 1-based, as in the NACHA spec.
"""
from __future__ import annotations

from datagen.safe import is_valid_aba

WIDTH = 94


def _f(line: str, first: int, last: int) -> str:
    """Characters ``first..last`` (1-based, inclusive)."""
    return line[first - 1 : last]


def _n(line: str, first: int, last: int) -> int:
    text = _f(line, first, last)
    assert text.isascii() and text.isdigit(), f"non-numeric field {first}-{last}: {text!r} in {line!r}"
    return int(text)


def _amounts(codes_and_cents: list[tuple[str, int]]) -> tuple[int, int]:
    """(debit, credit) cents. Debit: code ends 5-9; credit: 0-4; prenotes (x3, x8) count 0."""
    debit = credit = 0
    for code, cents in codes_and_cents:
        last = code[-1]
        if last in "38":
            continue
        if last in "56789":
            debit += cents
        else:
            credit += cents
    return debit, credit


def check(text: str) -> list[dict]:
    """Validate a NACHA file and return its parsed entries.

    Each entry is a dict: batch (1-based), trace (15 digits), transaction_code, routing_number,
    account_number, amount_cents, individual_id, name, addenda (count).
    """
    assert "\r\n" in text, "lines must end with CRLF"
    lines = text.split("\r\n")
    if lines and lines[-1] == "":
        lines.pop()
    assert lines, "empty file"
    for i, line in enumerate(lines, 1):
        assert len(line) == WIDTH, f"line {i}: expected {WIDTH} chars, got {len(line)}"
        assert line.isascii(), f"line {i}: non-ASCII"
    assert len(lines) % 10 == 0, f"{len(lines)} lines is not a multiple of 10"

    # Padding lines (all 9s) may only follow the 9 record.
    nines = "9" * WIDTH
    file_end = len(lines)
    while file_end > 0 and lines[file_end - 1] == nines:
        file_end -= 1
    body = lines[:file_end]
    assert body, "no records"
    assert body[0][0] == "1", "first record must be type 1"
    assert body[-1][0] == "9", "last record before padding must be type 9"
    for i, line in enumerate(body, 1):
        assert line != nines, f"line {i}: padding line before the 9 record"

    entries: list[dict] = []
    batches: list[dict] = []  # per batch: count, hash, debit, credit
    batch: dict | None = None
    entry: dict | None = None
    expect_addenda_seq = 0
    state = "start"  # start -> in_file -> in_batch -> in_file ... -> done

    for i, line in enumerate(body, 1):
        rtype = line[0]
        if rtype == "1":
            assert state == "start", f"line {i}: unexpected 1 record"
            assert _f(line, 2, 3) == "01"
            assert _f(line, 34, 40) == "A094101", f"line {i}: bad file id/format fields"
            state = "in_file"
        elif rtype == "5":
            assert state == "in_file", f"line {i}: 5 record outside a file or inside a batch"
            batch = {
                "no": len(batches) + 1,
                "scc": _f(line, 2, 4),
                "company_id": _f(line, 41, 50),
                "odfi": _f(line, 80, 87),
                "entries": [],
                "addenda": 0,
            }
            assert _n(line, 88, 94) == batch["no"], f"line {i}: batch number out of sequence"
            assert _f(line, 79, 79) == "1"
            state = "in_batch"
            entry = None
        elif rtype == "6":
            assert state == "in_batch" and batch is not None, f"line {i}: 6 record outside a batch"
            assert _f(line, 79, 79) in "01"
            assert _f(line, 80, 87) == batch["odfi"], f"line {i}: trace ODFI differs from batch ODFI"
            entry = {
                "batch": batch["no"],
                "trace": _f(line, 80, 94),
                "transaction_code": _f(line, 2, 3),
                "routing_number": _f(line, 4, 12),
                "account_number": _f(line, 13, 29).strip(),
                "amount_cents": _n(line, 30, 39),
                "individual_id": _f(line, 40, 54).strip(),
                "name": _f(line, 55, 76).strip(),
                "addenda": 0,
                "_indicator": int(_f(line, 79, 79)),
            }
            assert is_valid_aba(entry["routing_number"]), f"line {i}: bad ABA checksum {entry['routing_number']}"
            batch["entries"].append(entry)
            entries.append(entry)
            expect_addenda_seq = 0
        elif rtype == "7":
            assert state == "in_batch" and entry is not None, f"line {i}: 7 record without a 6 record"
            assert _f(line, 2, 3) == "05"
            expect_addenda_seq += 1
            assert _n(line, 84, 87) == expect_addenda_seq, f"line {i}: addenda sequence"
            assert _n(line, 88, 94) == int(entry["trace"][8:]), f"line {i}: addenda trace differs from entry"
            entry["addenda"] += 1
            batch["addenda"] += 1  # type: ignore[index]
        elif rtype == "8":
            assert state == "in_batch" and batch is not None, f"line {i}: 8 record outside a batch"
            for e in batch["entries"]:
                assert e["_indicator"] == (1 if e["addenda"] else 0), f"entry {e['trace']}: addenda indicator"
            assert _f(line, 2, 4) == batch["scc"], f"line {i}: service class differs from 5 record"
            assert _f(line, 45, 54) == batch["company_id"], f"line {i}: company id differs from 5 record"
            assert _f(line, 80, 87) == batch["odfi"]
            assert _n(line, 88, 94) == batch["no"]
            count = len(batch["entries"]) + batch["addenda"]
            ehash = sum(int(e["routing_number"][:8]) for e in batch["entries"]) % 10**10
            debit, credit = _amounts([(e["transaction_code"], e["amount_cents"]) for e in batch["entries"]])
            assert _n(line, 5, 10) == count, f"line {i}: entry/addenda count"
            assert _n(line, 11, 20) == ehash, f"line {i}: entry hash"
            assert _n(line, 21, 32) == debit, f"line {i}: total debit"
            assert _n(line, 33, 44) == credit, f"line {i}: total credit"
            if batch["scc"] == "220":
                assert debit == 0, f"line {i}: service class 220 batch has debits"
            if batch["scc"] == "225":
                assert credit == 0, f"line {i}: service class 225 batch has credits"
            assert batch["entries"], f"line {i}: batch with no entries"
            batches.append({"count": count, "hash": ehash, "debit": debit, "credit": credit})
            state = "in_file"
            batch = None
            entry = None
        elif rtype == "9":
            assert state == "in_file", f"line {i}: 9 record inside a batch or twice"
            assert batches, "file with no batches"
            assert i == len(body), f"line {i}: 9 record is not the last record"
            assert _n(line, 2, 7) == len(batches), f"line {i}: batch count"
            assert _n(line, 8, 13) == len(lines) // 10, f"line {i}: block count"
            assert _n(line, 14, 21) == sum(b["count"] for b in batches), f"line {i}: entry/addenda count"
            assert _n(line, 22, 31) == sum(b["hash"] for b in batches) % 10**10, f"line {i}: entry hash"
            assert _n(line, 32, 43) == sum(b["debit"] for b in batches), f"line {i}: total debit"
            assert _n(line, 44, 55) == sum(b["credit"] for b in batches), f"line {i}: total credit"
            state = "done"
        else:
            raise AssertionError(f"line {i}: unknown record type {rtype!r}")
    assert state == "done", f"file ended in state {state!r}"

    traces = [e["trace"] for e in entries]
    assert len(set(traces)) == len(traces), "trace numbers are not unique"
    assert traces == sorted(traces), "trace numbers are not ascending"
    for e in entries:
        del e["_indicator"]
    return entries
