---
name: datagen
description: Generate fake, PII-safe test data files with this repo's `datagen` CLI - CSV, TSV, pipe-delimited, XLSX, fixed-width and NACHA/ACH bank feeds - from JSON schemas, JSON render specs and Jinja templates. Use whenever the user wants sample, mock, dummy or test data, a test file for a partner or bank feed, a new feed layout, a fixed-width or ACH file, or asks to write, change, debug or run a datagen schema, render spec or template, even if they don't name datagen. Also use when they ask about field types, field rules, delimiters, headers/footers, seeds or reproducible output in this project.
---

# datagen

`datagen` turns two JSON files (and sometimes a Jinja template) into test-data files. New feeds need no
Python: you write JSON and, for special layouts, a template. The full reference is `README.md` at the
repo root; this skill is the working summary and points to README sections for detail.

## Setup

Run from the repo root. If `.venv/` is missing, install first:

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

Call the CLI as `.venv/bin/datagen ...` (or `datagen` after `source .venv/bin/activate`). Write output under
`out/`, which is gitignored. Only add files to `examples/` when the user wants a feed kept in the repo.

| Command | Use it to |
| --- | --- |
| `datagen check FILE` | Validate a schema or spec and compile its templates. Prints `ok`. |
| `datagen sample FILE [--seed N] [--set P=V]` | Print the generated data as JSON: what a template will see. |
| `datagen render SPEC [-o OUT] [--only FILE] [--seed N] [--now ISO] [--set P=V]` | Write every output of a spec. |

Exit codes: 0 ok, 1 datagen error (message names the JSON path or template line), 2 bad arguments.
`-o` is a directory (existing, or ending in `/`) or a single file; with no `-o`, a one-text-output spec
prints to stdout.

## The model: schema + spec (+ template)

- **Schema** (top-level `data` key): what the data is. Fields, types, rules, `params` constants, `locale`,
  default `seed`. Never mentions files.
- **Render spec** (top-level `schema` key): which schema, optional `set` edits to it, and `output` (one) or
  `outputs` (several, each with a unique `file`). All outputs of one render share one generated dataset, so
  an ACH file and its report agree row for row.
- **Paths inside a spec are relative to the spec file**, not the working directory. This is the most common
  mistake when writing a spec into `out/`: use `"../examples/schemas/customers.json"` there.

Pick the output style per output (exactly one):

| Need | Use |
| --- | --- |
| One row per list item, columns from fields, optional header row | `"table": {"rows": "customers", "header": true, "columns": [...]}` |
| Header/footer records, several record types, fixed-width, totals | `"template": "path/to/file.j2"` |

Start from the closest example rather than a blank file:

| Example | Shows |
| --- | --- |
| `examples/schemas/customers.json` | field rules: padding, lengths, retry, ranges |
| `examples/schemas/transactions.json` | header object + list; dates relative to `--now` |
| `examples/schemas/ach.json` | nested lists (batches > entries > addenda), `params`, sequences |
| `examples/renders/customers_with_header.json` | table with explicit columns and titles |
| `examples/renders/customers_bundle.json` | one dataset, three files (CSV, pipe TXT, XLSX) |
| `examples/renders/transactions_header_values.json` + `templates/header_values_footer.j2` | H/D/T records with `row()` |
| `examples/renders/ach_single_batch.json` | reuse a schema and narrow it with `set` |
| `examples/renders/ach_with_report.json` + `templates/nacha.ach.j2` | NACHA file plus a matching CSV report |

## Workflow for a new or changed feed

1. **Schema.** Reuse one from `examples/schemas/` if the fields exist; otherwise copy the nearest and edit.
2. **Spec**, plus a template if the layout needs one.
3. **`datagen check`** the spec. Fix errors by the JSON path or template line they name.
4. **`datagen sample`** the spec with `--seed 1 --set data.<list>.count=2` to see the exact names and values the
   template receives.
5. **`datagen render`** with `--seed N --now ISO` so the result is repeatable, then look at it (`head`,
   `tail`, `cat -A` for line endings). For fixed-width feeds set `line_width` so a wrong column width fails
   the render with the line number instead of slipping through.
6. Tell the user the command you ran, including seed and `--now`, so they can reproduce the file.

## One-off changes without editing files: `--set`

`--set PATH=VALUE` is repeatable. The value is parsed as JSON, else taken as text. The first path segment
routes it: `output`/`outputs` edits the spec's outputs, anything else edits the schema (after the spec's own
`set`, so the command line wins). Numbers index lists.

```bash
datagen render examples/renders/customers_with_header.json --seed 1 --set data.customers.count=500 -o out/c500.csv
datagen render examples/renders/customers_no_header.json --seed 1 --set output.delimiter=pipe -o out/c.txt
datagen render examples/renders/customers_bundle.json --seed 1 --set outputs.0.table.header=false -o out/bundle/
datagen render examples/renders/customers_no_header.json --seed 1 -o out/c.xlsx      # .xlsx target => XLSX
datagen render examples/renders/ach_with_report.json --seed 1 --now 2026-01-02T09:30:00 --only ach_report.csv -o out/r.csv
```

