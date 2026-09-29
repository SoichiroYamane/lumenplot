"""Private fill frame-spec slice for the Matplotlib backend adapter.

Leaf extraction of the adapter-owned fill frame-spec helper consumed by
:mod:`lumenplot_mpl.backend_frame`. Mixed into ``_FrameMixin`` alongside the
2D assembly; the 2D assembly (``build_frame_spec`` and helpers) and facade
wiring stay in ``backend_frame.py``.
"""

from __future__ import annotations

import matplotlib.collections
import matplotlib.colors
import matplotlib.patches
import numpy
from matplotlib.path import Path

from lumenplot_mpl.backend_support import (
    _finite,
    _rgba8,
)


class _FillMixin:
    """Fill frame-spec command moved verbatim from ``backend_frame.py``.

    Mixed into ``_FrameMixin`` (which stays in ``backend_frame.py`` so its
    ``__module__`` pin and ``backend_preflight`` import surface stay stable).
    Shared state (``__init__``) and the facade entries (``collect``,
    ``unsupported``) stay on the facade class; this mixin must not fork
    state and must not import from ``backend_frame`` or ``backend_preflight``.
    """

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
