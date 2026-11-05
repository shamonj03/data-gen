"""Data generation from a normalised ``Schema``. One seeded ``random.Random`` drives every built-in."""

from __future__ import annotations

import copy
import random
import string
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from datagen.errors import DatagenError
from datagen.safe import (
    account_number,
    random_string,
    safe_routing,
    safe_ssn,
    test_card,
)
from datagen.schema import parse_date_bound
from datagen.types import Schema

MAX_TRIES = 100


def _cell_text(v: Any) -> str:
    """Private copy of the render ``cell_text``: None -> "", dates -> ISO, bools -> true/false."""
    if v is None:
        return ""
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def generate(schema: Schema, *, seed: int, now: datetime) -> dict:
    """Generate the top-level ``data`` of ``schema``. Same seed and ``now`` give an equal result."""
    return _Generator(schema, seed, now).run()


class _Generator:
    """One generation run: holds the rng, the Faker instance and the sequence counters."""

    def __init__(self, schema: Schema, seed: int, now: datetime) -> None:
        self.schema = schema
        self.seed = seed
        self.today = now.date()
        self.rng = random.Random(seed)
        self._fake: Any = None
        self.counters: dict[str, int] = {}

    @property
    def fake(self) -> Any:
        """Seeded Faker, created on first use."""
        if self._fake is None:
            from faker import Faker

            self._fake = Faker(self.schema.locale)
            self._fake.seed_instance(self.seed)
        return self._fake

    def run(self) -> dict:
        return self._fields(self.schema.data, "data")

    # ------------------------------------------------------------ containers

    def _fields(self, fields: dict[str, dict], base: str) -> dict:
        out: dict[str, Any] = {}
        for name, spec in fields.items():
            out[name] = self._value(spec, f"{base}.{name}", out)
        return out

    def _value(self, spec: dict, path: str, siblings: dict) -> Any:
        typ = spec["type"]
        if typ == "object":
            return self._fields(spec["fields"], f"{path}.fields")
        if typ == "list":
            return self._list(spec, path)
        return self._scalar(spec, path, siblings)

    def _list(self, spec: dict, path: str) -> list:
        count = spec["count"]
        if isinstance(count, dict):
            count = self.rng.randint(count["min"], count["max"])
        if "fields" in spec:
            return [self._fields(spec["fields"], f"{path}.fields") for _ in range(count)]
        return [self._scalar(spec["item"], f"{path}.item", {}) for _ in range(count)]

    # ------------------------------------------------------------ scalars and field rules

    def _scalar(self, spec: dict, path: str, siblings: dict) -> Any:
        """Generate one scalar and apply the field rules (range, length, pad, on_invalid)."""
        typ = spec["type"]
        check_range = typ not in ("int", "decimal") and ("min" in spec or "max" in spec)
        has_length = "min_length" in spec or "max_length" in spec
        failed = "rule"
        for _ in range(MAX_TRIES):
            value = getattr(self, f"_t_{typ}")(spec, path, siblings)
            if check_range:
                broken = self._range_broken(value, spec, path)
                if broken:
                    failed = broken
                    continue
            if typ == "date" and "format" in spec:
                value = value.strftime(spec["format"])
            if not has_length:
                return value
            text = _cell_text(value)
            max_len, min_len = spec.get("max_length"), spec.get("min_length")
            if max_len is not None and len(text) > max_len:
                mode = spec.get("on_invalid", "truncate")
                if mode == "error":
                    raise DatagenError(f"{path}: value {text!r} is longer than max_length {max_len}")
                if mode == "retry":
                    failed = "max_length"
                    continue
                text = text[:max_len]
            if min_len is not None and len(text) < min_len:
                pad = spec.get("pad")
                if pad is None:
                    failed = "min_length"
                    continue
                fill = text.rjust if pad["side"] == "left" else text.ljust
                text = fill(min_len, pad["char"])
            return text
        raise DatagenError(f"{path}: could not satisfy {failed} after {MAX_TRIES} tries")

    def _range_broken(self, value: Any, spec: dict, path: str) -> str | None:
        """Return "min" or "max" if ``value`` is out of range, else None."""
        for rule, below in (("min", True), ("max", False)):
            if rule not in spec:
                continue
            bound = spec[rule]
            try:
                if isinstance(bound, str):
                    bound = parse_date_bound(bound, self.today)
                    if isinstance(value, datetime):
                        value = value.date()
                    elif isinstance(value, str):
                        value = date.fromisoformat(value)
                if value < bound if below else value > bound:
                    return rule
            except (TypeError, ValueError):
                raise DatagenError(f"{path}: cannot compare {value!r} against {rule} {spec[rule]!r}") from None
        return None

    # ------------------------------------------------------------ one generator per type

    def _t_faker(self, spec: dict, path: str, siblings: dict) -> Any:
        try:
            return getattr(self.fake, spec["faker"])(**spec["args"])
        except Exception as exc:
            raise DatagenError(f"{path}: Faker {spec['faker']!r} failed: {exc}") from exc

    def _t_int(self, spec: dict, path: str, siblings: dict) -> int:
        return self.rng.randint(spec["min"], spec["max"])

    def _t_decimal(self, spec: dict, path: str, siblings: dict) -> Decimal:
        places = spec["places"]
        scale = Decimal(10) ** places
        lo = int((Decimal(str(spec["min"])) * scale).to_integral_value(rounding="ROUND_CEILING"))
        hi = int((Decimal(str(spec["max"])) * scale).to_integral_value(rounding="ROUND_FLOOR"))
        return Decimal(self.rng.randint(lo, hi)).scaleb(-places)

    def _t_date(self, spec: dict, path: str, siblings: dict) -> date:
        start = parse_date_bound(spec["start"], self.today)
        end = parse_date_bound(spec["end"], self.today)
        if start > end:
            raise DatagenError(f"{path}: start {start} is after end {end}")
        return start + timedelta(days=self.rng.randint(0, (end - start).days))

    def _t_string(self, spec: dict, path: str, siblings: dict) -> str:
        lo, hi = spec.get("min_length"), spec.get("max_length")
        if lo is None and hi is None:
            lo, hi = 1, 10
        elif hi is None:
            hi = max(10, lo)
        elif lo is None:
            lo = min(1, hi)
        return random_string(self.rng, spec["charset"], lo, hi)

    def _t_choice(self, spec: dict, path: str, siblings: dict) -> Any:
        values = spec["values"]
        weights = spec.get("weights")
        picked = self.rng.choices(values, weights)[0] if weights else self.rng.choice(values)
        return copy.deepcopy(picked)

    def _t_constant(self, spec: dict, path: str, siblings: dict) -> Any:
        return copy.deepcopy(spec["value"])

    def _t_sequence(self, spec: dict, path: str, siblings: dict) -> int:
        n = self.counters.get(path, 0)
        self.counters[path] = n + 1
        return spec["start"] + n * spec["step"]

    def _t_pattern(self, spec: dict, path: str, siblings: dict) -> str:
        out = []
        for ch in spec["pattern"]:
            if ch == "#":
                out.append(self.rng.choice(string.digits))
            elif ch == "?":
                out.append(self.rng.choice(string.ascii_letters))
            else:
                out.append(ch)
        return "".join(out)

    def _t_format(self, spec: dict, path: str, siblings: dict) -> str:
        try:
            return spec["format"].format(**{**siblings, "params": self.schema.params})
        except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
            raise DatagenError(f"{path}: cannot format {spec['format']!r}: {exc!r}") from exc

    def _t_ssn(self, spec: dict, path: str, siblings: dict) -> str:
        if spec["safe"]:
            return safe_ssn(self.rng, spec["dashes"])
        ssn = self.fake.ssn()
        return ssn if spec["dashes"] else ssn.replace("-", "")

    def _t_card_number(self, spec: dict, path: str, siblings: dict) -> str:
        if spec["safe"]:
            return test_card(self.rng, spec["brand"])
        return str(self.fake.credit_card_number(spec["brand"]))

    def _t_routing_number(self, spec: dict, path: str, siblings: dict) -> str:
        if "values" in spec:
            return self.rng.choice(spec["values"])
        return safe_routing(self.rng) if spec["safe"] else str(self.fake.aba())

    def _t_account_number(self, spec: dict, path: str, siblings: dict) -> str:
        lo, hi = spec.get("min_length"), spec.get("max_length")
        lo = lo if lo is not None else (hi if hi is not None else 10)
        hi = hi if hi is not None else lo
        return account_number(self.rng, lo, hi)
