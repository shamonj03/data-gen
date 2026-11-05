"""Schema loading: validation, normalisation of field specs, and ``--set`` overrides."""

from __future__ import annotations

import copy
import functools
import json
import math
import re
import string
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from datagen.errors import DatagenError, SchemaError
from datagen.safe import CARD_BRANDS, CHARSETS, is_valid_aba
from datagen.types import Schema

RULE_KEYS = frozenset({"min", "max", "length", "min_length", "max_length", "pad", "on_invalid"})
ON_INVALID = ("truncate", "retry", "error")
RESERVED_DATA_KEYS = frozenset({"params", "now", "seed"})
CONTAINERS = frozenset({"list", "object"})

# type -> keys specific to the type (besides "type" and, for scalars, the rule keys)
_TYPE_KEYS: dict[str, frozenset[str]] = {
    "faker": frozenset({"faker", "args"}),
    "int": frozenset({"min", "max"}),
    "decimal": frozenset({"min", "max", "places"}),
    "date": frozenset({"start", "end", "format"}),
    "string": frozenset({"charset"}),
    "choice": frozenset({"values", "weights"}),
    "constant": frozenset({"value"}),
    "sequence": frozenset({"start", "step"}),
    "pattern": frozenset({"pattern"}),
    "format": frozenset({"format"}),
    "ssn": frozenset({"dashes", "safe"}),
    "card_number": frozenset({"brand", "safe"}),
    "routing_number": frozenset({"values", "safe"}),
    "account_number": frozenset(),
    "object": frozenset({"fields"}),
    "list": frozenset({"count", "fields", "item"}),
}

_REL_DATE = re.compile(r"^([+-])(\d+)([dw])$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FORMAT_NAME = re.compile(r"^([A-Za-z_]\w*)((?:\[[^\]]*\])*)$")


def parse_date_bound(text: str, today: date) -> date:
    """Resolve ``YYYY-MM-DD``, ``today`` or ``[+-]N[d|w]`` relative to ``today``. Raise ValueError if bad."""
    if text == "today":
        return today
    if _ISO_DATE.match(text):
        return date.fromisoformat(text)
    m = _REL_DATE.match(text)
    if m:
        days = int(m.group(2)) * (7 if m.group(3) == "w" else 1)
        return today + timedelta(days=days if m.group(1) == "+" else -days)
    raise ValueError(f"bad date bound {text!r}; use YYYY-MM-DD, today, or [+-]N[d|w]")


@dataclass(frozen=True)
class _Scope:
    """Sibling context of a field, needed to validate ``format`` references."""

    locale: str
    earlier: tuple[str, ...] = ()
    later: tuple[str, ...] = ()


@functools.lru_cache(maxsize=8)
def _faker_for(locale: str) -> Any:
    from faker import Faker

    return Faker(locale)


# ---------------------------------------------------------------- small validators


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _need(spec: dict, key: str, path: str) -> Any:
    if key not in spec:
        raise SchemaError(f"{path}.{key}", "required key is missing")
    return spec[key]


def _int_at(value: Any, path: str, *, minimum: int | None = None) -> int:
    if not _is_int(value):
        raise SchemaError(path, f"must be an integer, got {value!r}")
    if minimum is not None and value < minimum:
        raise SchemaError(path, f"must be >= {minimum}, got {value}")
    return value


