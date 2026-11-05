from __future__ import annotations

import json
from pathlib import Path

import pytest

from datagen.errors import DatagenError, SchemaError
from datagen.schema import apply_overrides, load_schema, schema_from_dict


def schema(data: dict, **top) -> object:
    return schema_from_dict({"data": data, **top}, None)


def err(data: dict, **top) -> SchemaError:
    with pytest.raises(SchemaError) as exc:
        schema(data, **top)
    return exc.value


# ------------------------------------------------------------------ top level


def test_load_schema_roundtrip(tmp_path: Path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"locale": "en_US", "seed": 5, "params": {"a": 1}, "data": {"x": {"type": "constant", "value": 1}}}))
    s = load_schema(p)
    assert (s.path, s.locale, s.seed, s.params) == (p, "en_US", 5, {"a": 1})
    assert s.data == {"x": {"type": "constant", "value": 1}}


def test_defaults():
    s = schema({"x": {"type": "sequence"}})
    assert (s.locale, s.seed, s.params) == ("en_US", None, {})
    assert s.data["x"] == {"type": "sequence", "start": 1, "step": 1}


def test_load_schema_overrides_applied_before_validation(tmp_path: Path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"params": {"a": 1}, "data": {"x": {"type": "int", "min": 1, "max": 2}}}))
    s = load_schema(p, ["data.x.max=9", "params.a=hello"])
    assert s.data["x"]["max"] == 9
    assert s.params["a"] == "hello"


def test_load_schema_bad_json_and_missing(tmp_path: Path):
    p = tmp_path / "s.json"
    p.write_text("{nope")
    with pytest.raises(SchemaError) as exc:
        load_schema(p)
    assert "invalid JSON" in str(exc.value)
    with pytest.raises(DatagenError):
        load_schema(tmp_path / "missing.json")


@pytest.mark.parametrize("key", ["output", "outputs"])
def test_outputs_rejected_with_hint(key: str):
    with pytest.raises(SchemaError) as exc:
        schema_from_dict({"data": {}, key: []}, None)
    assert exc.value.path == key
    assert "outputs belong in a render spec" in str(exc.value)


def test_unknown_top_level_key():
    with pytest.raises(SchemaError) as exc:
        schema_from_dict({"data": {}, "extra": 1}, None)
    assert exc.value.path == "extra"


def test_missing_data_and_bad_top_level_types():
    with pytest.raises(SchemaError, match="data"):
        schema_from_dict({}, None)
    with pytest.raises(SchemaError, match="data"):
        schema_from_dict({"data": []}, None)
    with pytest.raises(SchemaError, match="params"):
        schema_from_dict({"data": {}, "params": []}, None)
    with pytest.raises(SchemaError, match="seed"):
        schema_from_dict({"data": {}, "seed": "x"}, None)
    with pytest.raises(SchemaError, match="locale"):
        schema_from_dict({"data": {}, "locale": 3}, None)
    with pytest.raises(SchemaError):
        schema_from_dict([], None)  # type: ignore[arg-type]


@pytest.mark.parametrize("key", ["params", "now", "seed"])
def test_reserved_data_keys(key: str):
    assert f"data.{key}" in str(err({key: {"type": "sequence"}}))


def test_bad_locale():
    e = err({"x": "name"}, locale="xx_NOPE")
    assert e.path == "locale"


# ------------------------------------------------------------------ normalisation


def test_string_shorthand_becomes_faker():
    s = schema({"n": "name"})
    assert s.data["n"] == {"type": "faker", "faker": "name", "args": {}}


def test_faker_dict_without_type_gets_type_and_rules():
    s = schema({"n": {"faker": "first_name", "args": {}, "length": 6, "pad": "0"}})
    assert s.data["n"] == {
        "type": "faker",
        "faker": "first_name",
        "args": {},
        "min_length": 6,
        "max_length": 6,
        "pad": {"char": "0", "side": "left"},
    }


def test_pad_dict_defaults():
    s = schema({"n": {"type": "sequence", "min_length": 4, "pad": {"char": "x"}}})
    assert s.data["n"]["pad"] == {"char": "x", "side": "left"}


