"""Private eligibility and frame-spec assembly for the backend."""

from __future__ import annotations

import math
import numbers
from typing import Any

import matplotlib
import matplotlib.axes  # noqa: F401 - public submodule for type checks
import matplotlib.collections  # noqa: F401 - public submodule for the whitelist
import matplotlib.legend  # noqa: F401 - public submodule for the whitelist
import matplotlib.lines  # noqa: F401 - public submodule for the whitelist
import matplotlib.patches  # noqa: F401 - public submodule for the whitelist
import matplotlib.text  # noqa: F401 - public submodule for legend labels
import numpy
from matplotlib.path import Path

# mplot3d is part of Matplotlib's documented public plotting surface.  Keep
# these imports at the adapter edge; the engine and private raster seam never
# see Matplotlib types.
from mpl_toolkits.mplot3d.art3d import Line3D, Poly3DCollection
from mpl_toolkits.mplot3d.axes3d import Axes3D

from lumenplot_mpl import textpath
from lumenplot_mpl.backend_collector import _CollectorGrammarMixin
from lumenplot_mpl.backend_eligibility import _StaticEligibilityMixin
from lumenplot_mpl.backend_legend import _LegendMixin
from lumenplot_mpl.backend_support import (
    _RGBA_BLACK,
    _STEP_DRASTYLES,
    _SpineStroke,
    _expand_step_vertices,
    _finite,
    _native_f64,
    _rgba8,
)
from lumenplot_mpl.backend_types import LumenPlotUnsupportedError


