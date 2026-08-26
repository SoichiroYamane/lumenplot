"""Public Phase-3B Matplotlib backend adapter (first strict-mode slice).

Implements the accepted public surface contract recorded in
``docs/architecture/api-0005-phase3b-public-matplotlib-backend-surface.md``
(API 0005) and ``docs/adr/0015-phase3b-public-matplotlib-adapter-contract.md``
(ADR 0015), within the lane decisions fixed by the Phase-3B workstream
(parent task t_3339d0b5 comment thread):

- identity: distribution ``lumenplot-mpl``, package ``lumenplot_mpl``,
  backend module ``lumenplot_mpl.backend``, loader
  ``module://lumenplot_mpl.backend``, entry point name ``lumenplot``
  (registered by packaging, not here);
- exports: ``FigureCanvasLumenPlot(FigureCanvasBase)`` with alias
  ``FigureCanvas``, ``FigureManager = FigureManagerBase``,
  ``required_interactive_framework = None``, ``filetypes`` containing
  exactly PNG;
- result/diagnostic separation: ``savefig``/``print_figure``/``print_png``
  return ``None``; the separate helper :meth:`FigureCanvasLumenPlot.render_png`
  returns owned bytes plus immutable diagnostics; strict unsupported handling
  raises before any target write;
- documented public Matplotlib APIs only: no private names anywhere in this
  module.

Mode policy: the constructor kwarg ``mode`` selects ``"strict"`` (default)
or ``"hybrid"`` (ADR 0015 §12 ordered delivery). Strict mode renders only
the whitelisted eligible trace and raises
:class:`LumenPlotUnsupportedError` before any target write otherwise.
Since the PRAC-A-D amendment of ADR 0015 §4, the eligible trace includes
one standard ``Axes`` with decorations enabled: solid major gridlines,
major tick strokes, and spine edges are rendered natively as explicit
path commands ahead of the axes' content lines. Visible minor tick
content, non-solid grid styles, an opaque axes facecolor, titles, axis
labels, and tick labels remain outside the slice and raise.
Hybrid mode first attempts exactly the strict native path and, only when
that raises the stable ``unsupported-capability`` failure, succeeds with a
whole-frame Agg fallback: stock public ``FigureCanvasAgg`` PNG output plus
one structured :class:`LumenPlotFallbackDiagnostic` (reason, type,
generation, output format, raster/vector scope per API 0002). Missing
native infrastructure (``backend-unavailable``) and internal engine
failures are never converted into a visual fallback; nothing degrades
silently.

The native seam is the private extension module ``lumenplot_mpl._native``.
This slice consumes the frozen ``render_line_png`` signature from Phase-3A
and the additive ``render_frame_png(spec) -> bytes`` seam fixed by decision
2/3 of the parent workstream. The native import is deferred to first use so
that importing this module never depends on a built extension.
"""

from __future__ import annotations

import io
import math
import numbers
import os
from typing import Any

import matplotlib
import matplotlib.axes  # noqa: F401 - public submodule for type checks
import matplotlib.axis  # noqa: F401 - public submodule for tick positions
import matplotlib.collections  # noqa: F401 - public submodule for the whitelist
import matplotlib.lines  # noqa: F401 - public submodule for the whitelist
import matplotlib.patches  # noqa: F401 - public submodule for the whitelist
from matplotlib.backend_bases import FigureCanvasBase, FigureManagerBase
from matplotlib.path import Path

import numpy
from lumenplot_mpl import textpath

__all__ = [
    "FigureCanvas",
    "FigureCanvasLumenPlot",
    "FigureManager",
    "LumenPlotFallbackDiagnostic",
    "LumenPlotPngResult",
    "filetypes",
    "required_interactive_framework",
]

#: PNG is the only output format of this slice (API 0005 §1).
filetypes = {"png": "Portable Network Graphics"}

#: No GUI framework is required: this is a pure-rendering backend slice.
required_interactive_framework = None

#: Manager identity is unchanged; diagnostics live on the canvas only.
FigureManager = FigureManagerBase

# Stable API-0002 token reused by every strict-unsupported failure of this
# slice. The token is the machine contract; messages are non-contract.
_UNSUPPORTED_TOKEN = "unsupported-capability"

#: Opaque black used when an artist carries no explicit stroke/fill color.
_RGBA_BLACK = (0, 0, 0, 255)