def test_nested_normalisation():
    s = schema(
        {
            "people": {
                "type": "list",
                "count": {"min": 1, "max": 3},
                "fields": {"name": "name", "addr": {"type": "object", "fields": {"zip": "zipcode"}}},
            },
            "tags": {"type": "list", "count": 2, "item": {"type": "choice", "values": ["a", "b"]}},
        }
    )
    assert s.data["people"]["fields"]["name"]["faker"] == "name"
    assert s.data["people"]["fields"]["addr"]["fields"]["zip"]["faker"] == "zipcode"
    assert s.data["tags"]["item"]["type"] == "choice"


def test_params_are_copied():
    params = {"a": [1]}
    s = schema_from_dict({"data": {}, "params": params}, None)
    params["a"].append(2)
    assert s.params == {"a": [1]}


# ------------------------------------------------------------------ one valid spec per type


VALID = {
    "faker": {"faker": "name"},
    "int": {"type": "int", "min": 1, "max": 5},
    "decimal": {"type": "decimal", "min": 0, "max": 10.5, "places": 1},
    "date": {"type": "date", "start": "-30d", "end": "today", "format": "%Y"},
    "string": {"type": "string", "charset": "xyz", "min_length": 2, "max_length": 4},
    "choice": {"type": "choice", "values": [1, 2], "weights": [1, 3]},
    "constant": {"type": "constant", "value": None},
    "sequence": {"type": "sequence", "start": 5, "step": 2},
    "pattern": {"type": "pattern", "pattern": "AB-##-??"},
    "format": {"type": "format", "format": "{params[x]}"},
    "ssn": {"type": "ssn", "dashes": False, "safe": False},
    "card_number": {"type": "card_number", "brand": "amex", "safe": True},
    "routing_number": {"type": "routing_number", "values": ["011000015"]},
    "account_number": {"type": "account_number", "length": 12},
    "object": {"type": "object", "fields": {"a": "name"}},
    "list": {"type": "list", "count": 0, "item": "name"},
}


@pytest.mark.parametrize("name", sorted(VALID))
def test_every_type_loads(name: str):
    s = schema({"f": VALID[name]})
    assert s.data["f"]["type"] == (name if name != "faker" else "faker")


def test_explicit_faker_type():
    assert schema({"f": {"type": "faker", "faker": "name"}}).data["f"]["type"] == "faker"


# ------------------------------------------------------------------ load-time errors (each asserts the dotted path)


def test_unknown_type():
    e = err({"a": {"type": "wat"}})
    assert e.path == "data.a.type"


def test_field_must_be_string_or_object():
    assert err({"a": 5}).path == "data.a"


def test_missing_type_and_faker():
    assert err({"a": {"min": 1}}).path == "data.a.type"


@pytest.mark.parametrize(
    "spec, key",
    [
        ({"type": "int", "min": 1}, "max"),
        ({"type": "int", "max": 1}, "min"),
        ({"type": "decimal", "min": 1}, "max"),
        ({"type": "date", "start": "today"}, "end"),
        ({"type": "date", "end": "today"}, "start"),
        ({"type": "choice"}, "values"),
        ({"type": "constant"}, "value"),
        ({"type": "pattern"}, "pattern"),
        ({"type": "format"}, "format"),
        ({"type": "object"}, "fields"),
        ({"type": "list", "fields": {"a": "name"}}, "count"),
        ({"faker": None}, "faker"),
    ],
)
def test_missing_required_key(spec: dict, key: str):
    if spec == {"faker": None}:
        spec = {"type": "faker"}
    e = err({"outer": {"type": "object", "fields": {"a": spec}}})
    assert e.path == f"data.outer.fields.a.{key}"


def test_unknown_key():
    e = err({"a": {"type": "int", "min": 1, "max": 2, "bogus": 1}})
    assert e.path == "data.a.bogus"
    assert err({"a": {"type": "constant", "value": 1, "start": 1}}).path == "data.a.start"


def test_faker_method_missing_or_not_callable():
    assert err({"a": "no_such_method_xyz"}).path == "data.a.faker"
    assert err({"a": {"faker": "locales"}}).path == "data.a.faker"  # an attribute, not callable
    assert err({"a": {"faker": "name", "args": []}}).path == "data.a.args"


def test_weights_and_values():
    assert err({"a": {"type": "choice", "values": [1, 2], "weights": [1]}}).path == "data.a.weights"
    assert err({"a": {"type": "choice", "values": []}}).path == "data.a.values"
    assert err({"a": {"type": "choice", "values": [1], "weights": [0]}}).path == "data.a.weights"
    assert err({"a": {"type": "choice", "values": [1], "weights": ["x"]}}).path == "data.a.weights"


