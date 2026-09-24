"""Private publication slice for the Matplotlib backend adapter.

Leaf extraction of the adapter-owned hybrid-fallback and target-write
helpers consumed by :mod:`lumenplot_mpl.backend`. Mixed into
``FigureCanvasLumenPlot`` mixin-first alongside ``_StrictRenderMixin``;
the canvas shell, entries, dispatch core, guards, and module tail stay
in ``backend.py``.
"""

from __future__ import annotations

import io
import os
from typing import Any

from lumenplot_mpl.backend_types import (
    LumenPlotFallbackDiagnostic,
    LumenPlotPngResult,
    _UNSUPPORTED_TOKEN,
)


class _PublicationMixin:
    """Hybrid-fallback and target-write methods moved verbatim from ``backend.py``.

    Mixed into ``FigureCanvasLumenPlot`` mixin-first; defines no
    ``__init__`` and only the two moved names.
    """

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