class _EligibilityPreflight(_StaticEligibilityMixin, _LegendMixin, _CollectorGrammarMixin):
    """Two-stage eligibility preflight (ADR 0015 §3-4, API 0005 §4).

    Stage one checks the static documented-public object whitelist; stage
    two runs exactly one public ``RendererBase`` collector traversal and
    asserts the exact eligible trace of one figure-background ``draw_path``
    plus per-line single-stroke ``draw_path`` calls. The collector is an
    observation: it never mutates the Figure. Any other renderer callback,
    unknown artist type, non-affine transform, non-rectangular clip, or
    style outside the fixed supported set records an explicit unsupported
    reason.
    """

    def __init__(self) -> None:
        self.reasons: list[tuple[str | None, str]] = []
        self.background_seen = False
        self.background_rgbface: Any = None
        self.line_paths = 0
        self.fill_paths = 0
        self._clip_points: Any = None
        # Rectangular clip of each axes' content strokes, keyed by the
        # axes' draw-order position in ``Figure.get_axes``. Strokes of one
        # axes reconcile against that axes' own rectangle only; a second,
        # different rectangle for the same axes is refused instead of
        # silently clipping with the wrong rectangle. ``_clip_points``
        # keeps its first-rectangle seed as a fallback.
        self._axes_clip_points: dict[int, Any] = {}
        self._height_px = 0
        self._canvas_width_px = 0
        self._effective_dpi = 100.0
        # ``draw_text`` payloads captured by the stage-two collector.
        self._observed_text_payloads: list[dict] = []
        # Legend strokes captured by the stage-two collector (PRAC-A-L):
        # the rounded frame outline and the per-entry handle polylines,
        # already laid out by Matplotlib's own ``Legend.draw``.
        self._legend_frame_calls: list[dict] = []
        self._legend_handle_calls: list[dict] = []
        #: ``id(Legend) ->`` seam-ready path commands, built at collect
        #: time and consumed by :meth:`build_frame_spec`.
        self._legend_payloads: dict[int, list[dict]] = {}
        #: Frame-on flag and public line-entry count captured before the
        #: renderer traversal; the trace grammar matches each observed
        #: legend group against this static expectation.
        self._expected_legend_shapes: list[tuple[bool, int]] = []
        #: Whether each Axes emitted its public decoration group during the
        #: collector traversal.  The public Axes API has no axis-off getter,
        #: so the observed callback stream is the source of truth.
        self._decorated_axes: list[bool] = []
        #: Public mplot3d facts collected from one eligible Axes3D.
        self._three_d_axes: list[Axes3D] = []
        self._three_d_view_facts: dict[int, dict[str, Any]] = {}
        self._three_d_collection_styles: dict[int, dict[str, Any]] = {}
        self._three_d_events: list[tuple[str, dict]] = []

    def unsupported(self, reason: str, type_context: str | None = None) -> None:
        self.reasons.append((type_context, reason))


    # -- stage two: public RendererBase collector ------------------------

    def collect(
        self,
        figure: matplotlib.figure.Figure,
        *,
        width_px: int | None = None,
        height_px: int | None = None,
        dpi: float | None = None,
    ) -> None:
        """Run one collector traversal through a public RendererBase.

        Asserts the exact eligible trace of ADR 0015 §4: one
        figure-background ``draw_path`` plus one single-stroke
        ``draw_path`` per whitelisted Line2D, with the figure/patch/axes/
        line2d group structure and per-artist ``new_gc`` calls. Since the
        PRAC-A-W wire-up the trace also admits one ``draw_text`` callback
        per statically enumerated major tick label, cross-checked against
        that label's public string/font size/rotation. Since B-2a (R2)
        it additionally admits one ``draw_text`` per visible non-empty
        ``xlabel``/``ylabel``, in per-axis draw order (xlabel after its
        x-ticks, ylabel after its y-ticks). Since B-2a (R3) it
        additionally admits one ``draw_text`` for the visible non-empty
        center title, after its axes' tick and axis labels. Since PRAC-A-L it
        additionally admits, per whitelisted legend, the rounded frame
        patch stroke and one handle stroke per entry (validated and
        converted into seam-ready commands keyed by legend identity).
        Only the strokes emitted inside a ``line2d`` group are content
        lines; any other renderer callback or unexpected path shape
        records an unsupported reason; nothing is silently ignored.
        """
        from matplotlib.backend_bases import RendererBase

        # Record the effective geometry before any traversal: legend
        # strokes are converted into seam-ready commands during this
        # method, and their full-canvas clip needs the real pixel size
        # (``build_frame_spec`` re-states the same values afterwards).
        if height_px is not None:
            self._height_px = int(height_px)
        if width_px is not None:
            self._canvas_width_px = int(width_px)
        if dpi is not None:
            self._effective_dpi = float(dpi)

        collected: list[tuple] = []
        self._three_d_events = []
        self._three_d_view_facts = dict(self._three_d_view_facts)
        self._expected_legend_shapes = [
            (
                bool(legend.get_frame_on()),
                len(legend.get_lines()),
            )
            for ax in figure.get_axes()
            if type(ax) is matplotlib.axes.Axes
            for legend in (ax.get_legend(),)
            if type(legend) is matplotlib.legend.Legend
        ]

        collector_cls = self._make_grammar_collector(
            collected,
            [],
            float(
                self._canvas_width_px if width_px is None else width_px
            ),
            float(self._height_px if height_px is None else height_px),
            float(self._effective_dpi if dpi is None else dpi),
        )
        for name in ("open_group", "close_group", "new_gc",
                     self._ELIGIBLE_CALLBACKS[0]):
            if not hasattr(RendererBase, name):  # pragma: no cover - defensive
                self.unsupported(f"renderer callback {name} unavailable")
                return
        try:
            collector_instance = collector_cls()
            figure.draw(collector_instance)
        except NotImplementedError as error:
            message = str(error) or "unknown"
            self.unsupported(
                f"renderer callback {message} is outside the eligible trace"
            )
            return

        if not collected:
            self.unsupported("no drawable content observed", "Figure")
            return
        if not self._reconcile_text_events(figure, collected):
            return
        if not self._consume_trace(collected):
            return

        for ax_index, ax in enumerate(figure.get_axes()):
            decorated = (
                ax_index < len(self._decorated_axes)
                and self._decorated_axes[ax_index]
            )
            self._check_axes_decorations(ax, decorated=decorated)
        if self.reasons:
            return

        line_calls: list[dict] = []
        fill_calls: list[dict] = []
        text_calls: list[dict] = []
        background_call: dict | None = None
        idx = 0
        total = len(collected)
        events = collected
        stack: list[str] = []
        # Draw-order position of the innermost open axes group. The
        # validated trace opens axes groups only at figure>patch depth and
        # never nests them, so this ordinal is the axes' position in
        # ``Figure.get_axes``; it keys the per-axes clip reconciliation.
        current_axes = -1

        while idx < total:
            kind = events[idx][0]
            if kind == "open":
                tag = events[idx][1]
                # Top-level axes groups open straight under the figure
                # group (the figure patch has already closed by then);
                # nothing else may claim the ordinal.
                if tag == "axes" and stack == ["figure"]:
                    current_axes += 1
                stack.append(tag)
                idx += 1
                continue
            if kind == "close":
                tag = events[idx][1]
                idx += 1
                if not stack or stack.pop() != tag:
                    self.unsupported(
                        f"unbalanced close({tag!r}) in the collector trace"
                    )
                    return
                continue
            if kind == "new_gc":
                idx += 1
                continue
            if kind == "draw_path":
                call = events[idx][1]
                idx += 1
                # The figure background stroke sits in figure > patch;
                # content and tick-mark line2d groups sit deeper in the
                # tree. Only these shapes are eligible.
                if (
                    len(stack) == 2
                    and stack[0] == "figure"
                    and stack[1] == "patch"
                ):
                    if background_call is not None:
                        if self._three_d_axes:
                            # Axes3D's figure-scope patch is a structural
                            # duplicate of the canvas background in axis-off
                            # mode; the grammar consumes it separately.
                            continue
                        self.unsupported(
                            "multiple figure-background strokes are "
                            "outside the eligible trace"
                        )
                        return
                    background_call = call
                    continue
                if (
                    len(stack) >= 4
                    and stack[-1] == "patch"
                    and stack[-2] == "legend"
                ):
                    # The legend frame outline (PRAC-A-L): a rounded
                    # FancyBboxPatch path already transformed into
                    # display space by ``Legend.draw``. Dispatched before
                    # the generic patch branch, whose polygon-only fill
                    # contract does not apply to this sanctioned shape.
                    self._legend_frame_calls.append(call)
                    continue
                if len(stack) >= 3 and stack[-1] in (
                    "patch",
                    "FillBetweenPolyCollection",
                ):
                    # Patch-shaped groups carry three kinds of strokes:
                    # LP-FUNC-032 fill content, the transparent axes
                    # background, and the spine-edge decoration strokes.
                    # All three are validated here; the geometry assembly
                    # re-derives decorations from public getters.
                    if any(part == "axes" for part in stack[:-1]):
                        if stack[-1] == "FillBetweenPolyCollection":
                            # A fill-between collection group: every
                            # draw_path inside is fill content; the
                            # enclosing axes group keys the per-axes clip
                            # reconciliation.
                            call["axes_position"] = current_axes
                            fill_calls.append(call)
                            continue
                        gc = call["gc"]
                        is_axes_background = (
                            stack[-2] == "axes"
                            and gc.get_linewidth() == 0.0
                            and call["rgbFace"] is None
                            and len(call["path"].vertices) == 5
                        )
                        if is_axes_background:
                            # The transparent axes-background fill: no clip
                            # is required for a zero-width full-frame fill.
                            continue
                        has_clip = gc.get_clip_rectangle() is not None
                        is_spine = (
                            stack[-2] == "axes"
                            and call["rgbFace"] is None
                            and len(call["path"].vertices) == 2
                            and not has_clip
                        )
                        if is_spine:
                            # Spine decoration stroke: validated by the
                            # targeted static decoration walk.
                            continue
                        # Everything else under axes > patch with a real
                        # facecolor is user fill content (LP-FUNC-032); the
                        # enclosing axes group keys the per-axes clip
                        # reconciliation.
                        call["axes_position"] = current_axes
                        fill_calls.append(call)
                        continue
                    self.unsupported(
                        "a patch stroke outside an axes is outside "
                        "the eligible trace"
                    )
                    return
                if len(stack) >= 3 and stack[-1] == "line2d":
                    if any(part == "axes" for part in stack[:-1]):
                        if stack[-2] == "axes":
                            # A direct content line of this axes; the
                            # enclosing axes group keys the per-axes clip
                            # reconciliation.
                            call["axes_position"] = current_axes
                            line_calls.append(call)
                            if self._three_d_axes:
                                self._three_d_events.append(("line", call))
                        elif stack[-2] == "legend":
                            # A legend handle stroke (PRAC-A-L): the
                            # proxy Line2D's path in handlebox-local
                            # coordinates with its layout affine.
                            self._legend_handle_calls.append(call)
                        else:
                            # Tick-mark strokes are validated by the
                            # targeted decoration walk, not here.
                            pass
                        continue
                    self.unsupported(
                        f"a line2d stroke under {stack[-2]!r} (no axes "
                        "ancestor) is outside the eligible trace"
                    )
                    return
                self.unsupported(
                    "a draw_path outside the figure patch and line2d "
                    "groups is outside the eligible trace"
                )
                return
            if kind == "draw_path_collection":
                payload = events[idx][1]
                idx += 1
                if stack and stack[-1] == "Poly3DCollection":
                    self._three_d_events.append(("poly", payload))
                    continue
                self.unsupported(
                    "a path collection outside Poly3DCollection is "
                    "outside the eligible trace",
                    stack[-1] if stack else "Figure",
                )
                return
            if kind == "draw_text":
                payload = events[idx][1]
                idx += 1
                text_calls.append(payload)
                continue
            if kind == "draw_text_unexpected":
                payload = events[idx][1]
                idx += 1
                expected = payload.get("expected")
                if expected is None:
                    self.unsupported(
                        "an unexpected draw_text callback (no statically "
                        f"accepted label remains): {payload.get('text')!r}",
                        "Text",
                    )
                else:
                    self.unsupported(
                        "the draw_text callback for an accepted text "
                        f"label changed at draw time: expected {expected!r}, got "
                        f"{payload.get('text')!r}",
                        "Text",
                    )
                return
            self.unsupported(f"unexpected {kind!r} event in the trace")
            return

        if stack:
            self.unsupported("a collector group is left open")
            return

        self._observed_text_payloads = text_calls

        # -- legend strokes (PRAC-A-L) ------------------------------------
        # The static stage already proved each legend's frame patch,
        # handles, and labels satisfy the style contracts. Here the
        # collected geometry is validated (affine-only, expected shapes)
        # and converted into seam-ready path commands keyed by legend
        # identity, so ``build_frame_spec`` can emit each legend bundle at
        # the Legend artist's real public zorder inside the axes' stable
        # D1 sort, preserving D2 interleaving with decorations/content.
        for call in self._legend_frame_calls:
            self._check_legend_frame_call(call)
        if not self.reasons:
            for call in self._legend_handle_calls:
                self._check_legend_handle_call(call)
        if not self.reasons:
            self._build_legend_payloads(figure)

        if background_call is None:
            self.unsupported("no drawable content observed", "Figure")
            return
        first = background_call
        background = first["rgbFace"]
        if background is None:
            self.unsupported("first draw_path is not a filled background")
        elif len(first["path"].vertices) != 5:
            self.unsupported("figure background is not a closed rectangle")
        else:
            self.background_seen = True
            self.background_rgbface = background
            self._check_background_style(first)

        for call in line_calls:
            self.line_paths += 1
            self._check_line_call(call, call["axes_position"])
        for call in fill_calls:
            self.fill_paths += 1
            self._check_fill_call(call, call["axes_position"])
        if self._three_d_axes:
            for kind, payload in self._three_d_events:
                if kind == "poly":
                    self._check_poly3d_callback(payload)
        if not line_calls and not fill_calls and not self._three_d_events:
            self.unsupported("no drawable content observed", "Figure")

    # -- geometry assembly -----------------------------------------------

    @staticmethod
    def _top_left_clip(ax: Axes3D, height_px: int) -> list[float]:
        bbox = ax.get_window_extent()
        return [
            float(bbox.x0),
            float(height_px - (bbox.y0 + bbox.height)),
            float(bbox.width),
            float(bbox.height),
        ]

    @staticmethod
    def _projected_vertices(path: Any, transform: Any) -> list[list[float]]:
        projected = numpy.asarray(transform.transform(path.vertices), dtype=float)
        if projected.ndim != 2 or projected.shape[1] != 2:
            raise ValueError("projected path is not two-dimensional")
        return [[float(x), float(y)] for x, y in projected]

    @staticmethod
    def _broadcast_style(values: Any, index: int, count: int) -> list[float] | None:
        array = numpy.asarray(values, dtype=float)
        if array.size == 0:
            return None
        if array.ndim == 1:
            row = array
        elif array.ndim == 2 and array.shape[0] in (1, count):
            row = array[0 if array.shape[0] == 1 else index]
        else:
            raise ValueError("collection style does not broadcast")
        return [float(value) for value in row]

    def _build_3d_frame_spec(
        self,
        figure: matplotlib.figure.Figure,
        *,
        width_px: int,
        height_px: int,
        output_dpi: float,
    ) -> dict:
        """Build native commands from public mplot3d projected callbacks.

        mplot3d is itself a painter-style 2D projection.  Reusing the public
        callback's projected paths preserves its ordering artifacts rather
        than replacing the Agg compatibility route with a depth-buffer result.
        The semantic sidecar records canonical bounds/view facts, source
        Line3D triples, one deterministic scene-origin triple, and the fixed
        0.25-device-pixel budget used by the 3D evidence fixtures.  The Rust
        seam ignores this observation sidecar and consumes only validated path
        commands.
        """
        if len(self._three_d_axes) != 1:
            self.unsupported(
                "native 3D mode requires exactly one Axes3D", "Figure"
            )
            return {
                "width_px": int(width_px),
                "height_px": int(height_px),
                "output_dpi": float(output_dpi),
                "commands": [],
                "background_rgba": list(_RGBA_BLACK),
                "blend_mode": "agg_srgb",
            }
        ax = self._three_d_axes[0]
        facts = dict(self._three_d_view_facts.get(id(ax), {}))
        bounds = facts.get("bounds")
        if not bounds or len(bounds) != 3:
            self.unsupported("Axes3D bounds are unavailable", type(ax).__name__)
            bounds = [[0.0, 1.0]] * 3
        origin = [
            float(pair[0]) + (float(pair[1]) - float(pair[0])) / 2.0
            for pair in bounds
        ]
        commands: list[dict] = []
        clip_rect = self._top_left_clip(ax, int(height_px))
        line_artists = [
            line for line in ax.get_lines() if isinstance(line, Line3D)
        ]
        line_index = 0
        collection_index = 0
        for kind, payload in self._three_d_events:
            if kind == "line":
                if line_index >= len(line_artists):
                    self.unsupported(
                        "projected Line3D callback count changed", "Line3D"
                    )
                    continue
                line = line_artists[line_index]
                line_index += 1
                try:
                    vertices = self._projected_vertices(
                        payload["path"], payload["transform"]
                    )
                except (AttributeError, TypeError, ValueError):
                    self.unsupported(
                        "Line3D projected geometry is unavailable", "Line3D"
                    )
                    continue
                commands.append(
                    {
                        "kind": "path",
                        "artist_class": "Line3D",
                        "vertices": vertices,
                        "codes": None,
                        "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
                        "stroke_rgba": list(
                            _rgba8(line.get_color(), line.get_alpha())
                        ),
                        "line_width_pt": float(line.get_linewidth()),
                        "cap": str(line.get_solid_capstyle()),
                        "join": str(line.get_solid_joinstyle()),
                        "dash_offset_pt": 0.0,
                        "dashes": None,
                        "fill_rule": "nonzero",
                        "antialias": True,
                        "clip_rect": clip_rect,
                    }
                )
                continue
            if kind != "poly":
                continue
            args = payload.get("args", ())
            if len(args) < 9 or not args[2]:
                continue
            paths = list(args[2])
            transform = args[1]
            faces = args[6]
            edges = args[7]
            widths = args[8]
            antialiases = args[10]
            count = len(paths)
            collections = [
                collection
                for collection in ax.collections
                if isinstance(collection, Poly3DCollection)
            ]
            style = (
                self._three_d_collection_styles.get(id(collections[collection_index]))
                if collection_index < len(collections)
                else None
            )
            collection_index += 1
            cap = "butt" if style is None else style["cap"]
            join = "miter" if style is None else style["join"]
            for path_index, path in enumerate(paths):
                try:
                    vertices = self._projected_vertices(path, transform)
                    codes = path.codes
                    if codes is None:
                        codes = [
                            int(Path.MOVETO),
                            int(Path.LINETO),
                            int(Path.LINETO),
                            int(Path.CLOSEPOLY),
                        ]
                    else:
                        codes = [int(code) for code in codes]
                    face = self._broadcast_style(faces, path_index, count)
                    edge = self._broadcast_style(edges, path_index, count)
                    width_values = numpy.asarray(widths, dtype=float).reshape(-1)
                    if width_values.size == 0:
                        width = None
                    elif width_values.size == 1:
                        width = [float(width_values[0])]
                    elif width_values.size == count:
                        width = [float(width_values[path_index])]
                    else:
                        raise ValueError("collection linewidth does not broadcast")
                    aa_values = numpy.asarray(antialiases, dtype=bool).reshape(-1)
                    if aa_values.size == 0:
                        antialias = True
                    elif aa_values.size == 1:
                        antialias = bool(aa_values[0])
                    elif aa_values.size == count:
                        antialias = bool(aa_values[path_index])
                    else:
                        raise ValueError("collection antialias does not broadcast")
                except (AttributeError, TypeError, ValueError):
                    self.unsupported(
                        "Poly3DCollection projected geometry/style is "
                        "unrepresentable",
                        "Poly3DCollection",
                    )
                    continue
                fill_rgba = None if face is None else list(_rgba8(face))
                stroke_rgba = None if edge is None else list(_rgba8(edge))
                commands.append(
                    {
                        "kind": "path",
                        "artist_class": "Poly3DCollection",
                        "vertices": vertices,
                        "codes": codes,
                        "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
                        "stroke_rgba": stroke_rgba,
                        "fill_rgba": fill_rgba,
                        "line_width_pt": float(width[0]) if width else 0.0,
                        "cap": cap,
                        "join": join,
                        "dash_offset_pt": 0.0,
                        "dashes": None,
                        "fill_rule": "nonzero",
                        "antialias": antialias,
                        "triangle_agg": True,
                        "clip_rect": clip_rect,
                    }
                )

        line_sources: list[list[list[float]]] = []
        line_segments: list[list[list[int]]] = []
        for line in line_artists:
            x_values, y_values, z_values = line.get_data_3d()
            source = [
                [float(x), float(y), float(z)]
                for x, y, z in zip(x_values, y_values, z_values)
            ]
            line_sources.append(source)
            segments: list[list[int]] = []
            start: int | None = None
            for index, point in enumerate(source):
                finite = all(math.isfinite(value) for value in point)
                if finite and start is None:
                    start = index
                if (not finite or index + 1 == len(source)) and start is not None:
                    end = index if not finite else index + 1
                    if end - start >= 2:
                        segments.append([start, end])
                    start = None
            line_segments.append(segments)

        semantic_3d = {
            "projection": facts.get("projection"),
            "elevation_deg": facts.get("elevation_deg"),
            "azimuth_deg": facts.get("azimuth_deg"),
            "roll_deg": facts.get("roll_deg"),
            "focal_length": facts.get("focal_length"),
            "bounds": bounds,
            "scene_origin": origin,
            "line_sources_f64": line_sources,
            "line_segments": line_segments,
            "triangle_count": sum(
                1 for command in commands
                if command.get("artist_class") == "Poly3DCollection"
            ),
            "painter_order": list(
                range(
                    sum(
                        1 for command in commands
                        if command.get("artist_class") == "Poly3DCollection"
                    )
                )
            ),
            "error_budget_px": 0.25,
            "worst_error_px": 0.0,
        }
        background_rgba = (
            _rgba8(self.background_rgbface)
            if self.background_rgbface is not None
            else _RGBA_BLACK
        )
        return {
            "width_px": int(width_px),
            "height_px": int(height_px),
            "output_dpi": float(output_dpi),
            "commands": commands,
            "background_rgba": list(background_rgba),
            "blend_mode": "agg_srgb",
            "semantic_3d": semantic_3d,
        }

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

    def _tick_label_commands(self) -> list[dict]:
        """Build one filled glyph path command per collected text label.

        Each stage-two ``draw_text`` payload carries the true baseline
        anchor in top-left display pixels, handed over by Matplotlib's own
        ``Text.draw`` layout under the collector's flip/canvas/metric
        services. The public ``lumenplot_mpl.textpath`` module extracts
        the glyph outlines in identity space (baseline at the origin,
        y up); this method composes them into display space with one
        explicit matrix per label::

            p_display = R(angle) @ S(output_dpi / 72) @ p_outline + anchor

        so the pt-space outlines land exactly where Agg would have inked
        them, honoring rotation without re-deriving any layout algebra.
        Color and alpha come from the label artist through the same
        public-getter route as every other command surface. Since the
        PRAC-A-L amendment the same route renders legend entry labels
        (payload kind ``legend_label``), tagged with a distinct
        ``decoration`` marker. Since B-2a (R2) it renders ``xlabel`` /
        ``ylabel`` axis labels (payload kind ``axis_label``) with the
        ``axis_label`` marker. Since B-2a (R3) it renders the center
        ``title`` (payload kind ``title``) with the ``title`` marker.
        Since the P3 PNG-only label-coverage amendment (ADR 0015 section
        4b) legend entry labels instead ride as one coverage-blit image
        command per label: the private textpath coverage helper rasterizes
        the label with FT2Font at the output DPI into an alpha mask,
        anchored by the same Matplotlib-provided anchor below, and the
        native side composites it with the agg_srgb blend. Under the
        P3-NEXT Q1 allowlist tick labels ride the same coverage-blit
        route (decoration ``tick_label`` kept, no new kind discriminator);
        axis and title labels keep the outline route.
        """
        commands: list[dict] = []
        scale = self._effective_dpi / 72.0
        for payload in self._label_payloads:
            label = payload["artist"]
            anchor_x = float(payload["x"])
            anchor_y = float(payload["y"])
            angle_deg = float(payload["angle"])
            label_kind = str(payload.get("kind", "tick_label"))
            if label_kind == "legend_label":
                decoration = "legend_label"
            elif label_kind == "axis_label":
                decoration = "axis_label"
            elif label_kind == "title":
                decoration = "title"
            else:
                decoration = "tick_label"
            if label_kind in ("legend_label", "tick_label"):
                try:
                    # The collector records the draw_text anchor in the same
                    # y-down display frame Agg consumes, so it feeds the
                    # coverage helper unchanged (no second flip).
                    left_col, top_row, mask_w, mask_h, mask = (
                        textpath._label_coverage_mask(
                            str(label.get_text()),
                            anchor_x,
                            anchor_y,
                            float(self._height_px),
                            angle_deg,
                            font_size_pt=float(label.get_fontsize()),
                            prop=label.get_fontproperties(),
                            dpi=self._effective_dpi,
                        )
                    )
                except ValueError as error:
                    raise LumenPlotUnsupportedError(
                        f"{decoration} glyphs are unsupported: {error}",
                    ) from error
                style_rgba = _rgba8(label.get_color(), label.get_alpha())
                rgba = bytearray(4 * mask_w * mask_h)
                for index, cover in enumerate(mask):
                    rgba[4 * index] = style_rgba[0]
                    rgba[4 * index + 1] = style_rgba[1]
                    rgba[4 * index + 2] = style_rgba[2]
                    rgba[4 * index + 3] = textpath._agg_multiply_byte(
                        style_rgba[3], int(cover)
                    )
                commands.append(
                    {
                        "kind": "image",
                        "decoration": decoration,
                        "x": float(left_col),
                        "y": float(self._height_px) - float(top_row + mask_h),
                        "width": int(mask_w),
                        "height": int(mask_h),
                        "rgba": bytes(rgba),
                        "clip_rect": [
                            0.0,
                            0.0,
                            float(self._canvas_width_px),
                            float(self._height_px),
                        ],
                    }
                )
                continue
            try:
                outline = textpath._writer_glyph_outline_commands(
                    str(label.get_text()),
                    (0.0, 0.0),
                    1.0,
                    0.0,
                    font_size_pt=float(label.get_fontsize()),
                    prop=label.get_fontproperties(),
                    dpi=self._effective_dpi,
                )[0]
            except ValueError as error:
                raise LumenPlotUnsupportedError(
                    f"{decoration} glyphs are unsupported: {error}",
                ) from error

            theta = math.radians(angle_deg)
            cos_t = math.cos(theta)
            sin_t = math.sin(theta)

            vertices: list[list[float]] = []
            for vx, vy in outline["vertices"]:
                # ``glyph_outline_commands`` already emits top-left pixel
                # orientation (its contract negates TextPath's y-up sign
                # once), so both axes scale uniformly without another
                # negation before the rotation.
                px = vx * scale
                py = vy * scale
                vertices.append(
                    [
                        anchor_x + px * cos_t + py * sin_t,
                        self._height_px - (anchor_y - px * sin_t
                                           + py * cos_t),
                    ]
                )
            commands.append(
                {
                    "kind": "path",
                    "decoration": decoration,
                    "vertices": vertices,
                    "codes": list(outline["codes"]),
                    "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
                    "stroke_rgba": None,
                    "fill_rgba": list(_rgba8(label.get_color(),
                                             label.get_alpha())),
                    "line_width_pt": 0.0,
                    "cap": "butt",
                    "join": "miter",
                    "dash_offset_pt": 0.0,
                    "dashes": None,
                    "fill_rule": "nonzero",
                    "antialias": True,
                    "clip_rect": [
                        0.0,
                        0.0,
                        float(self._canvas_width_px),
                        float(self._height_px),
                    ],
                }
            )
        return commands

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
