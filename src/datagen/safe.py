"""PII-safe value functions. All are pure and driven by a caller-supplied ``random.Random``."""

from __future__ import annotations

import random
import string

CHARSETS: dict[str, str] = {
    "digits": string.digits,
    "letters": string.ascii_letters,
    "upper": string.ascii_uppercase,
    "lower": string.ascii_lowercase,
    "alnum": string.ascii_letters + string.digits,
}

# brand -> (test BIN, total length)
CARD_BRANDS: dict[str, tuple[str, int]] = {
    "visa": ("411111", 16),
    "mastercard": ("555555", 16),
    "amex": ("378282", 15),
    "discover": ("601111", 16),
}

_ABA_WEIGHTS = (3, 7, 1)


def _digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice(string.digits) for _ in range(n))


def luhn_check_digit(s: str) -> str:
    """Return the Luhn digit to append to the digit string ``s``."""
    total = 0
    for i, ch in enumerate(reversed(s)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def aba_check_digit(first8: str) -> str:
    """Return the ABA routing check digit for the first eight digits."""
    total = sum(int(c) * _ABA_WEIGHTS[i % 3] for i, c in enumerate(first8))
    return str((10 - total % 10) % 10)


def is_valid_aba(s: str) -> bool:
    """True when ``s`` is nine digits with a valid ABA checksum."""
    return len(s) == 9 and s.isascii() and s.isdigit() and aba_check_digit(s[:8]) == s[8]


def safe_ssn(rng: random.Random, dashes: bool = True) -> str:
    """An SSN in the never-issued range: area 900-999, group 01-49, serial 0001-9999."""
    area = rng.randint(900, 999)
    group = rng.randint(1, 49)
    serial = rng.randint(1, 9999)
    sep = "-" if dashes else ""
    return f"{area:03d}{sep}{group:02d}{sep}{serial:04d}"


def test_card(rng: random.Random, brand: str) -> str:
    """A Luhn-valid card number on a well-known test BIN for ``brand``."""
    if brand not in CARD_BRANDS:
        raise ValueError(f"unknown card brand {brand!r}")
    bin_, length = CARD_BRANDS[brand]
    body = bin_ + _digits(rng, length - len(bin_) - 1)
    return body + luhn_check_digit(body)


# pytest would otherwise try to collect this helper when it is imported into a test module.
test_card.__test__ = False  # type: ignore[attr-defined]


def safe_routing(rng: random.Random) -> str:
    """A routing number with an unassigned 50-59 prefix and a valid check digit."""
    first8 = str(rng.randint(50, 59)) + _digits(rng, 6)
    return first8 + aba_check_digit(first8)


def account_number(rng: random.Random, min_len: int, max_len: int) -> str:
    """A digit string of random length in ``min_len..max_len`` whose first digit is non-zero."""
    if min_len < 1 or min_len > max_len:
        raise ValueError(f"bad account number length range {min_len}..{max_len}")
    n = rng.randint(min_len, max_len)
    return rng.choice("123456789") + _digits(rng, n - 1)


def random_string(rng: random.Random, charset: str, min_len: int, max_len: int) -> str:
    """A random string. ``charset`` is a preset name or the literal pool of characters."""
    pool = CHARSETS.get(charset, charset)
    if not pool:
        raise ValueError("charset must not be empty")
    if min_len < 0 or min_len > max_len:
        raise ValueError(f"bad string length range {min_len}..{max_len}")
    n = rng.randint(min_len, max_len)
    return "".join(rng.choice(pool) for _ in range(n))
