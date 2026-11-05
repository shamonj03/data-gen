from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import load_workbook

import datagen
from datagen import (
    DatagenError,
    generate_data,
    load_render_spec,
    load_schema,
    render,
    render_file,
    write,
)

NOW = datetime(2026, 1, 2, 10, 0)

SCHEMA = {
    "params": {"bank": "TB"},
    "data": {
        "customers": {
            "type": "list",
            "count": 6,
            "fields": {
                "customer_id": {"type": "sequence", "start": 1, "length": 8, "pad": "0"},
                "first_name": {"type": "faker", "faker": "first_name"},
                "balance": {"type": "decimal", "min": 0, "max": 1000},
            },
        }
    },
}


def jwrite(path: Path, obj: dict) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


@pytest.fixture
def schema_path(tmp_path: Path) -> Path:
    return jwrite(tmp_path / "schema.json", SCHEMA)


def table_output(**extra) -> dict:
    return {"table": {"rows": "customers", "columns": ["customer_id", "first_name"]}, **extra}


def make_spec(tmp_path: Path, spec: dict, name: str = "spec.json") -> Path:
    return jwrite(tmp_path / name, spec)


def csv_rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def xlsx_rows(data: bytes) -> list[list]:
    ws = load_workbook(io.BytesIO(data)).active
    return [[c.value for c in row] for row in ws.iter_rows()]


# ---------------------------------------------------------------- load_render_spec


def test_spec_with_path_schema(tmp_path, schema_path):
    spec = make_spec(tmp_path, {"schema": "schema.json", "output": table_output()})
    loaded = load_render_spec(spec)
    assert loaded.schema.path == schema_path.resolve()
    assert loaded.outputs[0].table.rows == "customers"


def test_spec_with_inline_schema(tmp_path):
    spec = make_spec(tmp_path, {"schema": SCHEMA, "output": table_output()})
    loaded = load_render_spec(spec)
    assert loaded.schema.path is None
    assert loaded.schema.params == {"bank": "TB"}


def test_spec_set_changes_count(tmp_path, schema_path):
    spec = make_spec(
        tmp_path,
        {"schema": "schema.json", "set": {"data.customers.count": 2}, "output": table_output()},
    )
    assert len(render(spec, seed=1, now=NOW)["output"].splitlines()) == 3


def test_cli_set_applies_after_spec_set(tmp_path, schema_path):
    spec = make_spec(
        tmp_path,
        {"schema": "schema.json", "set": {"data.customers.count": 2}, "output": table_output()},
    )
    loaded = load_render_spec(spec, ["data.customers.count=4"])
    assert loaded.schema.data["customers"]["count"] == 4


def test_set_output_delimiter_reaches_output(tmp_path, schema_path):
    spec = make_spec(tmp_path, {"schema": "schema.json", "output": table_output()})
    loaded = load_render_spec(spec, ["output.delimiter=tab"])
    assert loaded.outputs[0].delimiter == "\t"


def test_set_outputs_index_reaches_right_output(tmp_path, schema_path):
    spec = make_spec(
        tmp_path,
        {
            "schema": "schema.json",
            "outputs": [table_output(file="a.csv"), table_output(file="b.csv")],
        },
    )
    loaded = load_render_spec(spec, ["outputs.1.table.header=false"])
    assert loaded.outputs[0].table.header is True
    assert loaded.outputs[1].table.header is False


# ---------------------------------------------------------------- generate_data


def test_generate_data_from_schema_and_from_spec(tmp_path, schema_path):
    spec = make_spec(tmp_path, {"schema": "schema.json", "output": table_output()})
    a = generate_data(schema_path, seed=5, now=NOW)
    b = generate_data(spec, seed=5, now=NOW)
    assert a == b
    assert len(a["customers"]) == 6


def test_generate_data_overrides(schema_path):
    data = generate_data(schema_path, seed=5, now=NOW, overrides=["data.customers.count=2"])
    assert len(data["customers"]) == 2


def test_seed_precedence_argument_then_schema(tmp_path):
    seeded = dict(SCHEMA, seed=99)
    p = jwrite(tmp_path / "s.json", seeded)
    assert generate_data(p, now=NOW) == generate_data(p, seed=99, now=NOW)
    assert generate_data(p, seed=1, now=NOW) != generate_data(p, now=NOW)


def test_random_seed_when_none_given(schema_path):
    seed = datagen.resolve_seed(load_schema(schema_path), None)
    assert 1 <= seed < 2**31


def test_generate_data_rejects_unknown_file(tmp_path):
    p = jwrite(tmp_path / "x.json", {"hello": 1})
    with pytest.raises(DatagenError):
        generate_data(p)


# ---------------------------------------------------------------- render / write


def three_outputs(tmp_path: Path) -> Path:
    return make_spec(
        tmp_path,
        {
            "schema": "schema.json",
            "outputs": [
                table_output(file="c_{now:%Y%m%d}.csv"),
                table_output(file="c.txt", delimiter="pipe", quoting="none"),
                table_output(file="c.xlsx", sheet_name="Customers"),
            ],
        },
    )


def test_render_returns_names_text_and_bytes(tmp_path, schema_path):
    result = render(three_outputs(tmp_path), seed=3, now=NOW)
    assert list(result) == ["c_20260102.csv", "c.txt", "c.xlsx"]
    assert isinstance(result["c_20260102.csv"], str)
    assert isinstance(result["c.xlsx"], bytes)
    assert result["c.txt"].splitlines()[0] == "customer_id|first_name"


