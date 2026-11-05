"""NACHA (ACH) helper functions used by the ``nacha.ach.j2`` example template."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Mapping

_CENTS = Decimal(100)


def _entry_cents(entry: Mapping[str, Any]) -> int:
    return int((Decimal(str(entry["amount"])) * _CENTS).to_integral_value())


def ach_batch_totals(entries: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Totals for one batch's 8 record.

    Debit when the last digit of the transaction code is 5-9, credit when 0-4. Prenote codes (x3, x8) count 0
    toward the totals but still count as entries and in the hash.
    """
    count = 0
    entry_hash = 0
    debit = 0
    credit = 0
    for entry in entries:
        count += 1 + len(entry.get("addenda") or [])
        entry_hash += int(str(entry["routing_number"])[:8])
        code = str(entry["transaction_code"])
        if code[-1] in "38":
            continue
        if code[-1] in "56789":
            debit += _entry_cents(entry)
        else:
            credit += _entry_cents(entry)
    return {
        "entry_addenda_count": count,
        "entry_hash": entry_hash % 10**10,
        "total_debit_cents": debit,
        "total_credit_cents": credit,
    }


def ach_file_totals(batches: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Totals for the file control (9) record."""
    batch_count = 0
    count = 0
    entry_hash = 0
    debit = 0
    credit = 0
    record_count = 2
    for batch in batches:
        totals = ach_batch_totals(batch["entries"])
        batch_count += 1
        count += totals["entry_addenda_count"]
        entry_hash += totals["entry_hash"]
        debit += totals["total_debit_cents"]
        credit += totals["total_credit_cents"]
        record_count += 2 + totals["entry_addenda_count"]
    return {
        "batch_count": batch_count,
        "entry_addenda_count": count,
        "entry_hash": entry_hash % 10**10,
        "total_debit_cents": debit,
        "total_credit_cents": credit,
        "block_count": -(-record_count // 10),
    }


GLOBALS = {"ach_batch_totals": ach_batch_totals, "ach_file_totals": ach_file_totals}