def test_routing_checksum_in_values():
    e = err({"a": {"type": "routing_number", "values": ["011000015", "011000016"]}})
    assert e.path == "data.a.values[1]"


def test_negative_count_and_bad_counts():
    assert err({"a": {"type": "list", "count": -1, "item": "name"}}).path == "data.a.count"
    assert err({"a": {"type": "list", "count": {"min": -1, "max": 2}, "item": "name"}}).path == "data.a.count.min"
    assert err({"a": {"type": "list", "count": {"min": 3, "max": 2}, "item": "name"}}).path == "data.a.count"
    assert err({"a": {"type": "list", "count": "3", "item": "name"}}).path == "data.a.count"
    assert err({"a": {"type": "list", "count": {"min": 1, "max": 2, "x": 1}, "item": "name"}}).path == "data.a.count.x"


def test_list_needs_exactly_one_of_fields_item():
    assert err({"a": {"type": "list", "count": 1}}).path == "data.a"
    assert err({"a": {"type": "list", "count": 1, "fields": {}, "item": "name"}}).path == "data.a"


def test_list_item_must_be_scalar():
    e = err({"a": {"type": "list", "count": 1, "item": {"type": "object", "fields": {"x": "name"}}}})
    assert e.path == "data.a.item"


def test_format_refs():
    ok = schema({"first": "first_name", "full": {"type": "format", "format": "{first} {params[x]!s:>5}"}})
    assert ok.data["full"]["format"].startswith("{first}")
    later = err({"full": {"type": "format", "format": "{last}"}, "last": "last_name"})
    assert later.path == "data.full.format" and "later" in later.msg
    missing = err({"full": {"type": "format", "format": "{nope}"}})
    assert missing.path == "data.full.format" and "nope" in missing.msg
    assert err({"a": {"type": "format", "format": "{"}}).path == "data.a.format"
    assert err({"a": {"type": "format", "format": "{params.__class__}"}}).path == "data.a.format"
    assert err({"a": {"type": "format", "format": "{}"}}).path == "data.a.format"


def test_format_in_nested_fields_sees_only_its_siblings():
    e = err(
        {
            "top": "name",
            "o": {"type": "object", "fields": {"f": {"type": "format", "format": "{top}"}}},
        }
    )
    assert e.path == "data.o.fields.f.format"


@pytest.mark.parametrize("bad", ["tomorrow", "3d", "+3", "+3m", "2024-13-01", "2024-1-1", "20240101", ""])
def test_bad_date_bounds(bad: str):
    assert err({"d": {"type": "date", "start": bad, "end": "today"}}).path == "data.d.start"
    assert err({"d": {"type": "date", "start": "today", "end": bad}}).path == "data.d.end"


def test_date_start_after_end_for_absolute_bounds():
    assert err({"d": {"type": "date", "start": "2024-02-01", "end": "2024-01-01"}}).path == "data.d.start"


def test_min_max_and_misc_value_checks():
    assert err({"a": {"type": "int", "min": 5, "max": 1}}).path == "data.a.min"
    assert err({"a": {"type": "int", "min": 1.5, "max": 3}}).path == "data.a.min"
    assert err({"a": {"type": "decimal", "min": "x", "max": 3}}).path == "data.a.min"
    assert err({"a": {"type": "decimal", "min": 0.001, "max": 0.002, "places": 2}}).path == "data.a"
    assert err({"a": {"type": "decimal", "min": 0, "max": 1, "places": -1}}).path == "data.a.places"
    assert err({"a": {"faker": "name", "min": 5, "max": 1}}).path == "data.a.min"
    assert err({"a": {"faker": "name", "min": 1, "max": "2024-01-01"}}).path == "data.a.min"
    assert err({"a": {"faker": "name", "min": "nonsense"}}).path == "data.a.min"
    assert err({"a": {"faker": "name", "min": "2024-05-01", "max": "2024-01-01"}}).path == "data.a.min"
    assert err({"a": {"type": "ssn", "safe": "yes"}}).path == "data.a.safe"
    assert err({"a": {"type": "card_number", "brand": "diners"}}).path == "data.a.brand"
    assert err({"a": {"type": "string", "charset": ""}}).path == "data.a.charset"
    assert err({"a": {"type": "sequence", "start": "1"}}).path == "data.a.start"
    assert err({"a": {"type": "account_number", "length": 0}}).path == "data.a.length"


# ------------------------------------------------------------------ rule load checks


