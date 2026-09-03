"""Public Phase-3B Matplotlib backend adapter (bounded strict/hybrid slice).

Implements the accepted public surface contract recorded in
``docs/architecture/api-0005-phase3b-public-matplotlib-backend-surface.md``
(API 0005) and ``docs/adr/0015-phase3b-public-matplotlib-adapter-contract.md``
(ADR 0015), within the lane decisions fixed by the Phase-3B workstream
(the accepted Phase-3B workstream):

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

Mode policy: the constructor kwarg ``mode`` selects ``"strict"`` or
``"hybrid"`` (the default, corresponding to the accepted
``hybrid-explicit`` profile). Strict mode renders only
the whitelisted eligible trace and raises
:class:`LumenPlotUnsupportedError` before any target write otherwise.
Since the PRAC-A-D amendment of ADR 0015 §4, the eligible trace includes
one standard ``Axes`` with decorations enabled: solid major gridlines,
major tick strokes, and spine edges are rendered natively as explicit
path commands ahead of the axes' content lines. Visible minor tick
content, non-solid grid styles, an opaque axes facecolor, titles, axis
labels, and tick labels remain outside the slice and raise.
Since the PRAC-A-L amendment of ADR 0015 §4a a standard Axes legend
(``matplotlib.legend.Legend``, single-column, line entries) is eligible
as well: its frame, handle strokes, and entry labels render as explicit
path commands with geometry handed over by Matplotlib's own legend
layout.
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
import threading
from typing import Any

import matplotlib
from matplotlib.backend_bases import FigureCanvasBase, FigureManagerBase

from lumenplot_mpl.backend_preflight import _EligibilityPreflight
from lumenplot_mpl.backend_types import (
    LumenPlotFallbackDiagnostic,
    LumenPlotPngResult,
    LumenPlotUnsupportedError,
    _BACKEND_UNAVAILABLE_TOKEN,
    _INTERNAL_TOKEN,
    _INVALID_INPUT_TOKEN,
    _OUT_OF_MEMORY_TOKEN,
    _UNSUPPORTED_TOKEN,
)


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

def _native():
    """Return the private ``lumenplot_mpl._native`` extension module.

    Deferred so that importing :mod:`lumenplot_mpl.backend` never requires
    a built extension; rendering raises a clear error when absent.
    """
    from lumenplot_mpl import _native as module

    return module


# ---------------------------------------------------------------------------
# Canvas
# ---------------------------------------------------------------------------


class FigureCanvasLumenPlot(FigureCanvasBase):
    """Public Phase-3B canvas with hybrid-explicit default and strict PNG mode.

    Adapter-owned state is limited to an immutable last-publication record
    (``last_diagnostics``) and a monotonic per-canvas generation counter.
    Publication is atomic: ``last_diagnostics`` is replaced only after a
    successful external write, and any failed attempt clears previously
    published diagnostics so stale fallback state is never reported.
    """

    filetypes = filetypes

    def __init__(self, figure=None, *, mode: str = "hybrid"):
        if mode not in ("strict", "hybrid"):
            raise ValueError(
                f"mode must be 'strict' or 'hybrid', got {mode!r}"
            )
        self._mode = mode
        self._generation = 0
        self._last_diagnostics: tuple = ()
        # This lock covers only adapter-owned counters/publication state.
        # It is never held while invoking a Matplotlib callback or a caller
        # supplied writer, preserving the reentrancy boundary in ADR 0015.
        self._publication_lock = threading.Lock()
        super().__init__(figure)

    @property
    def mode(self) -> str:
        """Selected profile mode: ``'strict'`` or ``'hybrid'``."""
        return self._mode

    @property
    def last_diagnostics(self) -> tuple:
        """Read-only observation of the last published diagnostics."""
        with self._publication_lock:
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
        generation: int | None = None
        try:
            result, generation = self._render_attempt(dpi=dpi, **kwargs)
            if target is not None:
                self._ensure_current_generation(generation)
                self._write_target(target, result.png_bytes)
            self._publish_result(generation, result)
            return result
        except BaseException:
            if generation is not None:
                self._clear_diagnostics_if_current(generation)
            raise

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
            self._raise_output_error(
                f"orientation {orientation!r} is unsupported",
                code=_INVALID_INPUT_TOKEN,
            )
        if metadata:
            self._raise_output_error(
                "non-empty PNG metadata is unsupported natively",
            )
        if pil_kwargs:
            self._raise_output_error(
                "non-empty pil_kwargs are unsupported natively",
            )
        dpi = kwargs.pop("dpi", None)
        facecolor = kwargs.pop("facecolor", None)
        edgecolor = kwargs.pop("edgecolor", None)
        bbox_inches_restore = kwargs.pop("bbox_inches_restore", None)
        if bbox_inches_restore not in (None,):
            self._raise_output_error(
                "bbox_inches output is unsupported natively",
            )
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            self._raise_output_error(
                f"unsupported print_png option(s): {unexpected}",
            )
        del facecolor, edgecolor
        generation: int | None = None
        try:
            result, generation = self._render_attempt(dpi=dpi)
            if filename_or_obj is not None:
                self._ensure_current_generation(generation)
                self._write_target(filename_or_obj, result.png_bytes)
            self._publish_result(generation, result)
        except BaseException:
            if generation is not None:
                self._clear_diagnostics_if_current(generation)
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
            name = os.fspath(filename)
            suffix = os.fsdecode(os.path.splitext(name)[1]).lstrip(".").lower()
            format = suffix or None
            if format is None:
                # Match the base-class convention of appending the default
                # extension to an extensionless filename.
                if isinstance(name, bytes):
                    filename = name.rstrip(b".") + b"." + (
                        self.get_default_filetype().encode("ascii")
                    )
                else:
                    filename = name.rstrip(".") + "." + self.get_default_filetype()
                format = "png"
        if format is None:
            format = self.get_default_filetype()
        format = str(format).lower()
        if format != "png":
            self._raise_output_error(
                f"format {format!r} is unsupported; only 'png' exists",
            )
        if bbox_inches is not None:
            self._raise_output_error(
                "bbox_inches output is unsupported natively",
            )
        if bbox_extra_artists:
            self._raise_output_error(
                "bbox_extra_artists are unsupported natively",
            )
        if pad_inches is not None and bbox_inches is None:
            self._raise_output_error(
                "non-default padding is unsupported natively",
            )
        if backend is not None:
            self._raise_output_error(
                "alternative backend selection is unsupported",
            )
        try:
            effective_dpi = self._resolve_dpi(dpi)
        except BaseException:
            self._clear_published_diagnostics()
            raise
        try:
            self.print_png(
                filename,
                dpi=effective_dpi,
                orientation=orientation,
                facecolor=facecolor,
                edgecolor=edgecolor,
            )
        finally:
            # ``print_png`` owns publication after its target write.  Keep
            # this method's return shape compatible with Matplotlib.
            pass

    # -- internal render pipeline -----------------------------------------

    def _resolve_dpi(self, dpi: float | str | None) -> float:
        """Resolve the effective savefig DPI (API 0005 §5).

        ``dpi='figure'`` resolves to the figure's original DPI; ``None``
        falls back to rcParams ``savefig.dpi``, which may be a number or
        itself ``'figure'``.
        """
        requested = (
            matplotlib.rcParams["savefig.dpi"] if dpi is None else dpi
        )
        if isinstance(requested, str):
            if requested == "figure":
                return float(self.figure.dpi)
            raise LumenPlotUnsupportedError(
                f"invalid dpi {requested!r}",
                code=_INVALID_INPUT_TOKEN,
            )
        try:
            value = float(requested)
        except (OverflowError, TypeError, ValueError) as error:
            raise LumenPlotUnsupportedError(
                f"invalid dpi {requested!r}",
                code=_INVALID_INPUT_TOKEN,
            ) from error
        if not math.isfinite(value) or value <= 0:
            raise LumenPlotUnsupportedError(
                f"invalid dpi {requested!r}",
                code=_INVALID_INPUT_TOKEN,
            )
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
        result, generation = self._render_attempt(dpi=dpi, **kwargs)
        self._publish_result(generation, result)
        return result

    def _render_attempt(
        self,
        *,
        dpi: float | str | None = None,
        **kwargs: Any,
    ) -> tuple[LumenPlotPngResult, int]:
        """Render one attempt and return its result with its generation.

        Publication is deliberately separate from rendering. Callers that
        write to an external target publish only after that write succeeds;
        callers that only request owned bytes publish immediately after this
        method returns.
        """
        generation = self._begin_attempt()
        try:
            return self._render_attempt_body(
                generation=generation,
                dpi=dpi,
                **kwargs,
            ), generation
        except BaseException:
            self._clear_diagnostics_if_current(generation)
            raise

    def _render_attempt_body(
        self,
        *,
        generation: int,
        dpi: float | str | None = None,
        **kwargs: Any,
    ) -> LumenPlotPngResult:
        """Run strict-first dispatch for an already-started attempt."""
        try:
            return self._render_strict(
                generation=generation,
                dpi=dpi,
                **kwargs,
            )
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

    def _begin_attempt(self) -> int:
        """Spend one generation and clear the previous observation."""
        with self._publication_lock:
            generation = self._generation + 1
            self._generation = generation
            self._last_diagnostics = ()
            return generation

    def _ensure_current_generation(self, generation: int) -> None:
        """Reject a result superseded by a newer render attempt."""
        with self._publication_lock:
            current = self._generation
        if current != generation:
            raise LumenPlotUnsupportedError(
                "render attempt became stale before publication",
                code=_INTERNAL_TOKEN,
                generation=generation,
            )

    def _publish_result(
        self, generation: int, result: LumenPlotPngResult
    ) -> None:
        """Atomically publish diagnostics for the current generation."""
        with self._publication_lock:
            if self._generation != generation:
                raise LumenPlotUnsupportedError(
                    "render attempt became stale before publication",
                    code=_INTERNAL_TOKEN,
                    generation=generation,
                )
            self._last_diagnostics = tuple(result.diagnostics)

    def _clear_diagnostics_if_current(self, generation: int) -> None:
        """Clear failed-attempt state without clobbering newer output."""
        with self._publication_lock:
            if self._generation == generation:
                self._last_diagnostics = ()

    def _clear_published_diagnostics(self) -> None:
        """Clear diagnostics for a rejected output request."""
        with self._publication_lock:
            self._last_diagnostics = ()

    def _raise_output_error(
        self,
        message: str,
        *,
        code: str = _UNSUPPORTED_TOKEN,
    ) -> None:
        """Raise a stable output guard error after clearing stale state."""
        self._clear_published_diagnostics()
        raise LumenPlotUnsupportedError(message, code=code)

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
            try:
                width_in, height_in = figure.get_size_inches()
                width_in = float(width_in)
                height_in = float(height_in)
                width_px = int(round(width_in * output_dpi))
                height_px = int(round(height_in * output_dpi))
            except (OverflowError, TypeError, ValueError) as error:
                raise LumenPlotUnsupportedError(
                    "figure size is not representable for PNG output",
                    code=_INVALID_INPUT_TOKEN,
                    generation=generation,
                ) from error
            if (
                not math.isfinite(width_in)
                or not math.isfinite(height_in)
                or width_in <= 0.0
                or height_in <= 0.0
            ):
                raise LumenPlotUnsupportedError(
                    "figure size must be finite and positive",
                    code=_INVALID_INPUT_TOKEN,
                    generation=generation,
                )
            if width_px <= 0 or height_px <= 0:
                raise LumenPlotUnsupportedError(
                    "non-positive canvas size",
                    code=_INVALID_INPUT_TOKEN,
                    generation=generation,
                )

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
            except (OverflowError, ValueError, TypeError, RuntimeError) as error:
                raise LumenPlotUnsupportedError(
                    f"preflight traversal failed: {error}",
                    code=_INTERNAL_TOKEN,
                    generation=generation,
                ) from error

            png_bytes = self._call_native(spec, generation)
        finally:
            figure.dpi = original_figure_dpi
        return LumenPlotPngResult(png_bytes, ())

    def _call_native(self, spec: dict, generation: int) -> bytes:
        try:
            native = _native()
        except (AttributeError, ImportError) as error:
            raise LumenPlotUnsupportedError(
                "the private lumenplot_mpl._native backend is unavailable",
                code=_BACKEND_UNAVAILABLE_TOKEN,
                generation=generation,
            ) from error
        try:
            render_frame_png = getattr(native, "render_frame_png", None)
        except (AttributeError, ImportError) as error:
            raise LumenPlotUnsupportedError(
                "the private lumenplot_mpl._native backend is unavailable",
                code=_BACKEND_UNAVAILABLE_TOKEN,
                generation=generation,
            ) from error
        if render_frame_png is not None:
            if not callable(render_frame_png):
                raise LumenPlotUnsupportedError(
                    "the private lumenplot_mpl._native backend is invalid",
                    code=_BACKEND_UNAVAILABLE_TOKEN,
                    generation=generation,
                )
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
                    code=_INTERNAL_TOKEN,
                    generation=generation,
                ) from error
            except RuntimeError as error:
                native_code = getattr(error, "code", None)
                if native_code not in (
                    _BACKEND_UNAVAILABLE_TOKEN,
                    _INVALID_INPUT_TOKEN,
                    _OUT_OF_MEMORY_TOKEN,
                    _INTERNAL_TOKEN,
                ):
                    native_code = _INTERNAL_TOKEN
                raise LumenPlotUnsupportedError(
                    "native raster failure",
                    code=native_code,
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
            code=_BACKEND_UNAVAILABLE_TOKEN,
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
        generation, output format, and raster/vector scope in the returned
        result; the caller publishes it only after any external write
        succeeds. A failed fallback attempt publishes nothing.
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
        return LumenPlotPngResult(png_bytes, (diagnostic,))

    def _write_target(self, target: Any, data: bytes) -> None:
        """Write finished bytes to path-like or binary file-like targets.

        Adapter-owned files are opened/written/closed here; caller-owned
        binary file-likes receive exactly one public ``write(bytes)`` and
        are never closed. ``OSError`` propagates unchanged.
        """
        if hasattr(target, "write") and callable(target.write):
            written = target.write(data)
            if written is not None and written != len(data):
                raise OSError(
                    f"short write: expected {len(data)} bytes, wrote {written}"
                )
            return
        with open(os.fspath(target), "wb") as handle:
            written = handle.write(data)
            if written != len(data):
                raise OSError(
                    f"short write: expected {len(data)} bytes, wrote {written}"
                )


#: Class alias fixed by API 0005 §1 (backend module identity).
FigureCanvas = FigureCanvasLumenPlot



# Keep provisional public record identities anchored at the backend module.
LumenPlotFallbackDiagnostic.__module__ = __name__
LumenPlotPngResult.__module__ = __name__
LumenPlotUnsupportedError.__module__ = __name__
