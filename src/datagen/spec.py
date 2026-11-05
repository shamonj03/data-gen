"""Loading and validating render specs (the outputs half of a datagen run)."""

from __future__ import annotations

import codecs
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from datagen.errors import DatagenError, SchemaError
from datagen.types import OutputSpec, RenderSpec, Schema, TableSpec

_TOP_KEYS = {"schema", "set", "output", "outputs"}
_OUTPUT_KEYS = {
    "file", "format", "template", "table", "delimiter", "quoting", "newline",
    "line_width", "encoding", "final_newline", "postprocess", "sheet_name",
}
_TEXT_ONLY = ("newline", "line_width", "encoding", "final_newline", "postprocess")
_TABLE_KEYS = {"rows", "header", "columns"}
_DELIMITER_ALIASES = {"comma": ",", "pipe": "|", "tab": "\t", "semicolon": ";"}
_QUOTING = ("minimal", "all", "none")
_NEWLINES = ("\n", "\r\n")
_CONTAINERS = ("list", "object")


def detect_kind(raw: dict) -> str:
    """Return "schema" (has `data`) or "spec" (has `schema`); anything else is an error."""
    if "data" in raw:
        return "schema"
    if "schema" in raw:
        return "spec"
    raise DatagenError("not a datagen file: expected a top-level 'data' (schema) or 'schema' (render spec) key")


def split_overrides(overrides: list[str] | None) -> tuple[list[str], list[str]]:
    """Split `PATH=VALUE` overrides into (schema_overrides, spec_overrides) by first path segment."""
    schema_sets: list[str] = []
    spec_sets: list[str] = []
    for item in overrides or []:
        first = item.split("=", 1)[0].split(".", 1)[0].strip()
        (spec_sets if first in ("output", "outputs") else schema_sets).append(item)
    return schema_sets, spec_sets


def format_filename(output: OutputSpec, *, seed: int, now: datetime, params: dict) -> str:
    """Expand `{seed}`, `{now:...}` and `{params[x]}` in the output's file name."""
    if output.file is None:
        return "output"
    try:
        return output.file.format(seed=seed, now=now, params=params)
    except (KeyError, ValueError, IndexError) as exc:
        raise SchemaError("output.file", f"cannot format {output.file!r}: {type(exc).__name__}: {exc}") from exc


