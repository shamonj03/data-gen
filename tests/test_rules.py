from __future__ import annotations

from datetime import date, datetime

import pytest
from faker import Faker

from datagen.errors import DatagenError, SchemaError
from datagen.generator import generate
from datagen.schema import schema_from_dict

NOW = datetime(2026, 11, 5)


def gen(data: dict, seed: int = 1) -> dict:
    return generate(schema_from_dict({"data": data}, None), seed=seed, now=NOW)


def rows(spec: dict, count: int = 30, seed: int = 1) -> list:
    return gen({"l": {"type": "list", "count": count, "item": spec}}, seed=seed)["l"]


# ------------------------------------------------------------------ padding


def test_sequence_length_8_zero_pad():
    assert rows({"type": "sequence", "length": 8, "pad": "0"}, 3) == ["00000001", "00000002", "00000003"]


def test_pad_shorthand_equals_dict_form():
    short = rows({"type": "sequence", "length": 5, "pad": "0"}, 4)
    full = rows({"type": "sequence", "length": 5, "pad": {"char": "0", "side": "left"}}, 4)
    assert short == full


def test_right_pad_with_spaces():
    out = rows({"type": "constant", "value": "ab", "length": 5, "pad": {"char": " ", "side": "right"}}, 1)
    assert out == ["ab   "]


def test_left_pad_default_char_is_space():
    out = rows({"type": "constant", "value": "ab", "length": 5, "pad": {"side": "left"}}, 1)
    assert out == ["   ab"]


def test_pad_uses_min_length_and_ignores_longer_values():
    out = rows({"type": "constant", "value": "abcdef", "min_length": 4, "pad": "0"}, 1)
    assert out == ["abcdef"]
    assert rows({"type": "int", "min": 5, "max": 5, "min_length": 3, "pad": "0"}, 1) == ["005"]


def test_pad_converts_value_with_cell_text():
    out = rows({"type": "constant", "value": True, "length": 6, "pad": "_"}, 1)
    assert out == ["__true"]
    out = rows({"type": "constant", "value": None, "length": 2, "pad": "x"}, 1)
    assert out == ["xx"]
    out = rows({"type": "date", "start": "2024-01-02", "end": "2024-01-02", "length": 12, "pad": "*"}, 1)
    assert out == ["**2024-01-02"]


def test_int_pad_from_spec_example():
    vals = rows({"type": "int", "min": 1, "max": 999, "length": 4, "pad": "0"}, 50)
    assert all(len(v) == 4 and v.isdigit() and 1 <= int(v) <= 999 for v in vals)


# ------------------------------------------------------------------ max_length / on_invalid


def test_max_length_truncates_by_default():
    out = rows({"type": "constant", "value": "abcdefgh", "max_length": 3}, 1)
    assert out == ["abc"]


def test_truncate_explicit_and_exact_length_untouched():
    assert rows({"type": "constant", "value": "abc", "max_length": 3, "on_invalid": "truncate"}, 1) == ["abc"]


def test_on_invalid_error_raises_with_path():
    with pytest.raises(DatagenError) as exc:
        gen({"nick": {"type": "constant", "value": "toolong", "max_length": 3, "on_invalid": "error"}})
    assert "data.nick" in str(exc.value)


def test_on_invalid_error_not_raised_when_value_fits():
    assert rows({"type": "constant", "value": "ok", "max_length": 3, "on_invalid": "error"}, 1) == ["ok"]


def test_on_invalid_retry_on_faker_name_matches_original_output():
    seed = 11
    spec = {"faker": "first_name", "max_length": 6, "on_invalid": "retry"}
    got = rows(spec, 25, seed=seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)
    expected: list[str] = []
    while len(expected) < 25:
        name = fake.first_name()
        if len(name) <= 6:
            expected.append(name)
    assert got == expected
    assert all(len(v) <= 6 for v in got)


def test_truncate_is_the_default_for_faker_too():
    got = rows({"faker": "first_name", "max_length": 3}, 40)
    assert all(len(v) <= 3 for v in got) and any(len(v) == 3 for v in got)


# ------------------------------------------------------------------ min_length / retries


def test_min_length_without_pad_retries():
    got = rows({"faker": "first_name", "min_length": 7}, 20, seed=3)
    assert all(len(v) >= 7 for v in got)
    fake = Faker("en_US")
    fake.seed_instance(3)
    expected: list[str] = []
    while len(expected) < 20:
        name = fake.first_name()
        if len(name) >= 7:
            expected.append(name)
    assert got == expected


def test_impossible_min_length_after_100_tries_names_the_path():
    with pytest.raises(DatagenError) as exc:
        gen({"outer": {"type": "object", "fields": {"nm": {"faker": "first_name", "min_length": 200}}}})
    msg = str(exc.value)
    assert "data.outer.fields.nm" in msg
    assert "could not satisfy min_length after 100 tries" in msg


def test_impossible_retry_max_length():
    with pytest.raises(DatagenError, match=r"data\.nm: could not satisfy max_length after 100 tries"):
        gen({"nm": {"faker": "first_name", "max_length": 0, "on_invalid": "retry"}})


