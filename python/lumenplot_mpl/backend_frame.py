"""Private frame-spec assembly for the backend."""

from __future__ import annotations

import math
from typing import Any

import matplotlib
import matplotlib.axes  # noqa: F401 - public submodule for type checks
import matplotlib.collections  # noqa: F401 - public submodule for the whitelist
import matplotlib.lines  # noqa: F401 - public submodule for the whitelist
import matplotlib.patches  # noqa: F401 - public submodule for the whitelist
import numpy
from matplotlib.path import Path

# mplot3d is part of Matplotlib's documented public plotting surface.  Keep
# 3D imports at the adapter edge in backend_frame_3d.py; the engine and
# private raster seam never see Matplotlib types.

from lumenplot_mpl.backend_decoration import _DecorationMixin
from lumenplot_mpl.backend_frame_3d import _Frame3DMixin
from lumenplot_mpl.backend_lines import _LineMixin
from lumenplot_mpl.backend_support import (
    _RGBA_BLACK,
    _SpineStroke,
    _finite,
    _rgba8,
)
from lumenplot_mpl.backend_textlabels import _TextLabelsMixin
from lumenplot_mpl.backend_types import LumenPlotUnsupportedError


class _FrameMixin(_DecorationMixin, _TextLabelsMixin, _Frame3DMixin, _LineMixin):
    """Frame-spec geometry commands (ADR 0015 sections 5-6, API 0005 section 5).

    Mixed into ``_EligibilityPreflight`` (which stays in
    ``backend_preflight.py`` so its ``__module__`` pin stays stable).
    Shared state (``__init__``) and the facade entries (``collect``,
    ``unsupported``) stay on the facade class; this mixin must not fork
    state and must not import from ``backend_preflight``.
    """

    def build_frame_spec(
        self,
        figure: matplotlib.figure.Figure,
        *,
        width_px: int,
        height_px: int,
        output_dpi: float,
    ) -> dict:
        """Build the ``render_frame_png`` spec from public getters.

        Rendering sources geometry through the data route: public Line2D
        data plus public linear increasing Axes limits feed one temporary
        affine request; the collected path only reconciles affine and clip
        behavior. Background color comes from the collected figure patch.
        Since the PRAC-A-D amendment, each decorated axes emits its
        solid major gridlines, major tick strokes, and visible spine edges
        as explicit path commands ahead of its content lines.
        Since PRAC-A-L a whitelisted legend contributes its frame and
        handle strokes as one bundle that rides the Legend artist's real
        public zorder inside the same per-axes sort (see the D1 contract
        below).

        LP-FUNC-035 compositing contract (D1): each axes reproduces Agg's
        ``Axes.draw`` ordering -- one stable sort of every eligible child
        by public ``get_zorder()`` (Python ``sorted`` keeps add order on
        ties, which is Agg's own stable-sort semantics). Gridline, tick,
        and spine decorations ride their artists' real zorders inside that
        single sort instead of the former decorations-first special case:
        at the default surface this preserves the legacy relative order
        (gridlines z2 and tick strokes z2.01 below content lines z2 are
        impossible under a strict per-value read, so the ratified model is
        the Axis-unit placement Agg actually draws: grid/tick strokes with
        their axis unit below default content, spines z2.5 above it),
        while inverted or negative zorders interleave exactly as Agg
        paints them. Tick, axis label, and center title glyphs stay appended
        after content: the text wire-up owns their emission position and
        Agg itself always paints labels last within the axes' decoration
        surface.
        """
        if self._three_d_axes:
            return self._build_3d_frame_spec(
                figure,
                width_px=width_px,
                height_px=height_px,
                output_dpi=output_dpi,
            )
        commands: list[dict] = []
        background_rgba = _RGBA_BLACK
        self._height_px = int(height_px)
        self._canvas_width_px = int(width_px)
        self._effective_dpi = float(output_dpi)
        self._label_payloads = list(self._observed_text_payloads)
        legend_commands_by_id: dict[int, list[dict]] = {}
        if not self.reasons:
            legend_commands_by_id = dict(self._legend_payloads)
        for ax_index, ax in enumerate(figure.get_axes()):
            xlim = ax.get_xlim()
            ylim = ax.get_ylim()
            # LP-FUNC-004 (W3): each axis projects through its own scale.
            # "linear" keeps the historical affine; base-10 "log" applies
            # the fractional log placement Agg's transData produces. Any
            # other scale records the explicit unsupported reason instead
            # of silently skipping the axes (the former skip emitted an
            # empty command surface for scaled frames -- a silent
            # degradation LP-MPL-020 forbids). Base selection reads only
            # public getters: matplotlib's own limit clamp (axis.py
            # ``_set_lim``) guarantees positive increasing limits on an
            # installed log axis, so log10 of both ends is well-defined;
            # non-base-10 log scales refuse explicitly rather than touch
            # private transform state.
            x_scale = str(ax.get_xscale())
            y_scale = str(ax.get_yscale())
            if x_scale not in ("linear", "log") or y_scale not in (
                "linear",
                "log",
            ):
                self.unsupported(
                    f"only linear and base-10 log scales are supported; "
                    f"xscale={x_scale!r}, yscale={y_scale!r} is unsupported "
                    "in strict mode",
                    type(ax).__name__,
                )
                continue
            if not (xlim[0] < xlim[1] and ylim[0] < ylim[1]):
                self.unsupported(
                    f"only increasing x/y limits are supported; "
                    f"xlim={xlim!r}, ylim={ylim!r} is unsupported "
                    "in strict mode",
                    type(ax).__name__,
                )
                continue
            bbox = ax.get_window_extent()
            x0, y0 = bbox.x0, bbox.y0
            w, h = bbox.width, bbox.height

            def _fraction(value: float, lo: float, hi: float,
                          scale: str) -> float:
                if scale == "log":
                    return (math.log10(max(value, 1e-300))
                            - math.log10(lo)) / (math.log10(hi)
                                                 - math.log10(lo))
                return (value - lo) / (hi - lo)

            def to_px_x(x: Any, _x0=x0, _w=w, _lim=xlim,
                        _s=x_scale) -> Any:
                return _x0 + _fraction(float(x), float(_lim[0]),
                                       float(_lim[1]), _s) * _w

            def to_px_y(y: Any, _y0=y0, _h=h, _lim=ylim,
                        _s=y_scale) -> Any:
                return _y0 + _fraction(float(y), float(_lim[0]),
                                       float(_lim[1]), _s) * _h

            if self._clip_points is None:
                self._clip_points = ((x0, y0), (x0 + w, y0 + h))
            # Content strokes of one axes reconcile against that axes'
            # own rectangle, keyed by draw-order position.
            if ax_index not in self._axes_clip_points:
                self._axes_clip_points[ax_index] = (
                    (x0, y0),
                    (x0 + w, y0 + h),
                )

            decorated = (
                ax_index < len(self._decorated_axes)
                and self._decorated_axes[ax_index]
            )
            # LP-FUNC-035 (D1): one stable z-order sort per axes over
            # every eligible child, exactly reproducing the ``sorted``
            # semantics of ``Axes.draw``. Matplotlib draws from one
            # add-ordered child list (public ``Axes.get_children``), so
            # equal-zorder ties keep pure add order across primitive
            # classes; the public children enumeration supplies that
            # rank. Decoration bundles ride the enumerated rank of
            # their representative artist (the x-axis unit, the bottom
            # spine).
            artist_rank: dict[int, int] = {
                id(child): rank
                for rank, child in enumerate(ax.get_children())
            }
            next_rank = len(artist_rank)
            entries: list[tuple[float, int, list[dict]]] = []
            seq = 0

            def _emit(zorder: float, rank: int,
                      cmds: list[dict]) -> None:
                nonlocal seq
                if cmds:
                    entries.append((float(zorder), rank, cmds))
                    seq += 1

            def _rank_of(artist: Any) -> int:
                nonlocal next_rank
                rank = artist_rank.get(id(artist))
                if rank is None:
                    # A live artist absent from the enumeration (should
                    # not happen) keeps a deterministic tail rank.
                    rank = next_rank
                    next_rank += 1
                return rank

            if decorated:
                # Decoration artists ride their real public zorders:
                # gridlines (default 2) and tick strokes (default 2.01)
                # sort with their Axis unit below default content lines,
                # spines (default 2.5) above it. Tick locations project
                # through the axis' own scale (LP-FUNC-004).
                _emit(
                    ax.xaxis.get_zorder(),
                    _rank_of(ax.xaxis),
                    self._decoration_commands(
                        ax, x0, y0, w, h, kinds=("gridline", "tick"),
                        to_px_x=to_px_x, to_px_y=to_px_y,
                    ),
                )
                _emit(
                    ax.spines["bottom"].get_zorder(),
                    _rank_of(ax.spines["bottom"]),
                    self._decoration_commands(
                        ax, x0, y0, w, h, kinds=("spine",),
                        to_px_x=to_px_x, to_px_y=to_px_y,
                    ),
                )
            for collection in ax.collections:
                if not isinstance(
                    collection,
                    matplotlib.collections.FillBetweenPolyCollection,
                ):
                    continue
                fill = self._fill_command(collection, to_px_x, to_px_y,
                                          ax_index)
                _emit(collection.get_zorder(),
                      _rank_of(collection),
                      [fill] if fill is not None else [])
            for patch in ax.patches:
                if not (
                    isinstance(patch, matplotlib.patches.Polygon)
                    or isinstance(patch, matplotlib.patches.Rectangle)
                ):
                    continue
                fill = self._fill_command(patch, to_px_x, to_px_y, ax_index)
                _emit(patch.get_zorder(), _rank_of(patch),
                      [fill] if fill is not None else [])
            for line in ax.get_lines():
                spec_command = self._line_command(line, to_px_x, to_px_y,
                                                  ax_index)
                _emit(line.get_zorder(), _rank_of(line),
                      [spec_command] if spec_command is not None else [])
            legend = ax.get_legend()
            legend_commands = legend_commands_by_id.pop(id(legend), None)
            if legend_commands:
                # PRAC-A-L: the Legend artist is a real whitelisted child
                # of the axes, so its frame and handles ride the same
                # stable public-zorder sort as every other axes child.
                _emit(
                    legend.get_zorder(),
                    _rank_of(legend),
                    legend_commands,
                )
            entries.sort(key=lambda entry: entry[:2])
            for _, _, entry_commands in entries:
                commands.extend(entry_commands)

        # Tick label glyphs paint above lines and decorations in Matplotlib
        # (text artists draw after the axes' line content), so the wire-up
        # appends them last: same relative order, no z-order regression.
        commands.extend(self._tick_label_commands())

        # A legend payload built for an axes skipped by the assembly
        # (non-linear or non-increasing limits) would silently vanish;
        # refusing keeps the render explicit about what it drops.
        if legend_commands_by_id:
            self.unsupported(
                "a legend could not be placed on its axes' supported "
                "projection",
                "Legend",
            )

        if self.background_rgbface is not None:
            background_rgba = _rgba8(self.background_rgbface)
        return {
            "width_px": int(width_px),
            "height_px": int(height_px),
            "output_dpi": float(output_dpi),
            "commands": commands,
            "background_rgba": list(background_rgba),
            # Architecture ruling 2026-08-25 (ADR 0012 additive amendment):
            # the adapter's quality oracle is matplotlib Agg, whose blend
            # arithmetic runs in encoded sRGB. The parity path opts in
            # explicitly; export and every default-mode consumer keep the
            # frozen linear-light compositing.
            "blend_mode": "agg_srgb",
        }

    def _fill_command(self, artist, to_px_x, to_px_y, axes_position: int):
        """Build one fill path command from a Polygon or poly-collection.

        LP-FUNC-032 style contract (Agg-identical resolution):

        - geometry: the artist's collected path (already split into
          polygon loops with CLOSEPOLY codes by matplotlib) mapped through
          the same public affine as lines;
        - face: ``fill_rgba`` = the resolved facecolor; the explicit
          artist alpha is applied exactly once (Agg bakes it into the
          resolved colors), never multiplied twice;
        - edge: an explicit nonzero-alpha edgecolor with positive width
          strokes the outline; the Polygon default resolves to fully
          transparent ('none'), which draws no stroke;
        - join/cap: the artist's resolved styles (Polygon defaults
          butt/miter, collections butt/round) — accepted values map onto
          seam selectors directly.
        """
        name = type(artist).__name__
        rectangle_geometry: list[tuple[float, float]] | None = None
        rectangle_geometry_in_px = False
        zero_area_rectangle = False
        if isinstance(artist, matplotlib.patches.Rectangle):
            # A Rectangle's stored path is the unit square scaled at draw
            # time, so the corners are re-derived from the public getters
            # (LP-FUNC-033): (x, y) anchor, signed width/height, and a
            # declared baseline. Negative heights (bars hanging below the
            # baseline) stay verbatim -- Agg fills the same loop.
            x0, y0 = (float(v) for v in artist.get_xy())
            width = float(artist.get_width())
            height = float(artist.get_height())
            if width == 0.0 or height == 0.0:
                # A zero-area Rectangle fills nothing, but Agg still
                # strokes its degenerate outline when an explicit edge
                # with positive width is set (pinned zero-area bar: a
                # 15px edge line with fringe caps).  Fall through so the
                # command below can carry that stroke; artists with no
                # stroke either are still skipped at assembly.
                zero_area_rectangle = True
            rectangle_geometry = [
                (x0, y0),
                (x0 + width, y0),
                (x0 + width, y0 + height),
                (x0, y0 + height),
                (x0, y0),
            ]
            span_axes = getattr(artist, "axes", None)
            span_data = getattr(span_axes, "transData", None)
            if (
                span_axes is not None
                and span_data is not None
                and artist.get_transform() is not span_data
            ):
                # Span-style rectangle (axvspan/axhspan, LP-FUNC-032): the
                # stored xy/width/height mix data units with axes-fraction
                # units under a blended transform, so the data-route
                # projection below would paint a sliver.  A Rectangle's
                # full transform maps its unit-square path (not the
                # stored data corners) to display, so resolve the unit
                # corners through the artist's own public transform into
                # display pixels (origin bottom-left, exactly the space
                # the data-route to_px_* helpers below produce; the seam
                # folds the display-to-device y-flip in itself).
                # Plain transData rectangles (bars) keep the historical
                # getter route untouched.
                try:
                    display = artist.get_transform().transform(
                        numpy.asarray(
                            [
                                [0.0, 0.0],
                                [1.0, 0.0],
                                [1.0, 1.0],
                                [0.0, 1.0],
                                [0.0, 0.0],
                            ],
                            dtype=float,
                        )
                    )
                except (TypeError, ValueError) as error:
                    self.unsupported(
                        f"span rectangle transform failed: {error}", name
                    )
                    return None
                rectangle_geometry = [
                    (float(x), float(y))
                    for x, y in (tuple(row) for row in display.tolist())
                ]
                rectangle_geometry_in_px = True
        if isinstance(artist, matplotlib.collections.Collection):
            paths = list(artist.get_paths())
            transform = artist.get_transform()
            facecolors = artist.get_facecolor()
            capstyle = str(artist.get_capstyle())
            joinstyle = str(artist.get_joinstyle())
            alpha = artist.get_alpha()
            offsets = artist.get_offsets()
            # FillBetweenPolyCollection carries one path per polygon run
            # and identity offsets; multi-offset collections are outside
            # this slice's contract.
            if offsets is not None and len(offsets) not in (0, 1):
                self.unsupported(
                    "multi-point collection offsets are unsupported", name
                )
                return None
            # An unset collection style resolves through the Agg graphics
            # context at draw time: cap defaults to butt and join to round
            # (GraphicsContextBase defaults, observed in the collector).
            if artist.get_capstyle() is None:
                capstyle = "butt"
            if artist.get_joinstyle() is None:
                joinstyle = "round"
            del transform
        elif rectangle_geometry is not None:
            # LP-FUNC-033: style getters mirror the Polygon route -- one
            # resolved face color, a scalar line width, explicit cap/join,
            # and the artist alpha; only the geometry source differs.
            paths = []
            facecolors = None
            capstyle = str(artist.get_capstyle())
            joinstyle = str(artist.get_joinstyle())
            alpha = artist.get_alpha()
        else:
            paths = [artist.get_path()]
            facecolors = None
            capstyle = str(artist.get_capstyle())
            joinstyle = str(artist.get_joinstyle())
            alpha = artist.get_alpha()

        # -- resolved colors -------------------------------------------------
        face_rgba_list = (
            list(facecolors)
            if facecolors is not None and len(facecolors)
            else [matplotlib.colors.to_rgba(
                artist.get_facecolor(), artist.get_alpha())]
        )
        if isinstance(artist, matplotlib.collections.Collection):
            # Collection facecolors arrive already resolved per member;
            # use the first as the representative for this command. The
            # explicit alpha is NOT re-applied: ``get_facecolor`` already
            # carries it (probe: FBPC alpha=0.5 facecolor alpha == 0.5).
            if alpha is None:
                face_color = tuple(float(c) for c in face_rgba_list[0])
            else:
                # Defensive: a collection whose stored facecolor predates
                # an alpha change still resolves single-application.
                raw = tuple(float(c) for c in face_rgba_list[0])
                face_color = raw[:3] + (float(alpha),)
        else:
            face_color = tuple(float(c) for c in matplotlib.colors.to_rgba(
                artist.get_facecolor()))
            if alpha is not None:
                # Agg applies the explicit alpha once when resolving the
                # Patch colors (probe: ``get_facecolor`` already carries
                # it); mirror that single application instead of
                # re-multiplying.
                face_color = face_color[:3] + (float(alpha),)
        fill_rgba = _rgba8(face_color)

        edge_color_raw = artist.get_edgecolor()
        edge_rgba = None
        try:
            edge_rows = list(edge_color_raw)
        except TypeError:
            edge_rows = []
        if not edge_rows:
            # ``edgecolor="none"`` on a collection resolves to an empty
            # edge array: no stroke, exactly like a fully transparent
            # patch edge (LP-FUNC-032 edge-none suppression).
            edge_tuple: tuple[float, ...] = ()
        elif isinstance(edge_rows[0], (float, int, numpy.floating)):
            edge_tuple = tuple(float(c) for c in edge_rows)
        else:
            edge_tuple = tuple(float(c) for c in edge_rows[0])
        explicit_edge = len(edge_tuple) == 4 and edge_tuple[3] != 0.0
        line_widths = artist.get_linewidth()
        if isinstance(line_widths, (list, tuple, numpy.ndarray)):
            width_array = numpy.atleast_1d(
                numpy.asarray(line_widths, dtype=float).ravel()
            )
            effective_width = (
                float(width_array[0]) if width_array.size else 0.0
            )
        else:
            effective_width = float(line_widths)
        if explicit_edge and effective_width > 0:
            edge_rgba = _rgba8(edge_tuple)

        if capstyle not in ("butt", "round", "projecting"):
            self.unsupported(
                f"fill cap style {capstyle!r} is unsupported", name
            )
            capstyle = "butt"
        if joinstyle not in ("miter", "round", "bevel"):
            self.unsupported(
                f"fill join style {joinstyle!r} is unsupported", name
            )
            joinstyle = "miter"

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

        vertices: list[list[float]] = []
        codes: list[int] = []
        emitted_loops = 0
        if rectangle_geometry is not None:
            if rectangle_geometry_in_px:
                # Span corners already sit in display pixels: no data
                # projection is applied.
                vertices = [
                    [float(x), float(y)] for x, y in rectangle_geometry
                ]
            else:
                vertices = [
                    [float(to_px_x(x)), float(to_px_y(y))]
                    for x, y in rectangle_geometry
                ]
            # One explicit closed loop: MOVETO, LINETO x3, CLOSEPOLY --
            # the same code shape Agg's draw_path shows for bars.
            codes = (
                [int(Path.MOVETO)]
                + [int(Path.LINETO)] * (len(vertices) - 2)
                + [int(Path.CLOSEPOLY)]
            )
            emitted_loops = 1
        for path in paths:
            loop_vertices = [
                [float(to_px_x(x)), float(to_px_y(y))]
                for x, y in path.vertices
                if _finite(x) and _finite(y)
            ]
            path_codes = (
                [int(code) for code in path.codes]
                if path.codes is not None
                else None
            )
            if path_codes is not None and len(path_codes) != len(loop_vertices):
                # Non-finite vertices were dropped; keep code alignment by
                # dropping the same positions.
                kept = [
                    (x, y)
                    for x, y in zip(path.vertices, path.codes)
                    if _finite(x) and _finite(y)
                ]
                path_codes = [int(code) for _, code in kept]
            if path_codes is None:
                # An unclosed vertex list: close it implicitly like the
                # seam's implicit-code path does.
                if len(loop_vertices) < 3:
                    continue
                vertices.extend(loop_vertices)
                codes.extend([int(Path.MOVETO)]
                             + [int(Path.LINETO)] * (len(loop_vertices) - 2)
                             + [int(Path.CLOSEPOLY)])
                emitted_loops += 1
                continue
            real_points = sum(1 for c in path_codes if c != int(Path.CLOSEPOLY))
            if real_points < 3:
                continue
            vertices.extend(loop_vertices)
            codes.extend(path_codes)
            emitted_loops += 1

        if emitted_loops == 0 or len(vertices) < 3:
            self.unsupported("degenerate fill path", name)
            return None

        if zero_area_rectangle and edge_rgba is None:
            # No fill coverage and no stroke: Agg paints nothing.
            return None

        command = {
            "kind": "path",
            "vertices": vertices,
            "codes": codes,
            "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            "stroke_rgba": list(edge_rgba) if edge_rgba is not None else None,
            "line_width_pt": float(effective_width),
            "cap": capstyle,
            "join": joinstyle,
            "dash_offset_pt": 0.0,
            "dashes": None,
            "fill_rule": "nonzero",
            "antialias": True,
            "clip_rect": clip_rect,
            # A zero-area Rectangle covers no fill pixels; emit the Agg
            # edge line as a stroke-only command.
            "fill_rgba": None if zero_area_rectangle else list(fill_rgba),
        }
        if rectangle_geometry is not None:
            # A Rectangle follows Agg's shared rectilinear snap path.  When
            # an edge is present, the native seam uses the snapped geometry
            # for both face and edge; fill-only commands remain unsnapped.
            command["rectilinear_snap"] = True
        return command
