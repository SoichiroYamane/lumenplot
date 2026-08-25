from collections.abc import Mapping, Sequence
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


def render_frame_png(spec: Mapping[str, Any]) -> bytes:
    """Render a validated frame spec to PNG bytes.

    ``spec`` carries required keys ``width_px``, ``height_px``,
    ``output_dpi`` and ``commands`` plus the optional straight-alpha sRGB8
    canvas seed ``background_rgba`` ([r, g, b, a]); an absent seed keeps
    the canvas fully transparent. The optional ``blend_mode`` key selects
    the compositing color model: ``"linear"`` (default) composites in
    premultiplied linear-sRGB per ADR 0012; ``"agg_srgb"`` composites in
    encoded sRGB to match the Agg quality oracle (architecture ruling
    2026-08-25).
    """
    ...
