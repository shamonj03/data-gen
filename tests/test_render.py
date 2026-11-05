from __future__ import annotations

import importlib
import sys
import types
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from datagen import formats
from datagen.errors import RenderError
from datagen.formats import register_all
from datagen.postprocess import POSTPROCESSORS, block_pad
from datagen.render import build_env, render
from datagen.types import OutputSpec, TableSpec


def tpl(tmp_path: Path, text: str, name: str = "t.j2", **kw: object) -> OutputSpec:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return OutputSpec(template=path, **kw)  # type: ignore[arg-type]


# ---- row() -----------------------------------------------------------------


@pytest.mark.parametrize("delim", [",", "|", ";", "\t"])
def test_row_delimiters(tmp_path: Path, delim: str) -> None:
    out = tpl(tmp_path, "{{ row('a', 1, none, true) }}\n", delimiter=delim)
    assert render(out, {}) == delim.join(["a", "1", "", "true"]) + "\n"


def test_row_cell_text(tmp_path: Path) -> None:
    out = tpl(tmp_path, "{{ row(d, b, n, x) }}\n")
    ctx = {"d": date(2026, 11, 5), "b": False, "n": None, "x": Decimal("1.50")}
    assert render(out, ctx) == "2026-11-05,false,,1.50\n"


def test_row_minimal_quotes_delimiter(tmp_path: Path) -> None:
    out = tpl(tmp_path, "{{ row('a,b', 'say \"hi\"', 'plain') }}\n")
    assert render(out, {}) == '"a,b","say ""hi""",plain\n'


def test_row_all_quoting(tmp_path: Path) -> None:
    out = tpl(tmp_path, "{{ row('a', 1) }}\n", quoting="all")
    assert render(out, {}) == '"a","1"\n'


def test_row_none_quoting_plain_ok(tmp_path: Path) -> None:
    out = tpl(tmp_path, "{{ row('a', 'b') }}\n", quoting="none")
    assert render(out, {}) == "a,b\n"


def test_row_none_quoting_raises_on_delimiter(tmp_path: Path) -> None:
    out = tpl(tmp_path, "{{ row('ok', 'a,b') }}\n", quoting="none")
    with pytest.raises(RenderError, match="value 2"):
        render(out, {})


@pytest.mark.parametrize("bad", ['q"q', "a\nb", "a\rb"])
def test_row_none_quoting_raises_on_quote_and_breaks(tmp_path: Path, bad: str) -> None:
    out = tpl(tmp_path, "{{ row(v) }}\n", quoting="none")
    with pytest.raises(RenderError):
        render(out, {"v": bad})


# ---- templates ---------------------------------------------------------------


def test_nested_loop_header_detail_footer(tmp_path: Path) -> None:
    text = (
        "H|{{ params.name | ljust(6) }}|{{ now | datefmt('%y%m%d') }}\n"
        "{% for b in batches %}\n"
        "B|{{ loop.index | num(3) }}\n"
        "{% for e in b.entries %}\n"
        "D|{{ e.amount | cents | num(6) }}|{{ e.who | ascii | upper }}\n"
        "{% endfor %}\n"
        "{% endfor %}\n"
        "T|{{ batches | length | num(2) }}\n"
    )
    ctx = {
        "params": {"name": "acme"},
        "now": date(2026, 11, 5),
        "batches": [
            {"entries": [{"amount": Decimal("1.5"), "who": "José"}, {"amount": "20", "who": "Ann"}]},
            {"entries": [{"amount": 3, "who": "Bo"}]},
        ],
    }
    expected = (
        "H|acme  |261105\n"
        "B|001\n"
        "D|000150|JOSE\n"
        "D|002000|ANN\n"
        "B|002\n"
        "D|000300|BO\n"
        "T|02\n"
    )
    assert render(tpl(tmp_path, text), ctx) == expected


def test_hand_written_delimiters(tmp_path: Path) -> None:
    out = tpl(tmp_path, "H|{{ a }}|{{ b }}\nD|x,y|z\n")
    assert render(out, {"a": 1, "b": "two"}) == "H|1|two\nD|x,y|z\n"