def test_write_creates_three_files_with_shared_data(tmp_path, schema_path):
    out = tmp_path / "deep" / "out"
    paths = write(three_outputs(tmp_path), out, seed=3, now=NOW)
    assert [p.name for p in paths] == ["c_20260102.csv", "c.txt", "c.xlsx"]
    assert all(p.is_file() for p in paths)
    csv_ids = [r[0] for r in csv_rows(paths[0].read_text(encoding="utf-8"))[1:]]
    xlsx = xlsx_rows(paths[2].read_bytes())
    assert [r[0] for r in xlsx[1:]] == csv_ids
    assert xlsx[0] == ["customer_id", "first_name"]
    assert load_workbook(paths[2]).active.title == "Customers"
    txt_ids = [line.split("|")[0] for line in paths[1].read_text(encoding="utf-8").splitlines()[1:]]
    assert txt_ids == csv_ids


def test_two_specs_one_schema_same_seed_same_customers(tmp_path, schema_path):
    a = make_spec(tmp_path, {"schema": "schema.json", "output": table_output()}, "a.json")
    b = make_spec(
        tmp_path,
        {"schema": "schema.json", "output": {"table": {"rows": "customers", "columns": ["customer_id", "first_name"]}, "delimiter": ";"}},
        "b.json",
    )
    ra = render(a, seed=11, now=NOW)["output"]
    rb = render(b, seed=11, now=NOW)["output"]
    assert ra.replace(",", ";") == rb


def test_render_only_selects_one(tmp_path, schema_path):
    result = render(three_outputs(tmp_path), seed=3, now=NOW, only="c.txt")
    assert list(result) == ["c.txt"]


def test_render_only_unknown_is_error(tmp_path, schema_path):
    with pytest.raises(DatagenError, match="matches no output"):
        render(three_outputs(tmp_path), seed=3, now=NOW, only="nope.csv")


def test_render_unnamed_output_key(tmp_path, schema_path):
    spec = make_spec(tmp_path, {"schema": "schema.json", "output": table_output()})
    assert list(render(spec, seed=1, now=NOW)) == ["output"]


def test_params_and_seed_in_file_name(tmp_path):
    spec = make_spec(
        tmp_path,
        {"schema": SCHEMA, "output": table_output(file="{params[bank]}_{seed}.csv")},
    )
    assert list(render(spec, seed=7, now=NOW)) == ["TB_7.csv"]


def test_template_output_gets_context(tmp_path, schema_path):
    (tmp_path / "t.j2").write_text(
        "{{ params.bank }} {{ seed }} {{ now | datefmt('%Y%m%d') }} {{ customers | length }}\n",
        encoding="utf-8",
    )
    spec = make_spec(tmp_path, {"schema": "schema.json", "output": {"template": "t.j2"}})
    assert render(spec, seed=4, now=NOW)["output"] == "TB 4 20260102 6\n"


def test_same_seed_identical_output(tmp_path, schema_path):
    spec = make_spec(tmp_path, {"schema": "schema.json", "output": table_output()})
    assert render(spec, seed=8, now=NOW) == render(spec, seed=8, now=NOW)


# ---------------------------------------------------------------- render_file


def test_render_file_single_output(tmp_path, schema_path):
    spec = make_spec(tmp_path, {"schema": "schema.json", "output": table_output()})
    text = render_file(spec, seed=1, now=NOW)
    assert isinstance(text, str) and text.startswith("customer_id,first_name\n")


def test_render_file_writes_out_and_keeps_crlf(tmp_path, schema_path):
    spec = make_spec(tmp_path, {"schema": "schema.json", "output": table_output(newline="\r\n")})
    out = tmp_path / "res" / "x.csv"
    text = render_file(spec, seed=1, now=NOW, out=out)
    assert out.read_bytes() == text.encode("utf-8")
    assert b"\r\n" in out.read_bytes()
    assert b"\n" not in out.read_bytes().replace(b"\r\n", b"")


def test_render_file_multiple_outputs_is_error(tmp_path, schema_path):
    with pytest.raises(DatagenError, match="exactly one output"):
        render_file(three_outputs(tmp_path), seed=1, now=NOW)


def test_render_file_xlsx_out_with_output_key(tmp_path, schema_path):
    spec = make_spec(tmp_path, {"schema": "schema.json", "output": table_output()})
    out = tmp_path / "x.xlsx"
    result = render_file(spec, seed=1, now=NOW, out=out)
    assert isinstance(result, bytes)
    assert xlsx_rows(out.read_bytes())[0] == ["customer_id", "first_name"]


def test_render_file_xlsx_out_with_single_item_outputs(tmp_path, schema_path):
    spec = make_spec(tmp_path, {"schema": "schema.json", "outputs": [table_output(file="a.csv")]})
    out = tmp_path / "x.xlsx"
    assert isinstance(render_file(spec, seed=1, now=NOW, out=out), bytes)
    assert load_workbook(out).active.max_row == 7


def test_render_file_xlsx_out_with_text_only_key_surfaces_error(tmp_path, schema_path):
    spec = make_spec(tmp_path, {"schema": "schema.json", "output": table_output(newline="\r\n")})
    with pytest.raises(DatagenError, match="text-only"):
        render_file(spec, seed=1, now=NOW, out=tmp_path / "x.xlsx")


def test_non_utf8_encoding_is_written_in_that_encoding(tmp_path):
    schema = {"data": {"rows": {"type": "list", "count": 1, "fields": {"c": {"type": "constant", "value": "café"}}}}}
    spec = make_spec(
        tmp_path,
        {"schema": schema, "output": {"table": {"rows": "rows"}, "encoding": "latin-1"}},
    )
    out = tmp_path / "l.csv"
    render_file(spec, seed=1, now=NOW, out=out)
    assert out.read_bytes() == b"c\ncaf\xe9\n"
