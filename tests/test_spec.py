from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from datagen.errors import DatagenError, SchemaError
from datagen.spec import build_render_spec, detect_kind, format_filename, split_overrides
from datagen.types import OutputSpec, RenderSpec, Schema, TableSpec

SCHEMA = Schema(
    path=None,
    locale="en_US",
    seed=None,
    params={"bank": "TB"},
    data={
        "customers": {
            "type": "list",
            "count": 3,
            "fields": {
                "id": {"type": "int"},
                "name": {"type": "faker", "faker": "name"},
                "tags": {"type": "list", "count": 2, "item": {"type": "int"}},
                "address": {"type": "object", "fields": {"city": {"type": "faker", "faker": "city"}}},
                "bare": "name",
            },
        },
        "scalars": {"type": "list", "count": 2, "item": {"type": "int"}},
        "meta": {"type": "object", "fields": {"a": {"type": "int"}}},
        "only_containers": {
            "type": "list",
            "count": 1,
            "fields": {"x": {"type": "object", "fields": {}}},
        },
    },
)


def spec(tmp_path: Path, raw: dict) -> RenderSpec:
    return build_render_spec({"schema": "s.json", **raw}, tmp_path / "spec.json", SCHEMA)


def one(tmp_path: Path, **output) -> OutputSpec:
    output.setdefault("table", {"rows": "customers"})
    return spec(tmp_path, {"output": output}).outputs[0]


def err(tmp_path: Path, raw: dict) -> SchemaError:
    with pytest.raises(SchemaError) as info:
        spec(tmp_path, raw)
    return info.value


# --- output vs outputs ---

def test_single_output(tmp_path: Path) -> None:
    rs = spec(tmp_path, {"output": {"table": {"rows": "customers"}}, "set": {"a": 1}})
    assert isinstance(rs, RenderSpec)
    assert rs.path == tmp_path / "spec.json"
    assert rs.schema is SCHEMA
    assert len(rs.outputs) == 1
    assert rs.outputs[0].file is None


def test_outputs_list(tmp_path: Path) -> None:
    rs = spec(tmp_path, {"outputs": [
        {"file": "a.csv", "table": {"rows": "customers"}},
        {"file": "b.csv", "table": {"rows": "customers"}},
    ]})
    assert [o.file for o in rs.outputs] == ["a.csv", "b.csv"]


def test_both_output_and_outputs(tmp_path: Path) -> None:
    t = {"rows": "customers"}
    e = err(tmp_path, {"output": {"table": t}, "outputs": [{"table": t}]})
    assert e.path == "outputs"


def test_neither_output_nor_outputs(tmp_path: Path) -> None:
    assert err(tmp_path, {}).path == "outputs"


def test_empty_outputs_list(tmp_path: Path) -> None:
    assert err(tmp_path, {"outputs": []}).path == "outputs"


def test_output_not_object(tmp_path: Path) -> None:
    assert err(tmp_path, {"output": "x"}).path == "output"
    assert err(tmp_path, {"outputs": ["x"]}).path == "outputs[0]"


def test_unknown_top_level_key(tmp_path: Path) -> None:
    e = err(tmp_path, {"output": {"table": {"rows": "customers"}}, "bogus": 1})
    assert e.path == "bogus"


def test_unknown_output_key(tmp_path: Path) -> None:
    e = err(tmp_path, {"outputs": [{"file": "a", "table": {"rows": "customers"}, "wat": 1}]})
    assert e.path == "outputs[0].wat"


# --- file rules ---

def test_file_required_with_several_outputs(tmp_path: Path) -> None:
    t = {"rows": "customers"}
    e = err(tmp_path, {"outputs": [{"file": "a.csv", "table": t}, {"table": t}]})
    assert e.path == "outputs[1].file"


def test_file_must_be_unique(tmp_path: Path) -> None:
    t = {"rows": "customers"}
    e = err(tmp_path, {"outputs": [{"file": "a.csv", "table": t}, {"file": "a.csv", "table": t}]})
    assert e.path == "outputs[1].file"


def test_xlsx_extension_infers_format(tmp_path: Path) -> None:
    assert one(tmp_path, file="x.xlsx").format == "xlsx"
    assert one(tmp_path, file="x.csv").format == "text"
    assert one(tmp_path).format == "text"


def test_explicit_format_wins_over_extension(tmp_path: Path) -> None:
    assert one(tmp_path, file="x.xlsx", format="text").format == "text"


def test_bad_format(tmp_path: Path) -> None:
    e = err(tmp_path, {"output": {"format": "pdf", "table": {"rows": "customers"}}})
    assert e.path == "output.format"


# --- template / table ---

