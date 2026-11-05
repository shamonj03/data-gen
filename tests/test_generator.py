from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

import pytest

from datagen.errors import DatagenError
from datagen.generator import generate
from datagen.safe import is_valid_aba
from datagen.schema import schema_from_dict

NOW = datetime(2026, 11, 5, 12, 30)


def gen(data: dict, seed: int = 1, now: datetime = NOW, **top) -> dict:
    return generate(schema_from_dict({"data": data, **top}, None), seed=seed, now=now)


def one(spec, seed: int = 1, **top):
    return gen({"f": spec}, seed=seed, **top)["f"]


# ------------------------------------------------------------------ determinism and shape


BIG = {
    "customers": {
        "type": "list",
        "count": {"min": 5, "max": 10},
        "fields": {
            "id": {"type": "sequence", "length": 6, "pad": "0"},
            "name": "name",
            "born": {"type": "date", "start": "-300d", "end": "today"},
            "balance": {"type": "decimal", "min": 0, "max": 1000},
            "n": {"type": "int", "min": 1, "max": 1000},
            "code": {"type": "string", "charset": "upper", "length": 5},
            "ssn": {"type": "ssn"},
            "card": {"type": "card_number", "brand": "mastercard"},
            "pick": {"type": "choice", "values": ["a", "b", "c"], "weights": [1, 2, 3]},
        },
    },
    "email": "email",
}


def test_same_seed_and_now_give_equal_dict():
    assert gen(BIG, seed=42) == gen(BIG, seed=42)


def test_different_seed_gives_different_dict():
    assert gen(BIG, seed=1) != gen(BIG, seed=2)


def test_now_shifts_relative_dates():
    spec = {"type": "date", "start": "-5d", "end": "-5d"}
    assert one(spec) == date(2026, 10, 31)
    assert gen({"f": spec}, now=datetime(2026, 1, 10))["f"] == date(2026, 1, 5)


def test_returns_only_top_level_data():
    out = gen({"a": {"type": "constant", "value": 1}}, params={"p": 1})
    assert out == {"a": 1}


def test_top_level_order_preserved():
    out = gen({"z": {"type": "constant", "value": 1}, "a": {"type": "constant", "value": 2}})
    assert list(out) == ["z", "a"]


# ------------------------------------------------------------------ types


def test_faker_with_args():
    for seed in range(20):
        assert 3 <= one({"faker": "pyint", "args": {"min_value": 3, "max_value": 5}}, seed=seed) <= 5


def test_faker_string_shorthand_and_locale():
    assert isinstance(one("name"), str)
    assert isinstance(one("name", locale="de_DE"), str)


def test_faker_failure_is_datagen_error():
    with pytest.raises(DatagenError, match=r"data\.f"):
        one({"faker": "pyint", "args": {"min_value": 10, "max_value": 1}})


def test_faker_is_seeded():
    assert one("name", seed=7) == one("name", seed=7)


def test_int_bounds_inclusive():
    seen = {one({"type": "int", "min": 1, "max": 3}, seed=s) for s in range(100)}
    assert seen == {1, 2, 3}


def test_decimal_places_and_range():
    for s in range(100):
        v = one({"type": "decimal", "min": 0, "max": 50000}, seed=s)
        assert isinstance(v, Decimal)
        assert 0 <= v <= 50000
        assert v.as_tuple().exponent == -2
    for s in range(100):
        v = one({"type": "decimal", "min": 0.5, "max": 2, "places": 1}, seed=s)
        assert Decimal("0.5") <= v <= 2 and v.as_tuple().exponent == -1
    assert one({"type": "decimal", "min": 3, "max": 3, "places": 0}) == Decimal(3)
    assert str(one({"type": "decimal", "min": 0, "max": 0})) == "0.00"


def test_date_types_and_bounds():
    for s in range(50):
        v = one({"type": "date", "start": "2020-01-01", "end": "2020-01-31"}, seed=s)
        assert isinstance(v, date) and not isinstance(v, datetime)
        assert date(2020, 1, 1) <= v <= date(2020, 1, 31)
    assert one({"type": "date", "start": "today", "end": "today"}) == date(2026, 11, 5)
    assert one({"type": "date", "start": "+1w", "end": "+1w"}) == date(2026, 11, 12)
    assert one({"type": "date", "start": "-2w", "end": "-2w"}) == date(2026, 10, 22)
    assert one({"type": "date", "start": "+3d", "end": "+3d"}) == date(2026, 11, 8)


def test_date_with_format_is_a_string():
    v = one({"type": "date", "start": "2020-03-04", "end": "2020-03-04", "format": "%Y%m%d"})
    assert v == "20200304"


def test_date_start_after_end_at_generation():
    with pytest.raises(DatagenError, match=r"data\.f"):
        one({"type": "date", "start": "+5d", "end": "-5d"})


def test_string_default_length_and_charsets():
    for s in range(50):
        v = one({"type": "string"}, seed=s)
        assert 1 <= len(v) <= 10 and v.isalnum()
    assert one({"type": "string", "charset": "digits", "length": 8}).isdigit()
    assert set(one({"type": "string", "charset": "ab", "length": 30})) <= {"a", "b"}


def test_choice_with_and_without_weights():
    assert {one({"type": "choice", "values": [1, 2, 3]}, seed=s) for s in range(60)} == {1, 2, 3}
    assert {one({"type": "choice", "values": [1, 2], "weights": [0, 1]}, seed=s) for s in range(30)} == {2}


