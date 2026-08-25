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
import matplotlib.lines  # noqa: F401 - public submodule for the whitelist
from matplotlib.backend_bases import FigureCanvasBase, FigureManagerBase
from matplotlib.path import Path

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

    # Documented-public artist whitelist for this slice.
    _ARTIST_WHITELIST = (matplotlib.lines.Line2D,)

    # RendererBase callbacks the collector may observe, in the exact order
    # and multiplicity the eligible trace allows (ADR 0015 §4).
    _ELIGIBLE_CALLBACKS = ("draw_path",)

    def __init__(self) -> None:
        self.reasons: list[tuple[str | None, str]] = []
        self.background_seen = False
        self.background_rgbface: Any = None
        self.line_paths = 0
        self._clip_points: Any = None
        self._height_px = 0
        self._canvas_width_px = 0
        self._effective_dpi = 100.0

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
            self._check_line2d_static(artist)

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
                # Tick label glyphs are the T-lane deliverable; any visible
                # non-empty label keeps the axes out of strict eligibility.
                if label.get_visible() and label.get_text() != "":
                    self.unsupported(
                        "tick labels are unsupported; disable them with "
                        "tick_params(labelbottom=False, labelleft=False)",
                        "Text",
                    )
                    break
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
        if line.get_drawstyle() != "default":
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

    # -- stage two: public RendererBase collector ------------------------

    def _make_grammar_collector(self, collected: list[tuple]) -> Any:
        """Return a public ``RendererBase`` collector class.

        The collector records the full callback event stream of ADR 0015
        §4 — group open/close pairs, per-artist ``new_gc`` calls and
        ``draw_path`` strokes. Any other renderer callback raises instead
        of silently succeeding through the base-class no-op.
        """
        from matplotlib.backend_bases import RendererBase

        class _GrammarCollector(RendererBase):
            def __init__(self) -> None:
                super().__init__()

            def _record(self, kind: str, *rest: Any) -> None:
                collected.append((kind, *rest))

            # -- eligible events ----------------------------------------
            def open_group(self, s, gid=None):  # noqa: N802
                self._record("open", s)

            def close_group(self, s):  # noqa: N802
                self._record("close", s)

            def new_gc(self):  # noqa: N802
                from matplotlib.backend_bases import GraphicsContextBase

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

            # -- everything else is outside the trace --------------------
            def __getattr__(self, name):
                if name.startswith("draw_"):
                    raise NotImplementedError(name)
                raise AttributeError(name)

        return _GrammarCollector

    def collect(self, figure: matplotlib.figure.Figure) -> None:
        """Run one collector traversal through a public RendererBase.

        Asserts the exact eligible trace of ADR 0015 §4: one
        figure-background ``draw_path`` plus one single-stroke
        ``draw_path`` per whitelisted Line2D, with the figure/patch/axes/
        line2d group structure and per-artist ``new_gc`` calls. Only the
        strokes emitted inside a ``line2d`` group are content lines; any
        other renderer callback or unexpected path shape records an
        unsupported reason; nothing is silently ignored.
        """
        from matplotlib.backend_bases import RendererBase

        collected: list[tuple] = []

        collector_cls = self._make_grammar_collector(collected)
        for name in ("open_group", "close_group", "new_gc",
                     self._ELIGIBLE_CALLBACKS[0]):
            if not hasattr(RendererBase, name):  # pragma: no cover - defensive
                self.unsupported(f"renderer callback {name} unavailable")
                return
        try:
            figure.draw(collector_cls())
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
                # tree. Only these two shapes are eligible.
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
                if len(stack) >= 3 and stack[-1] == "patch":
                    # Axes-structural patch strokes: the transparent axes
                    # background (5-vertex fill, zero width) and the spine
                    # edges. The static stage proved the surface; here they
                    # only reconcile clip behavior.
                    if any(part == "axes" for part in stack[:-1]):
                        if stack[-2] == "axes":
                            # The transparent axes-background fill: no clip
                            # is required for a zero-width full-frame fill.
                            if call["gc"].get_linewidth() == 0.0:
                                continue
                        # Spine strokes are axes > patch with no clip; they
                        # are validated by the targeted decoration walk.
                        continue
                    else:
                        self.unsupported(
                            "a patch stroke outside an axes is outside "
                            "the eligible trace"
                        )
                        return
                    continue
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
            self.unsupported(f"unexpected {kind!r} event in the trace")
            return

        if stack:
            self.unsupported("a collector group is left open")
            return

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
        if not line_calls:
            self.unsupported("no drawable content observed", "Figure")

    def _consume_trace(self, events: list[tuple]) -> bool:
        """Validate the group/new_gc grammar of ADR 0015 §4.

        Returns ``False`` after recording a reason when the event stream
        deviates from the accepted structure. The accepted stream for this
        slice is::

            open(figure) open(patch) new_gc draw_path(bg) close(patch)
            [open(axes) [open(tag) [new_gc draw_path]... close(tag)]...
             new_gc draw_path close(axes)]...
            close(figure)

        with exactly one background stroke, at least one line stroke, and
        no other event kinds. Group nesting is structural: any artist that
        emits an unaccepted callback inside a group has already raised
        through the collector, so the stream can only contain the four
        accepted event kinds here.
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
                    # A nested artist group (line2d content or decoration
                    # surface); its structure was proven by the targeted
                    # traversal. A group carrying at least one stroke
                    # counts as drawable content.
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
        gc = call["gc"]
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
        Since the PRAC-A-D amendment, each decorated axes emits its
        solid major gridlines, major tick strokes, and visible spine edges
        as explicit path commands ahead of its content lines.
        """
        commands: list[dict] = []
        background_rgba = _RGBA_BLACK
        self._height_px = int(height_px)
        self._canvas_width_px = int(width_px)
        self._effective_dpi = float(output_dpi)
        for ax in figure.get_axes():
            xlim = ax.get_xlim()
            ylim = ax.get_ylim()
            if ax.get_xscale() != "linear" or ax.get_yscale() != "linear":
                continue
            if not (xlim[0] < xlim[1] and ylim[0] < ylim[1]):
                continue
            bbox = ax.get_window_extent()
            x0, y0 = bbox.x0, bbox.y0
            w, h = bbox.width, bbox.height

            def to_px_x(x: Any, _x0=x0, _w=w, _lim=xlim) -> Any:
                return _x0 + (float(x) - _lim[0]) / (_lim[1] - _lim[0]) * _w

            def to_px_y(y: Any, _y0=y0, _h=h, _lim=ylim) -> Any:
                return _y0 + (float(y) - _lim[0]) / (_lim[1] - _lim[0]) * _h

            if self._clip_points is None:
                self._clip_points = ((x0, y0), (x0 + w, y0 + h))

            decorated = bool(getattr(ax, "axison", True))
            if decorated:
                # Decorations first (painted below content), per axes.
                commands.extend(
                    self._decoration_commands(ax, x0, y0, w, h)
                )
            for line in ax.get_lines():
                spec = self._line_command(line, to_px_x, to_px_y)
                if spec is not None:
                    commands.append(spec)

        if self.background_rgbface is not None:
            background_rgba = _rgba8(self.background_rgbface)
        return {
            "width_px": int(width_px),
            "height_px": int(height_px),
            "output_dpi": float(output_dpi),
            "commands": commands,
            "background_rgba": list(background_rgba),
        }

    def _decoration_commands(
        self,
        ax: matplotlib.axes.Axes,
        x0: float,
        y0: float,
        w: float,
        h: float,
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
            for loc in axis.get_ticklocs():
                value = float(loc)
                if not (data_lo <= value <= data_hi):
                    continue
                fraction = (value - data_lo) / (data_hi - data_lo)
                if vertical:
                    at = x0 + fraction * w
                    p0 = (at, float(y0))
                    p1 = (at, float(y0 + h))
                else:
                    at = y0 + fraction * h
                    p0 = (float(x0), at)
                    p1 = (float(x0 + w), at)
                commands.append(seg(p0, p1, representative, "gridline",
                                    axes_clip))

        # -- major tick strokes --------------------------------------------
        # One outward stroke per drawn tick position on each visible edge,
        # styled from the edge tick line's public marker getters.
        dpi_scale = self._effective_dpi / 72.0
        for axis, horizontal, edges in ((xaxis, True, ("bottom", "top")),
                                        (yaxis, False, ("left", "right"))):
            ticks = axis.get_major_ticks()
            locs = list(axis.get_ticklocs())
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
                span_lo, span_hi = (
                    (x0, x0 + w) if horizontal else (y0, y0 + h)
                )
                base = span_lo + (
                    (value - data_lo) / (data_hi - data_lo)
                ) * (span_hi - span_lo)
                for side in edges:
                    line = getattr(tick, f"tick{1 if side in ('bottom', 'left') else 2}line")
                    if not line.get_visible():
                        continue
                    length_px = float(line.get_markersize()) * dpi_scale
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
                    commands.append(seg(p0, p1, line, "tick", canvas_clip))

        # -- spine edges -----------------------------------------------------
        # Visible spines draw the axes rectangle edges with the fixed §5
        # stroke surface; width and color come from the spine getters.
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

    def _line_command(self, line, to_px_x, to_px_y):
        name = type(line).__name__
        if not isinstance(line, matplotlib.lines.Line2D):
            self.unsupported("non-line artist reached rendering", name)
            return None
        xdata = list(line.get_xdata())
        ydata = list(line.get_ydata())
        if len(xdata) != len(ydata) or not xdata:
            self.unsupported("mismatched or empty line data", name)
            return None
        vertices = [
            [to_px_x(x), to_px_y(y)]
            for x, y in zip(xdata, ydata)
            if _finite(x) and _finite(y)
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
                preflight.collect(figure)
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