def test_template_and_table_both(tmp_path: Path) -> None:
    (tmp_path / "t.j2").write_text("x")
    e = err(tmp_path, {"output": {"template": "t.j2", "table": {"rows": "customers"}}})
    assert e.path == "output"


def test_template_and_table_neither(tmp_path: Path) -> None:
    assert err(tmp_path, {"output": {"file": "a"}}).path == "output"


def test_template_resolved_relative_to_spec(tmp_path: Path) -> None:
    (tmp_path / "tpl").mkdir()
    (tmp_path / "tpl" / "t.j2").write_text("x")
    out = spec(tmp_path, {"output": {"template": "tpl/t.j2"}}).outputs[0]
    assert out.template == (tmp_path / "tpl" / "t.j2").resolve()
    assert out.template.is_absolute()
    assert out.table is None


def test_template_missing(tmp_path: Path) -> None:
    e = err(tmp_path, {"outputs": [{"file": "a", "table": {"rows": "customers"}},
                                   {"file": "b", "template": "nope.j2"}]})
    assert e.path == "outputs[1].template"


# --- delimiter, quoting, newline ---

@pytest.mark.parametrize("alias,char", [("comma", ","), ("pipe", "|"), ("tab", "\t"), ("semicolon", ";"),
                                        ("|", "|"), (",", ",")])
def test_delimiter_aliases(tmp_path: Path, alias: str, char: str) -> None:
    assert one(tmp_path, delimiter=alias).delimiter == char


def test_delimiter_default(tmp_path: Path) -> None:
    assert one(tmp_path).delimiter == ","


@pytest.mark.parametrize("bad", ["ab", "", "colon", 5])
def test_delimiter_invalid(tmp_path: Path, bad: object) -> None:
    e = err(tmp_path, {"outputs": [{"file": "a", "table": {"rows": "customers"}},
                                   {"file": "b", "table": {"rows": "customers"}, "delimiter": bad}]})
    assert e.path == "outputs[1].delimiter"


@pytest.mark.parametrize("q", ["minimal", "all", "none"])
def test_quoting_values(tmp_path: Path, q: str) -> None:
    assert one(tmp_path, quoting=q).quoting == q


def test_quoting_invalid(tmp_path: Path) -> None:
    assert err(tmp_path, {"output": {"quoting": "some", "table": {"rows": "customers"}}}).path == "output.quoting"


def test_newline(tmp_path: Path) -> None:
    assert one(tmp_path, newline="\r\n").newline == "\r\n"
    assert one(tmp_path).newline == "\n"
    assert err(tmp_path, {"output": {"newline": "\r", "table": {"rows": "customers"}}}).path == "output.newline"


# --- xlsx vs text-only keys ---

@pytest.mark.parametrize("key,value", [("newline", "\n"), ("line_width", 80), ("encoding", "ascii"),
                                       ("final_newline", False), ("postprocess", ["upper"])])
def test_xlsx_rejects_text_only_keys(tmp_path: Path, key: str, value: object) -> None:
    e = err(tmp_path, {"output": {"file": "a.xlsx", "table": {"rows": "customers"}, key: value}})
    assert e.path == f"output.{key}"


def test_xlsx_with_sheet_name_and_delimiter(tmp_path: Path) -> None:
    out = one(tmp_path, file="a.xlsx", sheet_name="Customers", delimiter="tab")
    assert out.format == "xlsx" and out.sheet_name == "Customers"


def test_text_keys_ok_for_text(tmp_path: Path) -> None:
    out = one(tmp_path, line_width=94, encoding="ascii", final_newline=False)
    assert (out.line_width, out.encoding, out.final_newline) == (94, "ascii", False)


def test_text_key_value_validation(tmp_path: Path) -> None:
    t = {"rows": "customers"}
    assert err(tmp_path, {"output": {"line_width": 0, "table": t}}).path == "output.line_width"
    assert err(tmp_path, {"output": {"encoding": "nope-9", "table": t}}).path == "output.encoding"
    assert err(tmp_path, {"output": {"final_newline": "yes", "table": t}}).path == "output.final_newline"


# --- postprocess ---

def test_postprocess_normalised(tmp_path: Path) -> None:
    out = one(tmp_path, postprocess=["upper", {"name": "pad", "width": 5}])
    assert out.postprocess == ({"name": "upper"}, {"name": "pad", "width": 5})
    assert isinstance(out.postprocess, tuple)


def test_postprocess_invalid(tmp_path: Path) -> None:
    t = {"rows": "customers"}
    assert err(tmp_path, {"output": {"postprocess": "upper", "table": t}}).path == "output.postprocess"
    assert err(tmp_path, {"output": {"postprocess": [{"x": 1}], "table": t}}).path == "output.postprocess[0]"


# --- table ---

