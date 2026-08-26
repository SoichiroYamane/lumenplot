"""Text-to-path glyph outline extraction (PRAC-A-T lane, Phase-3B).

Extracts filled-glyph outlines for a text string through the documented
public ``matplotlib.textpath.TextPath`` API only, and converts them into
path commands in the vocabulary of the frozen whole-frame seam spec.
This module is a pure library: it renders nothing, touches no canvas
state, and never imports the package's private extension module.

Coordinate contract (workstream-manager decisions 1-5, PRAC-A-T):

- TextPath emits glyph outlines in *points* with y increasing upward and
  the typographic baseline at y = 0 (descenders are negative). This is
  verified empirically by this lane's test suite against the installed
  Matplotlib rather than trusted from prose.
- The frozen seam signature has no frame-height parameter, so this module
  emits vertices already converted to *top-left pixel* coordinates
  (y increasing downward) under an identity transform; a spec assembler
  that needs display-space geometry instead applies its own global
  display flip to these vertices.

Failure policy (decision 4): unsupported inputs raise ValueError with a
stable ``unsupported-text-path`` reason token embedded in the message.
No fallback rasterization happens here and no warning is emitted; the
caller decides how to surface the failure.
"""

from __future__ import annotations

import math
from typing import Any

from matplotlib.path import Path
from matplotlib.textpath import TextPath

__all__ = ["glyph_outline_commands", "UNSUPPORTED_TEXT_PATH"]


def _unsupported(reason: str) -> ValueError:
    return ValueError(f"unsupported-text-path: {reason}")


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


# Matplotlib path code -> frozen seam path code. The numeric values match
# the seam's accepted set exactly (STOP=0, MOVETO=1, LINETO=2, CURVE3=3,
# CURVE4=4, CLOSEPOLY=79); the mapping is spelled out so a future seam
# change cannot pass silently.
_CODE_MAP = {
    Path.STOP: 0,
    Path.MOVETO: 1,
    Path.LINETO: 2,
    Path.CURVE3: 3,
    Path.CURVE4: 4,
    Path.CLOSEPOLY: 79,
}


def _as_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise _unsupported("non-finite vertex coordinate") from None
    if not math.isfinite(number):
        raise _unsupported("non-finite vertex coordinate")
    return number


def glyph_outline_commands(
    text: str,
    origin_px: tuple[float, float],
    scale_x: float,
    shear_x: float,
    *,
    font_size_pt: float = 10.0,
) -> list[dict[str, Any]]:
    """Return one frozen-seam ``kind: "path"`` command for ``text``.

    The command carries the complete filled outline of every glyph:
    vertices in top-left pixel coordinates, parallel codes, an identity
    transform, ``fill_rgba`` [0, 0, 0, 255], ``stroke_rgba`` null, zero
    stroke width, butt cap, miter join, nonzero fill rule, antialiasing
    on, and no clip rectangle (clip is applied by the frame assembler).

    ``origin_px`` anchors the baseline start in top-left pixel space;
    y grows downward from it. Glyph interiors keep TextPath's y-up sign,
    which is negated here once per vertex so ink extends upward on screen.

    Raises ValueError with the ``unsupported-text-path`` token for empty
    or whitespace-only text, non-finite arguments, or any outline shape
    the frozen seam cannot represent.
    """
    if not isinstance(text, str):
        raise _unsupported("text must be a string")
    if not text.strip():
        # TextPath itself crashes on whitespace-only input (observed on
        # 3.11.x: the empty outline reaches Path.__init__ as a plain
        # list), so this lane rejects it explicitly before construction.
        raise _unsupported("text must contain visible glyphs")
    origin_x = _as_float(origin_px[0] if len(origin_px) > 0 else None)
    origin_y = _as_float(origin_px[1] if len(origin_px) > 1 else None)
    scale_x = _as_float(scale_x)
    shear_x = _as_float(shear_x)
    font_size_pt = _as_float(font_size_pt)

    text_path = TextPath(
        (0.0, 0.0),
        text,
        size=float(font_size_pt),
        prop=None,
    )
    vertices = text_path.vertices
    raw_codes = text_path.codes

    if vertices.ndim != 2 or vertices.shape[1] != 2 or len(raw_codes) != len(vertices):
        raise _unsupported("TextPath produced an unexpected outline shape")

    commands: list[dict[str, Any]] = []
    out_vertices: list[list[float]] = []
    out_codes: list[int] = []
    for index in range(len(raw_codes)):
        code = int(raw_codes[index])
        mapped = _CODE_MAP.get(code)
        if mapped is None:
            raise _unsupported(f"path code {code} is not representable")
        x = _as_float(vertices[index][0])
        y = _as_float(vertices[index][1])
        # TextPath space: points, baseline y=0, y up. Target space: pixels,
        # y down. One explicit negation per vertex keeps the transform
        # identity and the arithmetic auditable.
        out_vertices.append(
            [
                origin_x + x * scale_x + (-y) * shear_x,
                origin_y + -y,
            ]
        )
        out_codes.append(mapped)
    if not out_vertices:
        raise _unsupported("outline contained no vertices")

    commands.append(
        {
            "kind": "path",
            "vertices": out_vertices,
            "codes": out_codes,
            "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            "stroke_rgba": None,
            "fill_rgba": [0, 0, 0, 255],
            "line_width_pt": 0.0,
            "cap": "butt",
            "join": "miter",
            "dash_offset_pt": 0.0,
            "dashes": None,
            "fill_rule": "nonzero",
            "antialias": True,
            "clip_rect": None,
        }
    )
    return commands