def test_rule_load_checks():
    assert err({"a": {"faker": "name", "min_length": 5, "max_length": 2}}).path == "data.a.min_length"
    assert err({"a": {"faker": "name", "length": 5, "min_length": 2}}).path == "data.a.length"
    assert err({"a": {"faker": "name", "length": 5, "max_length": 2}}).path == "data.a.length"
    assert err({"a": {"faker": "name", "length": 5, "pad": "ab"}}).path == "data.a.pad.char"
    assert err({"a": {"faker": "name", "length": 5, "pad": {"char": "", "side": "left"}}}).path == "data.a.pad.char"
    assert err({"a": {"faker": "name", "length": 5, "pad": {"char": "0", "side": "up"}}}).path == "data.a.pad.side"
    assert err({"a": {"faker": "name", "length": 5, "pad": {"char": "0", "extra": 1}}}).path == "data.a.pad.extra"
    assert err({"a": {"faker": "name", "length": 5, "pad": 5}}).path == "data.a.pad"
    assert err({"a": {"faker": "name", "on_invalid": "explode"}}).path == "data.a.on_invalid"
    assert err({"a": {"faker": "name", "length": -1}}).path == "data.a.length"
    assert err({"a": {"faker": "name", "length": "5"}}).path == "data.a.length"


def test_pad_without_length_is_an_error():
    e = err({"a": {"faker": "name", "pad": "0"}})
    assert e.path == "data.a.pad"
    # max_length alone is not enough to pad to
    assert err({"a": {"faker": "name", "max_length": 5, "pad": "0"}}).path == "data.a.pad"


@pytest.mark.parametrize("typ", ["list", "object"])
@pytest.mark.parametrize("rule", ["min", "max", "length", "min_length", "max_length", "pad", "on_invalid"])
def test_rules_on_containers_rejected(typ: str, rule: str):
    spec: dict = {"type": typ, rule: 1}
    if typ == "list":
        spec.update(count=1, item="name")
    else:
        spec.update(fields={"a": "name"})
    e = err({"c": spec})
    assert e.path == f"data.c.{rule}"


# ------------------------------------------------------------------ overrides


def raw() -> dict:
    return {
        "params": {"bank": "A", "n": 1},
        "data": {"items": {"type": "list", "count": 3, "fields": {"a": "name"}}, "vals": [10, 20, 30]},
    }


def test_override_int_string_and_json():
    r = apply_overrides(raw(), ["params.n=7", "params.bank=ACME", 'params.obj={"k": [1]}', "params.b=true"])
    assert r["params"] == {"bank": "ACME", "n": 7, "obj": {"k": [1]}, "b": True}


def test_override_mutates_and_returns_same_dict():
    r = raw()
    assert apply_overrides(r, ["params.n=2"]) is r
    assert r["params"]["n"] == 2


def test_override_list_index():
    r = apply_overrides(raw(), ["data.vals.1=99", "data.items.fields.a=job"])
    assert r["data"]["vals"] == [10, 99, 30]
    assert r["data"]["items"]["fields"]["a"] == "job"


def test_override_new_key_on_existing_object():
    r = apply_overrides(raw(), ["params.fresh=x"])
    assert r["params"]["fresh"] == "x"


def test_override_dict_form_keeps_values_as_is():
    r = apply_overrides(raw(), {"params.n": 5, "params.bank": "1", "data.vals.0": [1, 2]})
    assert r["params"]["n"] == 5 and r["params"]["bank"] == "1"
    assert r["data"]["vals"][0] == [1, 2]


def test_override_value_may_contain_equals():
    r = apply_overrides(raw(), ["params.bank=a=b"])
    assert r["params"]["bank"] == "a=b"


@pytest.mark.parametrize(
    "bad",
    ["params.nope.deep=1", "nope.x=1", "data.vals.9=1", "data.vals.x=1", "params.n.deep=1", "noequals", "=1", "params..x=1"],
)
def test_override_bad_paths_raise(bad: str):
    with pytest.raises(SchemaError):
        apply_overrides(raw(), [bad])


def test_override_bad_path_in_dict_form():
    with pytest.raises(SchemaError):
        apply_overrides(raw(), {"params.nope.x": 1})


def test_override_error_mentions_path():
    with pytest.raises(SchemaError) as exc:
        apply_overrides(raw(), ["params.nope.deep=1"])
    assert exc.value.path == "params.nope.deep"
