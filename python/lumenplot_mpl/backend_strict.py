"""Private strict native-render slice for the backend."""

from __future__ import annotations

import math
from typing import Any

from lumenplot_mpl.backend_preflight import _EligibilityPreflight
from lumenplot_mpl.backend_types import (
    LumenPlotPngResult,
    LumenPlotUnsupportedError,
    _BACKEND_UNAVAILABLE_TOKEN,
    _INTERNAL_TOKEN,
    _INVALID_INPUT_TOKEN,
    _OUT_OF_MEMORY_TOKEN,
)


def _native():
    """Return the private ``lumenplot_mpl._native`` extension module.

    Deferred so that importing :mod:`lumenplot_mpl.backend` never requires
    a built extension; rendering raises a clear error when absent.
    """
    from lumenplot_mpl import _native as module

    return module


class _StrictRenderMixin:
    """Strict-render methods moved verbatim from ``backend.py``.

    Mixed into ``FigureCanvasLumenPlot`` mixin-first (Q1 ruling, Option A);
    canvas shell, publication, and hybrid fallback stay in ``backend.py``.
    """

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
