"""Phase-3B compatibility-profile selection tests (batch-1 lane A, LP-MPL-003).

Canon (docs/requirements/lumenplot-v1.0.md §15): LP-MPL-003 — MUST "Offer the
fixed compatibility profiles ``strict-common-2d``, ``hybrid-explicit``, and
``accelerated-native``, with ``hybrid-explicit`` as the default and
``accelerated-native`` opt-in" (evidence AT-MPL-PROFILES; ADR 0015 §11 and
API 0005 "Requirement references": the shipped Phase-3B slice carries the
fixed trio with ``accelerated-native`` explicitly deferred out of the slice).

Boundary of this lane (orchestrator-scoped decision, shared with lanes B/C):
the full LP-MPL-003 clause is NOT closed here. The shipped constructor kwarg
is ``mode`` with values ``strict``/``hybrid`` (ADR 0015 §12 ordered delivery:
strict first, hybrid second, accelerated-native later). This module pins the
PYTHON-OBSERVABLE profile-selection consequences of that staged contract on
:class:`lumenplot_mpl.backend.FigureCanvasLumenPlot`:

- exactly the two shipped selection values are accepted, by name;
- every other value — including the not-yet-shipped ``accelerated-native``
  profile name — fails explicitly (ValueError) instead of approximating;
- ``hybrid`` is the shipped default and corresponds to the accepted
  ``hybrid-explicit`` profile;
- the selection is immutable after construction and observable via the
  public ``mode`` property;
- the selection actually drives dispatch: strict raises the stable
  ``unsupported-capability`` failure on ineligible content while hybrid
  converts the identical event into one structured whole-frame Agg fallback.

The ``mode`` -> canonical-profile-name mapping intent (which spelling maps to
``strict-common-2d`` versus ``hybrid-explicit``) is an unresolved public
signature and stays out of scope: nothing here asserts a mapping, only the
staged behavior above.

Offline cells without matplotlib skip cleanly; no native extension is needed
because the strict/hybrid dispatch divergence under test happens at the
adapter's preflight/fallback layer before any seam call.
"""

from __future__ import annotations

import io
import unittest

try:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.figure import Figure as _Figure  # noqa: F401 (guard use)

    MATPLOTLIB_PRESENT = True
except ImportError:  # offline cell without matplotlib
    MATPLOTLIB_PRESENT = False

try:
    import lumenplot_mpl.backend as backend_mod
except ImportError:  # package not importable in this cell
    backend_mod = None

HAS_BACKEND = backend_mod is not None


