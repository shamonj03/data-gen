"""Format helper modules registered into the Jinja environment."""
from __future__ import annotations

import importlib

from jinja2 import Environment

FORMAT_MODULES: list[str] = ["ach"]


def register_all(env: Environment) -> None:
    """Import each format module and add its `GLOBALS` to the environment."""
    for name in FORMAT_MODULES:
        module = importlib.import_module(f"datagen.formats.{name}")
        env.globals.update(module.GLOBALS)
