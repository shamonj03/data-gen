"""Line postprocessors applied to rendered text output."""
from __future__ import annotations

from typing import Callable


def block_pad(lines: list[str], size: int = 10, fill: str = "9", width: int | None = None) -> list[str]:
    """Pad with `fill`-lines up to a multiple of `size` lines."""
    if not lines:
        return lines
    pad = fill * (width or len(lines[0]))
    missing = -len(lines) % size
    return [*lines, *[pad] * missing]


POSTPROCESSORS: dict[str, Callable[..., list[str]]] = {"block_pad": block_pad}