def _ineligible_figure():
    """A figure whose content is outside the strict whitelist (marker)."""
    from matplotlib.lines import Line2D

    fig = _Figure(figsize=(2.0, 1.0), dpi=100)
    ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
    ax.axison = False
    ax.add_line(Line2D([0, 1], [0, 1], marker="o"))
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(0.0, 5.0)
    return fig


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and HAS_BACKEND,
    "matplotlib/lumenplot_mpl not in this offline cell",
)
class TestProfileSelectionValues(unittest.TestCase):
    """Only the two shipped profile selectors exist, and they select."""

    def _canvas(self, mode):
        return backend_mod.FigureCanvasLumenPlot(_ineligible_figure(), mode=mode)

    def test_strict_profile_selects(self):
        canvas = self._canvas("strict")
        self.assertEqual(canvas.mode, "strict")

    def test_hybrid_profile_selects(self):
        canvas = self._canvas("hybrid")
        self.assertEqual(canvas.mode, "hybrid")

    def test_accelerated_native_is_rejected_not_approximated(self):
        # The third fixed LP-MPL-003 profile is explicitly deferred out of
        # this slice (ADR 0015 §12); selecting it must fail loudly rather
        # than silently degrade to another profile.
        with self.assertRaises(ValueError):
            self._canvas("accelerated-native")

    def test_unknown_profile_name_rejected(self):
        for bogus in ("turbo", "Strict", "HYBRID", "", "auto", None):
            with self.subTest(mode=bogus):
                with self.assertRaises(ValueError):
                    self._canvas(bogus)

    def test_error_message_names_the_allowed_values(self):
        # Diagnostic quality contract of the ValueError raised at
        # construction (backend.py __init__); message text itself is
        # non-contract but must carry the machine-relevant values.
        with self.assertRaises(ValueError) as ctx:
            self._canvas("warp")
        self.assertIn("strict", str(ctx.exception))
        self.assertIn("hybrid", str(ctx.exception))


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and HAS_BACKEND,
    "matplotlib/lumenplot_mpl not in this offline cell",
)
class TestStagedDefaultProfile(unittest.TestCase):
    """The shipped default is the accepted hybrid-explicit profile."""

    def test_default_selection_is_hybrid_explicit(self):
        canvas = backend_mod.FigureCanvasLumenPlot(_ineligible_figure())
        self.assertEqual(canvas.mode, "hybrid")

    def test_default_selection_dispatches_explicit_whole_frame_fallback(self):
        canvas = backend_mod.FigureCanvasLumenPlot(_ineligible_figure())
        result = canvas.render_png()
        self.assertEqual(len(result.diagnostics), 1)
        diagnostic = result.diagnostics[0]
        self.assertEqual(diagnostic.kind, "unsupported-capability")
        self.assertEqual(diagnostic.scope, "whole-frame")
        self.assertEqual(diagnostic.representation, "raster")
        self.assertEqual(diagnostic.fallback_type, "matplotlib-agg")

    def test_mode_kwarg_is_keyword_only(self):
        # The selector is keyword-only by signature; passing it positionally
        # must be a TypeError, not a silent positional swallow.
        figure = _ineligible_figure()
        with self.assertRaises(TypeError):
            backend_mod.FigureCanvasLumenPlot(figure, "hybrid")


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and HAS_BACKEND,
    "matplotlib/lumenplot_mpl not in this offline cell",
)
class TestSelectionIsImmutable(unittest.TestCase):
    """The chosen profile cannot be flipped after construction."""

    def test_mode_property_has_no_setter(self):
        # The public selection surface is the read-only ``mode`` property
        # (API 0005 §2: diagnostics/state live behind observation names);
        # there is deliberately no public way to flip profiles mid-flight.
        canvas = backend_mod.FigureCanvasLumenPlot(_ineligible_figure())
        with self.assertRaises(AttributeError):
            canvas.mode = "hybrid"


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and HAS_BACKEND,
    "matplotlib/lumenplot_mpl not in this offline cell",
)
class TestSelectionDrivesDispatch(unittest.TestCase):
    """The same ineligible frame produces profile-divergent outcomes."""

    def setUp(self):
        # No native seam stub needed: preflight rejects before any seam call,
        # which is exactly the adapter-layer behavior under test.
        self.fig = _ineligible_figure()

    def test_strict_raises_stable_token_before_any_write(self):
        canvas = backend_mod.FigureCanvasLumenPlot(self.fig, mode="strict")
        target = io.BytesIO()
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError) as ctx:
            canvas.render_png(target)
        self.assertEqual(ctx.exception.code, "unsupported-capability")
        self.assertEqual(target.getvalue(), b"", "strict wrote despite failure")

    def test_hybrid_converts_same_event_to_whole_frame_agg_fallback(self):
        canvas = backend_mod.FigureCanvasLumenPlot(self.fig, mode="hybrid")
        result = canvas.render_png()
        self.assertEqual(len(result.diagnostics), 1)
        diagnostic = result.diagnostics[0]
        self.assertIsInstance(
            diagnostic, backend_mod.LumenPlotFallbackDiagnostic
        )
        self.assertEqual(diagnostic.kind, "unsupported-capability")
        self.assertEqual(diagnostic.scope, "whole-frame")
        self.assertEqual(diagnostic.representation, "raster")
        self.assertEqual(diagnostic.fallback_type, "matplotlib-agg")
        self.assertTrue(result.png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_outcomes_stay_divergent_across_repeat_attempts(self):
        strict_canvas = backend_mod.FigureCanvasLumenPlot(
            _ineligible_figure(), mode="strict"
        )
        hybrid_canvas = backend_mod.FigureCanvasLumenPlot(
            _ineligible_figure(), mode="hybrid"
        )
        for attempt in range(2):
            with self.subTest(attempt=attempt):
                with self.assertRaises(
                    backend_mod.LumenPlotUnsupportedError
                ) as ctx:
                    strict_canvas.render_png()
                self.assertEqual(
                    ctx.exception.code, "unsupported-capability"
                )
                fallback = hybrid_canvas.render_png()
                self.assertEqual(len(fallback.diagnostics), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