#: LP-FUNC-035 ordering contract, stated once for the whole adapter.
#:
#: This is the single normative description of how the emission stage
#: reproduces Matplotlib Agg's ``Axes.draw`` paint order; every stage
#: that touches ordering cites this text instead of restating its own
#: copy (W2-comp-fix-v2 review item: one contract, one home).
#:
#: 1. Sort input. ``Axes.draw`` sorts ``ax.get_children()`` minus
#:    ``ax.patch`` with Python's stable ``sorted`` keyed on zorder;
#:    equal-zorder ties keep enumeration (add) order across primitive
#:    classes. The adapter mirrors both halves: the single stable sort
#:    runs over every eligible child of an axes at once, and tie rank
#:    comes from the public ``Axes.get_children`` enumeration index --
#:    never from artist class, type name, or container membership.
#:
#: 2. Patch exclusion. Agg removes the axes' background patch from the
#:    sorted list and prepends it after sorting, so the background paints
#:    below every child whatever its zorder -- even negative ones. The
#:    adapter's eligibility walk excludes ``ax.patch`` (and every other
#:    structural artist) from the content surface for the same reason,
#:    and strict mode renders no axes-background fill command at all: an
#:    opaque facecolor is refused, so exclusion cannot reorder anything.
#:
#: 3. Decoration placement. Gridline and tick strokes ride their Axis
#:    unit's public zorder (default 1.5); spine edges ride the Spine
#:    artists' own public zorder (default 2.5). At the default surface
#:    this keeps grid/tick strokes below default content lines (z 2) --
#:    the ratified Axis-unit model Agg actually paints -- while inverted
#:    or negative zorders interleave exactly as Agg paints them. Tick
#:    label glyphs stay appended after all axes content: the text wire-up
#:    owns their emission position and Agg itself always paints labels
#:    last within the decoration surface.
#:
#: 4. Outside-the-sort artists. Images, legends, tables, texts outside
#:    the tick-label wire-up, rasterized artists (``rasterization_zorder``
#:    splitting), and every non-whitelisted class are outside this
#:    contract: they never enter the sort because they are not eligible
#:    content -- they refuse in preflight (strict) or fall back whole-
#:    frame through Agg (hybrid), so no silent reordering exists.
_ZORDER_CONTRACT_DOC = """LP-FUNC-035 ordering contract (backend.py header).

The normative text lives in the module comment block above; stages cite
this constant's name when they depend on one of its clauses so a future
editor finds every touchpoint from one search.
"""


