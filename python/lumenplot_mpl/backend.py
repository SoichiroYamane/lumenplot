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
path commands ahead of the axes' content lines. Since the T-lane
(PRAC-A-W) wire-up, visible non-empty major tick labels are eligible as
well: each label renders natively as one filled glyph-outline path
command built by the public ``lumenplot_mpl.textpath`` module from the
label's own ``FontProperties`` and resolved size. Since the B-2a (R2)
extension the visible non-empty ``xlabel``/``ylabel`` pair is eligible
as well: each label renders as explicit glyph path commands through the
same static text surface as tick labels. Visible minor tick
content, non-solid grid styles, an opaque axes facecolor, titles,
offset text, multi-line labels, labels with leading/trailing
whitespace, and math/TeX text remain outside the slice and raise.
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

import math
import os
from typing import Any

import matplotlib
from matplotlib.backend_bases import FigureCanvasBase, FigureManagerBase

from lumenplot_mpl.backend_attempt import _AttemptMixin
from lumenplot_mpl.backend_dispatch import _DispatchMixin
from lumenplot_mpl.backend_guards import _OutputGuardMixin
from lumenplot_mpl.backend_lifecycle import _LifecycleMixin
from lumenplot_mpl.backend_output import _OutputMixin
from lumenplot_mpl.backend_preflight import _EligibilityPreflight
from lumenplot_mpl.backend_publication import _PublicationMixin
from lumenplot_mpl.backend_state import _CanvasPublicationState
from lumenplot_mpl.backend_strict import _StrictRenderMixin, _native
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

# ---------------------------------------------------------------------------
# Canvas
# ---------------------------------------------------------------------------


class FigureCanvasLumenPlot(_DispatchMixin, _OutputGuardMixin, _PublicationMixin, _StrictRenderMixin, _AttemptMixin, _OutputMixin, _LifecycleMixin, FigureCanvasBase):
    """Public Phase-3B canvas with hybrid-explicit default and strict PNG mode.

    Adapter-owned state is limited to an immutable last-publication record
    (``last_diagnostics``) and a monotonic per-canvas generation counter.
    Publication is atomic: ``last_diagnostics`` is replaced only after a
    successful external write, and any failed attempt clears previously
    published diagnostics so stale fallback state is never reported.
    """

    filetypes = filetypes


#: Class alias fixed by API 0005 §1 (backend module identity).
FigureCanvas = FigureCanvasLumenPlot



# Keep provisional public record identities anchored at the backend module.
LumenPlotFallbackDiagnostic.__module__ = __name__
LumenPlotPngResult.__module__ = __name__
LumenPlotUnsupportedError.__module__ = __name__