def test_strict_undefined_typo(tmp_path: Path) -> None:
    out = tpl(tmp_path, "ok\nok\n{{ nme }}\n")
    with pytest.raises(RenderError) as ei:
        render(out, {"name": "x"})
    assert "nme" in ei.value.msg
    assert ei.value.line == 3


def test_syntax_error_has_line(tmp_path: Path) -> None:
    out = tpl(tmp_path, "a\nb\n{% for x in %}\n")
    with pytest.raises(RenderError) as ei:
        render(out, {})
    assert ei.value.line == 3


def test_filter_error_propagates_with_line(tmp_path: Path) -> None:
    out = tpl(tmp_path, "a\n{{ 'toolong' | ljust(3, truncate=False) }}\n")
    with pytest.raises(RenderError) as ei:
        render(out, {})
    assert ei.value.line == 2


def test_missing_template(tmp_path: Path) -> None:
    out = OutputSpec(template=tmp_path / "nope.j2")
    with pytest.raises(RenderError, match="not found"):
        render(out, {})


def test_sandbox_blocks_unsafe_access(tmp_path: Path) -> None:
    out = tpl(tmp_path, "{{ ''.__class__.__mro__ }}\n")
    with pytest.raises(RenderError):
        render(out, {})


def test_template_can_include_siblings(tmp_path: Path) -> None:
    (tmp_path / "part.j2").write_text("part\n", encoding="utf-8")
    out = tpl(tmp_path, "{% include 'part.j2' %}whole\n")
    assert render(out, {}) == "part\nwhole\n"


# ---- line width / ascii / join -------------------------------------------------


def test_line_width_ok(tmp_path: Path) -> None:
    out = tpl(tmp_path, "{{ 'a' | ljust(5) }}\n{{ 'b' | ljust(5) }}\n", line_width=5)
    assert render(out, {}) == "a    \nb    \n"


def test_line_width_failure_line_number(tmp_path: Path) -> None:
    out = tpl(tmp_path, "{{ 'a' | ljust(5) }}\n{{ 'b' | ljust(5) }}\nshorter\n", line_width=5)
    with pytest.raises(RenderError) as ei:
        render(out, {})
    assert ei.value.line == 3
    assert ei.value.msg == "expected 5 chars, got 7"


def test_ascii_check(tmp_path: Path) -> None:
    out = tpl(tmp_path, "fine\ncafé\n", encoding="ascii")
    with pytest.raises(RenderError, match="ascii") as ei:
        render(out, {})
    assert ei.value.line == 2


def test_ascii_check_passes_with_filter(tmp_path: Path) -> None:
    out = tpl(tmp_path, "{{ 'café' | ascii }}\n", encoding="ascii")
    assert render(out, {}) == "cafe\n"


def test_crlf_join_with_final_newline(tmp_path: Path) -> None:
    out = tpl(tmp_path, "a\nb\nc\n", newline="\r\n")
    assert render(out, {}) == "a\r\nb\r\nc\r\n"


def test_no_final_newline(tmp_path: Path) -> None:
    out = tpl(tmp_path, "a\nb\n", final_newline=False)
    assert render(out, {}) == "a\nb"


# ---- postprocessors -------------------------------------------------------------


def test_block_pad_23_to_30() -> None:
    lines = ["x" * 94] * 23
    padded = block_pad(lines)
    assert len(padded) == 30
    assert padded[23:] == ["9" * 94] * 7
    assert padded[:23] == lines


def test_block_pad_exact_multiple_unchanged() -> None:
    lines = ["x" * 94] * 20
    assert block_pad(lines) == lines


def test_block_pad_options_and_empty() -> None:
    assert block_pad(["ab"], size=3, fill="Z") == ["ab", "ZZ", "ZZ"]
    assert block_pad(["ab"], size=2, fill="Z", width=5) == ["ab", "ZZZZZ"]
    assert block_pad([]) == []


