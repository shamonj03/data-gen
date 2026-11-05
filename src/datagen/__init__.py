"""datagen: schema-driven fake data rendered to CSV, XLSX and ACH files.

Public API: load a schema or render spec, generate data once, render each output to text or XLSX bytes,
and write the results to disk. The ``datagen`` command line (``datagen.cli``) wraps these functions.
"""
from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

from datagen.errors import DatagenError, RenderError, SchemaError
from datagen.generator import generate
from datagen.render import render as _render_output
from datagen.schema import load_schema
from datagen.spec import detect_kind, format_filename, load_render_spec
from datagen.types import OutputSpec, RenderSpec, Schema
from datagen.xlsx import text_to_xlsx

__all__ = [
    "load_schema",
    "load_render_spec",
    "generate_data",
    "render",
    "render_file",
    "write",
    "DatagenError",
    "SchemaError",
    "RenderError",
]


class Rendered(NamedTuple):
    """One rendered output: its formatted file name, its spec and its content (str, or bytes for xlsx)."""

    name: str
    output: OutputSpec
    content: str | bytes


def read_raw(path: Path | str) -> dict:
    """Read a JSON file that must hold an object."""
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DatagenError(f"cannot read {p}: {exc.strerror or exc}") from None
    except json.JSONDecodeError as exc:
        raise DatagenError(f"{p}: invalid JSON: {exc}") from None
    if not isinstance(raw, dict):
        raise DatagenError(f"{p}: expected a JSON object at the top level")
    return raw


def load_any_schema(path: Path | str, overrides: list[str] | None = None) -> Schema:
    """Load the schema from a schema file, or from a render spec file (its `schema`)."""
    raw = read_raw(path)
    if detect_kind(raw) == "spec":
        return load_render_spec(path, overrides).schema
    return load_schema(path, overrides)


def resolve_seed(schema: Schema, seed: int | None) -> int:
    """Seed precedence: the argument, then the schema's `seed`, then a random seed."""
    if seed is not None:
        return seed
    if schema.seed is not None:
        return schema.seed
    return random.SystemRandom().randrange(1, 2**31)


def generate_data(
    schema_path: Path | str,
    *,
    seed: int | None = None,
    now: datetime | None = None,
    overrides: list[str] | None = None,
) -> dict:
    """Generate data from a schema file, or from the schema of a render spec file."""
    schema = load_any_schema(schema_path, overrides)
    return generate(schema, seed=resolve_seed(schema, seed), now=now or datetime.now())


def render_outputs(
    spec_path: Path | str,
    *,
    seed: int | None = None,
    now: datetime | None = None,
    overrides: list[str] | None = None,
    only: str | None = None,
) -> list[Rendered]:
    """Generate once, then render every selected output (all of them, or the one named by `only`)."""
    spec: RenderSpec = load_render_spec(spec_path, overrides)
    schema = spec.schema
    seed = resolve_seed(schema, seed)
    now = now or datetime.now()
    names = [format_filename(o, seed=seed, now=now, params=schema.params) for o in spec.outputs]
    chosen = list(zip(names, spec.outputs))
    if only is not None:
        chosen = [(n, o) for n, o in chosen if only in (n, o.file)]
        if not chosen:
            raise DatagenError(f"--only {only!r} matches no output; available: {', '.join(names)}")

    data = generate(schema, seed=seed, now=now)
    context = {**data, "params": schema.params, "now": now, "seed": seed}
    results: list[Rendered] = []
    for name, output in chosen:
        text = _render_output(output, context)
        content: str | bytes = text
        if output.format == "xlsx":
            content = text_to_xlsx(
                text,
                delimiter=output.delimiter,
                quoting=output.quoting,
                sheet_name=output.sheet_name,
                now=now,
            )
        results.append(Rendered(name, output, content))
    return results


def render(
    spec_path: Path | str,
    *,
    seed: int | None = None,
    now: datetime | None = None,
    overrides: list[str] | None = None,
    only: str | None = None,
) -> dict[str, str | bytes]:
    """Render a spec's outputs; key is the formatted file name ("output" if unnamed), bytes for xlsx."""
    done = render_outputs(spec_path, seed=seed, now=now, overrides=overrides, only=only)
    return {r.name: r.content for r in done}


def xlsx_override(spec_path: Path | str) -> list[str]:
    """The override that forces format xlsx on a single-output spec; empty when the shape is not single."""
    raw = read_raw(spec_path)
    if "output" in raw:
        return ["output.format=xlsx"]
    outputs = raw.get("outputs")
    if isinstance(outputs, list) and len(outputs) == 1:
        return ["outputs.0.format=xlsx"]
    return []


def write_output(path: Path, output: OutputSpec, content: str | bytes) -> None:
    """Write one rendered output: text in its encoding with no newline translation, xlsx as bytes."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            with open(path, "wb") as fh:
                fh.write(content)
        else:
            with open(path, "w", encoding=output.encoding, newline="") as fh:
                fh.write(content)
    except (OSError, UnicodeError) as exc:
        raise DatagenError(f"cannot write {path}: {exc}") from None


def render_file(
    spec_path: Path | str,
    *,
    seed: int | None = None,
    now: datetime | None = None,
    overrides: list[str] | None = None,
    out: Path | str | None = None,
) -> str | bytes:
    """Render a spec that has exactly one output; if `out` is set, also write it there."""
    overrides = list(overrides or [])
    if out is not None and str(out).lower().endswith(".xlsx"):
        overrides += xlsx_override(spec_path)
    done = render_outputs(spec_path, seed=seed, now=now, overrides=overrides)
    if len(done) != 1:
        raise DatagenError(f"render_file needs a spec with exactly one output, found {len(done)}")
    only = done[0]
    if out is not None:
        write_output(Path(out), only.output, only.content)
    return only.content


def write(
    spec_path: Path | str,
    out_dir: Path | str,
    *,
    seed: int | None = None,
    now: datetime | None = None,
    overrides: list[str] | None = None,
    only: str | None = None,
) -> list[Path]:
    """Render a spec and write every output into `out_dir` (created if needed); return the paths."""
    done = render_outputs(spec_path, seed=seed, now=now, overrides=overrides, only=only)
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for r in done:
        path = target / r.name
        write_output(path, r.output, r.content)
        paths.append(path)
    return paths
