"""Private output-entry slice for the Matplotlib backend adapter.

Leaf extraction of the adapter-owned output-entry helpers consumed by
:mod:`lumenplot_mpl.backend`. Mixed into ``FigureCanvasLumenPlot``
mixin-first alongside ``_DispatchMixin``, ``_OutputGuardMixin``,
``_PublicationMixin``, ``_StrictRenderMixin``, and ``_AttemptMixin``;
the canvas shell, guards, publication, strict render, attempt
orchestration, and module tail stay in ``backend.py``.
"""

from __future__ import annotations

import math
import os
from typing import Any

import matplotlib

from lumenplot_mpl.backend_types import (
    LumenPlotPngResult,
    LumenPlotUnsupportedError,
    _INVALID_INPUT_TOKEN,
)


class _OutputMixin:
    """Output-entry methods moved verbatim from ``backend.py``.

    Mixed into ``FigureCanvasLumenPlot`` mixin-first; defines no
    ``__init__`` and only the four moved names.
    """

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
                self._publication.ensure_current(generation)
                self._write_target(target, result.png_bytes)
            self._publication.publish(generation, result)
            return result
        except BaseException:
            if generation is not None:
                self._publication.clear_if_current(generation)
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
                self._publication.ensure_current(generation)
                self._write_target(filename_or_obj, result.png_bytes)
            self._publication.publish(generation, result)
        except BaseException:
            if generation is not None:
                self._publication.clear_if_current(generation)
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
            self._publication.clear()
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
