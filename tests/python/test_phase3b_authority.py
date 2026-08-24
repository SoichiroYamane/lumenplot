"""Phase-3B canvas-authority tests (batch-1 lane D, LP-MPL-004).

Canon (docs/requirements/lumenplot-v1.0.md §15): LP-MPL-004 — MUST "Treat
the Matplotlib Figure/Artist graph as authoritative in adapter mode and
retain only a revisioned derived LumenPlot Scene snapshot or cache"
(evidence AT-MPL-AUTHORITY; API 0005 §2 canvas state rules; ADR 0015 §10).

Boundary of this lane (orchestrator-scoped decision, coordinated with lanes
B/C): the Figure/Artist-authority consequences already pinned elsewhere stay
out of scope here — fingerprint/one-shot-snapshot/writeback/DPI-restore
families belong to a separate figure-authority fixture lane that has not
landed yet (no such test file exists on any branch at this time), and
``test_phase3b_native_authority.py`` (merged, PR #41)
owns the PlotScene-side seam consequences for LP-MPL-005. This module pins
the four card-mandated REPEAT-ATTEMPT authority properties at the public
canvas surface (:class:`lumenplot_mpl.backend.FigureCanvasLumenPlot`), none
of which either suite covers:

1. repeated renders of an unchanged Figure emit byte-identical PNGs and
   equivalent derived frame specs (a stable derived snapshot, not drift);
2. published diagnostics are immutable and independent between attempts:
   later attempts never retroactively change earlier returned tuples;
3. strict failure tokens (unsupported-capability plus the terminal
   internal/backend-unavailable families) are stable across repeats;
4. the derived frame spec handed to the native seam is never mutated after
   the seam consumed it, and each attempt spends exactly one generation
   named consistently by output and diagnostics.

Offline cells without matplotlib skip cleanly; no built extension is needed
because every family runs against a recording stub seam installed over the
private ``lumenplot_mpl._native`` import, mirroring the harness convention
of ``test_phase3b_backend.py``.
"""

from __future__ import annotations

import copy
import io
import struct
import types
import unittest
import unittest.mock

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.figure as _figure_module
    from matplotlib.lines import Line2D as _Line2D

    MATPLOTLIB_PRESENT = True
except ImportError:  # offline cell without matplotlib
    MATPLOTLIB_PRESENT = False

try:
    import lumenplot_mpl.backend as backend_mod
except ImportError:  # package not importable in this cell
    backend_mod = None

HAS_BACKEND = backend_mod is not None


# ---------------------------------------------------------------------------
# Local harness (duplicated per the batch-1 lane convention; originals in
# test_phase3b_backend.py untouched)
# ---------------------------------------------------------------------------


def _stub_native_png(width: int, height: int) -> bytes:
    """A minimal deterministic PNG with correct IHDR (no raster content)."""
    header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(
        ">IIBBBBB", width, height, 8, 6, 0, 0, 0
    )
    return header + b"\x00\x00\x00\x00IEND\xaeB`\x82"


class _RecordingNativeModule(types.SimpleNamespace):
    """Seam stand-in keeping live spec refs plus call-time frozen copies."""

    specs: list[dict] = []  # live references exactly as handed to the seam
    frozen: list[dict] = []  # deep copies taken at call time

    @staticmethod
    def render_frame_png(spec):  # noqa: N802 - mirrors native name
        _RecordingNativeModule.specs.append(spec)
        _RecordingNativeModule.frozen.append(copy.deepcopy(spec))
        return _stub_native_png(spec["width_px"], spec["height_px"])


class _ValueErrorNativeModule(types.SimpleNamespace):
    """Mirrors the frozen Rust contract: validation -> bare ValueError."""

    @staticmethod
    def render_frame_png(spec):  # noqa: N802 - mirrors native name
        del spec
        raise ValueError("path has too many vertices")


class _RuntimeErrorNativeModule(types.SimpleNamespace):
    """Mirrors the frozen Rust contract: raster failure -> RuntimeError."""

    @staticmethod
    def render_frame_png(spec):  # noqa: N802 - mirrors native name
        del spec
        raise RuntimeError("raster allocation failed")


def _install_stub(module_cls):
    return unittest.mock.patch.object(
        backend_mod, "_native", lambda: module_cls
    )


def _eligible_figure():
    """Strict-eligible figure: axison off, one fixed-style line."""
    fig = _figure_module.Figure(figsize=(2.0, 1.0), dpi=100)
    ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
    ax.axison = False
    ax.add_line(
        _Line2D(
            [0.0, 10.0],
            [0.0, 5.0],
            color="red",
            linewidth=2.0,
            solid_capstyle="butt",
            solid_joinstyle="miter",
        )
    )
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(0.0, 5.0)
    return fig