## Schema cheat sheet

A field is `{"type": ...}`; a bare string is a Faker method (`"email"`), and `{"faker": "company"}` needs no
`type`. Fields generate top to bottom. `params`, `now` and `seed` are reserved names. Unknown keys are errors.

| `type` | Keys |
| --- | --- |
| `faker` | `faker`, `args` |
| `int` / `decimal` | `min`, `max` (required); decimal `places` (2) |
| `date` | `start`, `end` (`YYYY-MM-DD`, `today`, `+Nd`/`-Nw` relative to `--now`), `format` |
| `string` | `charset` (`digits`, `letters`, `upper`, `lower`, `alnum`, or literal chars), lengths |
| `choice` | `values`, `weights` |
| `constant` / `sequence` / `pattern` | `value` / `start`, `step` / `pattern` (`#` digit, `?` letter) |
| `format` | `format`: `str.format` over **earlier** fields of the same object and `params` |
| `ssn` / `card_number` / `routing_number` | PII-safe by default (`safe: true`) |
| `account_number` | `length` or `min_length`/`max_length` |
| `object` | `fields` |
| `list` | `count` (n or `{"min","max"}`), and `fields` or `item` |

Rules on any scalar field: `min`/`max` (range check, regenerate up to 100 tries), `length` or
`min_length`/`max_length`, `pad` (`"0"` left, or `{"char": " ", "side": "right"}`), `on_invalid`
(`truncate` default, `retry`, `error`). A field with a length rule always yields a string.
Full tables: README "Field types" and "Field rules".

## Output and template cheat sheet

Output keys: `file` (expands `{seed}`, `{now:%Y%m%d}`, `{params[x]}`), `template` or `table`, `format`
(`text`/`xlsx`), `delimiter` (char or `comma`/`pipe`/`tab`/`semicolon`), `quoting`
(`minimal`/`all`/`none`), and text-only `newline`, `line_width`, `encoding`, `final_newline`, `postprocess`
(`block_pad`), plus XLSX-only `sheet_name`.

A template sees every top-level `data` key, `params`, `now`, `seed`, `row(...)`, and the ACH helpers
`ach_batch_totals(entries)` / `ach_file_totals(batches)`. Undefined names are errors; `trim_blocks` and
`lstrip_blocks` are on, so `{% %}` lines leave no blank lines.

| Filter | For |
| --- | --- |
| `ljust(w)` / `rjust(w)` | text columns; **silently truncate** unless `truncate=False` |
| `num(w)` | zero-padded non-negative integers; errors on overflow (never truncates) |
| `cents` / `money(places)` | implied-decimal cents / fixed-point text |
| `datefmt(fmt)`, `digits`, `ascii` | dates, keep 0-9, strip accents |

`row(a, b, ...)` writes one delimited line using the output's `delimiter` and `quoting`, the same way a
table row is written. Fixed-width filler is `'' | ljust(8)`. ACH data requirements and helper rules: README
"ACH variables and helpers".

## Pitfalls

- **PII:** never set `"safe": false` or use `"faker": "ssn"` / Faker credit-card methods unless the user asks
  on purpose; use the `ssn`, `card_number` and `routing_number` types instead.
- **Reproducibility:** Faker date methods (`date_of_birth`, `past_date`, ...) read the real clock and ignore
  `--now`; use the `date` type. Without `--seed`, datagen prints the random seed to stderr as
  `datagen: seed=N`; report it.
- **XLSX** is the CSV written into one sheet as text cells (leading zeros kept, no formulas or styling).
  Text-only keys (`newline`, `line_width`, `encoding`, `final_newline`, `postprocess`) are errors on XLSX.
  Compare XLSX files by cell contents with `openpyxl`, not `cmp`.
- **`quoting: none`** makes a value containing the delimiter, a quote or a newline an error. Pick a
  delimiter that cannot appear in the data, or keep `minimal`.
- **`encoding: ascii`** fails on any accent: pass names through `| ascii` in templates.
- `table.rows` must name a top-level list of objects; nested lists need a template.

## Python API

```python
import datagen
from datetime import datetime
now = datetime(2026, 1, 2, 9, 30)
data = datagen.generate_data("examples/schemas/customers.json", seed=1, now=now, overrides=["data.customers.count=3"])
text = datagen.render_file("examples/renders/customers_no_header.json", seed=1, now=now)   # one output
files = datagen.render("examples/renders/customers_bundle.json", seed=1, now=now)          # {name: text|bytes}
paths = datagen.write("examples/renders/ach_with_report.json", "out/api/", seed=1, now=now)
```

Errors derive from `datagen.DatagenError` (`SchemaError`, `RenderError`).

## Changing datagen itself

Source is `src/datagen/`, tests are in `tests/` (`.venv/bin/pytest -q`). Keep `README.md` in step with any
behaviour change, and update this skill too. Edit it in `.agents/skills/datagen/`; `.claude/skills/datagen`
and `.github/skills/datagen` are symlinks to that folder.
