from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

from datagen.cli import main

SCHEMA = {
    "data": {
        "customers": {
            "type": "list",
            "count": 4,
            "fields": {
                "customer_id": {"type": "sequence", "start": 1, "length": 6, "pad": "0"},
                "first_name": {"type": "faker", "faker": "first_name"},
            },
        }
    }
}
TABLE = {"rows": "customers"}
NOW = "2026-01-02T10:00:00"


def jwrite(path: Path, obj: dict) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


@pytest.fixture
def schema_path(tmp_path: Path) -> Path:
    return jwrite(tmp_path / "schema.json", SCHEMA)


@pytest.fixture
def one_spec(tmp_path: Path, schema_path: Path) -> Path:
    return jwrite(tmp_path / "one.json", {"schema": "schema.json", "output": {"table": TABLE}})


@pytest.fixture
def crlf_spec(tmp_path: Path, schema_path: Path) -> Path:
    return jwrite(
        tmp_path / "crlf.json",
        {"schema": "schema.json", "output": {"table": TABLE, "newline": "\r\n", "file": "crlf.csv"}},
    )


@pytest.fixture
def multi_spec(tmp_path: Path, schema_path: Path) -> Path:
    return jwrite(
        tmp_path / "multi.json",
        {
            "schema": "schema.json",
            "outputs": [
                {"file": "a.csv", "table": TABLE},
                {"file": "b.txt", "table": TABLE, "delimiter": "pipe"},
                {"file": "c.xlsx", "table": TABLE},
            ],
        },
    )


def run(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "datagen.cli", *argv], capture_output=True)


# ---------------------------------------------------------------- render


def test_render_stdout_keeps_crlf_bytes(crlf_spec):
    proc = run("render", str(crlf_spec), "--seed", "1", "--now", NOW)
    assert proc.returncode == 0
    assert proc.stdout.startswith(b"customer_id,first_name\r\n")
    assert proc.stdout.endswith(b"\r\n")
    assert b"\n" not in proc.stdout.replace(b"\r\n", b"")
    assert proc.stderr == b""


def test_render_to_file_keeps_crlf_bytes(crlf_spec, tmp_path):
    out = tmp_path / "o" / "x.csv"
    assert main(["render", str(crlf_spec), "-o", str(out), "--seed", "1", "--now", NOW]) == 0
    data = out.read_bytes()
    assert data.count(b"\r\n") == 5
    assert b"\n" not in data.replace(b"\r\n", b"")


