from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Schema:
    path: Path | None                      # None for an inline schema
    locale: str
    seed: int | None
    params: dict
    data: dict                             # normalised field specs


@dataclass(frozen=True)
class TableSpec:
    rows: str                              # name of a top-level list in data whose items are objects
    header: bool = True
    columns: tuple[tuple[str, str], ...] = ()  # (field, title); never empty after load


@dataclass(frozen=True)
class OutputSpec:
    file: str | None = None                # file name; may hold {seed} {now:%Y%m%d} {params[x]}
    format: str = "text"                   # "text" | "xlsx"
    template: Path | None = None           # absolute; exactly one of template / table is set
    table: TableSpec | None = None
    delimiter: str = ","
    quoting: str = "minimal"               # "minimal" | "all" | "none"
    newline: str = "\n"                    # text only
    line_width: int | None = None          # text only
    encoding: str = "utf-8"                # text only; "ascii" enforced per line
    final_newline: bool = True             # text only
    postprocess: tuple[dict, ...] = ()     # text only; each {"name": str, **kwargs}
    sheet_name: str = "Sheet1"             # xlsx only


@dataclass(frozen=True)
class RenderSpec:
    path: Path
    schema: Schema                         # after the spec's "set" and any CLI overrides
    outputs: tuple[OutputSpec, ...]        # at least one
