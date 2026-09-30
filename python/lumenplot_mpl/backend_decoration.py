"""Private decoration commands for the Matplotlib backend adapter.

Leaf extraction of the adapter-owned gridline/tick-stroke/spine helper
consumed by :mod:`lumenplot_mpl.backend_frame`. Mixed into ``_FrameMixin``
alongside the 2D assembly; the 2D assembly (``build_frame_spec`` and helpers)
and facade wiring stay in ``backend_frame.py``.
"""

from __future__ import annotations

from typing import Any

import matplotlib.axes
import matplotlib.colors
import matplotlib.lines

# mplot3d is part of Matplotlib's documented public plotting surface.  Keep
# these imports at the adapter edge; the engine and private raster seam never
# see Matplotlib types.
from mpl_toolkits.mplot3d.axes3d import Axes3D

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

    def _check_axes_decorations(
        self, ax: matplotlib.axes.Axes, *, decorated: bool
    ) -> None:
        """Whitelist-check one axes and its decoration surface.

        Since the PRAC-A-D amendment of ADR 0015 §4 a standard decorated
        ``Axes`` is eligible: solid major gridlines, major tick strokes,
        and spine edges render as explicit path commands. Since the B-2a
        (R2) extension the visible non-empty ``xlabel``/``ylabel`` pair is
        eligible as well: each label renders as explicit glyph path
        commands through the same ``_check_tick_label_static`` surface as
        tick labels. Since the B-2a (R3) extension the visible non-empty
        center ``title`` is eligible as well through that same surface,
        and since the loc-title slice the visible non-empty left/right
        ``title`` pair is eligible through it too. Everything else about
        the decoration surface (visible minor tick content, non-solid
        grid styles, an opaque facecolor, offset text, or child axes)
        records an explicit unsupported reason.
        """
        if isinstance(ax, Axes3D):
            if decorated:
                self.unsupported(
                    "3D axis, pane, or grid decorations are unsupported in "
                    "native mode; use explicit axis-off fixtures",
                    type(ax).__name__,
                )
            return
        if not decorated:
            # Decoration-less axes: no decoration properties were observed.
            return
        face = tuple(
            float(c) for c in matplotlib.colors.to_rgba(ax.get_facecolor())
        )
        # This slice renders no axes background fill command (transparent
        # maintenance, lane decision): an axes carrying any other facecolor
        # is explicitly refused rather than silently drawn unfilled.
        # AC (a)'s eligible fixture sets ``ax.set_facecolor("none")``.
        if face[3] != 0.0:
            self.unsupported(
                "axes background fills are unsupported; set "
                "facecolor='none' for strict mode",
                "Axes",
            )
        # Loc-title slice: the visible non-empty center/left/right titles
        # are each eligible through the shared T-lane static surface
        # (same whitespace, multi-line, math/TeX, path-effect, font-size,
        # sketch, snap, and clip contract as tick labels, plus an explicit
        # hyperlink refusal). Legend titles stay refused. Empty or
        # invisible titles draw nothing, so they skip the check like empty
        # tick labels. Draw order is center, then left, then right (the
        # order Matplotlib emits their direct text children).
        center_title = ax.title
        if center_title.get_visible() and center_title.get_text() != "":
            self._check_title_static(center_title)
        for loc_title in (ax._left_title, ax._right_title):
            if loc_title.get_visible() and loc_title.get_text() != "":
                self._check_title_static(loc_title)
        # B-2a (R2): the visible non-empty xlabel/ylabel pair is eligible
        # through the shared T-lane static surface (same whitespace,
        # multi-line, math/TeX, path-effect, font-size, sketch, snap, and
        # clip contract as tick labels, plus an explicit hyperlink
        # refusal). Titles (all three positions), offset text, and
        # legend titles stay refused. Empty or invisible labels draw
        # nothing, so they skip the check like empty tick labels.
        for axis in (ax.xaxis, ax.yaxis):
            label = axis.get_label()
            if not label.get_visible() or label.get_text() == "":
                continue
            self._check_axis_label_static(label)
        for axis in (ax.xaxis, ax.yaxis):
            axis_name = type(axis).__name__
            if axis.get_offset_text().get_text() != "":
                self.unsupported("offset text is unsupported", "Text")
            for label in axis.get_majorticklabels():
                # Tick label glyphs are the T-lane deliverable: since the
                # PRAC-A-W wire-up a visible non-empty major label is
                # accepted and rendered as explicit glyph path commands.
                if not label.get_visible() or label.get_text() == "":
                    continue
                self._check_tick_label_static(label)
            if any(t.get_visible() for t in axis.get_minorticklines()):
                self.unsupported(
                    "visible minor ticks are unsupported; strict mode "
                    "supports major ticks only",
                    axis_name,
                )
            for gridline in axis.get_gridlines():
                if not gridline.get_visible():
                    continue
                style = str(gridline.get_linestyle())
                if style != "-":
                    self.unsupported(
                        f"solid gridlines are required; {style!r} is "
                        "unsupported in strict mode",
                        axis_name,
                    )
                if gridline.is_dashed():
                    self.unsupported(
                        "solid gridlines are required; dashed grids are "
                        "unsupported in strict mode",
                        axis_name,
                    )
            minor_grid = [
                t.gridline for t in axis.get_minor_ticks()
                if t.gridline.get_visible()
            ]
            if minor_grid:
                self.unsupported(
                    "minor gridlines are unsupported; strict mode "
                    "supports which='major' only",
                    axis_name,
                )
            for side in ("left", "bottom"):
                # With decorations on, Matplotlib always draws these edges.
                self._check_spine_static(ax.spines[side])
            if axis is ax.xaxis and ax.xaxis.get_ticks_position() in (
                "top",
                "unknown",
            ):
                self._check_spine_static(ax.spines["top"])
            if axis is ax.yaxis and ax.yaxis.get_ticks_position() in (
                "right",
                "unknown",
            ):
                self._check_spine_static(ax.spines["right"])

    def _check_spine_static(self, spine: Any) -> None:
        """Collect visible spine edges into the fixed-style surface.

        Spines ride the seam with Miter join and the artist's own cap
        style (Matplotlib's Spine default is projecting caps, which Agg
        honors at the axes corners); only their width, color, cap, and
        visibility are honored from public getters. Cap styles outside
        the seam's Butt/Round/Projecting set are refused here.
        """
        name = type(spine).__name__
        if spine.get_linewidth() < 0:
            self.unsupported("negative line width", name)
        if spine.get_path_effects():
            self.unsupported("path effects are unsupported", name)
        if str(spine.get_capstyle()) not in ("butt", "round", "projecting"):
            self.unsupported(
                f"spine cap style {str(spine.get_capstyle())!r} is unsupported",
                name,
            )