def test_impossible_range():
    with pytest.raises(DatagenError, match=r"data\.n: could not satisfy min after 100 tries"):
        gen({"n": {"faker": "pyint", "args": {"min_value": 0, "max_value": 5}, "min": 100}})
    with pytest.raises(DatagenError, match=r"data\.n: could not satisfy max after 100 tries"):
        gen({"n": {"faker": "pyint", "args": {"min_value": 10, "max_value": 20}, "max": 5}})


def test_retries_are_deterministic():
    spec = {"faker": "first_name", "min_length": 7}
    assert rows(spec, 10, seed=5) == rows(spec, 10, seed=5)


# ------------------------------------------------------------------ min / max


def test_min_max_on_faker_pyint():
    got = rows({"faker": "pyint", "args": {"min_value": 0, "max_value": 100}, "min": 40, "max": 60}, 60)
    assert all(40 <= v <= 60 for v in got)
    assert len(got) == 60


def test_min_max_are_inclusive():
    got = rows({"faker": "pyint", "args": {"min_value": 0, "max_value": 2}, "min": 1, "max": 1}, 20)
    assert got == [1] * 20


def test_min_max_on_dates_against_iso_bounds():
    spec = {"faker": "date_object", "min": "2000-01-01", "max": "2100-01-01"}
    got = rows(spec, 15)
    assert all(isinstance(v, date) and date(2000, 1, 1) <= v <= date(2100, 1, 1) for v in got)
    got = rows({"type": "date", "start": "2020-01-01", "end": "2020-12-31", "min": "2020-03-01", "max": "2020-12-31"}, 10)
    assert all(date(2020, 3, 1) <= v <= date(2020, 12, 31) for v in got)


def test_min_max_on_date_with_format_checks_the_date_first():
    got = rows({"type": "date", "start": "2020-01-01", "end": "2020-12-31", "format": "%Y-%m-%d", "min": "2020-03-01", "max": "2020-12-31"}, 10)
    assert all("2020-03-01" <= v <= "2020-12-31" for v in got)


def test_min_max_on_a_number_type_with_decimal_value():
    # the range of a decimal is built in, so only a sequence-like type can break it
    got = rows({"type": "sequence", "max": 5}, 5)
    assert got == [1, 2, 3, 4, 5]
    with pytest.raises(DatagenError, match="could not satisfy max"):
        rows({"type": "sequence", "max": 5}, 6)


def test_min_max_on_incomparable_value_is_an_error():
    with pytest.raises(DatagenError, match=r"data\.s"):
        gen({"s": {"type": "constant", "value": "abc", "min": 1}})


def test_int_min_max_are_the_generation_range():
    assert {*rows({"type": "int", "min": 5, "max": 7}, 60)} == {5, 6, 7}


# ------------------------------------------------------------------ string type


def test_string_within_length_bounds_and_charset():
    got = rows({"type": "string", "min_length": 3, "max_length": 12, "charset": "letters"}, 100)
    assert all(3 <= len(v) <= 12 and v.isalpha() for v in got)
    assert len({len(v) for v in got}) > 3


def test_string_exact_length_and_literal_charset():
    got = rows({"type": "string", "length": 6, "charset": "01"}, 30)
    assert all(len(v) == 6 and set(v) <= {"0", "1"} for v in got)


def test_string_only_min_or_only_max():
    assert all(len(v) >= 15 for v in rows({"type": "string", "min_length": 15}, 20))
    assert all(len(v) <= 4 for v in rows({"type": "string", "max_length": 4}, 20))


def test_string_with_pad():
    got = rows({"type": "string", "length": 5, "charset": "digits", "pad": "0"}, 10)
    assert all(len(v) == 5 for v in got)


def test_account_number_with_length_rules():
    got = rows({"type": "account_number", "length": 12}, 20)
    assert all(len(v) == 12 for v in got)


# ------------------------------------------------------------------ load-time errors


def test_pad_without_length_is_a_schema_error():
    with pytest.raises(SchemaError) as exc:
        gen({"acct": {"faker": "name", "pad": "0"}})
    assert exc.value.path == "data.acct.pad"


def test_rules_on_a_list_are_a_schema_error():
    with pytest.raises(SchemaError) as exc:
        gen({"people": {"type": "list", "count": 1, "item": "name", "length": 3}})
    assert exc.value.path == "data.people.length"


def test_rules_on_an_object_are_a_schema_error():
    with pytest.raises(SchemaError) as exc:
        gen({"o": {"type": "object", "fields": {"a": "name"}, "max_length": 3}})
    assert exc.value.path == "data.o.max_length"


# Regression: relative date bounds on min/max used to crash with a raw ValueError
# (schema._normalise_bounds and generator._range_broken called date.fromisoformat).
def test_min_max_accept_relative_date_bounds() -> None:
    out = gen({"rows": {"type": "list", "count": 50, "item": {
        "type": "date", "start": "-60d", "end": "today",
        "min": "-30d", "max": "today"}}})
    for value in out["rows"]:
        assert date(2026, 10, 6) <= value <= date(2026, 11, 5)


def test_min_greater_than_max_with_relative_bounds_is_schema_error() -> None:
    with pytest.raises(SchemaError, match="greater than max"):
        schema_from_dict({"data": {"d": {"faker": "date_this_year", "min": "today", "max": "-5d"}}}, None)
