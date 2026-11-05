from __future__ import annotations

import random
import re

import pytest

from datagen.safe import (
    CHARSETS,
    aba_check_digit,
    account_number,
    is_valid_aba,
    luhn_check_digit,
    random_string,
    safe_routing,
    safe_ssn,
    test_card,
)


def _luhn_valid(number: str) -> bool:
    return luhn_check_digit(number[:-1]) == number[-1]


def test_luhn_known_value():
    assert luhn_check_digit("7992739871") == "3"


def test_aba_known_value():
    assert is_valid_aba("011000015")
    assert aba_check_digit("01100001") == "5"
    assert not is_valid_aba("011000016")
    assert not is_valid_aba("01100001")
    assert not is_valid_aba("01100001x")


def test_safe_ssn_ranges():
    rng = random.Random(1)
    for _ in range(1000):
        area, group, serial = safe_ssn(rng).split("-")
        assert 900 <= int(area) <= 999
        assert 1 <= int(group) <= 49
        assert 1 <= int(serial) <= 9999
        assert (len(area), len(group), len(serial)) == (3, 2, 4)


def test_safe_ssn_without_dashes():
    ssn = safe_ssn(random.Random(2), dashes=False)
    assert re.fullmatch(r"9\d{8}", ssn)


@pytest.mark.parametrize(
    "brand, prefix, length",
    [("visa", "411111", 16), ("mastercard", "555555", 16), ("amex", "378282", 15), ("discover", "601111", 16)],
)
def test_cards_are_luhn_valid(brand, prefix, length):
    rng = random.Random(3)
    for _ in range(1000):
        number = test_card(rng, brand)
        assert number.startswith(prefix)
        assert len(number) == length
        assert number.isdigit()
        assert _luhn_valid(number)


def test_card_unknown_brand():
    with pytest.raises(ValueError):
        test_card(random.Random(0), "diners")


def test_safe_routing_prefix_and_checksum():
    rng = random.Random(4)
    for _ in range(1000):
        number = safe_routing(rng)
        assert 50 <= int(number[:2]) <= 59
        assert is_valid_aba(number)


def test_account_number_length_and_first_digit():
    rng = random.Random(5)
    lengths = set()
    for _ in range(500):
        number = account_number(rng, 8, 12)
        assert number.isdigit() and number[0] != "0"
        lengths.add(len(number))
    assert lengths == {8, 9, 10, 11, 12}
    assert len(account_number(rng, 10, 10)) == 10


def test_account_number_bad_range():
    with pytest.raises(ValueError):
        account_number(random.Random(0), 0, 5)
    with pytest.raises(ValueError):
        account_number(random.Random(0), 6, 5)


@pytest.mark.parametrize("preset", sorted(CHARSETS))
def test_random_string_presets(preset):
    rng = random.Random(6)
    for _ in range(100):
        s = random_string(rng, preset, 3, 7)
        assert 3 <= len(s) <= 7
        assert set(s) <= set(CHARSETS[preset])


def test_random_string_literal_pool():
    s = random_string(random.Random(7), "xyz", 20, 20)
    assert len(s) == 20 and set(s) <= set("xyz")


def test_random_string_errors():
    with pytest.raises(ValueError):
        random_string(random.Random(0), "", 1, 2)
    with pytest.raises(ValueError):
        random_string(random.Random(0), "abc", 5, 2)


def test_deterministic_with_same_rng_seed():
    assert safe_ssn(random.Random(9)) == safe_ssn(random.Random(9))
    assert test_card(random.Random(9), "visa") == test_card(random.Random(9), "visa")
