from __future__ import annotations


class DatagenError(Exception):
    """Base class for all datagen errors."""


class SchemaError(DatagenError):
    """A schema is invalid. `path` locates the offending node, `msg` says why."""

    def __init__(self, path: str, msg: str) -> None:
        self.path = path
        self.msg = msg
        super().__init__(f"{path}: {msg}")


class RenderError(DatagenError):
    """Rendering failed, optionally at a template line."""

    def __init__(self, msg: str, line: int | None = None) -> None:
        self.msg = msg
        self.line = line
        super().__init__(f"line {line}: {msg}" if line is not None else msg)
