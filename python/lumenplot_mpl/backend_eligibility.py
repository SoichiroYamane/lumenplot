"""Private stage-one static eligibility checks for the backend."""

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

# mplot3d is part of Matplotlib's documented public plotting surface.  Keep
# these imports at the adapter edge; the engine and private raster seam never
# see Matplotlib types.
from mpl_toolkits.mplot3d.art3d import Line3D, Poly3DCollection
from mpl_toolkits.mplot3d.axes3d import Axes3D

from lumenplot_mpl.backend_support import (
    _STEP_DRASTYLES,
    _finite,
    _native_f64,
)


class _StaticEligibilityMixin:
    """Stage-one static whitelist checks (ADR 0015 §3, API 0005 §4)."""

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
        Line3D,
        Poly3DCollection,
    )

    # RendererBase callbacks the collector may observe, in the exact order
    # and multiplicity the eligible trace allows (ADR 0015 §4).
    _ELIGIBLE_CALLBACKS = ("draw_path",)

    # -- stage one: static whitelist ------------------------------------

    def check_static(self, figure: matplotlib.figure.Figure) -> None:
        self._three_d_axes = [
            ax for ax in figure.get_axes() if isinstance(ax, Axes3D)
        ]
        if self._three_d_axes and (
            len(figure.get_axes()) != 1 or len(self._three_d_axes) != 1
        ):
            self.unsupported(
                "3D native mode requires exactly one Axes3D and no mixed axes",
                "Figure",
            )
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
            # refused instead of silently mis-ordered.
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
            # 3D subclasses overlap the 2D Matplotlib class hierarchy. Check
            # them first so a Line3D cannot accidentally take the Line2D data
            # route and a Poly3DCollection cannot be reduced to one fill.
            if isinstance(artist, Line3D):
                self._check_line3d_static(artist)
            elif isinstance(artist, Poly3DCollection):
                self._check_poly3d_static(artist)
            elif isinstance(artist, matplotlib.lines.Line2D):
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
        """Check structural properties available before drawing.

        A 3D Axes is admitted only as the dedicated one-axes surface. Its
        public projection matrix, view angles, and three bound pairs become
        semantic facts; the collector later proves that axis/pane/grid
        decoration callbacks are absent (axis-off) rather than reading a
        private axis-state flag.
        """
        if isinstance(ax, Axes3D):
            name = type(ax).__name__
            try:
                projection = numpy.asarray(ax.get_proj(), dtype=float)
                bounds = (
                    tuple(float(value) for value in ax.get_xlim3d()),
                    tuple(float(value) for value in ax.get_ylim3d()),
                    tuple(float(value) for value in ax.get_zlim3d()),
                )
                projection_name = (
                    "perspective"
                    if not numpy.allclose(
                        projection[3, :3], 0.0, rtol=0.0, atol=1.0e-12
                    )
                    else "orthographic"
                )
                view = {
                    "projection": projection_name,
                    "elevation_deg": float(ax.elev),
                    "azimuth_deg": float(ax.azim),
                    "roll_deg": float(ax.roll),
                    # Matplotlib 3.11 exposes projection through get_proj but
                    # no public focal-length getter. The reference default is
                    # the accepted 1.0 rule; custom matrix/view cases remain
                    # representable because geometry comes from the same
                    # public projection callback.
                    "focal_length": (
                        1.0 if projection_name == "perspective" else None
                    ),
                    "bounds": [list(pair) for pair in bounds],
                    "projection_matrix_shape": list(projection.shape),
                    "box_aspect": [
                        float(value) for value in ax.get_box_aspect()
                    ],
                }
            except (AttributeError, TypeError, ValueError, IndexError):
                self.unsupported(
                    "public Axes3D projection/view facts are not representable",
                    name,
                )
                return
            if (
                projection.shape != (4, 4)
                or not numpy.isfinite(projection).all()
                or any(
                    len(pair) != 2
                    or not all(math.isfinite(value) for value in pair)
                    or pair[0] >= pair[1]
                    for pair in bounds
                )
                or not all(
                    math.isfinite(view[key])
                    for key in ("elevation_deg", "azimuth_deg", "roll_deg")
                )
                or not all(
                    math.isfinite(value) and value > 0.0
                    for value in view["box_aspect"]
                )
            ):
                self.unsupported(
                    "Axes3D bounds, view, or projection facts are invalid",
                    name,
                )
                return
            self._three_d_view_facts[id(ax)] = view
            return

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

    def _check_tick_label_static(self, label: Any) -> None:
        """Whitelist-check one visible major tick label (PRAC-A-W).

        Whitelisted tick labels (and legend entry labels) ride kind:image
        coverage-blit commands per the ADR 0015 section 4b PNG-only label-
        coverage amendment (per-label FT2Font raster at the output DPI
        into an alpha mask, same Matplotlib-provided anchor math, agg_srgb
        composite); only the label's string, font face, font size, color,
        alpha, rotation, alignment, and position are honored. Anything
        outside the supported surface is refused here so stage two never
        observes an unexpected ``draw_text``.
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
        # T-lane style contract: the glyph route resolves the label's own
        # public font face and size, so a non-positive size, sketch, snap
        # override, or custom clip has no representable outline and refuses
        # here (same surface the legend entry labels already enforce
        # downstream; recording it here keeps tick labels self-sufficient).
        size = float(label.get_fontsize())
        if not math.isfinite(size) or size <= 0.0:
            self.unsupported("non-positive font size", name)
        if label.get_sketch_params() is not None:
            self.unsupported("sketch parameters are unsupported", name)
        if label.get_snap() is not None:
            self.unsupported("explicit snap is unsupported", name)
        if label.get_clip_box() is not None or label.get_clip_path() is not None:
            self.unsupported("custom clipping is unsupported", name)

    def _check_axis_label_static(self, label: Any) -> None:
        """Whitelist-check one visible non-empty axis label (B-2a R2).

        Whitelisted axis labels ride kind:image coverage-blit
        commands per the ADR 0015 section 4b PNG-only label-coverage
        amendment (per-label FT2Font raster at the output DPI into an
        alpha mask, same Matplotlib-provided anchor math, agg_srgb
        composite); they satisfy the same static text contract as tick
        labels, plus an explicit hyperlink refusal (the native seam
        carries no URL target and must never drop one silently).
        """
        self._check_tick_label_static(label)
        name = type(label).__name__
        if label.get_url() is not None:
            self.unsupported("hyperlinks are unsupported", name)

    def _check_title_static(self, label: Any) -> None:
        """Whitelist-check one visible non-empty axes title (center/left/right).

        Whitelisted titles ride kind:image coverage-blit
        commands per the ADR 0015 section 4b PNG-only label-coverage
        amendment (per-label FT2Font raster at the output DPI into an
        alpha mask, same Matplotlib-provided anchor math, agg_srgb
        composite); they satisfy the same static text contract as tick
        labels, plus an explicit hyperlink refusal (the native seam
        carries no URL target and must never drop one silently).
        """
        self._check_tick_label_static(label)
        name = type(label).__name__
        if label.get_url() is not None:
            self.unsupported("hyperlinks are unsupported", name)

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

    def _check_line3d_static(self, line: Line3D) -> None:
        """Whitelist the public Line3D data/style surface.

        Projection is intentionally not recomputed here.  The collector gives
        the native seam the exact public mplot3d projected path, while this
        stage preserves the canonical three f64 source channels (including
        non-finite pen-lift samples) for semantic evidence.
        """
        name = type(line).__name__
        if line.get_marker() != "None":
            self.unsupported("3D markers are unsupported; use Line3D only", name)
        if line.is_dashed():
            self.unsupported("dashed 3D strokes are unsupported", name)
        width = float(line.get_linewidth())
        if not math.isfinite(width) or width < 0.0:
            self.unsupported("3D line width must be finite and non-negative", name)
        if line.get_path_effects() or line.get_sketch_params() is not None:
            self.unsupported("3D line path effects/sketch are unsupported", name)
        if line.get_snap() is not None or line.get_clip_path() is not None:
            self.unsupported("custom 3D clipping/snap is unsupported", name)
        if line.get_url() is not None:
            self.unsupported("3D hyperlinks are unsupported", name)
        if str(line.get_solid_capstyle()) != "butt":
            self.unsupported("3D strict mode requires butt caps", name)
        if str(line.get_solid_joinstyle()) != "miter":
            self.unsupported("3D strict mode requires miter joins", name)
        try:
            data = tuple(line.get_data_3d())
        except (AttributeError, TypeError, ValueError):
            self.unsupported("Line3D public data is unavailable", name)
            return
        if len(data) != 3:
            self.unsupported("Line3D must expose x/y/z data", name)
            return
        lengths = [len(values) for values in data]
        if len(set(lengths)) != 1 or lengths[0] < 2:
            self.unsupported("Line3D x/y/z data lengths are not drawable", name)
            return
        for axis_name, values in zip(("x", "y", "z"), data):
            for value in values:
                if not _native_f64(value):
                    self.unsupported(
                        f"Line3D {axis_name}-data contains a value that is "
                        "not representable as native f64",
                        name,
                    )
                    return

    def _check_poly3d_static(self, collection: Poly3DCollection) -> None:
        """Whitelist triangle geometry and resolved per-element style.

        ``Poly3DCollection`` exposes its projected paths through the public
        renderer callback rather than a public 3D-vertex getter.  The callback
        is therefore the geometry source, and the source bounds/view facts are
        recorded from the Axes3D public API.  A non-triangle, malformed, or
        non-broadcast style is refused before native allocation.
        """
        name = type(collection).__name__
        if collection.get_hatch() is not None:
            self.unsupported("3D hatching is unsupported", name)
        if collection.get_path_effects() or collection.get_sketch_params() is not None:
            self.unsupported("3D collection path effects/sketch are unsupported", name)
        if collection.get_clip_path() is not None:
            self.unsupported("custom 3D collection clipping is unsupported", name)
        try:
            widths = numpy.atleast_1d(
                numpy.asarray(collection.get_linewidth(), dtype=float).ravel()
            )
            faces = numpy.asarray(collection.get_facecolor(), dtype=float)
            edges = numpy.asarray(collection.get_edgecolor(), dtype=float)
            cap = collection.get_capstyle()
            join = collection.get_joinstyle()
        except (AttributeError, TypeError, ValueError):
            self.unsupported("Poly3DCollection style is not public/finite", name)
            return
        if widths.size == 0:
            widths = numpy.asarray([0.0], dtype=float)
        if not numpy.isfinite(widths).all() or numpy.any(widths < 0.0):
            self.unsupported("Poly3DCollection linewidths are invalid", name)
        if faces.ndim not in (1, 2) or (faces.size and faces.shape[-1] != 4):
            self.unsupported("Poly3DCollection facecolors are invalid", name)
        if edges.ndim not in (1, 2) or (edges.size and edges.shape[-1] != 4):
            self.unsupported("Poly3DCollection edgecolors are invalid", name)
        if faces.size and not numpy.isfinite(faces).all():
            self.unsupported("Poly3DCollection facecolors are not finite", name)
        if edges.size and not numpy.isfinite(edges).all():
            self.unsupported("Poly3DCollection edgecolors are not finite", name)
        cap_name = "butt" if cap is None else str(cap)
        join_name = "miter" if join is None else str(join)
        if cap_name not in ("butt", "round", "projecting"):
            self.unsupported("Poly3DCollection cap style is unsupported", name)
        if join_name not in ("miter", "round", "bevel"):
            self.unsupported("Poly3DCollection join style is unsupported", name)
        self._three_d_collection_styles[id(collection)] = {
            "cap": cap_name,
            "join": join_name,
            "widths": widths.tolist(),
            "faces": faces.tolist(),
            "edges": edges.tolist(),
        }

