"""Private render-dispatch slice for the Matplotlib backend adapter.

Leaf extraction of the adapter-owned render-dispatch helper consumed by
:mod:`lumenplot_mpl.backend`. Mixed into ``FigureCanvasLumenPlot``
mixin-first alongside ``_OutputGuardMixin``, ``_PublicationMixin``,
and ``_StrictRenderMixin``; the canvas shell, entries, guards,
publication, strict render, and module tail stay in ``backend.py``.
"""

from __future__ import annotations

from typing import Any

from lumenplot_mpl.backend_types import LumenPlotPngResult


class _DispatchMixin:
    """Render-dispatch method moved verbatim from ``backend.py``.

    Mixed into ``FigureCanvasLumenPlot`` mixin-first; defines no
    ``__init__`` and only the one moved name.
    """

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
        self._publication.publish(generation, result)
        return result