def test_constant_is_copied():
    sch = schema_from_dict({"data": {"c": {"type": "constant", "value": {"a": [1]}}}}, None)
    first = generate(sch, seed=1, now=NOW)
    first["c"]["a"].append(2)
    assert generate(sch, seed=1, now=NOW)["c"] == {"a": [1]}


def test_sequence_start_step():
    out = gen({"l": {"type": "list", "count": 3, "item": {"type": "sequence", "start": 10, "step": 5}}})
    assert out["l"] == [10, 15, 20]


def test_pattern_uses_digits_and_letters():
    for s in range(50):
        v = one({"type": "pattern", "pattern": "AB-##-??-x"}, seed=s)
        assert re.fullmatch(r"AB-\d\d-[A-Za-z]{2}-x", v)


def test_pattern_deterministic():
    assert one({"type": "pattern", "pattern": "####"}, seed=3) == one({"type": "pattern", "pattern": "####"}, seed=3)


def test_format_references_siblings_and_params():
    out = gen(
        {
            "first": {"type": "constant", "value": "Ann"},
            "n": {"type": "int", "min": 7, "max": 7},
            "full": {"type": "format", "format": "{first}-{n:03d}@{params[host]}"},
        },
        params={"host": "x.test"},
    )
    assert out["full"] == "Ann-007@x.test"


def test_format_inside_list_items_uses_item_siblings():
    out = gen(
        {
            "rows": {
                "type": "list",
                "count": 3,
                "fields": {"id": {"type": "sequence"}, "tag": {"type": "format", "format": "T{id}"}},
            }
        }
    )
    assert [r["tag"] for r in out["rows"]] == ["T1", "T2", "T3"]


def test_format_runtime_error_is_datagen_error():
    with pytest.raises(DatagenError, match=r"data\.t"):
        gen({"a": {"type": "constant", "value": "x"}, "t": {"type": "format", "format": "{a:d}"}})


def test_ssn_safe_dashes_and_plain():
    for s in range(200):
        area, group, serial = one({"type": "ssn"}, seed=s).split("-")
        assert 900 <= int(area) <= 999 and 1 <= int(group) <= 49 and 1 <= int(serial)
    assert re.fullmatch(r"9\d{8}", one({"type": "ssn", "dashes": False}))


def test_ssn_unsafe_uses_faker():
    v = one({"type": "ssn", "safe": False})
    assert re.fullmatch(r"\d{3}-\d{2}-\d{4}", v)
    assert re.fullmatch(r"\d{9}", one({"type": "ssn", "safe": False, "dashes": False}))


@pytest.mark.parametrize("brand, bin_, n", [("visa", "411111", 16), ("mastercard", "555555", 16), ("amex", "378282", 15), ("discover", "601111", 16)])
def test_card_number_safe(brand: str, bin_: str, n: int):
    v = one({"type": "card_number", "brand": brand})
    assert v.startswith(bin_) and len(v) == n


def test_card_number_default_brand_and_unsafe():
    assert one({"type": "card_number"}).startswith("411111")
    assert one({"type": "card_number", "safe": False}).isdigit()


def test_routing_number_variants():
    for s in range(50):
        v = one({"type": "routing_number"}, seed=s)
        assert is_valid_aba(v) and 50 <= int(v[:2]) <= 59
    assert one({"type": "routing_number", "values": ["011000015"]}) == "011000015"
    assert is_valid_aba(one({"type": "routing_number", "safe": False}))


def test_account_number_defaults_and_lengths():
    for s in range(50):
        v = one({"type": "account_number"}, seed=s)
        assert len(v) == 10 and v.isdigit() and v[0] != "0"
    for s in range(50):
        v = one({"type": "account_number", "min_length": 6, "max_length": 8}, seed=s)
        assert 6 <= len(v) <= 8
    assert len(one({"type": "account_number", "length": 12})) == 12


def test_object_and_nested_list():
    out = gen(
        {
            "o": {
                "type": "object",
                "fields": {"a": {"type": "constant", "value": 1}, "inner": {"type": "list", "count": 2, "item": {"type": "constant", "value": "x"}}},
            }
        }
    )
    assert out == {"o": {"a": 1, "inner": ["x", "x"]}}


def test_list_count_forms():
    assert gen({"l": {"type": "list", "count": 0, "item": "name"}})["l"] == []
    sizes = {len(gen({"l": {"type": "list", "count": {"min": 2, "max": 4}, "item": {"type": "int", "min": 1, "max": 1}}}, seed=s)["l"]) for s in range(60)}
    assert sizes == {2, 3, 4}


def test_list_of_objects_have_distinct_values():
    rows = gen({"l": {"type": "list", "count": 20, "fields": {"n": {"type": "int", "min": 0, "max": 10**9}}}})["l"]
    assert len({r["n"] for r in rows}) > 1


# ------------------------------------------------------------------ sequences


def test_sequence_counts_across_nested_parents():
    out = gen(
        {
            "orders": {
                "type": "list",
                "count": 3,
                "fields": {
                    "n": {"type": "sequence"},
                    "lines": {"type": "list", "count": 2, "fields": {"line": {"type": "sequence", "start": 100}}},
                },
            }
        }
    )
    assert [o["n"] for o in out["orders"]] == [1, 2, 3]
    assert [ln["line"] for o in out["orders"] for ln in o["lines"]] == [100, 101, 102, 103, 104, 105]


def test_sequences_are_independent_per_field_and_reset_per_run():
    spec = {"a": {"type": "sequence"}, "b": {"type": "sequence", "start": 50}}
    assert gen(spec) == {"a": 1, "b": 50}
    assert gen(spec) == {"a": 1, "b": 50}