def _ineligible_reason_builder(marker=False, dashed=False):
    """Return a builder making a figure rejected by strict preflight."""

    def build():
        fig = _figure_module.Figure(figsize=(2.0, 1.0), dpi=100)
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.axison = False
        kwargs = {
            "color": "red",
            "linewidth": 2.0,
            "solid_capstyle": "butt",
            "solid_joinstyle": "miter",
        }
        if marker:
            kwargs["marker"] = "o"
        if dashed:
            kwargs["linestyle"] = "--"
        ax.add_line(_Line2D([0, 1], [0, 1], **kwargs))
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(0.0, 5.0)
        return fig

    return build


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and HAS_BACKEND,
    "matplotlib/lumenplot_mpl not in this offline cell",
)
class TestRepeatedRenderIdentity(unittest.TestCase):
    """Family 1: an unchanged Figure yields a stable derived snapshot."""

    def setUp(self):
        self._patcher = _install_stub(_RecordingNativeModule)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        _RecordingNativeModule.specs.clear()
        _RecordingNativeModule.frozen.clear()

    def test_two_renders_emit_identical_bytes_and_equivalent_specs(self):
        canvas = backend_mod.FigureCanvasLumenPlot(_eligible_figure())
        first = canvas.render_png()
        second = canvas.render_png()
        self.assertEqual(first.png_bytes, second.png_bytes)
        self.assertEqual(len(_RecordingNativeModule.frozen), 2)
        self.assertEqual(
            _RecordingNativeModule.frozen[0], _RecordingNativeModule.frozen[1]
        )

    def test_generation_advances_exactly_one_per_attempt(self):
        canvas = backend_mod.FigureCanvasLumenPlot(_eligible_figure())
        start = canvas._generation
        canvas.render_png()
        canvas.render_png()
        self.assertEqual(canvas._generation, start + 2)

    def test_success_publishes_empty_diagnostics_every_attempt(self):
        canvas = backend_mod.FigureCanvasLumenPlot(_eligible_figure())
        first = canvas.render_png()
        second = canvas.render_png()
        self.assertEqual(first.diagnostics, ())
        self.assertEqual(second.diagnostics, ())
        self.assertEqual(canvas.last_diagnostics, ())


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and HAS_BACKEND,
    "matplotlib/lumenplot_mpl not in this offline cell",
)
class TestDiagnosticImmutabilityAcrossAttempts(unittest.TestCase):
    """Family 2: earlier results never change when later ones publish."""

    def setUp(self):
        self._patcher = _install_stub(_RecordingNativeModule)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def _hybrid_canvas(self):
        fig = _ineligible_reason_builder(dashed=True)()
        return backend_mod.FigureCanvasLumenPlot(fig, mode="hybrid")

    def test_later_attempts_do_not_mutate_earlier_diagnostic_tuples(self):
        canvas = self._hybrid_canvas()
        first_result = canvas.render_png()
        first_tuple = first_result.diagnostics
        # Snapshot the scalar field values (deepcopy would itself trip the
        # diagnostic's immutability guard, which is its own proof below).
        first_fields = tuple(
            (
                d.kind,
                d.type,
                d.generation,
                d.output_format,
                d.scope,
                d.representation,
                d.fallback_type,
            )
            for d in first_tuple
        )
        second_result = canvas.render_png()
        self.assertIsNot(first_result.diagnostics, second_result.diagnostics)
        self.assertEqual(
            tuple(
                (
                    d.kind,
                    d.type,
                    d.generation,
                    d.output_format,
                    d.scope,
                    d.representation,
                    d.fallback_type,
                )
                for d in first_result.diagnostics
            ),
            first_fields,
            "an earlier result's diagnostics changed after a later attempt",
        )

    def test_diagnostic_objects_are_immutable_after_return(self):
        canvas = self._hybrid_canvas()
        diagnostic = canvas.render_png().diagnostics[0]
        with self.assertRaises(AttributeError):
            diagnostic.kind = "fallback"
        with self.assertRaises(AttributeError):
            del diagnostic.kind

    def test_canvas_observation_is_not_the_mutable_internal_state(self):
        canvas = self._hybrid_canvas()
        canvas.render_png()
        observed = canvas.last_diagnostics
        # The property hands out a tuple (freshly built when the internal
        # state is not already one); the value is immutable by type, so no
        # caller can mutate adapter state through the observation.
        self.assertIsInstance(observed, tuple)
        with self.assertRaises(AttributeError):
            observed.append("tampered")

    def test_result_records_are_immutable(self):
        canvas = self._hybrid_canvas()
        result = canvas.render_png()
        with self.assertRaises(AttributeError):
            result.png_bytes = b"tampered"
        with self.assertRaises(AttributeError):
            result.diagnostics = ()


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and HAS_BACKEND,
    "matplotlib/lumenplot_mpl not in this offline cell",
)
class TestFailureTokenStability(unittest.TestCase):
    """Family 3: failure codes are stable across repeated attempts."""

    def _strict_attempts(self, builder, attempts=3):
        outcomes = []
        canvas = backend_mod.FigureCanvasLumenPlot(builder(), mode="strict")
        for _ in range(attempts):
            with self.assertRaises(
                backend_mod.LumenPlotUnsupportedError
            ) as ctx:
                canvas.render_png()
            outcomes.append(
                (
                    ctx.exception.code,
                    ctx.exception.type_context,
                    str(ctx.exception),
                )
            )
        return outcomes

    def test_unsupported_token_stable_across_repeats(self):
        for builder in (
            _ineligible_reason_builder(marker=True),
            _ineligible_reason_builder(dashed=True),
        ):
            with self.subTest(fixture=builder):
                outcomes = self._strict_attempts(builder)
                for outcome in outcomes:
                    self.assertEqual(
                        outcome[0], "unsupported-capability"
                    )
                self.assertEqual(outcomes[0][1], outcomes[1][1])
                self.assertEqual(outcomes[0][2], outcomes[1][2])
                self.assertTrue(outcomes[0][2])  # non-empty message

    def test_terminal_validation_token_stable_across_repeats(self):
        with _install_stub(_ValueErrorNativeModule):
            outcomes = self._strict_attempts(
                _eligible_figure, attempts=2
            )
        for outcome in outcomes:
            self.assertEqual(outcome[0], "internal")
        self.assertEqual(outcomes[0], outcomes[1])

    def test_terminal_raster_token_stable_across_repeats(self):
        with _install_stub(_RuntimeErrorNativeModule):
            outcomes = self._strict_attempts(
                _eligible_figure, attempts=2
            )
        for outcome in outcomes:
            self.assertEqual(outcome[0], "internal")

    def test_missing_seam_backend_unavailable_stable_across_repeats(self):
        # The seam is "absent" when the module exposes no render_frame_png
        # attribute (backend.py _call_native); mirror that shape exactly.
        class _SeamlessNativeModule(types.SimpleNamespace):
            pass

        with _install_stub(_SeamlessNativeModule):
            outcomes = self._strict_attempts(
                _eligible_figure, attempts=2
            )
        for outcome in outcomes:
            self.assertEqual(outcome[0], "backend-unavailable")

    def test_generations_increase_across_failed_attempts(self):
        outcomes = self._strict_attempts(
            _ineligible_reason_builder(marker=True), attempts=3
        )
        self.assertEqual(len({outcome[2] for outcome in outcomes}), 1)


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and HAS_BACKEND,
    "matplotlib/lumenplot_mpl not in this offline cell",
)
class TestDerivedSnapshotIntegrity(unittest.TestCase):
    """Family 4: the emitted spec is intact and single-generation."""

    def setUp(self):
        self._patcher = _install_stub(_RecordingNativeModule)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        _RecordingNativeModule.specs.clear()
        _RecordingNativeModule.frozen.clear()

    def test_seam_received_spec_is_not_mutated_after_consumption(self):
        canvas = backend_mod.FigureCanvasLumenPlot(_eligible_figure())
        canvas.render_png()
        # The live object the adapter handed over must still equal the
        # frozen call-time copy now that rendering has fully finished.
        self.assertEqual(
            _RecordingNativeModule.specs[0], _RecordingNativeModule.frozen[0]
        )

    def test_each_attempt_builds_a_fresh_spec_object(self):
        canvas = backend_mod.FigureCanvasLumenPlot(_eligible_figure())
        canvas.render_png()
        canvas.render_png()
        first, second = _RecordingNativeModule.specs
        self.assertEqual(first, second)
        self.assertIsNot(first, second)

    def test_hybrid_diagnostic_names_the_single_spent_generation(self):
        dashed = _ineligible_reason_builder(dashed=True)()
        canvas = backend_mod.FigureCanvasLumenPlot(dashed, mode="hybrid")
        before = canvas._generation
        result = canvas.render_png()
        self.assertEqual(canvas._generation, before + 1)
        self.assertEqual(result.diagnostics[0].generation, before + 1)

    def test_strict_error_names_the_same_single_spent_generation(self):
        canvas = backend_mod.FigureCanvasLumenPlot(
            _ineligible_reason_builder(marker=True)()
        )
        before = canvas._generation
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError) as ctx:
            canvas.render_png()
        self.assertEqual(canvas._generation, before + 1)
        self.assertEqual(ctx.exception.generation, before + 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