def load_render_spec(path: Path | str, overrides: list[str] | None = None) -> RenderSpec:
    """Read a render spec file, resolve its schema, apply `set` and overrides, and validate."""
    from datagen.schema import apply_overrides, schema_from_dict

    spec_path = Path(path).resolve()
    try:
        raw = json.loads(spec_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DatagenError(f"cannot read {spec_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise DatagenError(f"{spec_path}: invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise SchemaError("<root>", "a render spec must be a JSON object")
    if "schema" not in raw:
        raise SchemaError("schema", "required key is missing")

    schema_sets, spec_sets = split_overrides(overrides)
    if spec_sets:
        apply_overrides(raw, spec_sets)

    ref = raw["schema"]
    schema_path: Path | None
    if isinstance(ref, str):
        schema_path = (spec_path.parent / ref).resolve()
        try:
            raw_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise SchemaError("schema", f"cannot read {schema_path}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise SchemaError("schema", f"{schema_path}: invalid JSON: {exc}") from exc
    elif isinstance(ref, dict):
        schema_path, raw_schema = None, ref
    else:
        raise SchemaError("schema", "must be a path string or an inline schema object")
    if not isinstance(raw_schema, dict):
        raise SchemaError("schema", "a schema must be a JSON object")

    set_map = raw.get("set", {})
    if not isinstance(set_map, dict):
        raise SchemaError("set", "must be an object of dotted.path: value")
    if set_map:
        apply_overrides(raw_schema, set_map)
    if schema_sets:
        apply_overrides(raw_schema, schema_sets)

    schema = schema_from_dict(raw_schema, schema_path)
    return build_render_spec(raw, spec_path, schema)


def build_render_spec(raw: dict, spec_path: Path, schema: Schema) -> RenderSpec:
    """Validate the outputs of a raw spec against `schema` and return a normalised RenderSpec."""
    for key in raw:
        if key not in _TOP_KEYS:
            raise SchemaError(str(key), "unknown top-level key (allowed: schema, set, output, outputs)")
    has_one, has_many = "output" in raw, "outputs" in raw
    if has_one and has_many:
        raise SchemaError("outputs", "use either 'output' or 'outputs', not both")
    if not has_one and not has_many:
        raise SchemaError("outputs", "one of 'output' or 'outputs' is required")

    if has_one:
        items = [raw["output"]]
        prefixes = ["output"]
        if not isinstance(items[0], dict):
            raise SchemaError("output", "must be an object")
    else:
        items = raw["outputs"]
        if not isinstance(items, list) or not items:
            raise SchemaError("outputs", "must be a non-empty list of output objects")
        prefixes = [f"outputs[{i}]" for i in range(len(items))]
        for item, prefix in zip(items, prefixes):
            if not isinstance(item, dict):
                raise SchemaError(prefix, "must be an object")

    outputs = tuple(_build_output(item, prefix, spec_path, schema) for item, prefix in zip(items, prefixes))

    if len(outputs) > 1:
        seen: set[str] = set()
        for out, prefix in zip(outputs, prefixes):
            if out.file is None:
                raise SchemaError(f"{prefix}.file", "required when there is more than one output")
            if out.file in seen:
                raise SchemaError(f"{prefix}.file", f"duplicate file name {out.file!r}")
            seen.add(out.file)
    return RenderSpec(path=spec_path, schema=schema, outputs=outputs)


def _build_output(item: dict, p: str, spec_path: Path, schema: Schema) -> OutputSpec:
    """Validate one output object (`p` is its path prefix) and build an OutputSpec."""
    for key in item:
        if key not in _OUTPUT_KEYS:
            raise SchemaError(f"{p}.{key}", "unknown output key")

    file = item.get("file")
    if file is not None and (not isinstance(file, str) or not file):
        raise SchemaError(f"{p}.file", "must be a non-empty string")

    fmt = item.get("format")
    if fmt is None:
        fmt = "xlsx" if file is not None and file.lower().endswith(".xlsx") else "text"
    if fmt not in ("text", "xlsx"):
        raise SchemaError(f"{p}.format", f"must be 'text' or 'xlsx', got {fmt!r}")

    if ("template" in item) == ("table" in item):
        raise SchemaError(p, "exactly one of 'template' and 'table' must be set")

    template: Path | None = None
    table: TableSpec | None = None
    if "template" in item:
        template = _resolve_template(item["template"], f"{p}.template", spec_path)
    else:
        table = _build_table(item["table"], f"{p}.table", schema)

    delimiter = item.get("delimiter", ",")
    if not isinstance(delimiter, str):
        raise SchemaError(f"{p}.delimiter", "must be a string")
    delimiter = _DELIMITER_ALIASES.get(delimiter, delimiter)
    if len(delimiter) != 1:
        raise SchemaError(f"{p}.delimiter", f"must be one character or one of {sorted(_DELIMITER_ALIASES)}")

    quoting = item.get("quoting", "minimal")
    if quoting not in _QUOTING:
        raise SchemaError(f"{p}.quoting", f"must be one of {list(_QUOTING)}, got {quoting!r}")

    newline = item.get("newline", "\n")
    if newline not in _NEWLINES:
        raise SchemaError(f"{p}.newline", "must be '\\n' or '\\r\\n'")

    if fmt == "xlsx":
        for key in _TEXT_ONLY:
            if key in item:
                raise SchemaError(f"{p}.{key}", "is a text-only key and cannot be used with format 'xlsx'")

    line_width = item.get("line_width")
    if line_width is not None and (not isinstance(line_width, int) or isinstance(line_width, bool) or line_width < 1):
        raise SchemaError(f"{p}.line_width", "must be a positive integer")

    encoding = item.get("encoding", "utf-8")
    if not isinstance(encoding, str):
        raise SchemaError(f"{p}.encoding", "must be a string")
    try:
        codecs.lookup(encoding)
    except LookupError:
        raise SchemaError(f"{p}.encoding", f"unknown encoding {encoding!r}") from None

    final_newline = item.get("final_newline", True)
    if not isinstance(final_newline, bool):
        raise SchemaError(f"{p}.final_newline", "must be true or false")

    sheet_name = item.get("sheet_name", "Sheet1")
    if not isinstance(sheet_name, str) or not sheet_name:
        raise SchemaError(f"{p}.sheet_name", "must be a non-empty string")

    return OutputSpec(
        file=file, format=fmt, template=template, table=table, delimiter=delimiter, quoting=quoting,
        newline=newline, line_width=line_width, encoding=encoding, final_newline=final_newline,
        postprocess=_build_postprocess(item.get("postprocess", []), f"{p}.postprocess"),
        sheet_name=sheet_name,
    )


def _resolve_template(value: Any, p: str, spec_path: Path) -> Path:
    """Resolve a template path relative to the spec file; it must be an existing file."""
    if not isinstance(value, str) or not value:
        raise SchemaError(p, "must be a path string")
    resolved = (spec_path.parent / value).resolve()
    if not resolved.is_file():
        raise SchemaError(p, f"template file not found: {resolved}")
    return resolved


def _build_postprocess(value: Any, p: str) -> tuple[dict, ...]:
    """Normalise postprocess items: a string becomes {"name": ...}; dicts need a string `name`."""
    if not isinstance(value, list):
        raise SchemaError(p, "must be a list")
    out: list[dict] = []
    for i, entry in enumerate(value):
        if isinstance(entry, str):
            out.append({"name": entry})
        elif isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"]:
            out.append(dict(entry))
        else:
            raise SchemaError(f"{p}[{i}]", "must be a name string or an object with a 'name' string")
    return tuple(out)


def _is_container(field: Any) -> bool:
    """True for list/object field specs; a bare string (or anything else) is scalar."""
    return isinstance(field, dict) and field.get("type") in _CONTAINERS


def _build_table(value: Any, p: str, schema: Schema) -> TableSpec:
    """Validate a table block against the schema's top-level list and normalise its columns."""
    if not isinstance(value, dict):
        raise SchemaError(p, "must be an object")
    for key in value:
        if key not in _TABLE_KEYS:
            raise SchemaError(f"{p}.{key}", "unknown table key")

    rows = value.get("rows")
    if not isinstance(rows, str) or not rows:
        raise SchemaError(f"{p}.rows", "required: the name of a top-level list in the schema data")
    target = schema.data.get(rows)
    if target is None:
        raise SchemaError(f"{p}.rows", f"{rows!r} is not a top-level key of the schema data")
    if not (isinstance(target, dict) and target.get("type") == "list" and isinstance(target.get("fields"), dict)):
        raise SchemaError(f"{p}.rows", f"{rows!r} must be a list whose items are objects (a list with 'fields')")
    fields: dict = target["fields"]

    header = value.get("header", True)
    if not isinstance(header, bool):
        raise SchemaError(f"{p}.header", "must be true or false")

    if "columns" in value:
        columns = _build_columns(value["columns"], f"{p}.columns", fields)
    else:
        columns = tuple((name, name) for name, spec in fields.items() if not _is_container(spec))
        if not columns:
            raise SchemaError(f"{p}.columns", f"{rows!r} has no non-container fields to use as columns")
    return TableSpec(rows=rows, header=header, columns=columns)


def _build_columns(value: Any, p: str, fields: dict) -> tuple[tuple[str, str], ...]:
    """Normalise explicit columns to (field, title) tuples and check each against the item fields."""
    if not isinstance(value, list) or not value:
        raise SchemaError(p, "must be a non-empty list")
    out: list[tuple[str, str]] = []
    for i, col in enumerate(value):
        cp = f"{p}[{i}]"
        if isinstance(col, str):
            name, title = col, col
        elif isinstance(col, dict):
            for key in col:
                if key not in ("field", "title"):
                    raise SchemaError(f"{cp}.{key}", "unknown column key")
            name = col.get("field")
            if not isinstance(name, str):
                raise SchemaError(f"{cp}.field", "required: a field name")
            title = col.get("title", name)
            if not isinstance(title, str):
                raise SchemaError(f"{cp}.title", "must be a string")
        else:
            raise SchemaError(cp, "must be a field name or an object with 'field' and optional 'title'")
        if name not in fields:
            raise SchemaError(cp, f"unknown field {name!r}")
        if _is_container(fields[name]):
            raise SchemaError(cp, f"field {name!r} is a container and cannot be a column")
        out.append((name, title))
    return tuple(out)
