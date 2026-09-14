"""Private per-canvas publication state for the Matplotlib backend adapter.

Leaf extraction of the adapter-owned counters/publication record consumed
by :mod:`lumenplot_mpl.backend`. One :class:`_CanvasPublicationState`
instance per canvas owns a private :class:`threading.Lock` guarding a
monotonic generation counter and the last-published diagnostics tuple.

Publication is atomic: the diagnostics record is replaced only after a
successful external write, and any failed attempt clears previously
published diagnostics so stale fallback state is never reported.
"""

from __future__ import annotations

import threading
from typing import Any

from lumenplot_mpl.backend_types import (
    LumenPlotUnsupportedError,
    _INTERNAL_TOKEN,
)


class _CanvasPublicationState:
    """Thread-safe generation counter plus last-publication record.

    The lock covers only adapter-owned counters/publication state. It is
    never held while invoking a Matplotlib callback or a caller-supplied
    writer, preserving the reentrancy boundary in ADR 0015.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation = 0
        self._last_diagnostics: tuple = ()

    @property
    def generation(self) -> int:
        """Read-only observation of the current generation counter."""
        with self._lock:
            return self._generation

    @property
    def last_diagnostics(self) -> tuple:
        """Read-only observation of the last published diagnostics."""
        with self._lock:
            return tuple(self._last_diagnostics)

    def begin_attempt(self) -> int:
        """Spend one generation and clear the previous observation."""
        with self._lock:
            generation = self._generation + 1
            self._generation = generation
            self._last_diagnostics = ()
            return generation

    def ensure_current(self, generation: int) -> None:
        """Reject a result superseded by a newer render attempt."""
        with self._lock:
            current = self._generation
        if current != generation:
            raise LumenPlotUnsupportedError(
                "render attempt became stale before publication",
                code=_INTERNAL_TOKEN,
                generation=generation,
            )

    def publish(self, generation: int, result: Any) -> None:
        """Atomically publish diagnostics for the current generation."""
        with self._lock:
            if self._generation != generation:
                raise LumenPlotUnsupportedError(
                    "render attempt became stale before publication",
                    code=_INTERNAL_TOKEN,
                    generation=generation,
                )
            self._last_diagnostics = tuple(result.diagnostics)

    def clear_if_current(self, generation: int) -> None:
        """Clear failed-attempt state without clobbering newer output."""
        with self._lock:
            if self._generation == generation:
                self._last_diagnostics = ()

    def clear(self) -> None:
        """Clear diagnostics for a rejected output request."""
        with self._lock:
            self._last_diagnostics = ()