def _bool_at(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise SchemaError(path, f"must be true or false, got {value!r}")
    return value


def _str_at(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise SchemaError(path, f"must be a string, got {value!r}")
    return value


def _check_date_bound(value: Any, path: str) -> str:
    _str_at(value, path)
    try:
        parse_date_bound(value, date(2000, 1, 1))
    except ValueError as exc:
        raise SchemaError(path, str(exc)) from None
    return value


# ---------------------------------------------------------------- field rules


def _normalise_rules(spec: dict, path: str, out: dict) -> None:
    """Validate the length/pad/on_invalid/min/max rules of a scalar and copy them into ``out``."""
    length = spec.get("length")
    min_len = spec.get("min_length")
    max_len = spec.get("max_length")
    if length is not None:
        if min_len is not None or max_len is not None:
            raise SchemaError(f"{path}.length", "length cannot be combined with min_length/max_length")
        _int_at(length, f"{path}.length", minimum=0)
        min_len = max_len = length
    if min_len is not None:
        _int_at(min_len, f"{path}.min_length", minimum=0)
    if max_len is not None:
        _int_at(max_len, f"{path}.max_length", minimum=0)
    if min_len is not None and max_len is not None and min_len > max_len:
        raise SchemaError(f"{path}.min_length", f"min_length {min_len} is greater than max_length {max_len}")
    if min_len is not None:
        out["min_length"] = min_len
    if max_len is not None:
        out["max_length"] = max_len

    if "pad" in spec:
        out["pad"] = _normalise_pad(spec["pad"], f"{path}.pad")
        if min_len is None:
            raise SchemaError(f"{path}.pad", "pad needs length or min_length")

    if "on_invalid" in spec:
        if spec["on_invalid"] not in ON_INVALID:
            raise SchemaError(f"{path}.on_invalid", f"must be one of {', '.join(ON_INVALID)}")
        out["on_invalid"] = spec["on_invalid"]


def _normalise_pad(pad: Any, path: str) -> dict:
    if isinstance(pad, str):
        pad = {"char": pad, "side": "left"}
    if not isinstance(pad, dict):
        raise SchemaError(path, "must be a one-character string or {char, side}")
    extra = sorted(set(pad) - {"char", "side"})
    if extra:
        raise SchemaError(f"{path}.{extra[0]}", "unknown key")
    char = pad.get("char", " ")
    side = pad.get("side", "left")
    if not isinstance(char, str) or len(char) != 1:
        raise SchemaError(f"{path}.char", "pad char must be exactly one character")
    if side not in ("left", "right"):
        raise SchemaError(f"{path}.side", "side must be 'left' or 'right'")
    return {"char": char, "side": side}


def _normalise_bounds(spec: dict, path: str, out: dict, kind: str) -> None:
    """Validate ``min``/``max``. ``kind`` is "int" or "number" (they define the range) or "compare"."""
    present = [k for k in ("min", "max") if k in spec]
    for key in present:
        value = spec[key]
        if kind == "int":
            if not _is_int(value):
                raise SchemaError(f"{path}.{key}", f"must be an integer, got {value!r}")
        elif kind == "number":
            if not _is_number(value):
                raise SchemaError(f"{path}.{key}", f"must be a number, got {value!r}")
        elif isinstance(value, str):
            _check_date_bound(value, f"{path}.{key}")
        elif not _is_number(value):
            raise SchemaError(f"{path}.{key}", f"must be a number or an ISO date string, got {value!r}")
        out[key] = value
    if len(present) == 2:
        lo, hi = spec["min"], spec["max"]
        if isinstance(lo, str) != isinstance(hi, str):
            raise SchemaError(f"{path}.min", "min and max must both be numbers or both be dates")
        if isinstance(lo, str):
            # Relative bounds ("today", "-30d") resolve against the same reference day, so order is preserved.
            ref = date(2000, 1, 1)
            lo, hi = parse_date_bound(lo, ref), parse_date_bound(hi, ref)
        if lo > hi:
            raise SchemaError(f"{path}.min", f"min {spec['min']} is greater than max {spec['max']}")


# ---------------------------------------------------------------- field normalisation


def _format_names(fmt: str, path: str) -> list[str]:
    """All field names a ``str.format`` template refers to, including nested format specs."""
    names: list[str] = []
    try:
        for _, name, fspec, _ in string.Formatter().parse(fmt):
            if name is not None:
                names.append(name)
            if fspec:
                names.extend(_format_names(fspec, path))
    except ValueError as exc:
        raise SchemaError(path, f"bad format string: {exc}") from None
    return names


def _check_format_refs(fmt: str, path: str, scope: _Scope) -> None:
    for name in _format_names(fmt, path):
        m = _FORMAT_NAME.match(name)
        if not m:
            raise SchemaError(path, f"unsupported reference {{{name}}}; use a sibling name or params")
        first = m.group(1)
        if first == "params" or first in scope.earlier:
            continue
        if first in scope.later:
            raise SchemaError(path, f"format refers to sibling {first!r}, which comes later")
        raise SchemaError(path, f"format refers to {first!r}, which is not an earlier sibling")


def _normalise_fields(fields: Any, path: str, locale: str) -> dict[str, dict]:
    """Normalise a dict of named fields; ``path`` is where the dict lives."""
    if not isinstance(fields, dict):
        raise SchemaError(path, "must be an object of field specs")
    names = list(fields)
    out: dict[str, dict] = {}
    for i, name in enumerate(names):
        if not isinstance(name, str) or not name:
            raise SchemaError(path, f"field names must be non-empty strings, got {name!r}")
        scope = _Scope(locale, tuple(names[:i]), tuple(names[i + 1 :]))
        out[name] = _normalise_field(fields[name], f"{path}.{name}", scope)
    return out


def _normalise_field(raw: Any, path: str, scope: _Scope) -> dict:
    """Normalise one field spec into a dict that always carries ``type`` and explicit defaults."""
    if isinstance(raw, str):
        raw = {"faker": raw}
    if not isinstance(raw, dict):
        raise SchemaError(path, "a field must be a string (Faker method) or an object")
    typ = raw.get("type")
    if typ is None:
        if "faker" not in raw:
            raise SchemaError(f"{path}.type", "required key is missing (or give 'faker')")
        typ = "faker"
    if typ not in _TYPE_KEYS:
        raise SchemaError(f"{path}.type", f"unknown type {typ!r}")

    container = typ in CONTAINERS
    rules_used = sorted(RULE_KEYS & set(raw))
    if container and rules_used:
        raise SchemaError(f"{path}.{rules_used[0]}", f"field rules are not allowed on a {typ}")
    allowed = _TYPE_KEYS[typ] | {"type"} | (frozenset() if container else RULE_KEYS)
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise SchemaError(f"{path}.{unknown[0]}", f"unknown key for type {typ!r}")

    out: dict[str, Any] = {"type": typ}
    _BUILDERS[typ](raw, path, scope, out)
    if not container:
        if typ not in ("int", "decimal"):
            _normalise_bounds(raw, path, out, "compare")
        _normalise_rules(raw, path, out)
    return out


def _b_faker(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    name = _str_at(_need(raw, "faker", path), f"{path}.faker")
    args = raw.get("args", {})
    if not isinstance(args, dict):
        raise SchemaError(f"{path}.args", "must be an object")
    try:
        fake = _faker_for(scope.locale)
    except Exception as exc:  # Faker raises AttributeError for an unknown locale
        raise SchemaError("locale", f"cannot load Faker locale {scope.locale!r}: {exc}") from None
    if not callable(getattr(fake, name, None)):
        raise SchemaError(f"{path}.faker", f"Faker has no method {name!r}")
    out.update(faker=name, args=dict(args))


def _b_int(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    _normalise_bounds({k: _need(raw, k, path) for k in ("min", "max")}, path, out, "int")


def _b_decimal(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    _normalise_bounds({k: _need(raw, k, path) for k in ("min", "max")}, path, out, "number")
    places = _int_at(raw.get("places", 2), f"{path}.places", minimum=0)
    out["places"] = places
    scale = Decimal(10) ** places
    lo = math.ceil(Decimal(str(raw["min"])) * scale)
    hi = math.floor(Decimal(str(raw["max"])) * scale)
    if lo > hi:
        raise SchemaError(path, f"no value with {places} decimal places lies between min and max")


def _b_date(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    start = _check_date_bound(_need(raw, "start", path), f"{path}.start")
    end = _check_date_bound(_need(raw, "end", path), f"{path}.end")
    if _ISO_DATE.match(start) and _ISO_DATE.match(end) and start > end:
        raise SchemaError(f"{path}.start", f"start {start} is after end {end}")
    out.update(start=start, end=end)
    if "format" in raw:
        out["format"] = _str_at(raw["format"], f"{path}.format")


def _b_string(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    charset = _str_at(raw.get("charset", "alnum"), f"{path}.charset")
    if not CHARSETS.get(charset, charset):
        raise SchemaError(f"{path}.charset", "charset must not be empty")
    out["charset"] = charset


def _values(raw: dict, path: str, *, required: bool) -> list | None:
    if "values" not in raw:
        if required:
            raise SchemaError(f"{path}.values", "required key is missing")
        return None
    values = raw["values"]
    if not isinstance(values, list) or not values:
        raise SchemaError(f"{path}.values", "must be a non-empty list")
    return values


def _b_choice(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    values = _values(raw, path, required=True)
    out["values"] = copy.deepcopy(values)
    if "weights" in raw:
        weights = raw["weights"]
        if not isinstance(weights, list) or len(weights) != len(values):
            raise SchemaError(f"{path}.weights", f"must be a list with one weight per value ({len(values)})")
        if not all(_is_number(w) and w >= 0 for w in weights) or sum(weights) <= 0:
            raise SchemaError(f"{path}.weights", "weights must be non-negative numbers with a positive sum")
        out["weights"] = list(weights)


def _b_constant(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    out["value"] = copy.deepcopy(_need(raw, "value", path))


def _b_sequence(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    out["start"] = _int_at(raw.get("start", 1), f"{path}.start")
    out["step"] = _int_at(raw.get("step", 1), f"{path}.step")


def _b_pattern(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    out["pattern"] = _str_at(_need(raw, "pattern", path), f"{path}.pattern")


def _b_format(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    fmt = _str_at(_need(raw, "format", path), f"{path}.format")
    _check_format_refs(fmt, f"{path}.format", scope)
    out["format"] = fmt


def _b_ssn(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    out["dashes"] = _bool_at(raw.get("dashes", True), f"{path}.dashes")
    out["safe"] = _bool_at(raw.get("safe", True), f"{path}.safe")


def _b_card(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    brand = raw.get("brand", "visa")
    if brand not in CARD_BRANDS:
        raise SchemaError(f"{path}.brand", f"must be one of {', '.join(CARD_BRANDS)}")
    out["brand"] = brand
    out["safe"] = _bool_at(raw.get("safe", True), f"{path}.safe")


def _b_routing(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    out["safe"] = _bool_at(raw.get("safe", True), f"{path}.safe")
    values = _values(raw, path, required=False)
    if values is not None:
        for i, v in enumerate(values):
            if not isinstance(v, str) or not is_valid_aba(v):
                raise SchemaError(f"{path}.values[{i}]", f"{v!r} is not a valid ABA routing number (bad checksum)")
        out["values"] = list(values)


def _b_account(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    for key in ("min_length", "length"):
        if raw.get(key) == 0:
            raise SchemaError(f"{path}.{key}", "an account number needs at least one digit")


def _b_object(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    fields = _need(raw, "fields", path)
    out["fields"] = _normalise_fields(fields, f"{path}.fields", scope.locale)


def _b_list(raw: dict, path: str, scope: _Scope, out: dict) -> None:
    out["count"] = _normalise_count(_need(raw, "count", path), f"{path}.count")
    has_fields, has_item = "fields" in raw, "item" in raw
    if has_fields == has_item:
        raise SchemaError(path, "a list needs exactly one of 'fields' (objects) or 'item' (scalars)")
    if has_fields:
        out["fields"] = _normalise_fields(raw["fields"], f"{path}.fields", scope.locale)
    else:
        item = _normalise_field(raw["item"], f"{path}.item", _Scope(scope.locale))
        if item["type"] in CONTAINERS:
            raise SchemaError(f"{path}.item", "item must be a scalar field; use 'fields' for objects")
        out["item"] = item


def _normalise_count(count: Any, path: str) -> int | dict[str, int]:
    if isinstance(count, dict):
        extra = sorted(set(count) - {"min", "max"})
        if extra:
            raise SchemaError(f"{path}.{extra[0]}", "unknown key")
        lo = _int_at(_need(count, "min", path), f"{path}.min", minimum=0)
        hi = _int_at(_need(count, "max", path), f"{path}.max", minimum=0)
        if lo > hi:
            raise SchemaError(path, f"min {lo} is greater than max {hi}")
        return {"min": lo, "max": hi}
    return _int_at(count, path, minimum=0)


_BUILDERS = {
    "faker": _b_faker,
    "int": _b_int,
    "decimal": _b_decimal,
    "date": _b_date,
    "string": _b_string,
    "choice": _b_choice,
    "constant": _b_constant,
    "sequence": _b_sequence,
    "pattern": _b_pattern,
    "format": _b_format,
    "ssn": _b_ssn,
    "card_number": _b_card,
    "routing_number": _b_routing,
    "account_number": _b_account,
    "object": _b_object,
    "list": _b_list,
}


# ---------------------------------------------------------------- public API


def schema_from_dict(raw: dict, path: Path | None) -> Schema:
    """Validate and normalise a raw schema dict. ``path`` is the file it came from, if any."""
    if not isinstance(raw, dict):
        raise SchemaError("<root>", "a schema must be a JSON object")
    for key in raw:
        if key in ("output", "outputs"):
            raise SchemaError(key, "outputs belong in a render spec, not in a schema")
    unknown = sorted(set(raw) - {"locale", "seed", "params", "data"})
    if unknown:
        raise SchemaError(unknown[0], "unknown top-level key (allowed: locale, seed, params, data)")

    locale = _str_at(raw.get("locale", "en_US"), "locale")
    seed = raw.get("seed")
    if seed is not None:
        _int_at(seed, "seed")
    params = raw.get("params", {})
    if not isinstance(params, dict):
        raise SchemaError("params", "must be an object")
    if "data" not in raw:
        raise SchemaError("data", "required key is missing")
    data = raw["data"]
    if not isinstance(data, dict):
        raise SchemaError("data", "must be an object")
    for key in data:
        if key in RESERVED_DATA_KEYS:
            raise SchemaError(f"data.{key}", f"{key!r} is reserved and cannot be a data key")

    normalised = _normalise_fields(data, "data", locale)
    return Schema(path=path, locale=locale, seed=seed, params=copy.deepcopy(params), data=normalised)


def load_schema(path: str | Path, overrides: list[str] | dict[str, Any] | None = None) -> Schema:
    """Read a schema JSON file, apply ``overrides`` to it, then validate it."""
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DatagenError(f"cannot read {p}: {exc.strerror or exc}") from None
    except json.JSONDecodeError as exc:
        raise SchemaError(str(p), f"invalid JSON: {exc}") from None
    if overrides:
        if not isinstance(raw, dict):
            raise SchemaError("<root>", "a schema must be a JSON object")
        apply_overrides(raw, overrides)
    return schema_from_dict(raw, p)


def _parse_override_value(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


def apply_overrides(raw: dict, sets: list[str] | dict[str, Any]) -> dict:
    """Apply dotted-path overrides to ``raw`` in place and return it.

    ``sets`` is a list of ``PATH=VALUE`` strings (value parsed as JSON, else kept as text) or a dict of
    path to ready value. Numeric segments index lists. The parent of the last segment must exist.
    """
    pairs: list[tuple[str, Any]] = []
    if isinstance(sets, dict):
        pairs = list(sets.items())
    else:
        for item in sets:
            path, eq, text = item.partition("=")
            if not eq or not path:
                raise SchemaError(item, "override must look like PATH=VALUE")
            pairs.append((path, _parse_override_value(text)))
    for path, value in pairs:
        _set_path(raw, path, value)
    return raw


def _set_path(raw: Any, path: str, value: Any) -> None:
    segments = path.split(".")
    if not all(segments):
        raise SchemaError(path, "empty segment in override path")
    node = raw
    walked: list[str] = []
    for seg in segments[:-1]:
        walked.append(seg)
        node = _step(node, seg, ".".join(walked), path)
    last = segments[-1]
    if isinstance(node, dict):
        node[last] = value
    elif isinstance(node, list):
        node[_index(node, last, path)] = value
    else:
        raise SchemaError(path, f"cannot set {last!r} on a non-container value")


def _index(node: list, seg: str, path: str) -> int:
    if not seg.isdigit() or int(seg) >= len(node):
        raise SchemaError(path, f"{seg!r} is not a valid index into a list of {len(node)}")
    return int(seg)


def _step(node: Any, seg: str, walked: str, path: str) -> Any:
    if isinstance(node, dict):
        if seg not in node:
            raise SchemaError(path, f"parent {walked!r} does not exist")
        return node[seg]
    if isinstance(node, list):
        return node[_index(node, seg, path)]
    raise SchemaError(path, f"{walked!r} is not an object or list")
