"""ACH examples: independent NACHA check, report agreement, determinism and the totals helper."""
from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

import datagen
from datagen.formats.ach import ach_batch_totals, ach_file_totals
from tests.ach_check import check

RENDERS = Path(__file__).resolve().parent.parent / "examples" / "renders"
NOW = datetime(2026, 1, 2, 10, 0)
SEEDS = range(1, 51)


def render_ach(name: str, seed: int) -> str:
    out = datagen.render(RENDERS / name, seed=seed, now=NOW)
    (key,) = [k for k in out if k.endswith(".ach")]
    return out[key]  # type: ignore[return-value]


@pytest.mark.parametrize("seed", SEEDS)
def test_single_batch(seed: int) -> None:
    text = render_ach("ach_single_batch.json", seed)
    entries = check(text)
    lines = text.split("\r\n")
    assert sum(1 for line in lines if line.startswith("5")) == 1
    assert len(entries) >= 5
    assert {e["transaction_code"] for e in entries} <= {"22", "32"}
    assert {e["batch"] for e in entries} == {1}


@pytest.mark.parametrize("seed", SEEDS)
def test_multi_batch(seed: int) -> None:
    text = render_ach("ach_multi_batch.json", seed)
    entries = check(text)
    lines = text.split("\r\n")
    assert 3 <= sum(1 for line in lines if line.startswith("5")) <= 6
    per_batch: dict[int, int] = {}
    for e in entries:
        per_batch[e["batch"]] = per_batch.get(e["batch"], 0) + 1
    assert 3 <= len(per_batch) <= 6
    assert all(n >= 2 for n in per_batch.values())


@pytest.mark.parametrize("seed", [1, 2, 3, 7, 11, 25, 50])
def test_report_matches_ach(seed: int) -> None:
    out = datagen.render(RENDERS / "ach_with_report.json", seed=seed, now=NOW)
    assert sorted(out) == ["ach_20260102.ach", "ach_report.csv"]
    entries = check(out["ach_20260102.ach"])  # type: ignore[arg-type]
    rows = list(csv.reader(io.StringIO(out["ach_report.csv"])))  # type: ignore[arg-type]
    assert rows[0] == ["batch", "trace_number", "transaction_code", "routing_number", "account_number", "amount", "name"]
    reported = {(r[1], int(Decimal(r[5]) * 100), r[3]) for r in rows[1:]}
    parsed = {(e["trace"], e["amount_cents"], e["routing_number"]) for e in entries}
    assert len(rows) - 1 == len(entries)
    assert reported == parsed


def test_deterministic() -> None:
    first = datagen.render(RENDERS / "ach_multi_batch.json", seed=5, now=NOW)
    second = datagen.render(RENDERS / "ach_multi_batch.json", seed=5, now=NOW)
    assert first == second
    other = datagen.render(RENDERS / "ach_multi_batch.json", seed=6, now=NOW)
    assert first != other


def test_batch_totals_hand_computed() -> None:
    entries = [
        {"transaction_code": "22", "routing_number": "512345677", "amount": Decimal("100.50")},
        {"transaction_code": "27", "routing_number": "123456780", "amount": Decimal("20.25"), "addenda": [{"info": "x"}]},
        {"transaction_code": "32", "routing_number": "987654321", "amount": Decimal("5.00")},
    ]
    assert ach_batch_totals(entries) == {
        "entry_addenda_count": 4,
        "entry_hash": (51234567 + 12345678 + 98765432) % 10**10,
        "total_debit_cents": 2025,
        "total_credit_cents": 10550,
    }
    # Prenotes (x3 / x8) count 0 toward the totals.
    pre = [{"transaction_code": "23", "routing_number": "512345677", "amount": Decimal("0.00")}]
    assert ach_batch_totals(pre)["total_credit_cents"] == 0


def test_file_totals_block_count() -> None:
    entry = {"transaction_code": "22", "routing_number": "512345677", "amount": Decimal("1.00")}
    batch = {"entries": [entry] * 3}
    totals = ach_file_totals([batch, batch])
    assert totals["batch_count"] == 2
    assert totals["entry_addenda_count"] == 6
    assert totals["total_credit_cents"] == 600
    # records = 2 + 2 * (2 + 3) = 12 -> 2 blocks
    assert totals["block_count"] == 2
