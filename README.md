# datagen

Generate fake, PII-safe test data for bank feeds: CSV, XLSX and fixed-width files such as NACHA (ACH). You
describe the data in JSON and the file layout in JSON (plus a Jinja template when the layout is special). You
do not write Python to add a new feed.

New to bank feeds or to these tools? Read [Concepts](#concepts), try the [Quickstart](#quickstart), and keep
the [Glossary](#glossary) open for terms like *spec*, *seed*, *fixed-width* or *ODFI*.

- [Install](#install)
- [Concepts](#concepts): [`data` vs `params`](#data-vs-params)
- [Quickstart](#quickstart)
- [Table output or template?](#table-output-or-template)
- [Add a new feed in 3 steps](#add-a-new-feed-in-3-steps)
- [Schema reference](#schema-reference): [field types](#field-types), [field rules](#field-rules)
- [Render spec reference](#render-spec-reference): [output options](#output-options), [XLSX](#xlsx)
- [Templates](#templates): [filters and `row()`](#filters-and-row), [fixed-width tips](#fixed-width-tips), [ACH](#ach-variables-and-helpers)
- [PII safety](#pii-safety)
- [Determinism](#determinism)
- [Overrides](#overrides)
- [Python API](#python-api)
- [Running the tests](#running-the-tests)
- [Common mistakes](#common-mistakes)
- [Glossary](#glossary)

## Install

Needs Python 3.10 or newer. This block creates a virtual environment and installs the package with the test
tools:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

On a network that only reaches an internal package mirror, point pip at it: `PIP_INDEX_URL=https://your-mirror/simple pip install -e '.[dev]'`
(or set `PIP_INDEX_URL` once in your shell or in `pip.conf`).

Every `datagen ...` command below assumes you ran `source .venv/bin/activate` in the repo root. Without
activating, use `.venv/bin/datagen ...` instead. Commands write under `out/`. Check the install:

```bash
datagen --help
datagen check examples/schemas/customers.json
```

`datagen` has three commands:

| Command                                                                                  | What it does                                                               |
| ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `datagen render SPEC [-o OUT] [--only FILE] [--seed N] [--now ISO] [--set PATH=VALUE]` | Generate the data and write every output of the spec.                      |
| `datagen sample SCHEMA_OR_SPEC [--seed N] [--now ISO] [--set PATH=VALUE]`              | Print the generated data as JSON (to look at it, or to design a template). |
| `datagen check SCHEMA_OR_SPEC`                                                         | Validate a schema or spec and compile its templates. Prints `ok`.        |

Exit codes: 0 ok, 1 datagen error (the message names the JSON path or template line), 2 bad arguments.
`-o` takes a directory (existing, or ending in `/`; it is created) or a single file. With no `-o`, a spec with
one text output prints to stdout.

## Concepts

A **schema** says what the data looks like: fields, types, rules, and constants. A **render spec** says which
schema to use and how to write it: which files, in which layout. A schema never mentions files.

```
                          +--> spec: customers_with_header.json ---> customers.csv
                          |
 schema: customers.json --+--> spec: customers_no_header.json ----> customers_nohdr.csv
   (one dataset per       |
    spec per run)         +--> spec: customers_bundle.json  --+----> customers.csv
                                                              +----> customers.txt   same rows,
                                                              +----> customers.xlsx  3 files
```

- **One schema, many specs.** Several specs can point at the same schema file (`"schema": "../schemas/ach.json"`).
  A spec can tweak the schema with `set` (for example `data.batches.count = 1` turns the multi-batch ACH
  schema into a single-batch one).
- **One spec, many files.** A spec's `outputs` list writes several files from the **same** generated data, so
  the ACH file and its report agree row for row.
- **One dataset per spec per run.** Each `render` generates the data once, then renders every output from it.
- A spec file has a top-level `schema` key; a schema file has a top-level `data` key. `datagen` uses that to
  tell them apart.

### `data` vs `params`

Both live in the schema file. The difference: **`data` is generated, `params` is given.**

|                                    | `data`                                                       | `params`                                                                  |
| ---------------------------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------- |
| What it is                         | Field *definitions*: rules for making values                 | Plain *values* you type in                                                |
| Changes between runs?              | Yes, random (repeatable with `--seed`)                       | No, the same every run                                                      |
| Typical contents                   | Customers, transactions, ACH entries: things there are many of | Your bank's IDs and names, a domain, a file version: things there is one of |
| In a template                      | Each top-level key is a name: `customers`, `batches`       | `params.odfi`, `params.origin_name`                                     |
| In a `format` field or file name | Earlier fields by name: `{first_name}`                       | `{params[domain]}`                                                        |
| In a table output                  | `table.rows` names a `data` list                           | Not available (use a template)                                              |
| Shown by `datagen sample`?       | Yes                                                            | No (it is already in the schema file)                                       |

The ACH schema shows why both exist. Every entry in an ACH file needs a random amount and account number, so
those are `data`. But the whole file comes from one sending bank, so its routing number and name sit in
`params`, and the template uses them in the file header:

```json
{
  "params": {"odfi": "51234567", "origin_name": "TEST ORIGINATOR"},
  "data": {
    "batches": {"type": "list", "count": 3, "fields": {
      "amount": {"type": "decimal", "min": 1, "max": 25000}
    }}
  }
}
```

Rule of thumb: if a partner would give you the value in an email ("our ID is 1234567890"), make it a
`params` entry. If it should look different on every row, make it a `data` field. You can still change a
`params` entry for one run: `--set params.origin_name=ACME`.

Repo layout:

| Path                    | Holds                                                                                     |
| ----------------------- | ----------------------------------------------------------------------------------------- |
| `examples/schemas/`   | `customers.json`, `transactions.json`, `ach.json`                                   |
| `examples/renders/`   | render specs: CSV, XLSX, ACH, bundles                                                     |
| `examples/templates/` | Jinja templates: `header_values_footer.j2`, `nacha.ach.j2`, `ach_entries_report.j2` |

## Quickstart

One command per file shape. The `--seed` and `--now` flags make the output repeatable (see
[Determinism](#determinism)); drop them for random data. Paths inside a spec are relative to the spec file.

**1. CSV with a column-title header** (a table output, with explicit columns and titles):

```bash
datagen render examples/renders/customers_with_header.json --seed 1 -o out/customers.csv
head -3 out/customers.csv
```

```
customer_id,First Name,Last Name,nickname,ssn,dob,phone,email,card_number,account_number,branch_code,balance
00000001,Dennis,Boone,KZWeq,915-32-7365,1982-05-14,(631) 555-0170,scotttyler@example.com,4111116690743911,100806360837,0962,41591.74
00000002,Thomas,Gray,owoRoWDsbAJ,982-07-3046,1996-06-17,(415) 555-0186,cliffordjohnson@example.com,4111118344978695,836625851781,0798,13732.00
```

**2. CSV with no header** (`"header": false`):

```bash
datagen render examples/renders/customers_no_header.json --seed 1 -o out/customers_nohdr.csv
head -2 out/customers_nohdr.csv
```

**3. A header row of values, detail rows, then a footer with the row count** (a template using `row()`):

```bash
datagen render examples/renders/transactions_header_values.json --seed 1 --now 2026-01-02T09:30:00 -o out/transactions.txt
head -3 out/transactions.txt
tail -1 out/transactions.txt
```

```
H|529141770|20260102|Carroll Inc
D|20251223|4170669074|Jon Cole|992-15-9686|CREDIT|4727.07
D|20251213|1080636083|Rachel Davis|997-29-8124|DEBIT|1813.46
...
T|25
```

**4. A custom delimiter** on any of the above, with `--set` (`comma`, `pipe`, `tab`, `semicolon`, or any one character):

```bash
datagen render examples/renders/customers_no_header.json --seed 1 --set output.delimiter=pipe -o out/customers_pipe.txt
datagen render examples/renders/customers_with_header.json --seed 1 --set 'output.delimiter=;' -o out/customers_semicolon.csv
datagen render examples/renders/customers_with_header.json --seed 1 --set output.delimiter=tab -o out/customers_tab.tsv
datagen render examples/renders/customers_with_header.json --seed 1 --set output.table.header=false --set data.customers.count=5 -o out/customers_5.csv
```

**5. XLSX**, one sheet. Give a spec with an XLSX output, or name the target `.xlsx` and any single-output spec
becomes XLSX (see [XLSX](#xlsx)):

```bash
datagen render examples/renders/customers_xlsx.json --seed 1 -o out/customers.xlsx
datagen render examples/renders/customers_no_header.json --seed 1 -o out/customers_nohdr.xlsx
datagen render examples/renders/transactions_header_values.json --seed 1 --now 2026-01-02T09:30:00 -o out/transactions.xlsx
```

**6. ACH, a single batch with many entries.** This spec reuses the multi-batch schema and narrows it with `set`:

```bash
datagen render examples/renders/ach_single_batch.json --seed 1 --now 2026-01-02T09:30:00 -o out/single.ach
head -c 190 out/single.ach
```

**7. ACH, several batches** (the schema's own `count` is 3 to 6 batches of 2 to 20 entries):

```bash
datagen render examples/renders/ach_multi_batch.json --seed 1 --now 2026-01-02T09:30:00 -o out/multi.ach
```

**8. One spec, many files**, all from the same rows:

```bash
datagen render examples/renders/customers_bundle.json --seed 1 -o out/bundle/
datagen render examples/renders/ach_with_report.json --seed 1 --now 2026-01-02T09:30:00 -o out/achrep/
datagen render examples/renders/ach_with_report.json --seed 1 --now 2026-01-02T09:30:00 --only ach_report.csv -o out/achrep_only.csv
```

`out/bundle/` gets `customers.csv`, `customers.txt` (pipe-delimited, no header, no quoting) and
`customers.xlsx`; `out/achrep/` gets the `.ach` file and `ach_report.csv` listing the same entries. `--only`
renders one output, matched by its `file` value or its expanded name.

**9. Field rules** (value ranges, exact and min/max lengths, zero padding) live in the schema.
`examples/schemas/customers.json` uses them: look at the data it makes, and read [Field rules](#field-rules).

```bash
datagen sample examples/schemas/customers.json --seed 1 --set data.customers.count=2
```

Tools for working on a feed: `datagen check FILE` validates and compiles templates, `datagen sample FILE`
shows the JSON your template will see.

## Table output or template?

| You want                                                                                            | Use            | Why                                                                                 |
| --------------------------------------------------------------------------------------------------- | -------------- | ----------------------------------------------------------------------------------- |
| One row per item, columns straight from the fields, optional header row                             | `"table"`    | No template. Name the list and (optionally) the columns.                            |
| A header or footer with its own content, several record types, fixed-width columns, computed totals | `"template"` | You control every line. Use `row()` for delimited lines, filters for fixed-width. |

Exactly one of `table` and `template` per output. A table's `rows` must name a top-level list of objects in
the schema. Both styles accept `delimiter`, `quoting` and the other [output options](#output-options).

## Add a new feed in 3 steps

Say a partner wants a fixed-width customer extract: 8-digit ID, last name (20), first name (15), balance in
cents (12). The commands below write the new files into `out/` so nothing is added to the repo. In a real feed
put the spec in `examples/renders/` and the template in `examples/templates/`, and use `../schemas/customers.json`
as the schema path.

**Step 1. Reuse or copy a schema.** `examples/schemas/customers.json` already has the fields. If your feed
needs new fields, copy a schema, rename it and edit it (see [Schema reference](#schema-reference)).

**Step 2. Write a spec, and a template if you need one.** Paths in the spec are relative to the spec file.

```bash
cat > out/my_feed.json <<'EOF'
{
  "schema": "../examples/schemas/customers.json",
  "set": {"data.customers.count": 10},
  "output": {
    "file": "cust_{now:%Y%m%d}.dat",
    "template": "my_feed.j2",
    "line_width": 55,
    "encoding": "ascii"
  }
}
EOF
cat > out/my_feed.j2 <<'EOF'
{% for c in customers %}
{{ c.customer_id | num(8) }}{{ c.last_name | ascii | upper | ljust(20) }}{{ c.first_name | ascii | upper | ljust(15) }}{{ c.balance | cents | num(12) }}
{% endfor %}
EOF
```

**Step 3. Check, look at the data, render.**

```bash
datagen check out/my_feed.json
datagen sample out/my_feed.json --seed 1 --set data.customers.count=1
datagen render out/my_feed.json --seed 1 --now 2026-01-02T09:30:00 -o out/
head -3 out/cust_20260102.dat
```

```
00000001BOONE               DENNIS         000004159174
```

`line_width: 55` makes datagen fail with the line number if any line is not exactly 55 characters, so a
column that is too wide or too narrow cannot slip through.

## Schema reference

A schema file is a JSON object with these top-level keys:

| Key        | Meaning                                                                                                                                         |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `data`   | Required. Object of named fields that are generated each run (see below). Names `params`, `now` and `seed` are reserved.                  |
| `locale` | Faker locale, default `en_US`.                                                                                                                |
| `seed`   | Default seed, used when `--seed` is not given.                                                                                                |
| `params` | Fixed values, never generated: for templates (`params.odfi`), `format` fields and file names. See [`data` vs `params`](#data-vs-params). |

Fields are generated in order, top to bottom, and a nested `list` or `object` generates its own fields. A field
is an object with a `type`. As a shorthand, a bare string is a Faker method: `"email"` means
`{"type": "faker", "faker": "email"}`, and an object with a `faker` key does not need `type`. Unknown keys
are rejected, with the JSON path in the error.

### Field types

| `type`           | Keys                                                                                                                               | Produces                                                                                                                                                                               |
| ------------------ | ---------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `faker`          | `faker` (method name), `args` (object of keyword arguments)                                                                    | Any Faker method for the schema's locale: `"name"`, `"company"`, `"email"`, `"sentence"`. Not PII-safe for methods like `ssn` (use the dedicated types).                     |
| `int`            | `min`, `max` (both required, inclusive)                                                                                        | Integer.                                                                                                                                                                               |
| `decimal`        | `min`, `max` (required), `places` (default 2)                                                                                | Decimal with exactly `places` digits after the point.                                                                                                                                |
| `date`           | `start`, `end` (required), `format` (optional strftime)                                                                      | A date between the bounds, as a date, or as a string when `format` is set. Bounds: `YYYY-MM-DD`, `today`, or `+Nd`, `-Nd`, `+Nw`, `-Nw` relative to `--now`.           |
| `string`         | `charset` (default `alnum`), `min_length`, `max_length` or `length`                                                      | Random text, 1 to 10 characters if no length is given. `charset` is `digits`, `letters`, `upper`, `lower`, `alnum`, or the literal characters to pick from (`"ABC123"`). |
| `choice`         | `values` (non-empty list), `weights` (optional, one per value)                                                                 | One of the values; values can be strings, numbers or objects.                                                                                                                          |
| `constant`       | `value`                                                                                                                          | The same value every time.                                                                                                                                                             |
| `sequence`       | `start` (1), `step` (1)                                                                                                        | 1, 2, 3, ... The counter is per field and keeps counting across parents: `trace_seq` in the ACH schema continues from batch to batch.                                                |
| `pattern`        | `pattern`                                                                                                                        | `#` becomes a digit, `?` a letter, everything else is copied: `"(###) 555-01##"`.                                                                                                |
| `format`         | `format`                                                                                                                         | A Python `str.format` string using earlier fields of the same object and `params`: `"{first_name}.{last_name}@{params[domain]}"`. A field that comes later is an error.          |
| `ssn`            | `dashes` (true), `safe` (true)                                                                                                 | `ddd-dd-dddd`. Safe: area 900-999, never issued.                                                                                                                                     |
| `card_number`    | `brand` (`visa` default, `mastercard`, `amex`, `discover`), `safe` (true)                                              | A Luhn-valid number. Safe: a published test BIN (`411111...` for visa).                                                                                                              |
| `routing_number` | `values` (optional list of valid ABA numbers), `safe` (true)                                                                   | 9-digit ABA number with a valid checksum. Safe: a `50`-`59` prefix that is not assigned. With `values`, picks from your list.                                                    |
| `account_number` | `length` or `min_length`/`max_length` (default 10)                                                                           | Digits, never starting with 0, as text.                                                                                                                                                |
| `object`         | `fields`                                                                                                                         | A nested group of fields. No rules allowed.                                                                                                                                            |
| `list`           | `count` (a number, or `{"min": n, "max": n}`), and `fields` (list of objects) or `item` (one scalar field; list of values) | A list. `fields` and `item` are mutually exclusive. No rules allowed.                                                                                                              |

A tiny schema with several types (`format` can use earlier fields; `params` are available too):

```json
{
  "params": {"domain": "example.test"},
  "data": {
    "people": {
      "type": "list",
      "count": {"min": 3, "max": 5},
      "fields": {
        "id": {"type": "sequence", "start": 1000},
        "first": {"faker": "first_name"},
        "last": {"faker": "last_name"},
        "email": {"type": "format", "format": "{first}.{last}@{params[domain]}"},
        "tier": {"type": "choice", "values": ["GOLD", "STD"], "weights": [1, 9]},
        "opened": {"type": "date", "start": "-365d", "end": "today"}
      }
    }
  }
}
```

### Field rules

Every scalar field (not `object` or `list`) accepts these keys. They are how you meet a partner's limits.

| Rule                           | Applies to                                                                                                                   | Meaning                                                                                                                               |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `min`, `max`               | `int`, `decimal`: the range itself. Other scalars: a check on the generated value (number, or `YYYY-MM-DD` for dates). | Out-of-range values are regenerated, up to 100 tries, then the run fails.                                                             |
| `length`                     | any scalar                                                                                                                   | Exact text length. Same as `min_length` = `max_length`. Cannot be combined with the two below.                                    |
| `min_length`, `max_length` | any scalar                                                                                                                   | Length bounds of the value's text.                                                                                                    |
| `pad`                        | any scalar, needs `length` or `min_length`                                                                               | Fills short values: `"0"` (pad on the left) or `{"char": " ", "side": "right"}`. One character.                                   |
| `on_invalid`                 | any scalar                                                                                                                   | What to do with a value longer than `max_length`: `truncate` (default), `retry` (generate again, up to 100 tries) or `error`. |

Length rules look at the text form of the value (dates as ISO, a `decimal` as `41591.74`), and a field with
a length rule always yields a string. A value that is too short and has no `pad` is regenerated, like a
retry.

Examples, from `examples/schemas/customers.json`:

```json
"customer_id": {"type": "sequence", "start": 1, "length": 8, "pad": "0"},
"first_name":  {"faker": "first_name", "max_length": 15},
"last_name":   {"faker": "last_name", "max_length": 20, "on_invalid": "retry"},
"nickname":    {"type": "string", "charset": "letters", "min_length": 3, "max_length": 12},
"dob":         {"type": "date", "start": "1940-01-01", "end": "2005-12-31", "format": "%Y-%m-%d"},
"branch_code": {"type": "int", "min": 1, "max": 999, "length": 4, "pad": "0"},
"balance":     {"type": "decimal", "min": 0, "max": 50000}
```

- `customer_id` becomes `00000001`: a sequence, left-padded with zeros to exactly 8 characters.
- `first_name` longer than 15 is cut to 15; `last_name` longer than 20 is thrown away and regenerated.
- `branch_code` is a number from 1 to 999 written as `0962`.
- A range check on a Faker value: `{"faker": "date_of_birth", "min": "1950-01-01", "max": "2000-12-31"}` keeps
  regenerating until the date is inside the range.

## Render spec reference

A spec is a JSON object with these top-level keys:

| Key         | Meaning                                                                                                                       |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `schema`  | Required. A path to a schema file (relative to the spec), or an inline schema object.                                         |
| `set`     | Optional object of `dotted.path: value` edits applied to the schema before it is used.                                      |
| `output`  | One output object...                                                                                                          |
| `outputs` | ...or a list of them (use exactly one of `output` and `outputs`). With several outputs every one needs a unique `file`. |

### Output options

| Key               | Default     | Meaning                                                                                                                                                                                                               |
| ----------------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `file`          | none        | File name. `{seed}`, `{now:%Y%m%d}` and `{params[x]}` are expanded: `"ach_{now:%Y%m%d}.ach"`. Required when there are several outputs.                                                                        |
| `template`      |             | Jinja template path, relative to the spec.                                                                                                                                                                            |
| `table`         |             | `{"rows": "list_name", "header": true, "columns": [...]}`. `columns` entries are a field name, or `{"field": "first_name", "title": "First Name"}`; without `columns`, every non-container field is a column. |
| `format`        | `text`    | `text` or `xlsx`. Inferred as `xlsx` when `file` ends in `.xlsx`.                                                                                                                                           |
| `delimiter`     | `,`       | One character, or `comma`, `pipe`, `tab`, `semicolon`.                                                                                                                                                        |
| `quoting`       | `minimal` | `minimal` (quote only when needed), `all`, or `none`. With `none`, a value that contains the delimiter, a quote or a line break is an error.                                                                  |
| `newline`       | `"\n"`    | `"\n"` or `"\r\n"`. Text only.                                                                                                                                                                                    |
| `line_width`    | none        | Every line must be exactly this long, or the render fails with the line number. Text only.                                                                                                                            |
| `encoding`      | `utf-8`   | Any Python codec. With `ascii`, a non-ASCII character fails the render (use the `ascii` filter). Text only.                                                                                                       |
| `final_newline` | `true`    | End the file with a newline. Text only.                                                                                                                                                                               |
| `postprocess`   | `[]`      | List run over the rendered lines. One exists, `block_pad`: `{"name": "block_pad", "size": 10, "fill": "9"}` adds lines of 9s until the line count is a multiple of `size`. Text only.                           |
| `sheet_name`    | `Sheet1`  | XLSX only.                                                                                                                                                                                                            |

A template-based output with its table-style options, from `examples/renders/transactions_header_values.json`:

```json
{
  "schema": "../schemas/transactions.json",
  "output": {
    "file": "transactions_{now:%Y%m%d}.txt",
    "template": "../templates/header_values_footer.j2",
    "delimiter": "|",
    "quoting": "none"
  }
}
```

And a bundle, from `examples/renders/customers_bundle.json`: one schema, three files, one dataset.

```json
{
  "schema": "../schemas/customers.json",
  "outputs": [
    {"file": "customers.csv", "table": {"rows": "customers"}},
    {"file": "customers.txt", "delimiter": "pipe", "quoting": "none",
     "table": {"rows": "customers", "header": false}},
    {"file": "customers.xlsx", "table": {"rows": "customers"}}
  ]
}
```

### XLSX

**XLSX = the CSV, written into a sheet as text.** datagen renders the output exactly as it would a CSV (table
or template, with `delimiter` and `quoting`), then puts each cell of that text into one sheet.

- One sheet (named by `sheet_name`). Every cell is text, with the `@` text format: `00000001` and `0962` keep
  their leading zeros, and a value that starts with `=` is shown as text, not run.
- No formulas, styling, number formats or macros. Empty values become empty cells.
- Limits are Excel's: 1,048,576 rows, 16,384 columns, 32,767 characters per cell. Exceeding one is an error.
- Text-only keys (`newline`, `line_width`, `encoding`, `final_newline`, `postprocess`) are errors on an XLSX output.
- `-o name.xlsx` on any spec with a single output switches that output to XLSX. With several outputs, give
  the output a `.xlsx` file name or `"format": "xlsx"`, as the bundle does.

## Templates

A template is a [Jinja](https://jinja.palletsprojects.com/) file rendered once per output. It sees:

| Name                                      | What                                                                         |
| ----------------------------------------- | ---------------------------------------------------------------------------- |
| each top-level `data` key               | `customers`, `batches`, `header`, ... (what `datagen sample` prints) |
| `params`                                | the schema's `params`                                                      |
| `now`                                   | the run's date and time (`--now`, else the real clock)                     |
| `seed`                                  | the seed used                                                                |
| `row(...)`                              | one delimited line, see below                                                |
| `ach_batch_totals`, `ach_file_totals` | [ACH helpers](#ach-variables-and-helpers)                                     |

Behaviour to know: an undefined name is an error (no silent blanks), the environment is sandboxed, and
`{% ... %}` lines leave no blank line behind (`trim_blocks` and `lstrip_blocks` are on). Each line of rendered text becomes one line of the file. The full Jinja toolbox (`| upper`, `| length`, `loop.index`, `{% set %}`) works.

A header-of-values template, from `examples/templates/header_values_footer.j2`:

```jinja
{{ row('H', header.routing_number, now | datefmt('%Y%m%d'), header.institution_name) }}
{% for t in transactions %}
{{ row('D', t.posted_date, t.account_number, t.name, t.ssn, t.tx_type, t.amount) }}
{% endfor %}
{{ row('T', transactions | length) }}
```

### Filters and `row()`

| Filter                                    | Does                                                                                                                                    | Example                                 |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| `ljust(width, fill=" ", truncate=True)` | Cut to `width`, pad on the right                                                                                                      | `name \| ljust(22)`                    |
| `rjust(width, fill=" ", truncate=True)` | Cut to `width`, pad on the left                                                                                                       | `params.immediate_origin \| rjust(10)` |
| `num(width)`                            | Zero-pad a non-negative integer (an int, a digit string, or a whole decimal) on the left. Too big, negative or not a number is an error | `e.trace_seq \| num(7)`                |
| `cents`                                 | Amount to whole cents (half up)                                                                                                         | `e.amount \| cents \| num(10)`          |
| `money(places=2)`                       | Fixed-point text (half up)                                                                                                              | `amount \| money` gives `1234.50`    |
| `datefmt(fmt)`                          | strftime a date, a datetime or an ISO string                                                                                            | `now \| datefmt('%y%m%d%H%M')`         |
| `digits`                                | Keep only 0-9                                                                                                                           | `phone \| digits`                      |
| `ascii`                                 | Strip accents and non-ASCII                                                                                                             | `name \| ascii`                        |

`ljust` and `rjust` silently cut a value that is too wide. Pass `truncate=False` to make that an error:
`name | ljust(22, " ", false)`.

`row(a, b, c)` writes one line in the output's `delimiter` and `quoting`, with CSV quoting rules. Values are
text-ified the same way as in tables: a missing value (`None`) is empty, dates are ISO (`2026-01-02`), booleans
are `true` and `false`. It is also what a table output uses, so a `row()` line and a table line look the same.

### Fixed-width tips

- Set `line_width` on the output. It is the cheapest test that every record has the width the partner expects;
  the error names the offending line.
- Use `encoding: "ascii"` for legacy feeds and pass text through `| ascii` so an accent never breaks a line.
- Use `num(width)` for numeric fields that are zero-padded (counts, hash totals, trace numbers, amounts in
  cents). Use `ljust(width)` for text and `rjust(width)` for right-aligned text. `num` never truncates, so an
  overflow is an error instead of a corrupt file.
- Amounts: `amount | cents | num(10)` for implied-decimal fields, `amount | money` for text amounts.
- Filler is `'' | ljust(8)`.
- Windows line endings: `"newline": "\r\n"`. `line_width` counts the line without its newline.

## ACH variables and helpers

`examples/templates/nacha.ach.j2` writes a NACHA file (94-character records, `\r\n`, padded to blocks of 10).
It pairs with `examples/schemas/ach.json`. Spec options that go with it (see `examples/renders/ach_multi_batch.json`):

```json
"output": {
  "file": "ach_{now:%Y%m%d}.ach",
  "template": "../templates/nacha.ach.j2",
  "newline": "\r\n",
  "line_width": 94,
  "encoding": "ascii",
  "postprocess": [{"name": "block_pad", "size": 10, "fill": "9"}]
}
```

The template needs these in the data:

| Where                             | Names                                                                                                                                                  |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `params`                        | `immediate_destination`, `immediate_origin`, `destination_name`, `origin_name`, `odfi`                                                       |
| `batches[]`                     | `service_class_code`, `company_name`, `company_id`, `sec_code`, `entry_description`, `effective_date`, `entries`                         |
| `batches[].entries[]`           | `transaction_code`, `routing_number`, `account_number`, `amount`, `individual_id`, `name`, `trace_seq`, `addenda` (list, may be empty) |
| `batches[].entries[].addenda[]` | `info`                                                                                                                                               |

The helpers are available in every template:

| Helper                        | Input                                                                                                                     | Returns (all integers)                                                                                                   |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `ach_batch_totals(entries)` | a batch's `entries`. Each entry must have `amount`, `routing_number`, `transaction_code`; `addenda` is optional | `entry_addenda_count`, `entry_hash`, `total_debit_cents`, `total_credit_cents`                                   |
| `ach_file_totals(batches)`  | the `batches` list. Each batch must have `entries`                                                                    | `batch_count`, `entry_addenda_count`, `entry_hash`, `total_debit_cents`, `total_credit_cents`, `block_count` |

Rules the helpers follow: a transaction code whose last digit is 5-9 is a debit and 0-4 a credit; prenote codes
(ending in 3 or 8) add 0 to the money totals but still count as entries; the hash is the sum of the first 8
digits of each routing number, modulo 10 billion; `block_count` is the whole-file record count over 10, rounded
up. `{% set bt = ach_batch_totals(b.entries) %}` and then `bt.total_debit_cents | num(12)` is how the
template fills a batch control record.

The single-batch example is the multi-batch spec plus a `set`, which is the pattern for "same format, narrower
data":

```json
"set": {
  "data.batches.count": 1,
  "data.batches.fields.service_class_code.value": "220",
  "data.batches.fields.entries.count": {"min": 5, "max": 25},
  "data.batches.fields.entries.fields.transaction_code.values": ["22", "32"]
}
```

## PII safety

Output is test data and must not look like a real person's. By default:

| Type               | Default (`"safe": true`)                                              |
| ------------------ | ----------------------------------------------------------------------- |
| `ssn`            | Area 900-999 (never issued to anyone).                                  |
| `card_number`    | A well-known test BIN for the brand, with a valid Luhn digit.           |
| `routing_number` | A `50`-`59` prefix that is not assigned, with a valid ABA checksum. |

Set `"safe": false` on a field to get raw Faker values (a plausible SSN, card number or ABA number). Do this only
on purpose, and never for data that leaves a test environment. A `faker` field is Faker's own output, and
`"faker": "ssn"` is not made safe; use the `ssn` type. `account_number`, names, and the rest are random and do
not match real customers. Names and emails come from Faker, and email addresses use reserved domains such as
`example.com`.

## Determinism

- `--seed N` fixes the random data. The seed comes from `--seed`, else the schema's `seed`, else a random one,
  which datagen prints to stderr as `datagen: seed=N` so you can reuse it.
- `--now ISO` fixes "today": relative date bounds (`-30d`, `today`), `{now:...}` in file names, the template's
  `now`, and the XLSX creation time. Without it, the real clock is used.
- With the same schema, spec, seed and `--now`, text files match byte for byte. XLSX files hold the same cells,
  so compare them by cell contents (open them with `openpyxl`), not with `cmp`.
- **Faker date methods read the real clock.** `date_of_birth`, `date_this_year`, `past_date` and similar ignore
  `--now`, so a spec using them does not repeat from one day to the next. Use the `date` type, whose bounds
  follow `--now`.

```bash
datagen render examples/renders/ach_multi_batch.json --seed 1 --now 2026-01-02T09:30:00 -o out/multi2.ach
cmp out/multi.ach out/multi2.ach
```

## Overrides

Two ways to change a spec's schema without editing files, and one to change the outputs. All use dotted paths
into the JSON; numbers index lists (`outputs.0.file`); the parent of the last name must already exist.

| Where                                                 | How                     | Applies to                   |
| ----------------------------------------------------- | ----------------------- | ---------------------------- |
| In the spec: `"set": {"data.batches.count": 1}`     | Permanent for that spec | the **schema**         |
| On the command line: `--set data.customers.count=5` | One run, repeatable     | schema                       |
| On the command line: `--set output.delimiter=pipe`  | One run                 | the spec's **outputs** |

`--set PATH=VALUE` reads the value as JSON (`5`, `true`, `"x"`, `["22","32"]`, `{"min":1,"max":2}`) and, if that
fails, as plain text (`pipe`). Routing is by the first segment of the path: `output` or `outputs` edits the
spec's outputs, anything else edits the schema. A schema override is applied after the spec's `set`, so
`--set` wins. Single-output specs use `output.`; for a list, use `outputs.N.` with the index, for example
`outputs.1.delimiter=pipe` or `outputs.0.table.header=false`.

```bash
datagen render examples/renders/customers_bundle.json --seed 1 --set outputs.0.table.header=false --set data.customers.count=3 -o out/bundle3/
datagen render examples/renders/ach_single_batch.json --seed 1 --now 2026-01-02T09:30:00 --set params.origin_name=ACME -o out/acme.ach
```

## Python API

The same functions the CLI uses (`import datagen`). Errors derive from `datagen.DatagenError`
(`SchemaError`, `RenderError`).

```python
from datetime import datetime
import datagen

now = datetime(2026, 1, 2, 9, 30)

# data only, as dicts and lists
data = datagen.generate_data("examples/schemas/customers.json", seed=1, now=now,
                             overrides=["data.customers.count=3"])

# a spec with one output: its text (bytes for xlsx); out= also writes it
text = datagen.render_file("examples/renders/customers_no_header.json", seed=1, now=now, out="out/api.csv")

# any spec: {file name: text or bytes}, or write them all into a directory
files = datagen.render("examples/renders/customers_bundle.json", seed=1, now=now)
paths = datagen.write("examples/renders/ach_with_report.json", "out/api/", seed=1, now=now)

# validate without rendering
schema = datagen.load_schema("examples/schemas/ach.json")
spec = datagen.load_render_spec("examples/renders/ach_with_report.json")
```

`render`, `render_file` and `write` take the same `seed`, `now` and `overrides` (a list of `PATH=VALUE`
strings) as the CLI; `render` and `write` also take `only=`.

## Running the tests

```bash
pytest -q
```

## Common mistakes

| Symptom                                                                                               | Cause                                                                                                    | Fix                                                                             |
| ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `schema: cannot read .../examples/schemas/x.json: No such file or directory` for a file that exists | Paths in a spec are relative to the **spec file**, not to where you run the command                | From `out/my_feed.json`, the schema is `../examples/schemas/customers.json` |
| `line 2: 'dict object' has no attribute 'frist_name' in template t.j2`                              | The template uses a name the data does not have (here a typo)                                            | Run `datagen sample` on the spec and copy the names it prints                 |
| `... has no attribute 'x'` on `params.x`, or `KeyError: 'x'` on `{params[x]}`                 | `x` is a `data` field, or is missing from `params`                                                 | Check which section it belongs in: [`data` vs `params`](#data-vs-params)     |
| Different output every day with the same `--seed`                                                   | No `--now`, or a Faker date method (`date_of_birth`) that reads the real clock                       | Pass `--now`, and use the `date` type ([Determinism](#determinism))          |
| `line 7: expected 94 chars, got 93`                                                                 | A fixed-width column is too wide or too narrow                                                           | Add up the widths in that line of the template; they must equal `line_width`  |
| A value is cut short with no error                                                                    | `ljust`/`rjust` truncate by default                                                                  | `ljust(22, " ", false)` makes it an error instead                             |
| `output.delimiter: parent 'output' does not exist`                                                  | `--set output.x` on a spec with an `outputs` list (or `outputs.0.x` on a spec with one `output`) | One output: `output.x`. Several: `outputs.0.x`, `outputs.1.x`, ...        |

## Glossary

Terms used in this README, in alphabetical order.

| Term                              | Meaning                                                                                                                                                                                                         |
| --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **ABA routing number**      | The 9-digit number that identifies a US bank. The last digit is a checksum. datagen's `routing_number` type makes valid-looking but unassigned ones.                                                          |
| **ACH**                     | Automated Clearing House, the US network for batch bank payments (payroll, bills). ACH files follow the NACHA format.                                                                                           |
| **Addenda**                 | An optional extra 94-character record under an ACH entry, holding free-text payment info.                                                                                                                       |
| **Batch** (ACH)             | A group of entries from one company with one purpose (e.g. one payroll run), wrapped in a batch header and a batch control record.                                                                              |
| **BIN**                     | Bank Identification Number: the first 6-8 digits of a card number, naming the issuer. Test BINs (like `411111` for Visa) are never real cards.                                                                |
| **Block** (ACH)             | 10 records. An ACH file's record count must be a multiple of 10, so it ends with filler lines of `9`s (`block_pad`).                                                                                        |
| **Cents / implied decimal** | Writing `$12.34` as `1234`: fixed-width feeds often have no decimal point, and the reader knows the last two digits are cents.                                                                              |
| **Checksum**                | A digit computed from the others, so a typo is detected. Card numbers use Luhn; routing numbers use the ABA formula.                                                                                            |
| **CSV**                     | Comma-separated values: a text file, one row per line, values split by a delimiter.                                                                                                                             |
| **Delimiter**               | The character between values in a line: `,` in CSV, `\|` in pipe-delimited files, a tab in TSV.                                                                                                              |
| **Deterministic**           | Same inputs give the same output. With the same `--seed` and `--now`, datagen produces the same file.                                                                                                       |
| **Dotted path**             | A way to point into nested JSON: `data.customers.count` means the `count` key inside `customers` inside `data`. `outputs.0` is the first item of the `outputs` list. Used by `set` and `--set`. |
| **Entry** (ACH)             | One payment: a single debit or credit to one account.                                                                                                                                                           |
| **Entry hash**              | An ACH check value: the sum of the first 8 digits of every entry's routing number, keeping the last 10 digits.                                                                                                  |
| **Faker**                   | The Python library datagen uses for realistic names, companies, emails and so on. Any Faker method name can be a field.                                                                                         |
| **Feed**                    | A file a system sends to a partner (or receives) on a schedule, in a layout both sides agreed on.                                                                                                               |
| **Field**                   | One named value in the data, like `first_name`. Each field has a type and optional rules.                                                                                                                     |
| **Fixed-width**             | A file layout with no delimiters: each value sits at fixed character positions, padded with spaces or zeros. ACH is fixed-width (94 characters a line).                                                         |
| **Jinja**                   | The template language datagen uses. `{{ x }}` prints a value, `{% for ... %}` loops, `\| filter` transforms a value.                                                                                       |
| **Locale**                  | Which country's style Faker uses for names, addresses and phone numbers (`en_US`, `de_DE`, ...).                                                                                                            |
| **Luhn**                    | The checksum card numbers use. A Luhn-valid number passes basic validation even though it is fake.                                                                                                              |
| **NACHA**                   | The organization that sets the ACH rules, and the name of the ACH file format.                                                                                                                                  |
| **`now`**                 | The date and time datagen treats as "today". Set it with `--now` so relative dates and file names repeat.                                                                                                     |
| **ODFI**                    | Originating Depository Financial Institution: the bank that sends the ACH file. `params.odfi` is its routing number (first 8 digits).                                                                         |
| **Output**                  | One file a spec writes, described by an object in `output` or `outputs`.                                                                                                                                    |
| **Padding**                 | Filling a value to a fixed width: `42` padded to 6 with zeros on the left is `000042`.                                                                                                                      |
| **`params`**              | Fixed values in a schema that are never generated. See [`data` vs `params`](#data-vs-params).                                                                                                                |
| **PII**                     | Personally Identifiable Information: SSNs, card numbers, real names tied to accounts. datagen's output must never contain real PII.                                                                             |
| **Prenote**                 | A zero-dollar ACH test entry that checks an account exists before real payments. Its transaction code ends in 3 or 8.                                                                                           |
| **Quoting**                 | Wrapping a value in `"..."` so a delimiter or line break inside it is not read as a separator.                                                                                                                |
| **Render**                  | Turn generated data into files, using a table layout or a template.                                                                                                                                             |
| **Render spec** (spec)      | The JSON file that says which schema to use and which files to write.                                                                                                                                           |
| **Schema**                  | The JSON file that describes the data: its fields, types and rules.                                                                                                                                             |
| **SEC code**                | Standard Entry Class: a 3-letter ACH code for the kind of payment, e.g. `PPD` (to a person) or `CCD` (to a company).                                                                                        |
| **Seed**                    | A number that fixes the random generator, so the same seed gives the same "random" data.                                                                                                                        |
| **strftime**                | The pattern language for formatting dates: `%Y%m%d` gives `20260102`, `%y%m%d` gives `260102`.                                                                                                          |
| **Template**                | A Jinja file that controls every line of an output, for layouts a plain table cannot express.                                                                                                                   |
| **Trace number**            | A 15-digit ID on each ACH entry: the ODFI's 8 digits plus a 7-digit sequence.                                                                                                                                   |
| **Transaction code**        | A 2-digit ACH code for account type and direction: `22` checking credit, `27` checking debit, `32` savings credit, `37` savings debit.                                                                  |
| **XLSX**                    | The Excel file format. datagen writes one sheet with every cell as text.                                                                                                                                        |
