"""Private lifecycle slice for the Matplotlib backend adapter.

Leaf extraction of the adapter-owned constructor + publication-state
accessors consumed by :mod:`lumenplot_mpl.backend`. Mixed into
``FigureCanvasLumenPlot`` mixin-first alongside ``_DispatchMixin``,
``_OutputGuardMixin``, ``_PublicationMixin``, ``_StrictRenderMixin``,
``_AttemptMixin``, and ``_OutputMixin``; the canvas shell, module
identity surface, and module tail stay in ``backend.py``.
"""

from __future__ import annotations

from lumenplot_mpl.backend_state import _CanvasPublicationState


class _LifecycleMixin:
    """Constructor + publication-state accessors moved verbatim from ``backend.py``.

    Mixed into ``FigureCanvasLumenPlot`` mixin-first; defines
    ``__init__`` and only the four moved names.
    """

    def __init__(self, figure=None, *, mode: str = "hybrid"):
        if mode not in ("strict", "hybrid"):
            raise ValueError(
                f"mode must be 'strict' or 'hybrid', got {mode!r}"
            )
        self._mode = mode
        self._publication = _CanvasPublicationState()
        super().__init__(figure)

    @property
    def mode(self) -> str:
        """Selected profile mode: ``'strict'`` or ``'hybrid'``."""
        return self._mode

    @property
    def last_diagnostics(self) -> tuple:
        """Read-only observation of the last published diagnostics."""
        return self._publication.last_diagnostics

    @property
    def _generation(self) -> int:
        return self._publication.generation
