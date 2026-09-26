"""Private attempt-orchestration slice for the Matplotlib backend adapter.

Leaf extraction of the adapter-owned strict-first attempt helpers consumed by
:mod:`lumenplot_mpl.backend`. Mixed into ``FigureCanvasLumenPlot``
mixin-first alongside ``_DispatchMixin``, ``_OutputGuardMixin``,
``_PublicationMixin``, and ``_StrictRenderMixin``; the canvas shell,
entries, guards, publication, strict render, DPI resolution, and module
tail stay in ``backend.py``.
"""

from __future__ import annotations

from typing import Any

from lumenplot_mpl.backend_types import (
    LumenPlotPngResult,
    LumenPlotUnsupportedError,
    _UNSUPPORTED_TOKEN,
)


class _AttemptMixin:
    """Strict-first attempt methods moved verbatim from ``backend.py``.

    Mixed into ``FigureCanvasLumenPlot`` mixin-first; defines no
    ``__init__`` and only the two moved names.
    """

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
        generation = self._publication.begin_attempt()
        try:
            return self._render_attempt_body(
                generation=generation,
                dpi=dpi,
                **kwargs,
            ), generation
        except BaseException:
            self._publication.clear_if_current(generation)
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