def test_render_to_dir_with_trailing_slash(multi_spec, tmp_path):
    out = tmp_path / "newdir"
    assert main(["render", str(multi_spec), "-o", f"{out}/", "--seed", "1", "--now", NOW]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["a.csv", "b.txt", "c.xlsx"]


def test_render_to_existing_dir(crlf_spec, tmp_path):
    out = tmp_path / "exists"
    out.mkdir()
    assert main(["render", str(crlf_spec), "-o", str(out), "--seed", "1", "--now", NOW]) == 0
    assert (out / "crlf.csv").read_bytes().startswith(b"customer_id,first_name\r\n")


def test_dir_outputs_share_data(multi_spec, tmp_path):
    out = tmp_path / "d"
    assert main(["render", str(multi_spec), "-o", f"{out}/", "--seed", "2", "--now", NOW]) == 0
    csv_ids = [r[0] for r in csv.reader(io.StringIO((out / "a.csv").read_text()))][1:]
    ws = load_workbook(out / "c.xlsx").active
    assert [row[0].value for row in ws.iter_rows(min_row=2)] == csv_ids


def test_several_outputs_without_o_is_error(multi_spec, capsys):
    assert main(["render", str(multi_spec), "--seed", "1"]) == 1
    err = capsys.readouterr().err
    assert "use -o DIR" in err and "Traceback" not in err


def test_xlsx_output_without_o_is_error(tmp_path, schema_path, capsys):
    spec = jwrite(tmp_path / "x.json", {"schema": "schema.json", "output": {"table": TABLE, "format": "xlsx"}})
    assert main(["render", str(spec), "--seed", "1"]) == 1
    assert "use -o DIR" in capsys.readouterr().err


def test_file_target_with_several_outputs_is_error(multi_spec, tmp_path, capsys):
    assert main(["render", str(multi_spec), "-o", str(tmp_path / "f.csv"), "--seed", "1"]) == 1
    assert "use -o DIR or --only" in capsys.readouterr().err
    assert not (tmp_path / "f.csv").exists()


def test_only_selects_one_output_to_stdout_and_file(multi_spec, tmp_path):
    proc = run("render", str(multi_spec), "--only", "b.txt", "--seed", "1", "--now", NOW)
    assert proc.returncode == 0
    assert proc.stdout.startswith(b"customer_id|first_name\n")
    out = tmp_path / "just.txt"
    assert main(["render", str(multi_spec), "--only", "b.txt", "-o", str(out), "--seed", "1", "--now", NOW]) == 0
    assert out.read_bytes() == proc.stdout


def test_only_unknown_is_error(multi_spec, capsys):
    assert main(["render", str(multi_spec), "--only", "zzz", "--seed", "1"]) == 1
    assert "matches no output" in capsys.readouterr().err


def test_o_xlsx_on_text_table_spec_writes_workbook(one_spec, tmp_path):
    out = tmp_path / "w.xlsx"
    assert main(["render", str(one_spec), "-o", str(out), "--seed", "1", "--now", NOW]) == 0
    assert out.read_bytes()[:2] == b"PK"
    ws = load_workbook(out).active
    assert [c.value for c in ws[1]] == ["customer_id", "first_name"]
    assert ws.max_row == 5


def test_o_xlsx_with_text_only_key_is_error(crlf_spec, tmp_path, capsys):
    assert main(["render", str(crlf_spec), "-o", str(tmp_path / "w.xlsx"), "--seed", "1"]) == 1
    assert "text-only" in capsys.readouterr().err


def test_set_override_from_cli(one_spec, tmp_path):
    out = tmp_path / "s.csv"
    argv = ["render", str(one_spec), "-o", str(out), "--seed", "1", "--set", "data.customers.count=2",
            "--set", "output.delimiter=tab"]
    assert main(argv) == 0
    lines = out.read_text().splitlines()
    assert len(lines) == 3 and lines[0] == "customer_id\tfirst_name"


# ---------------------------------------------------------------- seed


def test_same_seed_gives_identical_output(one_spec):
    a = run("render", str(one_spec), "--seed", "5", "--now", NOW)
    b = run("render", str(one_spec), "--seed", "5", "--now", NOW)
    assert a.stdout == b.stdout and b"seed=" not in a.stderr


def test_no_seed_prints_seed_to_stderr(one_spec, capsys):
    assert main(["render", str(one_spec)]) == 0
    assert capsys.readouterr().err.startswith("datagen: seed=")


def test_printed_seed_reproduces_output(one_spec):
    first = run("render", str(one_spec), "--now", NOW)
    seed = first.stderr.decode().split("seed=")[1].split()[0]
    second = run("render", str(one_spec), "--seed", seed, "--now", NOW)
    assert first.stdout == second.stdout


def test_schema_seed_is_not_announced(tmp_path, capsys):
    schema = jwrite(tmp_path / "s.json", dict(SCHEMA, seed=12))
    spec = jwrite(tmp_path / "sp.json", {"schema": "s.json", "output": {"table": TABLE}})
    assert main(["render", str(spec)]) == 0
    assert "seed=" not in capsys.readouterr().err
    assert schema.exists()


def test_bad_now_is_usage_error(one_spec, capsys):
    assert main(["render", str(one_spec), "--now", "yesterday"]) == 2
    assert "invalid ISO" in capsys.readouterr().err


# ---------------------------------------------------------------- sample / check


def test_sample_accepts_schema_and_spec(schema_path, one_spec, capsys):
    for path in (schema_path, one_spec):
        assert main(["sample", str(path), "--seed", "3", "--now", NOW]) == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data["customers"]) == 4
        assert data["customers"][0]["customer_id"] == "000001"


def test_sample_set(schema_path, capsys):
    assert main(["sample", str(schema_path), "--seed", "3", "--set", "data.customers.count=1"]) == 0
    assert len(json.loads(capsys.readouterr().out)["customers"]) == 1


def test_check_accepts_schema_and_spec(schema_path, one_spec, capsys):
    for path in (schema_path, one_spec):
        assert main(["check", str(path)]) == 0
        assert capsys.readouterr().out.strip() == "ok"


def test_check_compiles_templates(tmp_path, schema_path, capsys):
    (tmp_path / "bad.j2").write_text("{% for x in y %}\n", encoding="utf-8")
    spec = jwrite(tmp_path / "t.json", {"schema": "schema.json", "output": {"template": "bad.j2"}})
    assert main(["check", str(spec)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("datagen: error:") and "Traceback" not in err


def test_check_good_template(tmp_path, schema_path, capsys):
    (tmp_path / "ok.j2").write_text("{% for c in customers %}{{ row(c.customer_id) }}\n{% endfor %}", encoding="utf-8")
    spec = jwrite(tmp_path / "t.json", {"schema": "schema.json", "output": {"template": "ok.j2"}})
    assert main(["check", str(spec)]) == 0
    assert capsys.readouterr().out.strip() == "ok"


# ---------------------------------------------------------------- errors and help


def test_bad_json_file_exit_1_no_traceback(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    for cmd in ("check", "sample", "render"):
        proc = run(cmd, str(bad))
        assert proc.returncode == 1
        assert proc.stderr.startswith(b"datagen: error:")
        assert b"Traceback" not in proc.stderr


def test_missing_file_exit_1(tmp_path, capsys):
    assert main(["check", str(tmp_path / "missing.json")]) == 1
    assert "datagen: error:" in capsys.readouterr().err


def test_unknown_kind_exit_1(tmp_path, capsys):
    p = jwrite(tmp_path / "k.json", {"hello": 1})
    assert main(["check", str(p)]) == 1
    assert "not a datagen file" in capsys.readouterr().err


def test_help_exits_zero():
    proc = run("--help")
    assert proc.returncode == 0 and b"render" in proc.stdout


def test_help_via_main_returns_zero(capsys):
    assert main(["--help"]) == 0


def test_no_command_is_usage_error(capsys):
    assert main([]) == 2
