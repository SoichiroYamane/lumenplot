"""Private support helpers for the public Matplotlib backend."""

from __future__ import annotations

import math
import numbers
from typing import Any

import matplotlib


_RGBA_BLACK = (0, 0, 0, 255)
_STEP_DRASTYLES = frozenset({"steps", "steps-pre", "steps-post", "steps-mid"})


def _rgba8(color: Any, alpha: float | None = None) -> tuple[int, int, int, int]:
    """Convert a Matplotlib color to an encoded RGBA8 tuple."""
    r, g, b, a = matplotlib.colors.to_rgba(color)
    if alpha is not None:
        a = float(alpha) * a
    channel = (
        int(round(min(max(r, 0.0), 1.0) * 255)),
        int(round(min(max(g, 0.0), 1.0) * 255)),
        int(round(min(max(b, 0.0), 1.0) * 255)),
        int(round(min(max(a, 0.0), 1.0) * 255)),
    )
    return (0, 0, 0, 0) if channel[3] == 0 else channel


def _native_f64(value: Any) -> bool:
    """Return whether a processed value can enter the native f64 seam."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return False
    try:
        float(value)
    except (OverflowError, TypeError, ValueError):
        return False
    return True


def _finite(value: Any) -> bool:
    """Return whether a value is a finite native-real scalar."""
    return _native_f64(value) and math.isfinite(float(value))


def _expand_step_vertices(xdata: list, ydata: list, drawstyle: str):
    """Expand sampled data according to Matplotlib step semantics."""
    count = len(xdata)
    if drawstyle == "steps-mid":
        expanded_x: list = [xdata[0]]
        expanded_y: list = [ydata[0]]
        for index in range(count - 1):
            midpoint = (xdata[index] + xdata[index + 1]) / 2.0
            expanded_x.append(midpoint)
            expanded_y.append(ydata[index])
            expanded_x.append(midpoint)
            expanded_y.append(ydata[index + 1])
        expanded_x.append(xdata[-1])
        expanded_y.append(ydata[-1])
        return expanded_x, expanded_y
    expanded_x = [0.0] * (2 * count - 1)
    expanded_y = [0.0] * (2 * count - 1)
    for index in range(count):
        expanded_x[2 * index] = xdata[index]
        expanded_y[2 * index] = ydata[index]
        if index == count - 1:
            break
        if drawstyle == "steps-post":
            expanded_x[2 * index + 1] = xdata[index + 1]
            expanded_y[2 * index + 1] = ydata[index]
        else:
            expanded_x[2 * index + 1] = xdata[index]
            expanded_y[2 * index + 1] = ydata[index + 1]
    return expanded_x, expanded_y


class _SpineStroke:
    """Line2D-style public-getter view over one Matplotlib Spine."""

    def __init__(self, spine: Any) -> None:
        self._spine = spine

    def get_color(self) -> Any:
        return self._spine.get_edgecolor()

    def get_alpha(self) -> float | None:
        alpha = self._spine.get_alpha()
        return None if alpha is None else float(alpha)

    def get_linewidth(self) -> float:
        return float(self._spine.get_linewidth())