def test_table_rows_unknown(tmp_path: Path) -> None:
    assert err(tmp_path, {"output": {"table": {"rows": "nope"}}}).path == "output.table.rows"


def test_table_rows_missing(tmp_path: Path) -> None:
    assert err(tmp_path, {"output": {"table": {}}}).path == "output.table.rows"


@pytest.mark.parametrize("rows", ["scalars", "meta"])
def test_table_rows_must_be_list_of_objects(tmp_path: Path, rows: str) -> None:
    assert err(tmp_path, {"output": {"table": {"rows": rows}}}).path == "output.table.rows"


def test_table_unknown_key_and_bad_header(tmp_path: Path) -> None:
    assert err(tmp_path, {"output": {"table": {"rows": "customers", "x": 1}}}).path == "output.table.x"
    assert err(tmp_path, {"output": {"table": {"rows": "customers", "header": "y"}}}).path == "output.table.header"


def test_default_columns_skip_containers(tmp_path: Path) -> None:
    table = one(tmp_path).table
    assert isinstance(table, TableSpec)
    assert table.columns == (("id", "id"), ("name", "name"), ("bare", "bare"))
    assert table.header is True
    assert table.rows == "customers"


def test_default_columns_all_containers(tmp_path: Path) -> None:
    e = err(tmp_path, {"output": {"table": {"rows": "only_containers"}}})
    assert e.path == "output.table.columns"


def test_custom_titles_and_mixed_columns(tmp_path: Path) -> None:
    table = one(tmp_path, table={
        "rows": "customers", "header": False,
        "columns": ["id", {"field": "name", "title": "Full Name"}, {"field": "bare"}],
    }).table
    assert table.columns == (("id", "id"), ("name", "Full Name"), ("bare", "bare"))
    assert table.header is False


def test_column_unknown_field(tmp_path: Path) -> None:
    e = err(tmp_path, {"outputs": [
        {"file": "a", "table": {"rows": "customers"}},
        {"file": "b", "table": {"rows": "customers", "columns": ["id", "zzz"]}},
    ]})
    assert e.path == "outputs[1].table.columns[1]"


@pytest.mark.parametrize("field", ["tags", "address"])
def test_column_container_rejected(tmp_path: Path, field: str) -> None:
    e = err(tmp_path, {"output": {"table": {"rows": "customers", "columns": [{"field": field}]}}})
    assert e.path == "output.table.columns[0]"


def test_column_bad_shape(tmp_path: Path) -> None:
    t = {"rows": "customers"}
    assert err(tmp_path, {"output": {"table": {**t, "columns": [5]}}}).path == "output.table.columns[0]"
    assert err(tmp_path, {"output": {"table": {**t, "columns": [{"title": "x"}]}}}).path == "output.table.columns[0].field"
    assert err(tmp_path, {"output": {"table": {**t, "columns": []}}}).path == "output.table.columns"


# --- detect_kind ---

def test_detect_kind() -> None:
    assert detect_kind({"data": {}}) == "schema"
    assert detect_kind({"schema": "x.json", "output": {}}) == "spec"
    with pytest.raises(DatagenError):
        detect_kind({"foo": 1})


# --- format_filename ---

def test_format_filename(tmp_path: Path) -> None:
    out = OutputSpec(file="cust_{now:%Y%m%d}_{seed}_{params[bank]}.csv")
    now = datetime(2026, 11, 5, 12, 0)
    assert format_filename(out, seed=7, now=now, params={"bank": "TB"}) == "cust_20261105_7_TB.csv"


def test_format_filename_none_and_plain() -> None:
    now = datetime(2026, 1, 1)
    assert format_filename(OutputSpec(), seed=1, now=now, params={}) == "output"
    assert format_filename(OutputSpec(file="a.csv"), seed=1, now=now, params={}) == "a.csv"


@pytest.mark.parametrize("name", ["{nope}", "{params[missing]}", "{", "{0}"])
def test_format_filename_errors(name: str) -> None:
    with pytest.raises(SchemaError) as info:
        format_filename(OutputSpec(file=name), seed=1, now=datetime(2026, 1, 1), params={})
    assert info.value.path == "output.file"


# --- split_overrides ---

def test_split_overrides() -> None:
    schema_sets, spec_sets = split_overrides([
        "data.customers.count=5", "output.delimiter=tab", "outputs.1.file=x.csv", "params.bank=Z", "outputsish=1",
    ])
    assert schema_sets == ["data.customers.count=5", "params.bank=Z", "outputsish=1"]
    assert spec_sets == ["output.delimiter=tab", "outputs.1.file=x.csv"]


def test_split_overrides_empty() -> None:
    assert split_overrides(None) == ([], [])
    assert split_overrides([]) == ([], [])
