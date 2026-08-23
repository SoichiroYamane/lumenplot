from collections.abc import Sequence
from typing import Any


def render_line_png(
    x: Any,
    y: Any,
    *,
    viewport: Sequence[float],
    canvas: Sequence[float],
    plot_rect: Sequence[float],
    logical_units_per_inch: float,
    output_dpi: float,
    line_rgba: Sequence[int],
    line_width: float,
    background_rgba: Sequence[int],
) -> bytes: ...
