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

from lumenplot_mpl import textpath
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


class _EligibilityPreflight:
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

    # Documented-public artist whitelist for this slice. Since the
    # LP-FUNC-032 eligibility extension (LP-MPL-020: whitelist entry,
    # collector-trace expectation, style contract, and fixtures landed in
    # one commit) the eligible content surface also carries filled areas:
    # ``Polygon`` (``Axes.fill``) and ``FillBetweenPolyCollection``
    # (``Axes.fill_between``). The LP-FUNC-033 bar lane adds axis-aligned
    # ``Rectangle`` artists (``Axes.bar`` / ``Axes.barh`` bars). The
    # PRAC-A-L legend lane adds ``matplotlib.legend.Legend`` itself; the
    # frame/handle/label surface *inside* the legend is checked by
    # :meth:`_check_legend_static`, not by this tuple.
    _ARTIST_WHITELIST = (
        matplotlib.lines.Line2D,
        matplotlib.patches.Polygon,
        matplotlib.patches.Rectangle,
        matplotlib.collections.FillBetweenPolyCollection,
        matplotlib.legend.Legend,
    )

    # RendererBase callbacks the collector may observe, in the exact order
    # and multiplicity the eligible trace allows (ADR 0015 §4).
    _ELIGIBLE_CALLBACKS = ("draw_path",)

    def __init__(self) -> None:
        self.reasons: list[tuple[str | None, str]] = []
        self.background_seen = False
        self.background_rgbface: Any = None
        self.line_paths = 0
        self.fill_paths = 0
        self._clip_points: Any = None
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
        #: collector traversal.  The public Axes API has no decoration-mode
        #: getter, so the observed callback stream is the source of truth.
        self._decorated_axes: list[bool] = []

    def unsupported(self, reason: str, type_context: str | None = None) -> None:
        self.reasons.append((type_context, reason))

    # -- stage one: static whitelist ------------------------------------

    def check_static(self, figure: matplotlib.figure.Figure) -> None:
        for ax in figure.get_axes():
            self._check_axes_structure(ax)
        for artist in self._iterate_content_artists(figure):
            if not isinstance(artist, self._ARTIST_WHITELIST):
                self.unsupported(
                    f"artist {type(artist).__name__} is outside the "
                    "supported whitelist",
                    type(artist).__name__,
                )
                continue
            # LP-FUNC-035 compositing gate: the emission stage reproduces
            # Agg's stable ``Axes.draw`` z-order sort, so every eligible
            # content artist must carry a real finite zorder up front. A
            # non-real or non-finite value has no Agg meaning (Matplotlib
            # would sort it with Python comparison semantics) and is
            # refused instead of silently mis-ordered. Negative zorder is
            # supported: it is exactly how content sinks below the
            # decoration surface.
            zorder = artist.get_zorder()
            if (
                isinstance(zorder, bool)
                or not isinstance(zorder, numbers.Real)
                or not math.isfinite(float(zorder))
            ):
                self.unsupported(
                    f"content zorder {zorder!r} is outside the supported "
                    "real-number surface",
                    type(artist).__name__,
                )
                continue
            # Static checks dispatch on the artist's class family: the
            # fixed §5 stroke surface applies to lines, the LP-FUNC-032
            # fill style contract applies to patches and poly-collections,
            # and the LP-FUNC-033 axis-aligned rectangle contract applies
            # to bars.
            if isinstance(artist, matplotlib.lines.Line2D):
                self._check_line2d_static(artist)
            elif isinstance(artist, matplotlib.patches.Rectangle):
                self._check_rectangle_static(artist)
            elif isinstance(artist, matplotlib.collections.Collection):
                self._check_fill_collection_static(artist)
            elif isinstance(artist, matplotlib.legend.Legend):
                self._check_legend_static(artist)
            else:
                self._check_patch_static(artist)

    def _check_axes_structure(self, ax: matplotlib.axes.Axes) -> None:
        """Check only structural Axes properties available before drawing.

        Matplotlib intentionally exposes no public getter for whether axis
        decorations are enabled.  Decoration-specific checks therefore run
        after the one required collector traversal, using the groups that
        the public draw protocol actually emitted.
        """
        name = type(ax).__name__
        if type(ax) is not matplotlib.axes.Axes:
            self.unsupported(
                f"{name} is outside the supported Axes whitelist", name
            )
            return
        if ax.get_subplotspec() is not None or ax.get_gridspec() is not None:
            self.unsupported(
                "subplots/grid-spec layouts are unsupported", "Figure"
            )

    def _check_axes_decorations(
        self, ax: matplotlib.axes.Axes, *, decorated: bool
    ) -> None:
        """Whitelist-check one axes and its decoration surface.

        Since the PRAC-A-D amendment of ADR 0015 §4 a standard decorated
        ``Axes`` is eligible: solid major gridlines, major tick strokes,
        and spine edges render as explicit path commands. Everything else
        about the decoration surface (visible minor tick content, non-solid
        grid styles, an opaque facecolor, titles, axis labels, offset
        text, or child axes) records an explicit unsupported reason.
        """
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
        for title in (
            ax.get_title("center"),
            ax.get_title("left"),
            ax.get_title("right"),
        ):
            if title != "":
                self.unsupported("titles are unsupported", "Text")
        if ax.get_xlabel() != "" or ax.get_ylabel() != "":
            self.unsupported("axis labels are unsupported", "Text")
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

        Spines are rendered as explicit path commands with the §5 stroke
        surface (Butt cap, Miter join), not approximated through the
        artist's own cap/join style; only their width, color, and
        visibility are honored from public getters.
        """
        name = type(spine).__name__
        if spine.get_linewidth() < 0:
            self.unsupported("negative line width", name)
        if spine.get_path_effects():
            self.unsupported("path effects are unsupported", name)

    def _check_tick_label_static(self, label: Any) -> None:
        """Whitelist-check one visible major tick label (PRAC-A-W).

        The label is rendered as explicit filled glyph path commands built
        by the public ``lumenplot_mpl.textpath`` module; only its string,
        font size, color, alpha, rotation, alignment, and position are
        honored. Anything outside the supported surface is refused here so
        stage two never observes an unexpected ``draw_text``.
        """
        name = type(label).__name__
        if label.get_text() != label.get_text().strip():
            # Leading/trailing whitespace changes Agg's layout box but not
            # the glyph outlines; refuse instead of shifting silently.
            self.unsupported(
                "tick labels with leading or trailing whitespace are "
                "unsupported",
                name,
            )
        if "\n" in label.get_text() or "\r" in label.get_text():
            self.unsupported(
                "multi-line tick labels are unsupported", name
            )
        if label.get_path_effects():
            self.unsupported("path effects are unsupported", name)
        # ``get_parse_math()`` merely enables ``$...$`` interpretation and
        # defaults to True on plain labels, so eligibility is gated on the
        # marker itself: TextPath draws dollars literally while Agg may
        # interpret them, which must never diverge silently.
        if label.get_usetex() or "$" in label.get_text():
            self.unsupported("math/TeX text is unsupported", name)

    def _check_legend_static(self, legend: Any) -> None:
        """Whitelist-check one Axes legend (PRAC-A-L, LP-MPL-020).

        The eligibility surface is deliberately narrow: the standard
        ``matplotlib.legend.Legend`` class attached to exactly one axes,
        one public-layout column, no title, and only line handles with visible
        non-empty labels. All decisions use documented Legend/Artist
        accessors; rendered geometry is checked during the collector stage.
        """
        name = type(legend).__name__
        if type(legend) is not matplotlib.legend.Legend:
            self.unsupported(
                "legend subclasses are unsupported; use the standard "
                "matplotlib.legend.Legend class",
                name,
            )
            return
        parent_axes = legend.axes
        if (
            parent_axes is None
            or type(parent_axes) is not matplotlib.axes.Axes
        ):
            self.unsupported(
                "legend is attached outside a standard Axes", name
            )
        figure = legend.get_figure()
        if any(leg is legend for leg in figure.legends):
            self.unsupported(
                "figure-level legends are unsupported", name
            )
        if legend.get_title().get_text() != "":
            self.unsupported("legend titles are unsupported", "Text")
        if bool(legend.get_frame_on()):
            frame = legend.get_frame()
            if type(frame) is not matplotlib.patches.FancyBboxPatch:
                self.unsupported(
                    "legend frames must use the standard FancyBboxPatch", name
                )
            else:
                self._check_legend_frame_static(frame)
        labels = list(legend.get_texts())
        handles = list(legend.get_lines())
        patches = [
            patch for patch in legend.get_patches()
            if patch is not legend.get_frame()
        ]
        if not labels:
            self.unsupported("legend carries no entries", name)
        if patches or len(handles) != len(labels):
            self.unsupported(
                "only line handles are supported in strict-mode legends",
                name,
            )
        if labels:
            # Legend has no public column-count getter. Its public layout
            # geometry is sufficient to prove the contract: after the
            # public window extent lays out the legend, all entry labels in
            # a single-column legend share one x origin. Multiple x origins
            # are a multi-column layout and refuse explicitly.
            try:
                from matplotlib.backends.backend_agg import RendererAgg

                width_px = max(
                    1, int(round(figure.get_figwidth() * figure.get_dpi()))
                )
                height_px = max(
                    1, int(round(figure.get_figheight() * figure.get_dpi()))
                )
                renderer = RendererAgg(width_px, height_px, figure.get_dpi())
                legend.draw(renderer)
                x_origins = {
                    round(float(handle.get_window_extent(renderer).x0), 7)
                    for handle in handles
                    if handle.get_visible()
                }
            except (AttributeError, TypeError, ValueError, RuntimeError) as error:
                self.unsupported(
                    f"legend column layout could not be validated: {error}",
                    name,
                )
            else:
                if len(x_origins) > 1:
                    self.unsupported(
                        "multi-column legends are unsupported; strict mode "
                        "supports single-column legends",
                        name,
                    )
        for handle, label in zip(handles, labels):
            if type(handle) is not matplotlib.lines.Line2D:
                self.unsupported(
                    "only plain Line2D handles are supported in strict-mode "
                    "legends",
                    type(handle).__name__,
                )
                continue
            if type(label) is not matplotlib.text.Text:
                self.unsupported(
                    "only plain Text labels are supported in strict-mode "
                    "legends",
                    type(label).__name__,
                )
                continue
            if not label.get_visible() or label.get_text() == "":
                self.unsupported(
                    "legend entries require visible, non-empty labels",
                    type(label).__name__,
                )
            # LP-FUNC-034 permits exact step expansion for axes content, but
            # ADR-0015 §4b deliberately fixes legend proxy handles to the
            # default drawstyle. Keep that narrower contract local to the
            # legend so stepped content remains eligible without silently
            # extending the legend surface.
            if handle.get_drawstyle() != "default":
                self.unsupported(
                    "legend handles require the default drawstyle",
                    type(handle).__name__,
                )
            # Re-check the proxy handle through the remaining fixed-style
            # surface as content lines: the legend must never relax the
            # stroke contract its owner already satisfied.
            self._check_line2d_static(handle)
            self._check_legend_label_static(label)

    def _check_legend_frame_static(
        self, frame: matplotlib.patches.FancyBboxPatch
    ) -> None:
        """Whitelist the exact rounded frame style for the native seam."""
        name = type(frame).__name__
        if type(frame.get_boxstyle()) is not matplotlib.patches.BoxStyle.Round:
            self.unsupported(
                "legend frames require the standard BoxStyle.Round", name
            )
        if not bool(frame.get_fill()):
            self.unsupported("legend frames must be filled", name)
        if frame.get_hatch() is not None:
            self.unsupported("legend frame hatching is unsupported", name)
        if frame.get_path_effects():
            self.unsupported("legend frame path effects are unsupported", name)
        if frame.get_sketch_params() is not None:
            self.unsupported(
                "legend frame sketch parameters are unsupported", name
            )
        width = float(frame.get_linewidth())
        if not math.isfinite(width) or width <= 0.0:
            self.unsupported(
                "legend frame line width must be finite and positive", name
            )
        alpha = frame.get_alpha()
        if alpha is not None and (
            not _finite(alpha) or not 0.0 <= float(alpha) <= 1.0
        ):
            self.unsupported("legend frame alpha must be finite", name)
        if frame.get_snap() is not True:
            self.unsupported(
                "legend frame snap must remain at the default True", name
            )
        if frame.get_clip_box() is not None or frame.get_clip_path() is not None:
            self.unsupported("legend frame custom clipping is unsupported", name)
        if frame.get_url() is not None:
            self.unsupported("legend frame hyperlinks are unsupported", name)
        if str(frame.get_capstyle()) != "butt":
            self.unsupported("legend frame cap style must be 'butt'", name)
        if str(frame.get_joinstyle()) != "miter":
            self.unsupported("legend frame join style must be 'miter'", name)
        if not bool(frame.get_antialiased()):
            self.unsupported("legend frame antialiasing is required", name)

    def _check_legend_label_static(self, label: Any) -> None:
        """Whitelist-check one legend entry label (PRAC-A-L).

        Legend labels render as filled glyph path commands through the
        public ``lumenplot_mpl.textpath`` module exactly like tick
        labels; they satisfy the same static text contract.
        """
        self._check_tick_label_static(label)
        name = type(label).__name__
        size = float(label.get_fontsize())
        if not math.isfinite(size) or size <= 0.0:
            self.unsupported("non-positive font size", name)
        if label.get_sketch_params() is not None:
            self.unsupported("sketch parameters are unsupported", name)
        if label.get_snap() is not None:
            self.unsupported("explicit snap is unsupported", name)
        if label.get_clip_box() is not None or label.get_clip_path() is not None:
            self.unsupported("custom clipping is unsupported", name)
        if label.get_url() is not None:
            self.unsupported("hyperlinks are unsupported", name)

    def _iterate_content_artists(self, figure: matplotlib.figure.Figure):
        """Yield drawable content artists, not structural containers.

        The Figure/Axes objects, their patch, spines, axis containers, and
        tick wrappers are structural: when the caller disables decorations
        through Matplotlib's public API they draw nothing, and the stage-two
        collector trace rejects them if they ever emit a callback.
        """
        yield from figure.images
        yield from figure.lines
        yield from figure.patches
        yield from figure.texts
        yield from figure.artists
        yield from figure.legends
        for ax in figure.get_axes():
            yield from ax.lines
            yield from ax.collections
            yield from ax.images
            yield from ax.patches
            yield from ax.tables
            yield from ax.texts
            yield from ax.artists
            if ax.get_legend() is not None:
                yield ax.get_legend()

    def _check_line2d_static(self, line: matplotlib.lines.Line2D) -> None:
        name = type(line).__name__
        if line.get_marker() != "None":
            self.unsupported("markers are unsupported in strict mode", name)
        # LP-FUNC-034: the step drawstyles are exact vertex-generation
        # semantics, not approximations -- the line path is expanded to
        # Matplotlib's own step polyline before projection, so eligibility
        # extends only to this family. Every other non-default drawstyle
        # (and any future value) is still refused explicitly.
        if (
            line.get_drawstyle() != "default"
            and line.get_drawstyle() not in _STEP_DRASTYLES
        ):
            self.unsupported("non-default drawstyle is unsupported", name)
        if line.is_dashed():
            self.unsupported("dashed strokes are unsupported in strict mode", name)
        width = float(line.get_linewidth())
        if not math.isfinite(width) or width < 0.0:
            self.unsupported("line width must be finite and non-negative", name)
        if line.get_path_effects():
            self.unsupported("path effects are unsupported", name)
        if line.get_sketch_params() is not None:
            self.unsupported("sketch parameters are unsupported", name)
        if line.get_snap() is not None:
            self.unsupported("explicit snap is unsupported", name)
        if line.get_clip_path() is not None:
            self.unsupported("custom clipping is unsupported", name)
        if line.get_url() is not None:
            self.unsupported("hyperlinks are unsupported", name)
        # ADR-0015 §5: the native request supports exactly Butt cap and
        # Miter join. Effective styles outside that set are rejected, not
        # approximated; Matplotlib's defaults (projecting/round) must be
        # overridden explicitly by strict-mode callers.
        cap = str(line.get_solid_capstyle())
        join = str(line.get_solid_joinstyle())
        if cap != "butt":
            self.unsupported(
                f"solid cap style {cap!r} is unsupported; "
                "strict mode requires 'butt'",
                name,
            )
        if join != "miter":
            self.unsupported(
                f"solid join style {join!r} is unsupported; "
                "strict mode requires 'miter'",
                name,
            )
        if line.get_gid() is None:
            return

    def _check_patch_static(self, patch: matplotlib.patches.Patch) -> None:
        """Static style checks for one whitelisted ``Patch`` (LP-FUNC-032).

        The fill style contract mirrors Agg's own resolution: the artist's
        resolved face/edge colors and alpha are authoritative, hatching
        and path effects are outside the slice, and a negative width is
        refused rather than clamped.
        """
        name = type(patch).__name__
        if patch.get_hatch() is not None:
            self.unsupported("hatching is unsupported in strict mode", name)
        if patch.get_path_effects():
            self.unsupported("path effects are unsupported", name)
        if patch.get_sketch_params() is not None:
            self.unsupported("sketch parameters are unsupported", name)
        if float(patch.get_linewidth()) < 0:
            self.unsupported("negative line width", name)
        if not bool(getattr(patch, "get_fill", bool)()):
            self.unsupported(
                "unfilled patches are unsupported; use a line instead",
                name,
            )
        if str(patch.get_joinstyle()) not in ("miter", "round", "bevel"):
            # Defensive: every Matplotlib joinstyle maps to a seam selector;
            # an unknown value means the collector contract drifted.
            self.unsupported(
                f"joinstyle {patch.get_joinstyle()!r} is unsupported", name
            )

    def _check_rectangle_static(
        self, patch: matplotlib.patches.Rectangle
    ) -> None:
        """Static style checks for one bar ``Rectangle`` (LP-FUNC-033).

        Bars are axis-aligned filled rectangles anchored to a declared
        baseline: the LP-FUNC-032 patch surface applies, plus an explicit
        refusal of rotated rectangles (``angle != 0``) — a tilted bar is
        outside the declared-baseline contract and must never be silently
        rendered as its axis-aligned bounding box.
        """
        self._check_patch_static(patch)
        name = type(patch).__name__
        if float(patch.get_angle()) != 0.0:
            self.unsupported(
                f"rotated rectangles (angle {float(patch.get_angle())!r}) "
                "are unsupported; bars must be axis-aligned",
                name,
            )

    def _check_fill_collection_static(
        self, collection: matplotlib.collections.Collection
    ) -> None:
        """Static style checks for one whitelisted poly-collection.

        Only the LP-FUNC-032 ``FillBetweenPolyCollection`` is eligible;
        any other collection class reaching here is an internal fault of
        the whitelist dispatch and records an explicit reason.
        """
        name = type(collection).__name__
        if not isinstance(
            collection, matplotlib.collections.FillBetweenPolyCollection
        ):
            self.unsupported(
                f"collection {name} is outside the supported whitelist",
                name,
            )
            return
        if collection.get_hatch() is not None:
            self.unsupported("hatching is unsupported in strict mode", name)
        if collection.get_path_effects():
            self.unsupported("path effects are unsupported", name)
        if collection.get_sketch_params() is not None:
            self.unsupported("sketch parameters are unsupported", name)
        widths = collection.get_linewidth()
        import numpy as _np

        width_list = _np.atleast_1d(
            _np.asarray(widths, dtype=float).ravel()
        )
        for width in width_list:
            if float(width) < 0:
                self.unsupported("negative line width", name)
                return

    # -- stage two: public RendererBase collector ------------------------

    def _make_grammar_collector(
        self,
        collected: list[tuple],
        expected_labels: list[dict],
        canvas_width_px: float,
        canvas_height_px: float,
        output_dpi: float,
    ) -> Any:
        """Return a public ``RendererBase`` collector class.

        The collector records the full callback event stream of ADR 0015
        §4 — group open/close pairs, per-artist ``new_gc`` calls and
        ``draw_path`` strokes. Text callbacks are recorded as raw public
        observations and reconciled with the Figure after the traversal;
        this avoids inferring the undocumented Axes decoration-mode state
        before the one required collector pass. Any other renderer callback
        raises instead of silently succeeding through the base-class no-op.

        ``Text.draw`` consults three renderer services while laying out
        each label: the canvas size, the display flip, and text metrics.
        The flip and canvas size reproduce the top-left display space the
        adapter renders in, so Matplotlib itself hands over the true
        baseline-start anchors. Metrics delegate to a real public
        ``RendererAgg`` so alignment arithmetic sees Agg's exact numbers;
        nothing is approximated here.
        """
        from matplotlib.backend_bases import GraphicsContextBase
        from matplotlib.backend_bases import RendererBase

        class _GrammarCollector(RendererBase):
            def __init__(self) -> None:
                super().__init__()
                self._metrics_renderer: Any = None

            def _record(self, kind: str, *rest: Any) -> None:
                collected.append((kind, *rest))

            # -- eligible events ----------------------------------------
            def open_group(self, s, gid=None):  # noqa: N802
                self._record("open", s)

            def close_group(self, s):  # noqa: N802
                self._record("close", s)

            def new_gc(self):  # noqa: N802
                self._record("new_gc")
                return GraphicsContextBase()

            def draw_path(self, gc, path, transform, rgbFace=None):  # noqa: N802
                self._record(
                    "draw_path",
                    {
                        "gc": gc,
                        "path": path,
                        "transform": transform,
                        "rgbFace": rgbFace,
                        "affine": bool(transform.is_affine),
                    },
                )

            def draw_text(  # noqa: N802
                self,
                gc,
                x,
                y,
                s,
                prop,
                angle,
                ismath=False,
                mtext=None,
            ):
                del gc, mtext
                self._record(
                    "draw_text_raw",
                    {
                        "text": str(s),
                        "x": float(x),
                        "y": float(y),
                        "angle": float(angle),
                        "prop": prop,
                        "ismath": bool(ismath),
                    },
                )

            # -- layout services consumed by ``Text.draw`` ---------------
            def get_canvas_width_height(self):  # noqa: N802
                return (float(canvas_width_px), float(canvas_height_px))

            def flipy(self):  # noqa: N802
                return True

            def get_text_width_height_descent(  # noqa: N802
                self, s, prop, ismath
            ):
                if self._metrics_renderer is None:
                    from matplotlib.backends.backend_agg import RendererAgg

                    self._metrics_renderer = RendererAgg(
                        max(1, int(canvas_width_px)),
                        max(1, int(canvas_height_px)),
                        float(output_dpi),
                    )
                return self._metrics_renderer.get_text_width_height_descent(
                    s, prop, ismath
                )

            # -- everything else is outside the trace --------------------
            def __getattr__(self, name):
                if name.startswith("draw_"):
                    raise NotImplementedError(name)
                raise AttributeError(name)

        return _GrammarCollector

    def _enumerate_expected_labels(
        self,
        figure: matplotlib.figure.Figure,
    ) -> list[dict]:
        """Enumerate accepted tick and legend labels in draw order.

        Matplotlib draws each decorated axes' major ticks through public
        ``Axis.get_major_ticks``/``get_ticklocs`` in the same order the
        collector observes their ``draw_text`` callbacks (x-axis first,
        then y-axis; ``label1`` before ``label2`` per tick). Only visible
        non-empty labels whose tick location lies inside
        ``Axis.get_view_interval()`` enter the queue: ``Tick.draw`` skips
        out-of-view ticks entirely, so an unfiltered enumeration would
        accept labels the renderer never draws. A whitelisted legend then
        contributes its entry labels after its axes' tick labels.
        """
        entries: list[dict] = []
        decorated_axes = self._decorated_axes or None
        for ax_index, ax in enumerate(figure.get_axes()):
            if type(ax) is not matplotlib.axes.Axes:
                continue
            decorated = (
                decorated_axes is None
                or ax_index >= len(decorated_axes)
                or decorated_axes[ax_index]
            )
            if decorated:
                for axis in (ax.xaxis, ax.yaxis):
                    # Public formatter access materializes the labels that
                    # ``Tick.draw`` will subsequently emit.  This mirrors
                    # the former static pass without reading a private Axes
                    # decoration flag.
                    axis.get_majorticklabels()
                    view_lo, view_hi = (
                        float(axis.get_view_interval()[0]),
                        float(axis.get_view_interval()[1]),
                    )
                    locations = [float(loc) for loc in axis.get_ticklocs()]
                    for index, tick in enumerate(axis.get_major_ticks()):
                        if index >= len(locations):
                            break
                        location = locations[index]
                        if not (view_lo <= location <= view_hi):
                            continue
                        for label in (tick.label1, tick.label2):
                            text = label.get_text()
                            if not label.get_visible() or text == "":
                                continue
                            entries.append(
                                {
                                    "artist": label,
                                    "text": str(text),
                                    "size": float(label.get_fontsize()),
                                    "angle": float(label.get_rotation()),
                                }
                            )
            legend = ax.get_legend()
            if type(legend) is matplotlib.legend.Legend:
                for label in legend.get_texts():
                    text = label.get_text()
                    if not label.get_visible() or text == "":
                        continue
                    entries.append(
                        {
                            "kind": "legend_label",
                            "artist": label,
                            "text": str(text),
                            "size": float(label.get_fontsize()),
                            "angle": float(label.get_rotation()),
                        }
                    )
        return entries

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
                and tag == "matplotlib.axis"
            ):
                flags[axes_index] = True
        return flags

    def _reconcile_text_events(
        self,
        figure: matplotlib.figure.Figure,
        events: list[tuple],
    ) -> bool:
        """Match raw public text callbacks to observed Figure labels.

        Text callbacks are deliberately reconciled after drawing.  This
        preserves one collector pass while allowing an undecorated Axes to
        omit labels without consulting a private mode flag.
        """
        self._decorated_axes = self._decoration_flags(
            events, len(figure.get_axes())
        )
        expected = self._enumerate_expected_labels(figure)
        actual = [
            (index, event[1])
            for index, event in enumerate(events)
            if event[0] == "draw_text_raw"
        ]
        if len(actual) < len(expected):
            self.unsupported(
                "a statically accepted text label was not drawn",
                "Text",
            )
            return False
        if len(actual) > len(expected):
            self.unsupported(
                "an unexpected draw_text callback was emitted for a public "
                "label observation",
                "Text",
            )
            return False
        for (index, payload), entry in zip(actual, expected):
            try:
                size_ok = (
                    abs(float(payload["prop"].get_size()) - entry["size"])
                    <= 1.0e-9
                )
                angle_ok = (
                    abs(float(payload["angle"]) - entry["angle"]) <= 1.0e-9
                )
            except (AttributeError, TypeError, ValueError):
                size_ok = angle_ok = False
            if payload.get("ismath") or "$" in entry["text"]:
                self.unsupported("math/TeX text is unsupported", "Text")
                return False
            if (
                payload.get("text") != entry["text"]
                or not size_ok
                or not angle_ok
            ):
                self.unsupported(
                    "the draw_text callback for a public label changed "
                    f"at draw time: expected {entry['text']!r}, got "
                    f"{payload.get('text')!r}",
                    "Text",
                )
                return False
            events[index] = (
                "draw_text",
                {
                    "kind": entry.get("kind", "tick_label"),
                    "artist": entry["artist"],
                    "x": float(payload["x"]),
                    "y": float(payload["y"]),
                    "angle": float(payload["angle"]),
                },
            )
        return True

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
        that label's public string/font size/rotation. Since PRAC-A-L it
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

        while idx < total:
            kind = events[idx][0]
            if kind == "open":
                stack.append(events[idx][1])
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
                            # draw_path inside is fill content.
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
                        # facecolor is user fill content (LP-FUNC-032).
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
                            # A direct content line of this axes.
                            line_calls.append(call)
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
            self._check_line_call(call)
        for call in fill_calls:
            self.fill_paths += 1
            self._check_fill_call(call)
        if not line_calls and not fill_calls:
            self.unsupported("no drawable content observed", "Figure")

    def _consume_trace(self, events: list[tuple]) -> bool:
        """Validate the exact grouped callback grammar for this slice.

        Every leaf artist group has one ``new_gc`` immediately followed by
        its callback. ``FillBetweenPolyCollection`` is the one exception:
        one graphics context may service several polygon paths. Axis groups
        contain only ``xtick``/``ytick`` groups, and a legend contains an
        optional frame patch followed by line/text entry pairs. The axes
        body remains order-free under LP-FUNC-035 D2, but unknown groups,
        bare callbacks, missing graphics contexts, and unbalanced nesting
        are refused instead of being silently accepted.
        """
        index = 0
        total = len(events)

        def fail(reason: str) -> bool:
            self.unsupported(reason, "Figure")
            return False

        def is_open(tag: str) -> bool:
            return (
                index < total
                and events[index][0] == "open"
                and events[index][1] == tag
            )

        def consume_leaf(
            tag: str, callback: str, alternatives: tuple[str, ...] = ()
        ) -> dict | None:
            """Consume ``open(tag), new_gc, callback, close(tag)``."""
            nonlocal index
            if not is_open(tag):
                fail(f"expected open({tag!r}) group")
                return None
            index += 1
            if index >= total or events[index][0] != "new_gc":
                fail(
                    f"{tag} group is missing its graphics context before "
                    f"{callback}"
                )
                return None
            index += 1
            accepted_callbacks = (callback, *alternatives)
            if index >= total or events[index][0] not in accepted_callbacks:
                actual = events[index][0] if index < total else "end-of-trace"
                fail(
                    f"{tag} group expected one of {accepted_callbacks}, "
                    f"observed {actual}"
                )
                return None
            payload = events[index][1]
            index += 1
            if index >= total or events[index] != ("close", tag):
                fail(f"{tag} group is not balanced after {callback}")
                return None
            index += 1
            return payload

        def consume_fill() -> bool:
            """Consume a collection group with shared graphics contexts."""
            nonlocal index
            tag = "FillBetweenPolyCollection"
            if not is_open(tag):
                fail(f"expected open({tag!r}) group")
                return False
            index += 1
            gc_count = 0
            while index < total and events[index][0] == "new_gc":
                gc_count += 1
                index += 1
            if gc_count == 0:
                fail(f"{tag} group is missing its graphics context")
                return False
            paths = 0
            while index < total and events[index][0] == "draw_path":
                paths += 1
                index += 1
            if paths == 0:
                fail(f"{tag} group carries no draw_path callback")
                return False
            if index >= total or events[index] != ("close", tag):
                fail(f"{tag} group is not balanced after its paths")
                return False
            index += 1
            return True

        def consume_axis_tick(tag: str) -> bool:
            nonlocal index
            if not is_open(tag):
                fail(f"expected open({tag!r}) group")
                return False
            index += 1
            while index < total and events[index][0] == "open":
                child = events[index][1]
                if child == "line2d":
                    if consume_leaf(child, "draw_path") is None:
                        return False
                elif child == "text":
                    if consume_leaf(
                        "text", "draw_text", ("draw_text_unexpected",)
                    ) is None:
                        return False
                else:
                    fail(
                        f"unexpected {child!r} group inside {tag!r}"
                    )
                    return False
            if index >= total or events[index] != ("close", tag):
                fail(f"{tag} group is not balanced")
                return False
            index += 1
            return True

        def consume_axis() -> bool:
            nonlocal index
            tag = "matplotlib.axis"
            if not is_open(tag):
                fail(f"expected open({tag!r}) group")
                return False
            index += 1
            while index < total and events[index][0] == "open":
                child = events[index][1]
                if child not in ("xtick", "ytick"):
                    fail(
                        f"unexpected {child!r} group inside {tag!r}"
                    )
                    return False
                if not consume_axis_tick(child):
                    return False
            if index >= total or events[index] != ("close", tag):
                fail(f"{tag} group is not balanced")
                return False
            index += 1
            return True

        expected_shapes = list(self._expected_legend_shapes)
        expected_legend_count = len(expected_shapes)

        def consume_legend() -> bool:
            nonlocal index
            tag = "legend"
            if not is_open(tag):
                fail(f"expected open({tag!r}) group")
                return False
            index += 1
            frame_count = 0
            if is_open("patch"):
                if consume_leaf("patch", "draw_path") is None:
                    return False
                frame_count = 1
            if is_open("patch"):
                fail(
                    "legend emitted an extra frame patch; shadows and "
                    "repeated frames are unsupported"
                )
                return False
            entries = 0
            while is_open("line2d"):
                if consume_leaf("line2d", "draw_path") is None:
                    return False
                if not is_open("text"):
                    fail(
                        "legend handle is not followed by a text label; "
                        "label was not drawn"
                    )
                    return False
                if consume_leaf(
                    "text", "draw_text", ("draw_text_unexpected",)
                ) is None:
                    return False
                entries += 1
            if entries == 0:
                fail("legend group carries no line/text entries")
                return False
            shape = (frame_count == 1, entries)
            if expected_legend_count == 0:
                fail("collector emitted an unexpected legend group")
                return False
            if shape not in expected_shapes:
                fail(
                    "legend group frame/entry shape does not match the "
                    "statically enumerated legend"
                )
                return False
            expected_shapes.remove(shape)
            if index >= total or events[index] != ("close", tag):
                fail("legend group is not balanced")
                return False
            index += 1
            return True

        def consume_axes() -> bool:
            nonlocal index
            tag = "axes"
            if not is_open(tag):
                fail(f"expected open({tag!r}) group")
                return False
            index += 1
            while index < total and events[index][0] == "open":
                child = events[index][1]
                if child in ("line2d", "patch"):
                    if consume_leaf(child, "draw_path") is None:
                        return False
                elif child == "FillBetweenPolyCollection":
                    if not consume_fill():
                        return False
                elif child == "matplotlib.axis":
                    if not consume_axis():
                        return False
                elif child == "legend":
                    if not consume_legend():
                        return False
                else:
                    fail(f"unexpected {child!r} group inside axes")
                    return False
            if index >= total or events[index] != ("close", tag):
                fail("axes group is not balanced")
                return False
            index += 1
            return True

        if not is_open("figure"):
            return fail("collector trace does not start with open('figure')")
        index += 1
        background = consume_leaf("patch", "draw_path")
        if background is None:
            return False
        if background.get("rgbFace") is None:
            return fail("figure background stroke is missing its facecolor")
        while is_open("axes"):
            if not consume_axes():
                return False
        if index >= total or events[index] != ("close", "figure"):
            return fail("figure group is not balanced")
        index += 1
        if index != total:
            kind = events[index][0]
            return fail(
                f"unexpected {kind!r} event outside the eligible trace"
            )
        if expected_shapes:
            return fail(
                "one or more statically enumerated legends were absent "
                "from the collector trace"
            )
        return True

    def _check_background_style(self, call: dict) -> None:
        gc = call["gc"]
        if bool(gc.get_antialiased()):
            self.unsupported("antialiased figure background is unsupported")
        if gc.get_linewidth() != 0.0:
            self.unsupported("stroked figure background is unsupported")

    def _check_line_call(self, call: dict) -> None:
        path = call["path"]
        codes = path.codes
        if codes is not None and len(codes):
            code_values = {int(code) for code in codes}
            allowed = {
                int(Path.MOVETO),
                int(Path.LINETO),
                int(Path.CLOSEPOLY),
                0,
            }
            if not code_values <= allowed:
                self.unsupported("curved path segments are unsupported")
        vertices = path.vertices
        if len(vertices) < 2:
            self.unsupported("degenerate single-vertex stroke")
        self._check_stroke_common(call["gc"])

    def _check_fill_call(self, call: dict) -> None:
        """Collector-side checks for one fill draw_path (LP-FUNC-032).

        Fills must stay polygonal (MOVETO/LINETO/CLOSEPOLY only), carry
        a facecolor, and share the rectangular axes clip with every
        other eligible stroke. The shared ``_check_stroke_common`` runs
        the dash/sketch/snap/clip surface; the clip bookkeeping also
        seeds the fill command's ``clip_rect``.
        """
        path = call["path"]
        codes = path.codes
        if codes is not None and len(codes):
            code_values = {int(code) for code in codes}
            allowed = {
                int(Path.MOVETO),
                int(Path.LINETO),
                int(Path.CLOSEPOLY),
                0,
            }
            if not code_values <= allowed:
                self.unsupported("curved path segments are unsupported")
        vertices = path.vertices
        # A closed loop needs at least three real positions (CLOSEPOLY's
        # vertex is a positional dummy); fewer cannot enclose area.
        real_points = (
            len(vertices)
            if codes is None
            else sum(1 for code in codes if int(code) != int(Path.CLOSEPOLY))
        )
        if real_points < 3:
            self.unsupported("degenerate fill path")
        gc = call["gc"]
        if gc.get_hatch() is not None:
            self.unsupported("hatching is unsupported in strict mode")
        self._check_stroke_common(gc)

    def _check_stroke_common(self, gc: Any) -> None:
        """Shared dash/sketch/snap/clip checks for one eligible stroke.

        The rectangular-clip branch also seeds ``_clip_points`` so the
        geometry assembly can attach an explicit ``clip_rect``; fills and
        lines share exactly one axes rectangle.
        """
        if gc.get_dashes()[1] is not None:
            self.unsupported("dashed strokes are unsupported in strict mode")
        if gc.get_sketch_params() is not None:
            self.unsupported("sketch parameters are unsupported")
        if gc.get_snap() is not None:
            self.unsupported("explicit snap is unsupported")
        clip_rect = gc.get_clip_rectangle()
        if clip_rect is None:
            self.unsupported("absent rectangular clip where required")
        else:
            points = clip_rect.get_points()
            if not (
                _finite(points[0][0])
                and _finite(points[0][1])
                and _finite(points[1][0])
                and _finite(points[1][1])
            ):
                self.unsupported("non-finite clip rectangle")
        if gc.get_clip_path() != (None, None):
            self.unsupported("non-rectangular custom clip is unsupported")
        elif clip_rect is not None:
            # Remember the validated rectangular clip so the request can
            # carry an explicit clip_rect. Every eligible stroke of this
            # slice shares one axes rectangle.
            if self._clip_points is None:
                self._clip_points = points

    # -- legend collector-side validation (PRAC-A-L) ----------------------

    def _check_legend_gc(self, gc: Any, *, frame: bool) -> None:
        """Re-check the legend stroke surface at callback time.

        Static artist properties can change after stage one, so the
        collected graphics context is checked independently before its
        values reach the native seam.
        """
        width = float(gc.get_linewidth())
        if not math.isfinite(width) or width <= 0.0:
            self.unsupported(
                "legend stroke width must be finite and positive", "Legend"
            )
        if gc.get_dashes()[1] is not None:
            self.unsupported(
                "dashed strokes are unsupported in strict mode", "Legend"
            )
        if gc.get_hatch() is not None:
            self.unsupported("hatching is unsupported in strict mode", "Legend")
        if gc.get_sketch_params() is not None:
            self.unsupported("sketch parameters are unsupported", "Legend")
        expected_snap = True if frame else None
        if gc.get_snap() is not expected_snap:
            self.unsupported(
                "legend stroke snap differs from the fixed style surface",
                "Legend",
            )
        if not bool(gc.get_antialiased()):
            self.unsupported("legend stroke antialiasing is required", "Legend")
        if str(gc.get_capstyle()) != "butt":
            self.unsupported("legend stroke cap style must be 'butt'", "Legend")
        if str(gc.get_joinstyle()) != "miter":
            self.unsupported(
                "legend stroke join style must be 'miter'", "Legend"
            )
        if gc.get_clip_rectangle() is not None:
            self.unsupported(
                "legend strokes cannot carry a clip rectangle", "Legend"
            )
        if gc.get_clip_path() != (None, None):
            self.unsupported("legend strokes cannot carry a custom clip", "Legend")
        try:
            rgba = tuple(float(value) for value in gc.get_rgb())
        except (TypeError, ValueError):
            rgba = ()
        if len(rgba) != 4 or any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in rgba
        ):
            self.unsupported("legend stroke color must be finite RGBA", "Legend")

    def _check_legend_frame_call(self, call: dict) -> None:
        """Validate one collected legend-frame stroke (PRAC-A-L).

        The rounded ``FancyBboxPatch`` frame arrives already transformed
        into display space by Matplotlib's own legend layout: an affine
        transform, a filled path with curve-capable codes, and no clip.
        The fill/stroke style surface was checked statically; only the
        geometric shape contract is enforced here so the assembly below
        never consumes an unexpected path shape.
        """
        transform = call["transform"]
        if not bool(call.get("affine", True)):
            self.unsupported(
                "the legend frame carries a non-affine transform",
                "Legend",
            )
            return
        identity = (
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        )
        try:
            matrix = transform.get_matrix()
            is_identity = all(
                math.isfinite(float(matrix[row][column]))
                and abs(float(matrix[row][column]) - identity[row][column])
                <= 1.0e-12
                for row in range(3)
                for column in range(3)
            )
        except (AttributeError, IndexError, TypeError, ValueError):
            is_identity = False
        if not is_identity:
            self.unsupported(
                "the legend frame transform is not identity display space",
                "Legend",
            )
            return
        path = call["path"]
        codes = path.codes
        if codes is None or not len(codes):
            self.unsupported(
                "the legend frame outline is not a closed loop", "Legend"
            )
            return
        code_values = {int(code) for code in codes}
        allowed = {
            int(Path.MOVETO),
            int(Path.LINETO),
            int(Path.CURVE3),
            int(Path.CLOSEPOLY),
            0,
        }
        if not code_values <= allowed:
            self.unsupported(
                "the legend frame outline contains unsupported segments",
                "Legend",
            )
            return
        real_points = sum(
            1 for code in codes if int(code) != int(Path.CLOSEPOLY)
        )
        if real_points < 3:
            self.unsupported("degenerate legend frame path", "Legend")
            return
        gc = call["gc"]
        self._check_legend_gc(gc, frame=True)
        if int(codes[0]) != int(Path.MOVETO) or int(codes[-1]) != int(Path.CLOSEPOLY):
            self.unsupported(
                "the legend frame outline is not a closed rounded path",
                "Legend",
            )
        if any(
            not _finite(float(value))
            for vertex in path.vertices
            for value in vertex
        ):
            self.unsupported("non-finite legend frame geometry", "Legend")
        rgb_face = call.get("rgbFace")
        try:
            face_values = tuple(float(value) for value in rgb_face)
        except (TypeError, ValueError):
            face_values = ()
        if len(face_values) != 4 or any(
            not _finite(value) or not 0.0 <= value <= 1.0
            for value in face_values
        ):
            self.unsupported("legend frame facecolor must be finite RGBA", "Legend")

    def _check_legend_handle_call(self, call: dict) -> None:
        """Validate one collected legend handle stroke (PRAC-A-L)."""
        if not bool(call.get("affine", True)):
            self.unsupported(
                "a legend handle carries a non-affine transform",
                "Legend",
            )
            return
        self._check_legend_gc(call["gc"], frame=False)
        path = call["path"]
        vertices = path.vertices
        if len(vertices) < 2:
            self.unsupported("degenerate single-vertex stroke", "Legend")
        if any(
            not _finite(float(value))
            for vertex in vertices
            for value in vertex
        ):
            self.unsupported("non-finite legend handle geometry", "Legend")
        codes = path.codes
        if codes is not None and len(codes):
            allowed = {
                int(Path.MOVETO),
                int(Path.LINETO),
                int(Path.CLOSEPOLY),
                0,
            }
            if any(int(code) not in allowed for code in codes):
                self.unsupported(
                    "legend handle contains unsupported path segments",
                    "Legend",
                )
        transform = call["transform"]
        try:
            matrix = transform.get_matrix()
            if any(
                not _finite(float(matrix[row][column]))
                for row in range(3)
                for column in range(3)
            ):
                self.unsupported(
                    "legend handle transform contains non-finite values",
                    "Legend",
                )
        except (AttributeError, IndexError, TypeError, ValueError):
            self.unsupported(
                "legend handle transform is malformed", "Legend"
            )

    def _legend_clip(self, legend: Any) -> list[float]:
        """Return the frozen-seam clip rectangle for one legend.

        The frameless legend clips its strokes to the canvas exactly like
        the tick-label glyphs; a framed legend additionally paints inside
        its frame patch, which Agg realizes through patch clipping. The
        conservative full-canvas rectangle keeps every visible pixel of
        either case while staying inside the frozen seam's axis-aligned
        clip vocabulary (top-left origin, exclusive right/bottom edges).
        """
        del legend
        return [
            0.0,
            0.0,
            float(self._canvas_width_px),
            float(self._height_px),
        ]

    def _legend_frame_command(self, call: dict) -> dict | None:
        """Build one seam path command from the collected frame stroke."""
        path = call["path"]
        gc = call["gc"]
        rgb_face = call["rgbFace"]
        if rgb_face is None:
            # A framed legend always fills its patch; a missing facecolor
            # means the collector trace drifted from the static stage.
            self.unsupported(
                "the legend frame stroke lost its facecolor", "Legend"
            )
            return None
        edge_rgb = gc.get_rgb()
        width = float(gc.get_linewidth())
        try:
            edge_rgba8 = _rgba8(tuple(float(c) for c in edge_rgb))
        except (TypeError, ValueError):
            edge_rgba8 = None
        explicit_edge = (
            tuple(float(c) for c in edge_rgb)[3] != 0.0 and width > 0.0
        )
        face_color = tuple(float(c) for c in rgb_face)
        command: dict[str, Any] = {
            "kind": "path",
            "decoration": "legend_frame",
            "vertices": [
                # Collected display space is bottom-left-origin; the
                # frozen seam wants top-left pixels, so y flips once,
                # linearly (curve control points included).
                [float(vx), float(self._height_px) - float(vy)]
                for vx, vy in path.vertices
            ],
            "codes": [int(code) for code in path.codes],
            "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            "stroke_rgba": list(edge_rgba8) if explicit_edge else None,
            "line_width_pt": width,
            "cap": str(gc.get_capstyle()),
            "join": str(gc.get_joinstyle()),
            "dash_offset_pt": 0.0,
            "dashes": None,
            "fill_rule": "nonzero",
            "antialias": True,
            "clip_rect": self._legend_clip(None),
            "fill_rgba": list(_rgba8(face_color)),
        }
        if command["cap"] not in ("butt", "round", "projecting"):
            self.unsupported(
                f"legend frame cap style {command['cap']!r} is unsupported",
                "Legend",
            )
            return None
        if command["join"] not in ("miter", "round", "bevel"):
            self.unsupported(
                f"legend frame join style "
                f"{command['join']!r} is unsupported",
                "Legend",
            )
            return None
        return command

    def _legend_handle_command(self, call: dict) -> dict | None:
        """Build one seam stroke command from a collected handle."""
        path = call["path"]
        gc = call["gc"]
        transform = call["transform"]
        affine = transform.get_matrix()
        vertices = [
            [
                float(affine[0][0]) * float(x)
                + float(affine[0][1]) * float(y)
                + float(affine[0][2]),
                float(affine[1][0]) * float(x)
                + float(affine[1][1]) * float(y)
                + float(affine[1][2]),
            ]
            for x, y in path.vertices
        ]
        rgb = gc.get_rgb()
        color = tuple(float(c) for c in rgb)
        alpha = gc.get_alpha()
        if alpha is not None:
            color = color[:3] + (float(alpha),)
        # Handle strokes arrive in handlebox-local coordinates under the
        # legend layout affine (bottom-left-origin display space); the
        # seam wants top-left pixels, so the flip composes after the
        # affine, once, linearly.
        flipped_vertices = [
            [float(vx), float(self._height_px) - float(vy)]
            for vx, vy in vertices
        ]
        return {
            "kind": "path",
            "decoration": "legend_handle",
            "vertices": flipped_vertices,
            "codes": None,
            "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            "stroke_rgba": list(_rgba8(color)),
            "line_width_pt": float(gc.get_linewidth()),
            "cap": str(gc.get_capstyle()),
            "join": str(gc.get_joinstyle()),
            "dash_offset_pt": 0.0,
            "dashes": None,
            "fill_rule": "nonzero",
            "antialias": True,
            "clip_rect": self._legend_clip(None),
        }

    def _build_legend_payloads(
        self, figure: matplotlib.figure.Figure
    ) -> None:
        """Group collected legend strokes per legend, in paint order."""
        legends = [
            ax.get_legend()
            for ax in figure.get_axes()
            if ax.get_legend() is not None
        ]
        legends.extend(figure.legends)
        frames = list(self._legend_frame_calls)
        handles = list(self._legend_handle_calls)
        expected_frames = sum(
            1 for legend in legends
            if type(legend) is matplotlib.legend.Legend
            and bool(legend.get_frame_on())
        )
        expected_handles = sum(
            len(legend.get_lines())
            for legend in legends
            if type(legend) is matplotlib.legend.Legend
        )
        if len(frames) != expected_frames:
            self.unsupported(
                "collector emitted unmatched legend frame strokes; "
                "shadowed or repeated frames are unsupported",
                "Legend",
            )
            return
        if len(handles) != expected_handles:
            self.unsupported(
                "collector emitted unmatched legend handle strokes",
                "Legend",
            )
            return
        for legend in legends:
            if type(legend) is not matplotlib.legend.Legend:
                continue
            commands: list[dict] = []
            frame_count = 1 if bool(legend.get_frame_on()) else 0
            for _ in range(frame_count):
                command = self._legend_frame_command(frames.pop(0))
                if command is not None:
                    commands.append(command)
            entry_count = len(legend.get_lines())
            for _ in range(entry_count):
                command = self._legend_handle_command(handles.pop(0))
                if command is not None:
                    commands.append(command)
            self._legend_payloads[id(legend)] = commands

    # -- geometry assembly -----------------------------------------------

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
        while inverted or negative zorders now interleave exactly as Agg
        paints them. Tick label glyphs stay appended after content: the
        text wire-up owns their emission position and Agg itself always
        paints labels last within the axes' decoration surface.
        """
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
                fill = self._fill_command(collection, to_px_x, to_px_y)
                _emit(collection.get_zorder(),
                      _rank_of(collection),
                      [fill] if fill is not None else [])
            for patch in ax.patches:
                if not (
                    isinstance(patch, matplotlib.patches.Polygon)
                    or isinstance(patch, matplotlib.patches.Rectangle)
                ):
                    continue
                fill = self._fill_command(patch, to_px_x, to_px_y)
                _emit(patch.get_zorder(), _rank_of(patch),
                      [fill] if fill is not None else [])
            for line in ax.get_lines():
                spec_command = self._line_command(line, to_px_x, to_px_y)
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
        ``decoration`` marker.
        """
        commands: list[dict] = []
        scale = self._effective_dpi / 72.0
        for payload in self._label_payloads:
            label = payload["artist"]
            anchor_x = float(payload["x"])
            anchor_y = float(payload["y"])
            angle_deg = float(payload["angle"])
            label_kind = str(payload.get("kind", "tick_label"))
            decoration = (
                "legend_label"
                if label_kind == "legend_label"
                else "tick_label"
            )
            try:
                outline = textpath.glyph_outline_commands(
                    str(label.get_text()),
                    (0.0, 0.0),
                    1.0,
                    0.0,
                    font_size_pt=float(label.get_fontsize()),
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
        Gridlines and spines clip to their own axes rectangle; tick
        strokes protrude outside it, so they clip to the full canvas
        like Agg (which does not clip tick marks).
        """
        # The frozen seam clip is bottom-left-origin (x, y, w, h). Gridlines
        # and spines stay inside the axes rectangle; tick strokes protrude
        # outside it, so they carry a full-canvas clip like Agg.
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
                clip: list[float]) -> dict:
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
                "cap": "butt",
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
                    axes_clip,
                )
                commands.append(command)

        return commands

    def _fill_command(self, artist, to_px_x, to_px_y):
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
                # Zero-area bars paint nothing in Agg (no coverage).
                return None
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

        # The validated rectangular clip, in top-left pixel space with
        # exclusive right/bottom edges (frozen seam contract).
        clip_rect: list[float] | None = None
        if self._clip_points is not None:
            (cx0, cy0), (cx1, cy1) = self._clip_points
            left = min(cx0, cx1)
            right = max(cx0, cx1)
            bottom = min(cy0, cy1)
            top = max(cy0, cy1)
            clip_rect = [
                float(left),
                float(self._height_px - top),
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
            "fill_rgba": list(fill_rgba),
        }
        return command

    def _line_command(self, line, to_px_x, to_px_y):
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
        # The validated rectangular clip, in top-left pixel space with
        # exclusive right/bottom edges (frozen seam contract).
        clip_rect: list[float] | None = None
        if self._clip_points is not None:
            (cx0, cy0), (cx1, cy1) = self._clip_points
            left = min(cx0, cx1)
            right = max(cx0, cx1)
            bottom = min(cy0, cy1)
            top = max(cy0, cy1)
            clip_rect = [
                float(left),
                float(self._height_px - top),
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
