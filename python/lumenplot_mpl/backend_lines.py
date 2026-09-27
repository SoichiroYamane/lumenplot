"""Private line frame-spec slice for the Matplotlib backend adapter.

Leaf extraction of the adapter-owned Line2D frame-spec helper consumed by
:mod:`lumenplot_mpl.backend_frame`. Mixed into ``_FrameMixin`` alongside the
2D assembly; the 2D assembly (``build_frame_spec`` and helpers) and facade
wiring stay in ``backend_frame.py``.
"""

from __future__ import annotations

import matplotlib.lines

from lumenplot_mpl.backend_support import (
    _STEP_DRASTYLES,
    _expand_step_vertices,
    _finite,
    _native_f64,
    _rgba8,
)


class _LineMixin:
    """Line frame-spec command moved verbatim from ``backend_frame.py``.

    Mixed into ``_FrameMixin`` (which stays in ``backend_frame.py`` so its
    ``__module__`` pin and ``backend_preflight`` import surface stay stable).
    Shared state (``__init__``) and the facade entries (``collect``,
    ``unsupported``) stay on the facade class; this mixin must not fork
    state and must not import from ``backend_frame`` or ``backend_preflight``.
    """

    def _line_command(self, line, to_px_x, to_px_y, axes_position: int):
        name = type(line).__name__
        if not isinstance(line, matplotlib.lines.Line2D):
            self.unsupported("non-line artist reached rendering", name)
            return None
        # LP-FUNC-037: ``orig=False`` is the unit-processed route -- date
        # and other unit converters have already resolved to floats here
        # (parity draft §4, F-10), matching both Agg's drawn geometry and
        # this builder's axes-limits projection. The raw route would hand
        # back datetime objects that the finite filter must refuse.
        xdata = list(line.get_xdata(orig=False))
        ydata = list(line.get_ydata(orig=False))
        if len(xdata) != len(ydata) or not xdata:
            self.unsupported("mismatched or empty line data", name)
            return None
        for axis_name, values in (("x", xdata), ("y", ydata)):
            for value in values:
                if not _native_f64(value):
                    # Do not let the finite-row filter below turn a failed
                    # unit conversion into a partial or empty success. The
                    # message intentionally names only the public data
                    # boundary and value type; converted payload contents are
                    # not a diagnostic identity.
                    self.unsupported(
                        f"processed {axis_name}-data contains a "
                        f"{type(value).__name__} that is not representable "
                        "as native f64",
                        name,
                    )
                    return None
        # LP-FUNC-040: keep every non-finite row in the default path as a
        # pen-lift sentinel. The frame seam consumes those sentinels without
        # drawing them, and starts a new subpath at the next finite sample;
        # filtering them here would reconnect the runs and bridge the gap.
        # LP-FUNC-034: the step family expands the SAMPLED data exactly.
        # A non-finite sample has no step semantics (Agg's own path
        # cleaning re-pairs the risers around the gap, so neither dropping
        # the row nor bridging it reproduces the oracle), therefore stepped
        # lines refuse explicitly instead of approximating -- LP-MPL-020
        # forbids silent approximation.
        finite_rows = [
            (x, y)
            for x, y in zip(xdata, ydata)
            if _finite(x) and _finite(y)
        ]
        drawstyle = line.get_drawstyle()
        if drawstyle in _STEP_DRASTYLES:
            if len(finite_rows) != len(xdata):
                self.unsupported(
                    "non-finite samples are unsupported under step "
                    "drawstyles",
                    name,
                )
                return None
            base_x, base_y = xdata, ydata
        else:
            if len(finite_rows) < 2:
                self.unsupported("fewer than two finite points", name)
                return None
            base_x, base_y = xdata, ydata
        if drawstyle in _STEP_DRASTYLES and len(base_x) >= 1:
            expanded_x, expanded_y = _expand_step_vertices(
                base_x, base_y,
                "steps-pre" if drawstyle == "steps" else drawstyle,
            )
        else:
            expanded_x, expanded_y = base_x, base_y
        vertices = [
            [
                float(x) if not _finite(x) else to_px_x(x),
                float(y) if not _finite(y) else to_px_y(y),
            ]
            for x, y in zip(expanded_x, expanded_y)
        ]
        if len(vertices) < 2:
            self.unsupported("fewer than two finite points", name)
            return None
        stroke = _rgba8(line.get_color(), line.get_alpha())
        cap = str(line.get_solid_capstyle())
        join = str(line.get_solid_joinstyle())
        if cap != "butt" or join != "miter":
            # Stage one already rejected non-Butt/Miter effective styles
            # (ADR-0015 §5); reaching here means the collector trace and
            # static whitelist disagreed, which is an internal fault.
            self.unsupported(
                f"effective cap/join {cap!r}/{join!r} outside the fixed "
                "strict-mode style set",
                name,
            )
        # The validated rectangular clip, in seam-canonical bottom-left
        # display pixels ``(x, y, w, h)``. The native rasterizer folds the
        # display-to-row flip itself (``DeviceClip::from_display``), so
        # the adapter must not pre-flip.
        clip_rect: list[float] | None = None
        clip_points = self._axes_clip_points.get(
            axes_position, self._clip_points
        )
        if clip_points is not None:
            (cx0, cy0), (cx1, cy1) = clip_points
            left = min(cx0, cx1)
            right = max(cx0, cx1)
            bottom = min(cy0, cy1)
            top = max(cy0, cy1)
            clip_rect = [
                float(left),
                float(bottom),
                float(right - left),
                float(top - bottom),
            ]
        return {
            "kind": "path",
            "vertices": [[float(vx), float(vy)] for vx, vy in vertices],
            "codes": None,
            "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            "stroke_rgba": list(stroke),
            "line_width_pt": float(line.get_linewidth()),
            "cap": cap,
            "join": join,
            "dash_offset_pt": 0.0,
            "dashes": None,
            "fill_rule": "nonzero",
            "antialias": True,
            "clip_rect": clip_rect,
        }
