from pathlib import Path

from datagen.errors import DatagenError, RenderError, SchemaError
from datagen.types import OutputSpec, RenderSpec, Schema, TableSpec


def test_schema_error_str():
    assert str(SchemaError("a.b", "bad")) == "a.b: bad"


def test_render_error_str():
    assert str(RenderError("x", line=3)) == "line 3: x"
    assert str(RenderError("x")) == "x"


def test_output_spec_defaults():
    assert OutputSpec().format == "text"


def test_types_construct():
    schema = Schema(path=None, locale="en_US", seed=None, params={}, data={})
    assert TableSpec(rows="r")
    assert RenderSpec(path=Path("x"), schema=schema, outputs=(OutputSpec(),))


def test_error_hierarchy():
    assert issubclass(SchemaError, DatagenError)
    assert issubclass(RenderError, DatagenError)
