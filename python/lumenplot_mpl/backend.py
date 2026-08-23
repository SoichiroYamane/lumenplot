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
import os
from typing import Any

import matplotlib
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
    return channel


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


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
    # and multiplicity the eligible trace allows.
    _ELIGIBLE_CALLBACKS = ("draw_path",)

    def __init__(self) -> None:
        self.reasons: list[tuple[str | None, str]] = []
        self.background_seen = False
        self.background_rgbface: Any = None
        self.line_paths = 0

    def unsupported(self, reason: str, type_context: str | None = None) -> None:
        self.reasons.append((type_context, reason))

    # -- stage one: static whitelist ------------------------------------

    def check_static(self, figure: matplotlib.figure.Figure) -> None:
        for ax in figure.get_axes():
            if not bool(getattr(ax, "axison", True)):
                continue
            self.unsupported("axes decorations are enabled", type(ax).__name__)
        for artist in self._iterate_content_artists(figure):
            if not isinstance(artist, self._ARTIST_WHITELIST):
                self.unsupported(
                    f"artist {type(artist).__name__} is outside the "
                    "supported whitelist",
                    type(artist).__name__,
                )
                continue
            self._check_line2d_static(artist)

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
        if line.get_gid() is None:
            return

        # -- stage two: public RendererBase collector ------------------------

    def collect(self, figure: matplotlib.figure.Figure) -> None:
        """Run one collector traversal through a public RendererBase.

        Builds the exact eligible trace: exactly one figure-background
        ``draw_path`` followed by one single-stroke ``draw_path`` per
        whitelisted Line2D. Any other renderer callback or unexpected path
        shape records an unsupported reason.
        """
        from matplotlib.backend_bases import RendererBase

        collected: list[dict] = []

        class _Collector(RendererBase):
            def draw_path(self, gc, path, transform, rgbFace=None):  # noqa: N802
                collected.append(
                    {
                        "gc": gc,
                        "path": path,
                        "transform": transform,
                        "rgbFace": rgbFace,
                    }
                )

            def __getattr__(self, name):  # pragma: no cover - defensive
                raise AttributeError(name)

        collector = _Collector()
        for name in self._ELIGIBLE_CALLBACKS:
            if not hasattr(RendererBase, name):  # pragma: no cover - defensive
                self.unsupported(f"renderer callback {name} unavailable")
                return
        figure.draw(collector)

        if not collected:
            self.unsupported("no drawable content observed", "Figure")
            return
        first = collected[0]
        background = first["rgbFace"]
        if background is None:
            self.unsupported("first draw_path is not a filled background")
        elif len(first["path"].vertices) != 5:
            self.unsupported("figure background is not a closed rectangle")
        else:
            self.background_seen = True
            self.background_rgbface = background
            self._check_background_style(first)

        for call in collected[1:]:
            self.line_paths += 1
            self._check_line_call(call)

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


        if gc.get_clip_path() != (None, None):
            self.unsupported("non-rectangular custom clip is unsupported")

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
        """
        commands: list[dict] = []
        background_rgba = _RGBA_BLACK
        for ax in figure.get_axes():
            if bool(getattr(ax, "axison", True)):
                # Preflight already recorded this as unsupported.
                continue
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
        if cap == "projecting":
            cap = "projecting"
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
            "clip_rect": None,
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
        falls back to rcParams ``savefig.dpi`` which may itself be
        ``'figure'``.
        """
        if dpi is None or dpi == "figure":
            rc = matplotlib.rcParams["savefig.dpi"]
            if dpi is None and isinstance(rc, str):
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
