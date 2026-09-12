"""Text-to-path glyph outline extraction (PRAC-A-T lane, Phase-3B).

The compatibility helper extracts filled-glyph outlines through the
documented ``matplotlib.textpath.TextPath`` API and converts them
into path commands in the vocabulary of the frozen whole-frame seam spec.
The adapter-internal P3 writer helper additionally follows Agg's
font-at-output-DPI glyph layout and hinting path for labels. Both routes are
pure: they render nothing, touch no canvas state, and never import the
package's private extension module.

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

from matplotlib.font_manager import FontProperties
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
    prop: FontProperties | None = None,
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

    ``prop`` carries the label's public ``FontProperties`` (family, style,
    variant, weight, stretch); ``font_size_pt`` carries its resolved size.
    Both are forwarded to ``TextPath`` so the outline honors exactly the
    face Agg resolves for the same artist (T-lane style contract, §15.1
    part 3). When ``prop`` is None the previous default-face behavior is
    kept. A non-``FontProperties`` ``prop`` is refused explicitly.

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
    if prop is not None and not isinstance(prop, FontProperties):
        raise _unsupported("font properties must be a FontProperties")
    origin_x = _as_float(origin_px[0] if len(origin_px) > 0 else None)
    origin_y = _as_float(origin_px[1] if len(origin_px) > 1 else None)
    scale_x = _as_float(scale_x)
    shear_x = _as_float(shear_x)
    font_size_pt = _as_float(font_size_pt)

    text_path = TextPath(
        (0.0, 0.0),
        text,
        size=float(font_size_pt),
        prop=prop,
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


def _writer_glyph_outline_commands(
    text: str,
    origin_px: tuple[float, float],
    scale_x: float,
    shear_x: float,
    *,
    font_size_pt: float = 10.0,
    prop: FontProperties | None = None,
    dpi: float = 100.0,
) -> list[dict[str, Any]]:
    """Return an Agg-hinted outline for the adapter's label writer path.

    Matplotlib's ordinary ``TextPath`` deliberately asks FreeType for
    ``NO_HINTING`` outlines.  Agg instead lays out each glyph at the output
    DPI with its configured hinting flags before rasterizing it.  The P3
    route mirrors that writer-side preparation and converts the resulting
    glyph paths back to logical points because the frame assembler applies
    the output-DPI scale once more.

    This helper is intentionally private.  The documented
    ``glyph_outline_commands`` route remains the stable TextPath contract
    used by callers that need unhinted point-space outlines; the backend
    selects this route only for its native tick/legend label commands.  It
    emits the same frozen command shape and coordinate convention as
    :func:`glyph_outline_commands`.
    """
    if not isinstance(text, str):
        raise _unsupported("text must be a string")
    if not text.strip():
        raise _unsupported("text must contain visible glyphs")
    if prop is not None and not isinstance(prop, FontProperties):
        raise _unsupported("font properties must be a FontProperties")

    try:
        origin_x = _as_float(origin_px[0] if len(origin_px) > 0 else None)
        origin_y = _as_float(origin_px[1] if len(origin_px) > 1 else None)
    except (IndexError, TypeError):
        raise _unsupported("origin_px must contain two finite coordinates") from None
    scale_x = _as_float(scale_x)
    shear_x = _as_float(shear_x)
    font_size_pt = _as_float(font_size_pt)
    dpi = _as_float(dpi)
    if dpi <= 0.0:
        raise _unsupported("dpi must be finite and > 0")

    if prop is None:
        prop = FontProperties()

    # Matplotlib's public FT2Font methods expose the same output-DPI
    # positions and hinted glyph outlines that Agg consumes.  Keeping this
    # bridge inside the adapter avoids importing a renderer or its bitmap
    # buffer while retaining the writer's quantized glyph geometry.
    try:
        from matplotlib.backends.backend_agg import get_hinting_flag
        from matplotlib.font_manager import findfont, get_font

        font = get_font(findfont(prop, fontext="ttf"))
        font.clear()
        font.set_size(float(font_size_pt), float(dpi))
        hinting_flags = get_hinting_flag()
        positions = font.set_text(text, 0.0, flags=hinting_flags)
        if len(positions) != len(text):
            raise ValueError("writer returned one position per glyph")
    except ValueError as error:
        if str(error).startswith("unsupported-text-path:"):
            raise
        raise _unsupported(f"font layout failed: {error}") from error
    except (AttributeError, OSError, RuntimeError, TypeError) as error:
        raise _unsupported(f"font layout failed: {error}") from error

    scale = dpi / 72.0
    out_vertices: list[list[float]] = []
    out_codes: list[int] = []
    try:
        for char, position in zip(text, positions):
            glyph_index = font.get_char_index(ord(char))
            font.load_glyph(glyph_index, flags=hinting_flags)
            vertices, raw_codes = font.get_path()
            position_x = _as_float(position[0]) / 64.0
            position_y = _as_float(position[1]) / 64.0
            for index in range(len(raw_codes)):
                code = int(raw_codes[index])
                mapped = _CODE_MAP.get(code)
                if mapped is None:
                    raise _unsupported(
                        f"path code {code} is not representable"
                    )
                x = _as_float(vertices[index][0])
                y = _as_float(vertices[index][1])
                # Agg's item positions and glyph paths are output pixels;
                # return points so the frame assembler's one DPI scale is
                # the only subsequent unit conversion.
                x_pt = (position_x + x) / scale
                y_pt = -(position_y + y) / scale
                out_vertices.append(
                    [
                        origin_x + x_pt * scale_x + y_pt * shear_x,
                        origin_y + y_pt,
                    ]
                )
                out_codes.append(mapped)
    except ValueError as error:
        if str(error).startswith("unsupported-text-path:"):
            raise
        raise _unsupported(f"font outline failed: {error}") from error
    except (AttributeError, IndexError, TypeError) as error:
        raise _unsupported(f"font outline failed: {error}") from error

    if not out_vertices:
        raise _unsupported("outline contained no vertices")

    return [
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
    ]
