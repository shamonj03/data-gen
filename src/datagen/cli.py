"""The `datagen` command line: render, sample and check."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from jinja2 import TemplateError

import datagen
from datagen.errors import DatagenError, RenderError
from datagen.render import build_env
from datagen.spec import detect_kind, load_render_spec


def _iso(text: str) -> datetime:
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid ISO date/time: {text!r}") from None


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="datagen", description="Render fake data from schemas to CSV, XLSX and text files.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--seed", type=int, help="random seed (default: the schema's seed, else random)")
        sp.add_argument("--now", type=_iso, help="ISO date/time to use as 'now'")
        sp.add_argument("--set", dest="sets", action="append", default=[], metavar="PATH=VALUE",
                        help="override a value (repeatable)")

    r = sub.add_parser("render", help="render a spec's outputs")
    r.add_argument("spec")
    r.add_argument("-o", "--out", help="output directory (existing, or ending in /) or a single file")
    r.add_argument("--only", metavar="FILE", help="render only the output with this file name")
    common(r)

    s = sub.add_parser("sample", help="print generated data as JSON")
    s.add_argument("file", metavar="SCHEMA_OR_SPEC")
    common(s)

    c = sub.add_parser("check", help="validate a schema or spec (and compile its templates)")
    c.add_argument("file", metavar="SCHEMA_OR_SPEC")
    return p


def _announce_seed(path: str, seed: int | None, overrides: list[str]) -> int:
    """Return the seed to use; print `datagen: seed=<n>` to stderr when it was neither given nor in the schema."""
    schema = datagen.load_any_schema(path, overrides)
    if seed is not None or schema.seed is not None:
        return datagen.resolve_seed(schema, seed)
    chosen = datagen.resolve_seed(schema, None)
    print(f"datagen: seed={chosen}", file=sys.stderr)
    return chosen


def _emit_stdout(content: str, encoding: str) -> None:
    sys.stdout.flush()
    buffer = getattr(sys.stdout, "buffer", None)
    try:
        if buffer is not None:
            buffer.write(content.encode(encoding))
            buffer.flush()
        else:
            sys.stdout.write(content)
            sys.stdout.flush()
    except UnicodeError as exc:
        raise DatagenError(f"cannot encode output as {encoding}: {exc}") from None


def _cmd_render(args: argparse.Namespace) -> int:
    overrides = list(args.sets)
    target = args.out
    is_dir = target is not None and (Path(target).is_dir() or target.endswith(("/", os.sep)))
    is_xlsx_file = target is not None and not is_dir and target.lower().endswith(".xlsx")
    if is_xlsx_file:
        overrides += datagen.xlsx_override(args.spec)
    seed = _announce_seed(args.spec, args.seed, overrides)
    done = datagen.render_outputs(args.spec, seed=seed, now=args.now, overrides=overrides, only=args.only)

    if target is None:
        if len(done) != 1 or isinstance(done[0].content, bytes):
            raise DatagenError("this spec has several outputs or an xlsx output: use -o DIR")
        _emit_stdout(done[0].content, done[0].output.encoding)
    elif is_dir:
        out_dir = Path(target)
        out_dir.mkdir(parents=True, exist_ok=True)
        for r in done:
            datagen.write_output(out_dir / r.name, r.output, r.content)
    else:
        if len(done) != 1:
            raise DatagenError(f"-o {target} is a file but {len(done)} outputs were selected: use -o DIR or --only FILE")
        only = done[0]
        if is_xlsx_file and isinstance(only.content, str):
            raise DatagenError(f"-o {target}: the selected output is not xlsx (set its format to xlsx)")
        datagen.write_output(Path(target), only.output, only.content)
    return 0


def _cmd_sample(args: argparse.Namespace) -> int:
    seed = _announce_seed(args.file, args.seed, args.sets)
    data = datagen.generate_data(args.file, seed=seed, now=args.now, overrides=args.sets)
    print(json.dumps(data, indent=2, default=str))
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    path = Path(args.file)
    raw = datagen.read_raw(path)
    if detect_kind(raw) == "schema":
        datagen.load_schema(path)
    else:
        spec = load_render_spec(path)
        for output in spec.outputs:
            t = output.template
            if t is None:
                continue
            try:
                build_env(t.parent).get_template(t.name)
            except TemplateError as exc:
                line = getattr(exc, "lineno", None)
                raise RenderError(f"{t}: {getattr(exc, 'message', None) or exc}", line=line) from None
    print("ok")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI; return the exit code (0 ok, 1 datagen error, 2 bad arguments)."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    handlers = {"render": _cmd_render, "sample": _cmd_sample, "check": _cmd_check}
    try:
        return handlers[args.cmd](args)
    except DatagenError as exc:
        print(f"datagen: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