def test_postprocess_in_render(tmp_path: Path) -> None:
    text = "".join(f"{{{{ {i} | num(4) }}}}\n" for i in range(23))
    out = tpl(tmp_path, text, postprocess=({"name": "block_pad"},), line_width=4)
    lines = render(out, {}).splitlines()
    assert len(lines) == 30
    assert lines[-1] == "9999"


def test_postprocess_kwargs(tmp_path: Path) -> None:
    out = tpl(tmp_path, "a\n", postprocess=({"name": "block_pad", "size": 3, "fill": "-"},))
    assert render(out, {}) == "a\n-\n-\n"


def test_unknown_postprocessor(tmp_path: Path) -> None:
    out = tpl(tmp_path, "a\n", postprocess=({"name": "nope"},))
    with pytest.raises(RenderError, match="nope"):
        render(out, {})


def test_registry() -> None:
    assert POSTPROCESSORS == {"block_pad": block_pad}


# ---- table mode ------------------------------------------------------------------

COLUMNS = (("id", "ID"), ("name", "Name"), ("born", "Born"))
ROWS = [
    {"id": 1, "name": "Ann", "born": date(1990, 1, 2), "extra": "ignored"},
    {"id": 2, "name": "Bo, Jr", "born": date(1985, 12, 31)},
]


def test_table_with_header() -> None:
    out = OutputSpec(table=TableSpec(rows="people", header=True, columns=COLUMNS))
    assert render(out, {"people": ROWS}) == 'ID,Name,Born\n1,Ann,1990-01-02\n2,"Bo, Jr",1985-12-31\n'


def test_table_without_header() -> None:
    out = OutputSpec(table=TableSpec(rows="people", header=False, columns=COLUMNS), delimiter="|")
    assert render(out, {"people": ROWS}) == "1|Ann|1990-01-02\n2|Bo, Jr|1985-12-31\n"


def test_table_options() -> None:
    out = OutputSpec(
        table=TableSpec(rows="people", columns=COLUMNS[:2]), quoting="all", newline="\r\n", final_newline=False
    )
    assert render(out, {"people": ROWS}) == '"ID","Name"\r\n"1","Ann"\r\n"2","Bo, Jr"'


def test_table_none_quoting_error() -> None:
    out = OutputSpec(table=TableSpec(rows="people", columns=COLUMNS), quoting="none")
    with pytest.raises(RenderError):
        render(out, {"people": ROWS})


def test_table_missing_rows_and_field() -> None:
    out = OutputSpec(table=TableSpec(rows="people", columns=COLUMNS))
    with pytest.raises(RenderError, match="people"):
        render(out, {})
    with pytest.raises(RenderError, match="born"):
        render(out, {"people": [{"id": 1, "name": "x"}]})


def test_table_empty_rows_header_only() -> None:
    out = OutputSpec(table=TableSpec(rows="people", columns=COLUMNS))
    assert render(out, {"people": []}) == "ID,Name,Born\n"


# ---- env and format registry --------------------------------------------------------


def test_build_env_settings(tmp_path: Path) -> None:
    env = build_env(tmp_path)
    assert env.trim_blocks and env.lstrip_blocks and env.keep_trailing_newline
    assert not env.autoescape
    assert {"ljust", "rjust", "num", "cents", "money", "datefmt", "digits", "ascii"} <= set(env.filters)


def test_register_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = types.ModuleType("datagen.formats.fake")
    mod.GLOBALS = {"fake_fn": lambda x: x * 2}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "datagen.formats.fake", mod)
    monkeypatch.setattr(formats, "FORMAT_MODULES", ["fake"])
    env = build_env(tmp_path)
    assert env.globals["fake_fn"](2) == 4
    out = tpl(tmp_path, "{{ fake_fn(21) }}\n")
    assert render(out, {}) == "42\n"
    assert importlib.import_module("datagen.formats.fake") is mod


def test_register_all_empty(tmp_path: Path) -> None:
    env = build_env(tmp_path)
    register_all(env)  # no modules registered: no-op
