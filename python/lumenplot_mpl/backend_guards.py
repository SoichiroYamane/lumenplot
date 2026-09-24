"""Private output-guard slice for the Matplotlib backend adapter.

Leaf extraction of the adapter-owned output-guard helper consumed by
:mod:`lumenplot_mpl.backend`. Mixed into ``FigureCanvasLumenPlot``
mixin-first alongside ``_PublicationMixin`` and ``_StrictRenderMixin``;
the canvas shell, entries, dispatch core, publication, strict render,
and module tail stay in ``backend.py``.
"""

from __future__ import annotations

from lumenplot_mpl.backend_types import (
    LumenPlotUnsupportedError,
    _UNSUPPORTED_TOKEN,
)


class _OutputGuardMixin:
    """Output-guard method moved verbatim from ``backend.py``.

    Mixed into ``FigureCanvasLumenPlot`` mixin-first; defines no
    ``__init__`` and only the one moved name.
    """

    def _raise_output_error(
        self,
        message: str,
        *,
        code: str = _UNSUPPORTED_TOKEN,
    ) -> None:
        """Raise a stable output guard error after clearing stale state."""
        self._publication.clear()
        raise LumenPlotUnsupportedError(message, code=code)
