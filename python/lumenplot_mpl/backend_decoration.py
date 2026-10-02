"""Private decoration commands for the Matplotlib backend adapter.

Leaf extraction of the adapter-owned gridline/tick-stroke/spine helper
consumed by :mod:`lumenplot_mpl.backend_frame`. Mixed into ``_FrameMixin``
alongside the 2D assembly; the 2D assembly (``build_frame_spec`` and helpers)
and facade wiring stay in ``backend_frame.py``.
"""

from __future__ import annotations

import matplotlib.axes
import matplotlib.lines

from lumenplot_mpl.backend_support import (
    _SpineStroke,
    _rgba8,
)


class _DecorationMixin:
    """Gridline/tick-stroke/spine commands moved verbatim from ``backend_frame.py``.

    Mixed into ``_FrameMixin`` (which stays in ``backend_frame.py`` so its
    ``__module__`` pin and ``backend_preflight`` import surface stay stable).
    Shared state (``__init__``) and the facade entries (``collect``,
    ``unsupported``) stay on the facade class; this mixin must not fork
    state and must not import from ``backend_frame`` or ``backend_preflight``.
    """

    def _decoration_commands(
        self,
        ax: matplotlib.axes.Axes,
        x0: float,
        y0: float,
        w: float,
        h: float,
        *,
        kinds: tuple[str, ...] = ("gridline", "tick", "spine"),
        to_px_x=None,
        to_px_y=None,
    ) -> list[dict]:
        """Build gridline/tick/spine path commands for one axes.

        Geometry comes from documented public getters only: major tick
        locations from ``Axis.get_ticklocs`` filtered into view, tick
        stroke style from the edge ``Line2D`` markers, and spine edges
        from the axes rectangle with the fixed §5 stroke surface.
        Gridlines clip to their own axes rectangle; spine edges and tick
        strokes protrude outside it, so they clip to the full canvas
        like Agg (which draws spine strokes and tick marks unclipped:
        pinned Agg draw_path reports clip_rect=None for every spine).
        """
        # The frozen seam clip is bottom-left-origin (x, y, w, h). Gridlines
        # stay inside the axes rectangle; spine edges sit exactly on its
        # boundary (half the stroke width spills outside) and tick strokes
        # protrude outside it, so both carry a full-canvas clip like Agg.
        axes_clip = [float(x0), float(y0), float(w), float(h)]
        canvas_clip = [
            0.0,
            0.0,
            float(self._canvas_width_px),
            float(self._height_px),
        ]
        commands: list[dict] = []
        xaxis, yaxis = ax.xaxis, ax.yaxis
        xlim, ylim = ax.get_xlim(), ax.get_ylim()

        def seg(p0: tuple[float, float], p1: tuple[float, float],
                line: matplotlib.lines.Line2D, deco: str,
                clip: list[float], cap: str = "butt") -> dict:
            return {
                "kind": "path",
                "decoration": deco,
                "vertices": [[float(p0[0]), float(p0[1])],
                             [float(p1[0]), float(p1[1])]],
                "codes": None,
                "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
                "stroke_rgba": list(_rgba8(line.get_color(),
                                           line.get_alpha())),
                "line_width_pt": float(line.get_linewidth()),
                "cap": cap,
                "join": "miter",
                "dash_offset_pt": 0.0,
                "dashes": None,
                "fill_rule": "nonzero",
                "antialias": True,
                "clip_rect": list(clip),
            }

        # -- solid major gridlines (which='major') ------------------------
        # A visible major gridline spans the axes at each in-view tick
        # location; the static stage proved every visible one is solid.
        # The per-tick gridline Line2D carries the effective style; the
        # first one is a style-safe representative for the whole axis.
        if "gridline" in kinds:
            for axis, vertical in ((xaxis, True), (yaxis, False)):
                representative = next(
                    (g for g in axis.get_gridlines() if g.get_visible()),
                    None,
                )
                if representative is None:
                    continue
                data_lo, data_hi = (
                    (float(xlim[0]), float(xlim[1]))
                    if vertical
                    else (float(ylim[0]), float(ylim[1]))
                )
                project = to_px_x if vertical else to_px_y
                for loc in axis.get_ticklocs():
                    value = float(loc)
                    if not (data_lo <= value <= data_hi):
                        continue
                    if vertical:
                        at = float(project(value))
                        p0 = (at, float(y0))
                        p1 = (at, float(y0 + h))
                    else:
                        at = float(project(value))
                        p0 = (float(x0), at)
                        p1 = (float(x0 + w), at)
                    commands.append(seg(p0, p1, representative,
                                        "gridline", axes_clip))

        # -- major tick strokes --------------------------------------------
        # One outward stroke per drawn tick position on each visible edge,
        # styled from the edge tick line's public marker getters.
        if "tick" in kinds:
            dpi_scale = self._effective_dpi / 72.0
            for axis, horizontal, edges in ((xaxis, True, ("bottom", "top")),
                                            (yaxis, False, ("left", "right"))):
                ticks = axis.get_major_ticks()
                locs = list(axis.get_ticklocs())
                project = to_px_x if horizontal else to_px_y
                for index, tick in enumerate(ticks):
                    if index >= len(locs):
                        break
                    value = float(locs[index])
                    data_lo, data_hi = (
                        (float(xlim[0]), float(xlim[1]))
                        if horizontal
                        else (float(ylim[0]), float(ylim[1]))
                    )
                    if not (data_lo <= value <= data_hi):
                        continue
                    base = float(project(value))
                    for side in edges:
                        line = getattr(
                            tick,
                            f"tick{1 if side in ('bottom', 'left') else 2}line",
                        )
                        if not line.get_visible():
                            continue
                        length_px = (
                            float(line.get_markersize()) * dpi_scale
                        )
                        # Bottom-left pixel space (matching the content-line
                        # geometry): outward means downward from the bottom
                        # edge and leftward from the left edge.
                        direction = -1.0 if side in ("bottom", "left") else 1.0
                        if horizontal:
                            p0 = (base, float(y0))
                            p1 = (base, float(y0 + direction * length_px))
                        else:
                            p0 = (float(x0), base)
                            p1 = (float(x0 + direction * length_px), base)
                        commands.append(seg(p0, p1, line, "tick",
                                            canvas_clip))

        # -- spine edges -----------------------------------------------------
        # Visible spines draw the axes rectangle edges with the fixed §5
        # stroke surface; width and color come from the spine getters.
        # Agg draws spine strokes unclipped (clip_rect=None), so spines
        # carry the full-canvas clip: an axes clip would shave the half
        # stroke width that legitimately spills over the boundary.
        if "spine" in kinds:
            for side, p0, p1 in (
                ("bottom", (x0, y0), (x0 + w, y0)),
                ("top", (x0, y0 + h), (x0 + w, y0 + h)),
                ("left", (x0, y0), (x0, y0 + h)),
                ("right", (x0 + w, y0), (x0 + w, y0 + h)),
            ):
                spine = ax.spines[side]
                if not spine.get_visible():
                    continue
                command = seg(
                    (float(p0[0]), float(p0[1])),
                    (float(p1[0]), float(p1[1])),
                    _SpineStroke(spine),
                    "spine",
                    canvas_clip,
                    cap=str(spine.get_capstyle()),
                )
                commands.append(command)

        return commands

    def _decoration_flags(
        self, events: list[tuple], axes_count: int
    ) -> list[bool]:
        """Return which Axes emitted a public decoration group.

        The callback stream is the only public observation of the decoration
        mode.  Keep the result aligned with ``Figure.get_axes()`` so the
        geometry assembler can make the same decision without reading an
        undocumented Axes attribute.
        """
        flags = [False] * axes_count
        axes_index = -1
        in_axes = False
        for event in events:
            kind = event[0]
            tag = event[1] if len(event) > 1 else None
            if kind == "open" and tag == "axes":
                axes_index += 1
                in_axes = axes_index < axes_count
            elif kind == "close" and tag == "axes":
                in_axes = False
            elif (
                in_axes
                and axes_index < axes_count
                and kind == "open"
                and tag in ("matplotlib.axis", "axis3d", "pane3d", "grid3d")
            ):
                flags[axes_index] = True
        return flags