class LumenPlotFallbackDiagnostic:
    """Immutable structured fallback record (API 0005 §3).

    Field content follows the accepted diagnostic envelope; exact naming is
    the workstream-fixed spelling. Instances are immutable after creation
    and carry no behavior beyond observation.
    """

    __slots__ = (
        "_fallback_type",
        "_generation",
        "_kind",
        "_output_format",
        "_representation",
        "_scope",
        "_type_context",
    )

    def __init__(
        self,
        *,
        kind: str,
        type: str | None,  # noqa: A002 - contract field name
        generation: int,
        output_format: str = "png",
        scope: str = "whole-frame",
        representation: str = "raster",
        fallback_type: str = "matplotlib-agg",
    ) -> None:
        object.__setattr__(self, "_kind", kind)
        object.__setattr__(self, "_type_context", type)
        object.__setattr__(self, "_generation", int(generation))
        object.__setattr__(self, "_output_format", output_format)
        object.__setattr__(self, "_scope", scope)
        object.__setattr__(self, "_representation", representation)
        object.__setattr__(self, "_fallback_type", fallback_type)

    def __setattr__(self, name: str, value: Any) -> None:  # pragma: no cover
        raise AttributeError("LumenPlotFallbackDiagnostic is immutable")

    def __delattr__(self, name: str) -> None:  # pragma: no cover
        raise AttributeError("LumenPlotFallbackDiagnostic is immutable")

    @property
    def kind(self) -> str:
        """Stable token: ``unsupported-capability`` or a fallback token."""
        return self._kind

    @property
    def type(self) -> str | None:  # noqa: A003 - contract field name
        """Public artist or callback type context."""
        return self._type_context

    @property
    def generation(self) -> int:
        """Non-negative per-canvas attempt number."""
        return self._generation

    @property
    def output_format(self) -> str:
        return self._output_format

    @property
    def scope(self) -> str:
        return self._scope

    @property
    def representation(self) -> str:
        return self._representation

    @property
    def fallback_type(self) -> str:
        return self._fallback_type

    def __repr__(self) -> str:
        return (
            "LumenPlotFallbackDiagnostic("
            f"kind={self._kind!r}, type={self._type_context!r}, "
            f"generation={self._generation}, "
            f"output_format={self._output_format!r}, "
            f"scope={self._scope!r}, "
            f"representation={self._representation!r}, "
            f"fallback_type={self._fallback_type!r})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LumenPlotFallbackDiagnostic):
            return NotImplemented
        return (
            self._kind == other._kind
            and self._type_context == other._type_context
            and self._generation == other._generation
            and self._output_format == other._output_format
            and self._scope == other._scope
            and self._representation == other._representation
            and self._fallback_type == other._fallback_type
        )

    def __hash__(self) -> int:
        return hash(
            (
                self._kind,
                self._type_context,
                self._generation,
                self._output_format,
                self._scope,
                self._representation,
                self._fallback_type,
            )
        )


class LumenPlotPngResult:
    """Owned PNG bytes plus immutable diagnostics (API 0005 §3).

    The bytes are owned by the result; ``diagnostics`` is an immutable
    tuple of :class:`LumenPlotFallbackDiagnostic`. Native success carries
    an empty tuple.
    """

    __slots__ = ("_diagnostics", "_png_bytes")

    def __init__(self, png_bytes: bytes, diagnostics: tuple) -> None:
        object.__setattr__(self, "_png_bytes", bytes(png_bytes))
        object.__setattr__(self, "_diagnostics", tuple(diagnostics))

    def __setattr__(self, name: str, value: Any) -> None:  # pragma: no cover
        raise AttributeError("LumenPlotPngResult is immutable")

    def __delattr__(self, name: str) -> None:  # pragma: no cover
        raise AttributeError("LumenPlotPngResult is immutable")

    @property
    def png_bytes(self) -> bytes:
        """The owned PNG byte string."""
        return self._png_bytes

    @property
    def diagnostics(self) -> tuple:
        """Immutable diagnostics tuple (empty on native success)."""
        return self._diagnostics

    def __repr__(self) -> str:
        return (
            "LumenPlotPngResult("
            f"{len(self._png_bytes)} bytes, "
            f"{len(self._diagnostics)} diagnostic(s))"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LumenPlotPngResult):
            return NotImplemented
        return (
            self._png_bytes == other._png_bytes
            and self._diagnostics == other._diagnostics
        )

    def __hash__(self) -> int:
        return hash((self._png_bytes, self._diagnostics))


class LumenPlotUnsupportedError(RuntimeError):
    """Strict-mode unsupported-capability failure.

    Raised before any target write when preflight rejects the request in
    strict mode. ``code`` carries the stable API-0002 token; the message is
    non-contract human text.
    """

    def __init__(self, message: str, *, code: str = _UNSUPPORTED_TOKEN,
                 type_context: str | None = None,
                 generation: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.type_context = type_context
        self.generation = generation


# ---------------------------------------------------------------------------
# Native seam (deferred import)
# ---------------------------------------------------------------------------


def _native():
    """Return the private ``lumenplot_mpl._native`` extension module.

    Deferred so that importing :mod:`lumenplot_mpl.backend` never requires
    a built extension; rendering raises a clear error when absent.
    """
    from lumenplot_mpl import _native as module

    return module


def _rgba8(color: Any, alpha: float | None = None) -> tuple[int, int, int, int]:
    """Convert a Matplotlib color to an unpremultiplied 0-255 RGBA tuple.

    Uses only the public ``matplotlib.colors.to_rgba``. A ``None`` alpha
    keeps the color's own alpha; otherwise the explicit alpha multiplies
    it. Values quantize by rounding half away from overflow and clamp.
    """
    r, g, b, a = matplotlib.colors.to_rgba(color)
    if alpha is not None:
        a = float(alpha) * a
    channel = (
        int(round(min(max(r, 0.0), 1.0) * 255)),
        int(round(min(max(g, 0.0), 1.0) * 255)),
        int(round(min(max(b, 0.0), 1.0) * 255)),
        int(round(min(max(a, 0.0), 1.0) * 255)),
    )
    if channel[3] == 0:
        # ADR-0015 §5: fully transparent strokes encode RGB as zero.
        return (0, 0, 0, 0)
    return channel


def _finite(value: Any) -> bool:
    # numpy integer/floating scalars (what Line2D.get_{x,y}data returns for
    # int or float input) are not Python int/float instances, so accept any
    # numbers.Real except bool.
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return False
    return math.isfinite(float(value))


#: Step drawstyles admitted by the LP-FUNC-034 eligibility extension
#: (LP-MPL-020: whitelist entry unchanged, collector-trace expectation
#: unchanged, style contract, and fixtures landed in one commit). Each
#: value names the exact vertex-generation semantics Matplotlib's own
#: ``cbook`` step functions apply before projection; the bare ``steps``
#: alias is Matplotlib's historical spelling of ``steps-pre``.
_STEP_DRASTYLES = frozenset(
    {"steps", "steps-pre", "steps-post", "steps-mid"}
)


def _expand_step_vertices(xdata: list, ydata: list, drawstyle: str):
    """Expand sampled data per Matplotlib's step semantics.

    The formulas mirror ``matplotlib.cbook.pts_to_{pre,post,mid}step``
    exactly (Agg quality oracle, parity draft §5.4): N samples become
    2N-1 vertices for pre/post and 2N vertices for mid, so the emitted
    polyline is the same geometry Agg strokes for the same Figure.
    Callers refuse non-finite samples before reaching here (see
    ``_line_command``): Agg's path cleaning re-pairs risers around NaN
    gaps, so no expansion of masked data reproduces that oracle.
    """
    count = len(xdata)
    if drawstyle == "steps-mid":
        expanded_x: list = [xdata[0]]
        expanded_y: list = [ydata[0]]
        for index in range(count - 1):
            midpoint = (xdata[index] + xdata[index + 1]) / 2.0
            expanded_x.append(midpoint)
            expanded_y.append(ydata[index])
            expanded_x.append(midpoint)
            expanded_y.append(ydata[index + 1])
        expanded_x.append(xdata[-1])
        expanded_y.append(ydata[-1])
        return expanded_x, expanded_y
    # steps / steps-pre / steps-post share the 2N-1 shape; only which
    # side of each interval carries the vertical riser differs.
    expanded_x = [0.0] * (2 * count - 1)
    expanded_y = [0.0] * (2 * count - 1)
    for index in range(count):
        expanded_x[2 * index] = xdata[index]
        expanded_y[2 * index] = ydata[index]
        if index == count - 1:
            break
        if drawstyle == "steps-post":
            expanded_x[2 * index + 1] = xdata[index + 1]
            expanded_y[2 * index + 1] = ydata[index]
        else:
            # steps / steps-pre: riser sits at the left sample.
            expanded_x[2 * index + 1] = xdata[index]
            expanded_y[2 * index + 1] = ydata[index + 1]
    return expanded_x, expanded_y


class _SpineStroke:
    """Line2D-style view over one Spine for the decoration builder.

    Exposes only the public getters the fixed §5 stroke surface needs:
    color, width, and alpha. Cap/join are the lane-fixed Butt/Miter, not
    the artist's own styles.
    """

    def __init__(self, spine: Any) -> None:
        self._spine = spine

    def get_color(self) -> Any:
        return self._spine.get_edgecolor()

    def get_alpha(self) -> float | None:
        alpha = self._spine.get_alpha()
        return None if alpha is None else float(alpha)

    def get_linewidth(self) -> float:
        return float(self._spine.get_linewidth())


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
    # ``Rectangle`` artists (``Axes.bar`` / ``Axes.barh`` bars).
    _ARTIST_WHITELIST = (
        matplotlib.lines.Line2D,
        matplotlib.patches.Polygon,
        matplotlib.patches.Rectangle,
        matplotlib.collections.FillBetweenPolyCollection,
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

    def unsupported(self, reason: str, type_context: str | None = None) -> None:
        self.reasons.append((type_context, reason))

    # -- stage one: static whitelist ------------------------------------

    def check_static(self, figure: matplotlib.figure.Figure) -> None:
        for ax in figure.get_axes():
            self._check_axes_decorations(ax)
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
            else:
                self._check_patch_static(artist)

    def _check_axes_decorations(self, ax: matplotlib.axes.Axes) -> None:
        """Whitelist-check one axes and its decoration surface.

        Since the PRAC-A-D amendment of ADR 0015 §4 a standard decorated
        ``Axes`` is eligible: solid major gridlines, major tick strokes,
        and spine edges render as explicit path commands. Everything else
        about the decoration surface (visible minor tick content, non-solid
        grid styles, an opaque facecolor, titles, axis labels, offset
        text, or child axes) records an explicit unsupported reason.
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
        if not bool(getattr(ax, "axison", True)):
            # Decoration-less axes: nothing below applies.
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

    def _iterate_content_artists(self, figure: matplotlib.figure.Figure):
        """Yield drawable content artists, not structural containers.

        The Figure/Axes objects, their patch, spines, axis containers, and
        tick wrappers are structural: with ``axison`` disabled they draw
        nothing, and the stage-two collector trace rejects them if they
        ever emit a callback.
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
        if line.get_linewidth() < 0:
            self.unsupported("negative line width", name)
        if line.get_path_effects():
            self.unsupported("path effects are unsupported", name)
        if line.get_sketch_params() is not None:
            self.unsupported("sketch parameters are unsupported", name)
        if line.get_snap() is not None:
            self.unsupported("explicit snap is unsupported", name)
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
        ``draw_path`` strokes. Since the PRAC-A-W wire-up it also accepts
        ``draw_text`` callbacks for major tick labels: each callback must
        carry exactly the next statically enumerated label's text, font
        size, and rotation, and is recorded together with the label
        artist so rendering can rebuild the glyphs. Any other renderer
        callback raises instead of silently succeeding through the
        base-class no-op.

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
                self._pending_labels = list(expected_labels)
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
                del gc
                if not self._pending_labels:
                    self._record(
                        "draw_text_unexpected",
                        {"text": str(s)},
                    )
                    return
                entry = self._pending_labels.pop(0)
                size_ok = (
                    abs(float(prop.get_size()) - entry["size"]) <= 1e-9
                )
                angle_ok = (
                    abs(float(angle) - entry["angle"]) <= 1e-9
                )
                if bool(ismath) or s != entry["text"] or not size_ok or (
                    not angle_ok
                ):
                    self._record(
                        "draw_text_unexpected",
                        {
                            "text": str(s),
                            "expected": entry["text"],
                        },
                    )
                    return
                self._record(
                    "draw_text",
                    {
                        "artist": entry["artist"],
                        "x": float(x),
                        "y": float(y),
                        "angle": float(angle),
                    },
                )

            def remaining_labels(self) -> list[dict]:
                """Statically accepted labels never observed at draw time."""
                return list(self._pending_labels)

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
        self, figure: matplotlib.figure.Figure
    ) -> list[dict]:
        """Enumerate the tick labels stage one accepted, in draw order.

        Matplotlib draws each decorated axes' major ticks through public
        ``Axis.get_major_ticks``/``get_ticklocs`` in the same order the
        collector observes their ``draw_text`` callbacks (x-axis first,
        then y-axis; ``label1`` before ``label2`` per tick). Only visible
        non-empty labels whose tick location lies inside
        ``Axis.get_view_interval()`` enter the queue: ``Tick.draw`` skips
        out-of-view ticks entirely, so an unfiltered enumeration would
        accept labels the renderer never draws (observed with date/unit
        locators whose end ticks fall outside the data margins --
        LP-FUNC-037 fixtures pin this). Filtering by the same public view
        interval keeps the queue aligned with the live stream without
        duplicating Matplotlib's layout work.
        """
        entries: list[dict] = []
        for ax in figure.get_axes():
            if type(ax) is not matplotlib.axes.Axes:
                continue
            if not bool(getattr(ax, "axison", True)):
                continue
            for axis in (ax.xaxis, ax.yaxis):
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
        return entries

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
        that label's public string/font size/rotation. Only the strokes
        emitted inside a ``line2d`` group are content lines; any other
        renderer callback or unexpected path shape records an
        unsupported reason; nothing is silently ignored.
        """
        from matplotlib.backend_bases import RendererBase

        collected: list[tuple] = []
        expected_labels = self._enumerate_expected_labels(figure)

        collector_cls = self._make_grammar_collector(
            collected,
            expected_labels,
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
                        "the draw_text callback for an accepted tick label "
                        f"changed at draw time: expected {expected!r}, got "
                        f"{payload.get('text')!r}",
                        "Text",
                    )
                return
            self.unsupported(f"unexpected {kind!r} event in the trace")
            return

        if stack:
            self.unsupported("a collector group is left open")
            return

        if collector_instance.remaining_labels():
            # A label that stage one accepted never reached the renderer:
            # refusing keeps the trace exact instead of silently dropping
            # visible text.
            self.unsupported(
                "a statically accepted tick label was not drawn",
                "Text",
            )
            return

        self._observed_text_payloads = text_calls

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
        """Validate the group/new_gc grammar of ADR 0015 §4.

        Returns ``False`` after recording a reason when the event stream
        deviates from the accepted structure. The accepted stream for this
        slice is::

            open(figure) open(patch) new_gc draw_path(bg) close(patch)
            [open(axes) [artist groups / new_gc / draw_path]...
             close(axes)]...
            close(figure)

        with exactly one background stroke and at least one drawable
        stroke per axes group. Since LP-FUNC-035 (D2) the axes body is
        order-free: eligible artist groups (``line2d`` content,
        ``patch`` fills, decoration surfaces) may interleave in any
        order because ``Axes.draw`` sorts children by zorder, so no
        whole-trace ordering is imposed; only the figure/patch prefix,
        the balanced group nesting, and per-group structure remain.
        Any artist that emits an unaccepted callback inside a group has
        already raised through the collector, so the stream can only
        contain the four accepted event kinds here.
        """
        index = 0
        total = len(events)

        def expect_open(tag: str) -> bool:
            nonlocal index
            if index < total and events[index] == ("open", tag):
                index += 1
                return True
            return False

        def expect_close(tag: str) -> bool:
            nonlocal index
            if index < total and events[index] == ("close", tag):
                index += 1
                return True
            return False

        def consume_group() -> bool:
            """Consume one balanced open(tag)...close(tag) artist group.

            The group body may nest further groups; any accepted event
            kind inside is structural for this stage. Returns ``False``
            only when the stream deviates or the group is left open.
            """
            nonlocal index
            tag = events[index][1]
            start = index
            index += 1
            while index < total:
                kind = events[index][0]
                if kind == "close" and events[index][1] == tag:
                    index += 1
                    return True
                if kind == "open":
                    if not consume_group():
                        return False
                    continue
                if kind in ("new_gc", "draw_path"):
                    index += 1
                    continue
                self.unsupported(
                    f"unexpected {kind!r} inside the {tag} group "
                    f"opened at event {start}"
                )
                return False
            self.unsupported(
                f"the {tag} group opened at event {start} is left open"
            )
            return False

        if not (expect_open("figure") and expect_open("patch")):
            self.unsupported(
                "collector trace does not start with the figure/patch groups"
            )
            return False
        if index >= total or events[index][0] != "new_gc":
            self.unsupported(
                "figure background stroke is missing its graphics context"
            )
            return False
        index += 1
        if (
            index >= total
            or events[index][0] != "draw_path"
            or events[index][1].get("rgbFace") is None
        ):
            self.unsupported("figure background stroke is missing")
            return False
        index += 1
        if not expect_close("patch"):
            self.unsupported("the figure patch group is left open")
            return False
        while index < total and events[index] == ("open", "axes"):
            index += 1
            saw_line = False
            while index < total:
                kind = events[index][0]
                if kind == "close" and events[index] == ("close", "axes"):
                    break
                if kind == "draw_path":
                    saw_line = True
                    index += 1
                    continue
                if kind == "new_gc":
                    index += 1
                    continue
                if kind == "open":
                    # A nested artist group (line2d content, patch fill,
                    # or decoration surface). Since LP-FUNC-035 (D2)
                    # groups may interleave in any order -- ``Axes.draw``
                    # sorts children by zorder, so no whole-trace
                    # ordering exists to assert. A group carrying at
                    # least one stroke counts as drawable content.
                    if not consume_group():
                        return False
                    saw_line = True
                    continue
                self.unsupported(
                    f"unexpected {kind!r} inside an axes group"
                )
                return False
            if not saw_line:
                self.unsupported("an axes group carries no drawable line")
                return False
            if not expect_close("axes"):
                self.unsupported("an axes group is left open")
                return False
        if not expect_close("figure"):
            self.unsupported("the figure group is left open")
            return False
        if index != total:
            kind = events[index][0]
            detail = events[index][1] if len(events[index]) > 1 else ""
            self.unsupported(
                f"unexpected {kind} {detail!r} outside the eligible trace"
            )
            return False
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

        LP-FUNC-035 compositing contract (D1): each axes reproduces Agg's
        ``Axes.draw`` ordering -- one stable sort of every eligible child
        by public ``get_zorder()`` (Python ``sorted`` keeps add order on
        ties, which is Agg's own stable-sort semantics). The normative
        ordering text is the module-level ``_ZORDER_CONTRACT_DOC`` block;
        this stage implements its clauses 1-3 directly: gridline, tick,
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
        for ax in figure.get_axes():
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

            decorated = bool(getattr(ax, "axison", True))
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
            entries.sort(key=lambda entry: entry[:2])
            for _, _, entry_commands in entries:
                commands.extend(entry_commands)

        # Tick label glyphs paint above lines and decorations in Matplotlib
        # (text artists draw after the axes' line content), so the wire-up
        # appends them last: same relative order, no z-order regression.
        commands.extend(self._tick_label_commands())

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
        """Build one filled glyph path command per collected tick label.

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
        public-getter route as every other command surface.
        """
        commands: list[dict] = []
        scale = self._effective_dpi / 72.0
        for payload in self._label_payloads:
            label = payload["artist"]
            anchor_x = float(payload["x"])
            anchor_y = float(payload["y"])
            angle_deg = float(payload["angle"])
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
                    f"tick label glyphs are unsupported: {error}",
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
                    "decoration": "tick_label",
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

        Tick locations project through the axis' own scale via the
        caller's ``to_px_x``/``to_px_y`` closures (LP-FUNC-004): a log
        axis places gridlines and tick strokes at the fractional log
        position Agg uses, not at the linear fraction.

        Since LP-FUNC-035 the ``kinds`` selector splits the decoration
        surface along its artists' z-order boundaries: gridlines and
        tick strokes travel with their Axis unit's zorder while spine
        edges ride the Spine artist's own zorder, so the caller can slot
        each group into the single stable ``Axes.draw`` sort instead of
        painting every decoration first.
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
        if isinstance(artist, matplotlib.collections.Collection):
            paths = list(artist.get_paths())
            transform = artist.get_transform()
            facecolors = artist.get_facecolor()
            edgecolors = artist.get_edgecolor()
            linewidths = artist.get_linewidth()
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
            edgecolors = None
            linewidths = float(artist.get_linewidth())
            capstyle = str(artist.get_capstyle())
            joinstyle = str(artist.get_joinstyle())
            alpha = artist.get_alpha()
        else:
            paths = [artist.get_path()]
            facecolors = None
            edgecolors = None
            linewidths = float(artist.get_linewidth())
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
            edge_tuple = tuple(float(c) for c in edge_color_raw)
        except TypeError:
            edge_tuple = tuple(float(c) for c in edge_color_raw[0])
        explicit_edge = edge_tuple[3] != 0.0
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
        # LP-FUNC-034: the step family expands the SAMPLED data exactly.
        # A non-finite sample has no step semantics (Agg's own path
        # cleaning re-pairs the risers around the gap, so neither dropping
        # the row nor bridging it reproduces the oracle), therefore
        # stepped lines refuse explicitly instead of approximating --
        # LP-MPL-020 forbids silent approximation. The default drawstyle
        # keeps its historical row-filtering behavior untouched.
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
            base_x = [x for x, _ in finite_rows]
            base_y = [y for _, y in finite_rows]
        if drawstyle in _STEP_DRASTYLES and len(base_x) >= 1:
            expanded_x, expanded_y = _expand_step_vertices(
                base_x, base_y,
                "steps-pre" if drawstyle == "steps" else drawstyle,
            )
        else:
            expanded_x, expanded_y = base_x, base_y
        vertices = [
            [to_px_x(x), to_px_y(y)]
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


# ---------------------------------------------------------------------------
# Canvas
# ---------------------------------------------------------------------------


class FigureCanvasLumenPlot(FigureCanvasBase):
    """Public Phase-3B canvas: strict-mode native PNG rendering.

    Adapter-owned state is limited to an immutable last-publication record
    (``last_diagnostics``) and a monotonic per-canvas generation counter.
    Publication is atomic: ``last_diagnostics`` is replaced only after a
    successful external write, and any failed attempt clears previously
    published diagnostics so stale fallback state is never reported.
    """

    filetypes = filetypes

    def __init__(self, figure=None, *, mode: str = "strict"):
        if mode not in ("strict", "hybrid"):
            raise ValueError(
                f"mode must be 'strict' or 'hybrid', got {mode!r}"
            )
        self._mode = mode
        self._generation = 0
        self._last_diagnostics: tuple = ()
        super().__init__(figure)

    @property
    def mode(self) -> str:
        """Selected profile mode: ``'strict'`` or ``'hybrid'``."""
        return self._mode

    @property
    def last_diagnostics(self) -> tuple:
        """Read-only observation of the last published diagnostics."""
        return tuple(self._last_diagnostics)

    # -- helper API -------------------------------------------------------

    def render_png(
        self,
        target: Any = None,
        *,
        dpi: float | str | None = None,
        **kwargs: Any,
    ) -> LumenPlotPngResult:
        """Render natively and return owned bytes plus diagnostics.

        When ``target`` is None the bytes are only returned. When ``target``
        is a binary file-like object it receives exactly one public
        ``write(bytes)`` call and is never closed; path-like targets are
        written by the adapter.
        """
        result = self._render(dpi=dpi, **kwargs)
        if target is not None:
            try:
                self._write_target(target, result.png_bytes)
            except BaseException:
                # The render succeeded but publication failed. ADR-0015 §9:
                # a failed attempt must not leave previously published
                # diagnostics behind, so stale fallback state is never
                # reported.
                self._last_diagnostics = ()
                raise
        return result

    # -- Matplotlib-compatible output methods -----------------------------

    def print_png(self, filename_or_obj=None, *, metadata=None,
                  pil_kwargs=None, **kwargs: Any) -> None:
        """Render a PNG natively; returns ``None`` (API 0005 §3).

        ``metadata`` must be ``None`` or empty: non-empty metadata is
        unsupported natively and raises in strict mode before any write.
        ``pil_kwargs`` must be ``None`` or empty. Inherited ``orientation``
        is validated explicitly rather than ignored.
        """
        orientation = kwargs.pop("orientation", "portrait")
        if orientation not in ("portrait", "landscape"):
            raise LumenPlotUnsupportedError(
                f"orientation {orientation!r} is unsupported",
            )
        if metadata:
            raise LumenPlotUnsupportedError(
                "non-empty PNG metadata is unsupported natively",
            )
        if pil_kwargs:
            raise LumenPlotUnsupportedError(
                "non-empty pil_kwargs are unsupported natively",
            )
        dpi = kwargs.pop("dpi", None)
        facecolor = kwargs.pop("facecolor", None)
        edgecolor = kwargs.pop("edgecolor", None)
        bbox_inches_restore = kwargs.pop("bbox_inches_restore", None)
        if bbox_inches_restore not in (None,):
            raise LumenPlotUnsupportedError(
                "bbox_inches output is unsupported natively",
            )
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise LumenPlotUnsupportedError(
                f"unsupported print_png option(s): {unexpected}",
            )
        del facecolor, edgecolor
        result = self._render(dpi=dpi)
        if filename_or_obj is not None:
            try:
                self._write_target(filename_or_obj, result.png_bytes)
            except BaseException:
                # The render succeeded but publication failed (e.g. an
                # OSError from the target). ADR-0015 §9: a failed attempt
                # must not leave previously published diagnostics behind,
                # so stale fallback state is never reported.
                self._last_diagnostics = ()
                raise

    def print_figure(self, filename, dpi=None, facecolor=None, edgecolor=None,
                     orientation="portrait", format=None, *,
                     bbox_inches=None, pad_inches=None, bbox_extra_artists=None,
                     backend=None, **kwargs: Any) -> None:
        """Guarded override of the base file-output entry point.

        PNG-only with an explicit guard: non-PNG formats fail explicitly
        instead of silently selecting another registered encoder.
        """
        if format is None and isinstance(filename, (str, os.PathLike)):
            from pathlib import PurePath

            name = os.fspath(filename)
            suffix = PurePath(name).suffix.lstrip(".").lower()
            format = suffix or None
            if format is None and isinstance(filename, str):
                # Match the base-class convention of appending the default
                # extension to an extensionless filename.
                filename = filename.rstrip(".") + "." + self.get_default_filetype()
                format = "png"
        if format is None:
            format = self.get_default_filetype()
        format = str(format).lower()
        if format != "png":
            raise LumenPlotUnsupportedError(
                f"format {format!r} is unsupported; only 'png' exists",
            )
        if bbox_inches is not None:
            raise LumenPlotUnsupportedError(
                "bbox_inches output is unsupported natively",
            )
        if bbox_extra_artists:
            raise LumenPlotUnsupportedError(
                "bbox_extra_artists are unsupported natively",
            )
        if pad_inches is not None and bbox_inches is None:
            pass
        if backend is not None:
            raise LumenPlotUnsupportedError(
                "alternative backend selection is unsupported",
            )
        effective_dpi = self._resolve_dpi(dpi)
        try:
            self.print_png(
                filename,
                dpi=effective_dpi,
                orientation=orientation,
                facecolor=facecolor,
                edgecolor=edgecolor,
            )
        finally:
            pass

    # -- internal render pipeline -----------------------------------------

    def _resolve_dpi(self, dpi: float | str | None) -> float:
        """Resolve the effective savefig DPI (API 0005 §5).

        ``dpi='figure'`` resolves to the figure's original DPI; ``None``
        falls back to rcParams ``savefig.dpi``, which may be a number or
        itself ``'figure'``.
        """
        if dpi is None or dpi == "figure":
            rc = matplotlib.rcParams["savefig.dpi"]
            if dpi is None:
                dpi = rc
        if dpi in (None, "figure"):
            return float(getattr(self.figure, "_original_dpi", self.figure.dpi))
        if isinstance(dpi, str):
            raise LumenPlotUnsupportedError(f"invalid dpi {dpi!r}")
        value = float(dpi)
        if not math.isfinite(value) or value <= 0:
            raise LumenPlotUnsupportedError(f"invalid dpi {dpi!r}")
        return value

    def _render(self, *, dpi: float | str | None = None,
                **kwargs: Any) -> LumenPlotPngResult:
        """Run preflight, build the spec, call the native seam once.

        In hybrid mode a stable ``unsupported-capability`` failure of the
        strict path is replaced by the whole-frame Agg fallback result; the
        generation counter is spent exactly once for the whole attempt so
        the diagnostic names the same attempt as the output. Any other
        failure (missing native seam, internal errors) propagates in both
        modes.
        """
        generation = self._generation + 1
        self._generation = generation
        self._last_diagnostics = ()

        try:
            return self._render_strict(generation=generation, dpi=dpi,
                                       **kwargs)
        except LumenPlotUnsupportedError as error:
            if error.code != _UNSUPPORTED_TOKEN or self._mode != "hybrid":
                raise
            reason = str(error)
            type_context = error.type_context
            return self._render_hybrid_fallback(
                generation=generation,
                dpi=self._resolve_dpi(dpi),
                reason=reason,
                type_context=type_context,
            )

    def _render_strict(self, *, generation: int,
                       dpi: float | str | None = None,
                       **kwargs: Any) -> LumenPlotPngResult:
        """Run one strict native attempt at an already-spent generation."""

        output_dpi = self._resolve_dpi(dpi)
        figure = self.figure

        # API 0005 §5 / ADR-0015 §6: the whole attempt -- eligibility
        # traversal and geometry assembly alike -- runs under the effective
        # savefig DPI, and the temporary effective-DPI state is restored
        # afterwards whatever the outcome.
        original_figure_dpi = float(figure.dpi)
        figure.dpi = output_dpi
        try:
            width_in, height_in = figure.get_size_inches()
            width_px = int(round(float(width_in) * output_dpi))
            height_px = int(round(float(height_in) * output_dpi))
            if width_px <= 0 or height_px <= 0:
                raise LumenPlotUnsupportedError("non-positive canvas size")

            try:
                preflight = _EligibilityPreflight()
                preflight.check_static(figure)
                # The collector needs the real canvas geometry up front:
                # ``Text.draw`` consults the renderer's canvas size and
                # display flip while laying out each label, so stale
                # defaults here would misplace every anchor it reports.
                preflight.collect(
                    figure,
                    width_px=width_px,
                    height_px=height_px,
                    dpi=output_dpi,
                )
                if preflight.reasons:
                    type_context, reason = preflight.reasons[0]
                    raise LumenPlotUnsupportedError(
                        f"unsupported content in strict mode: {reason}",
                        type_context=type_context,
                        generation=generation,
                    )
                if not preflight.background_seen:
                    raise LumenPlotUnsupportedError(
                        "figure background was not observed",
                        generation=generation,
                    )
                if preflight.line_paths == 0:
                    # An eligible frame still needs at least one line stroke;
                    # a bare background renders fine though.
                    pass
                spec = preflight.build_frame_spec(
                    figure,
                    width_px=width_px,
                    height_px=height_px,
                    output_dpi=output_dpi,
                )
                # Geometry assembly records its own refusals
                # (``_line_command``: mismatched/empty data, fewer than
                # two finite points -- LP-FUNC-034 fixtures exercise the
                # all-non-finite row case). They must gate the render
                # exactly like collector-stage reasons, still before any
                # seam call.
                if preflight.reasons:
                    type_context, reason = preflight.reasons[0]
                    raise LumenPlotUnsupportedError(
                        f"unsupported content in strict mode: {reason}",
                        type_context=type_context,
                        generation=generation,
                    )
            except LumenPlotUnsupportedError as error:
                if error.generation is None:
                    error.generation = generation
                raise
            except (ValueError, TypeError, RuntimeError) as error:
                raise LumenPlotUnsupportedError(
                    f"preflight traversal failed: {error}",
                    generation=generation,
                ) from error

            png_bytes = self._call_native(spec, generation)
        finally:
            figure.dpi = original_figure_dpi
        return LumenPlotPngResult(png_bytes, ())

    def _call_native(self, spec: dict, generation: int) -> bytes:
        native = _native()
        render_frame_png = getattr(native, "render_frame_png", None)
        if render_frame_png is not None:
            try:
                data = render_frame_png(spec)
            except ValueError as error:
                # The frozen seam contract (crates/lumenplot-python
                # ``FrameError``) raises bare ValueError only for Rust-side
                # spec-validation failures, which include capacity budgets
                # (e.g. the per-path point cap). ADR-0015 §9 makes capacity
                # and overflow terminal: this must NOT carry the default
                # unsupported-capability token, or hybrid mode would convert
                # it into a whole-frame Agg fallback.
                raise LumenPlotUnsupportedError(
                    f"native seam rejected the frame spec: {error}",
                    code="internal",
                    generation=generation,
                ) from error
            except RuntimeError as error:
                raise LumenPlotUnsupportedError(
                    f"native raster failure: {error}",
                    code="internal",
                    generation=generation,
                ) from error
            if not isinstance(data, (bytes, bytearray)):
                raise LumenPlotUnsupportedError(
                    "native seam returned a non-bytes result",
                    code="internal",
                    generation=generation,
                )
            return bytes(data)
        # The additive Phase-3B seam is absent (L1 lane not merged yet).
        # Strict mode never silently substitutes another rasterizer; it
        # reports the missing capability explicitly.
        raise LumenPlotUnsupportedError(
            "the private lumenplot_mpl._native.render_frame_png seam is "
            "not available in this environment",
            code="backend-unavailable",
            generation=generation,
        )

    def _render_hybrid_fallback(
        self,
        *,
        generation: int,
        dpi: float,
        reason: str,
        type_context: str | None,
    ) -> LumenPlotPngResult:
        """Produce the whole-frame Agg fallback result (API 0002/0005).

        Renders the complete frame through stock public ``FigureCanvasAgg``
        PNG output at the requested effective DPI, then restores any
        temporary canvas state even on failure. Success publishes exactly
        one structured diagnostic describing reason, type context,
        generation, output format, and raster/vector scope; a failed
        fallback attempt publishes nothing.
        """
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        buffer = io.BytesIO()
        previous_canvas = self.figure.canvas
        try:
            FigureCanvasAgg(self.figure)
            self.figure.savefig(buffer, format="png", dpi=dpi)
        finally:
            previous_canvas.figure = self.figure
            self.figure.canvas = previous_canvas
        png_bytes = buffer.getvalue()
        diagnostic = LumenPlotFallbackDiagnostic(
            kind=_UNSUPPORTED_TOKEN,
            type=type_context,
            generation=generation,
            output_format="png",
            scope="whole-frame",
            representation="raster",
            fallback_type="matplotlib-agg",
        )
        self._last_diagnostics = (diagnostic,)
        return LumenPlotPngResult(png_bytes, self._last_diagnostics)

    def _write_target(self, target: Any, data: bytes) -> None:
        """Write finished bytes to path-like or binary file-like targets.

        Adapter-owned files are opened/written/closed here; caller-owned
        binary file-likes receive exactly one public ``write(bytes)`` and
        are never closed. ``OSError`` propagates unchanged.
        """
        if hasattr(target, "write") and callable(target.write):
            target.write(data)
            return
        with open(os.fspath(target), "wb") as handle:
            handle.write(data)


#: Class alias fixed by API 0005 §1 (backend module identity).
FigureCanvas = FigureCanvasLumenPlot
