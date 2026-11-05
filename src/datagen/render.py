"""Render an OutputSpec and a context to text: Jinja templates or plain tables."""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any, Callable, Mapping

from jinja2 import FileSystemLoader, StrictUndefined, TemplateNotFound, TemplateSyntaxError
from jinja2.exceptions import SecurityError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

from datagen.errors import RenderError
from datagen.filters import FILTERS, cell_text
from datagen.formats import register_all
from datagen.postprocess import POSTPROCESSORS
from datagen.types import OutputSpec

_QUOTING = {"minimal": csv.QUOTE_MINIMAL, "all": csv.QUOTE_ALL, "none": csv.QUOTE_NONE}


def build_env(template_dir: Path) -> SandboxedEnvironment:
    """Sandboxed Jinja environment with the datagen filters and format globals."""
    env = SandboxedEnvironment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters.update(FILTERS)
    register_all(env)
    return env


def _make_row(output: OutputSpec) -> Callable[..., str]:
    quoting = _QUOTING.get(output.quoting)
    if quoting is None:
        raise RenderError(f"unknown quoting {output.quoting!r}")

    def row(*values: Any) -> str:
        cells = [cell_text(v) for v in values]
        if quoting == csv.QUOTE_NONE:
            for i, cell in enumerate(cells, 1):
                if any(ch in cell for ch in (output.delimiter, '"', "\r", "\n")):
                    raise RenderError(
                        f"row(): value {i} ({cell!r}) contains the delimiter, a quote or a "
                        "line break and quoting is 'none'"
                    )
        buf = io.StringIO()
        csv.writer(buf, delimiter=output.delimiter, quoting=quoting, lineterminator="").writerow(cells)
        return buf.getvalue()

    return row


def _template_line(exc: BaseException, filename: str | None) -> int | None:
    """Line in the template where `exc` was raised, from its traceback."""
    line = None
    tb = exc.__traceback__
    while tb is not None:
        if filename and tb.tb_frame.f_code.co_filename == filename:
            line = tb.tb_lineno
        tb = tb.tb_next
    return line


def _render_template(output: OutputSpec, context: Mapping[str, Any], row: Callable[..., str]) -> list[str]:
    assert output.template is not None
    env = build_env(output.template.parent)
    name = output.template.name
    try:
        template = env.get_template(name)
    except TemplateNotFound:
        raise RenderError(f"template not found: {output.template}") from None
    except TemplateSyntaxError as e:
        raise RenderError(f"{e.message} in template {name}", line=e.lineno) from e
    try:
        text = template.render({**context, "row": row})
    except UndefinedError as e:
        raise RenderError(f"{e.message} in template {name}", _template_line(e, template.filename)) from e
    except SecurityError as e:
        raise RenderError(f"{e} in template {name}", _template_line(e, template.filename)) from e
    except RenderError as e:
        if e.line is not None:
            raise
        line = _template_line(e, template.filename)
        raise RenderError(f"{e.msg} in template {name}", line) from e
    lines = text.splitlines()
    for spec in output.postprocess:
        kwargs = dict(spec)
        pname = kwargs.pop("name", None)
        func = POSTPROCESSORS.get(pname)
        if func is None:
            raise RenderError(f"unknown postprocessor {pname!r}; known: {sorted(POSTPROCESSORS)}")
        try:
            lines = func(lines, **kwargs)
        except TypeError as e:
            raise RenderError(f"postprocessor {pname!r}: {e}") from e
    return lines


def _render_table(output: OutputSpec, context: Mapping[str, Any], row: Callable[..., str]) -> list[str]:
    table = output.table
    assert table is not None
    try:
        items = context[table.rows]
    except KeyError:
        raise RenderError(f"table rows {table.rows!r} not found in data") from None
    lines: list[str] = []
    if table.header:
        lines.append(row(*(title for _, title in table.columns)))
    for i, item in enumerate(items, 1):
        try:
            values = [item[field] for field, _ in table.columns]
        except KeyError as e:
            raise RenderError(f"table row {i} of {table.rows!r} has no field {e.args[0]!r}") from None
        lines.append(row(*values))
    return lines


def render(output: OutputSpec, context: Mapping[str, Any]) -> str:
    """Render one output to text (lines joined by `newline`)."""
    row = _make_row(output)
    if output.template is not None:
        lines = _render_template(output, context, row)
    elif output.table is not None:
        lines = _render_table(output, context, row)
    else:
        raise RenderError("output has neither a template nor a table")

    if output.line_width is not None:
        for i, line in enumerate(lines, 1):
            if len(line) != output.line_width:
                raise RenderError(f"expected {output.line_width} chars, got {len(line)}", line=i)
    if output.encoding.lower() in ("ascii", "us-ascii"):
        for i, line in enumerate(lines, 1):
            bad = next((c for c in line if ord(c) > 127), None)
            if bad is not None:
                raise RenderError(
                    f"non-ASCII character {bad!r}; use the `ascii` filter to strip it", line=i
                )
    text = output.newline.join(lines)
    if output.final_newline and lines:
        text += output.newline
    return text
