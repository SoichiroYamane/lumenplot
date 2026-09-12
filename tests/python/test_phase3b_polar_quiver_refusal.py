"""Phase-3B fail-closed pins for polar axes and quiver artists.

Covers two requirement lanes that remain unimplemented in this slice:

- ``LP-FUNC-036`` (polar projection, ``AT-FUNC-POLAR``): polar transform
  fixtures are a v1 non-blocking Phase-5 item; the current adapter has no
  polar transform family and rectangular clip/background contracts assume
  rectangles (``docs/requirements/lumenplot-v1.0.md``,
  ``docs/requirements/traceability-v1.0.md`` row: Not implemented).
- ``LP-FUNC-038`` (quiver vector fields, ``AT-FUNC-QUIVER``): deterministic
  arrow-glyph geometry is a v1 non-blocking Phase-5 item; the current
  adapter has no quiver geometry/scaling surface (same sources, row:
  Not implemented).

These tests pin the existing fail-closed behavior only; they do not claim
support, Agg parity, tolerance, performance, platform, WCAG, or release
closure. Each representative class uses the documented public Matplotlib
construction (``Figure.add_subplot(projection="polar")`` with
``PolarAxes.plot``; ``Axes.quiver`` returning ``matplotlib.quiver.Quiver``)
and asserts the existing documented outcome: strict mode raises the stable
``unsupported-capability`` ``LumenPlotUnsupportedError`` before any target
write or native publication, and hybrid mode succeeds with the documented
whole-frame ``matplotlib-agg`` fallback plus exactly one
``unsupported-capability`` diagnostic, a valid nonzero PNG, and no silent
degradation.

All fixtures exercise the public ``lumenplot_mpl.backend`` surface with a
stubbed ``lumenplot_mpl._native`` seam, exactly like
``tests/python/test_phase3b_backend.py``; the real Rust seam is not
required here.

Governing sources: requirements ``LP-FUNC-036``/``LP-FUNC-038``, API 0005
§3/§5, ADR 0015 §4/§12, API 0002 taxonomy.
"""

from __future__ import annotations

import struct
import types
import unittest
import unittest.mock

try:
    import matplotlib
except ModuleNotFoundError:  # offline cells: matplotlib evidence is a later slice
    matplotlib = None
else:
    matplotlib.use("module://matplotlib.backends.backend_agg")  # baseline only

    from matplotlib import figure  # noqa: E402

try:
    import numpy
except ModuleNotFoundError:  # pragma: no cover - offline cells
    numpy = None

MATPLOTLIB_PRESENT = matplotlib is not None
NUMPY_PRESENT = numpy is not None


class _BackendProxy:
    """Lazily resolve lumenplot_mpl.backend; raises if matplotlib is absent."""

    def __getattr__(self, name):
        import importlib

        return getattr(importlib.import_module("lumenplot_mpl.backend"), name)


backend_mod = _BackendProxy()  # noqa: E402


def _stub_native_png(width: int, height: int) -> bytes:
    """A minimal deterministic PNG with correct IHDR (no raster content)."""
    header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(
        ">IIBBBBB", width, height, 8, 6, 0, 0, 0
    )
    return header + b"\x00\x00\x00\x00IEND\xaeB`\x82"


def _ihdr_dimensions(png_bytes: bytes) -> tuple[int, int]:
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "PNG magic missing"
    length = struct.unpack(">I", png_bytes[8:12])[0]
    chunk = png_bytes[12:16]
    assert chunk == b"IHDR", f"first chunk is {chunk!r}, expected IHDR"
    width, height = struct.unpack(">II", png_bytes[16:24])
    del length
    return width, height


class _StubNativeModule(types.SimpleNamespace):
    """Stand-in for ``lumenplot_mpl._native`` recording the last spec."""

    last_spec: dict | None = None

    @staticmethod
    def render_frame_png(spec):  # noqa: N802 - mirrors native name
        _StubNativeModule.last_spec = spec
        return _stub_native_png(spec["width_px"], spec["height_px"])


def _load_backend():
    """Import the backend lazily; requires matplotlib (absent in offline cells)."""
    import importlib

    return importlib.import_module("lumenplot_mpl.backend")


def _install_stub_native():
    real = backend_mod if isinstance(backend_mod, types.ModuleType) else (
        __import__("lumenplot_mpl.backend", fromlist=["_native"])
    )
    return unittest.mock.patch.object(real, "_native", lambda: _StubNativeModule)


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and NUMPY_PRESENT,
    "matplotlib/numpy not in this offline cell",
)
class TestPolarQuiverRefusal(unittest.TestCase):
    """Polar (LP-FUNC-036) and quiver (LP-FUNC-038) stay fail-closed.

    Strict mode raises the existing documented ``LumenPlotUnsupportedError``
    outcome; hybrid mode produces the documented whole-frame
    ``matplotlib-agg`` fallback with exactly one ``unsupported-capability``
    diagnostic, a valid nonzero PNG, and no silent degradation. Neither
    mode publishes to the native seam on these fixtures.
    """

    def setUp(self):
        _StubNativeModule.last_spec = None
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- strict: explicit failure, nothing published ---------------------

    def test_strict_polar_axes_refused(self):
        """LP-FUNC-036: a polar Axes fails explicitly in strict mode."""
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="strict")
        ax = fig.add_subplot(111, projection="polar")
        # Non-vacuous guard: the fixture really carries a PolarAxes.
        self.assertEqual(type(ax).__name__, "PolarAxes")
        ax.plot([0.0, 1.0, 2.0], [1.0, 2.0, 1.0])
        with self.assertRaises(
            backend_mod.LumenPlotUnsupportedError
        ) as ctx:
            canvas.render_png()
        self.assertEqual(ctx.exception.code, "unsupported-capability")
        self.assertEqual(ctx.exception.type_context, "PolarAxes")
        self.assertIn("PolarAxes", str(ctx.exception))
        # Nothing was published to the native seam and no fallback
        # diagnostics exist: the failure is the explicit result itself.
        self.assertIs(_StubNativeModule.last_spec, None)
        self.assertEqual(canvas.last_diagnostics, ())

    def test_strict_quiver_artist_refused(self):
        """LP-FUNC-038: a quiver artist fails explicitly in strict mode."""
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="strict")
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        X, Y = numpy.meshgrid([0.0, 1.0, 2.0], [0.0, 1.0])
        U = numpy.ones_like(X, dtype=float)
        V = numpy.zeros_like(Y, dtype=float)
        artist = ax.quiver(X, Y, U, V)
        # Non-vacuous guards: the fixture really carries a Quiver
        # collection artist.
        self.assertEqual(type(artist).__name__, "Quiver")
        self.assertIn(artist, list(ax.collections))
        with self.assertRaises(
            backend_mod.LumenPlotUnsupportedError
        ) as ctx:
            canvas.render_png()
        self.assertEqual(ctx.exception.code, "unsupported-capability")
        self.assertEqual(ctx.exception.type_context, "Quiver")
        self.assertIn("Quiver", str(ctx.exception))
        self.assertIs(_StubNativeModule.last_spec, None)
        self.assertEqual(canvas.last_diagnostics, ())

    # -- hybrid: one whole-frame fallback diagnostic, valid PNG ----------

    def test_hybrid_polar_falls_back_whole_frame(self):
        """LP-FUNC-036: hybrid renders polar via one whole-frame Agg fallback."""
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="hybrid")
        ax = fig.add_subplot(111, projection="polar")
        self.assertEqual(type(ax).__name__, "PolarAxes")
        ax.plot([0.0, 1.0, 2.0], [1.0, 2.0, 1.0])
        before_generation = canvas._generation
        result = canvas.render_png()
        self.assertEqual(canvas._generation, before_generation + 1)
        # No silent native publication: the whole frame went through Agg.
        self.assertIs(_StubNativeModule.last_spec, None)
        # Valid nonzero PNG at the requested geometry.
        self.assertEqual(result.png_bytes[:8], b"\x89PNG\r\n\x1a\n")
        width, height = _ihdr_dimensions(result.png_bytes)
        self.assertEqual((width, height), (200, 100))
        self.assertGreater(width, 0)
        self.assertGreater(height, 0)
        # Exactly one unsupported-capability diagnostic with the
        # documented whole-frame raster envelope.
        self.assertEqual(len(result.diagnostics), 1)
        diagnostic = result.diagnostics[0]
        self.assertIsInstance(
            diagnostic, backend_mod.LumenPlotFallbackDiagnostic
        )
        self.assertEqual(diagnostic.kind, "unsupported-capability")
        self.assertEqual(diagnostic.type, "PolarAxes")
        self.assertEqual(diagnostic.scope, "whole-frame")
        self.assertEqual(diagnostic.representation, "raster")
        self.assertEqual(diagnostic.output_format, "png")
        self.assertEqual(diagnostic.fallback_type, "matplotlib-agg")
        self.assertIsInstance(diagnostic.generation, int)
        self.assertGreaterEqual(diagnostic.generation, 1)
        self.assertEqual(diagnostic.generation, canvas._generation)
        self.assertEqual(canvas.last_diagnostics, result.diagnostics)

    def test_hybrid_quiver_falls_back_whole_frame(self):
        """LP-FUNC-038: hybrid renders quiver via one whole-frame Agg fallback."""
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="hybrid")
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        X, Y = numpy.meshgrid([0.0, 1.0, 2.0], [0.0, 1.0])
        U = numpy.ones_like(X, dtype=float)
        V = numpy.zeros_like(Y, dtype=float)
        artist = ax.quiver(X, Y, U, V)
        self.assertEqual(type(artist).__name__, "Quiver")
        self.assertIn(artist, list(ax.collections))
        before_generation = canvas._generation
        result = canvas.render_png()
        self.assertEqual(canvas._generation, before_generation + 1)
        self.assertIs(_StubNativeModule.last_spec, None)
        self.assertEqual(result.png_bytes[:8], b"\x89PNG\r\n\x1a\n")
        width, height = _ihdr_dimensions(result.png_bytes)
        self.assertEqual((width, height), (200, 100))
        self.assertGreater(width, 0)
        self.assertGreater(height, 0)
        self.assertEqual(len(result.diagnostics), 1)
        diagnostic = result.diagnostics[0]
        self.assertIsInstance(
            diagnostic, backend_mod.LumenPlotFallbackDiagnostic
        )
        self.assertEqual(diagnostic.kind, "unsupported-capability")
        self.assertEqual(diagnostic.type, "Quiver")
        self.assertEqual(diagnostic.scope, "whole-frame")
        self.assertEqual(diagnostic.representation, "raster")
        self.assertEqual(diagnostic.output_format, "png")
        self.assertEqual(diagnostic.fallback_type, "matplotlib-agg")
        self.assertIsInstance(diagnostic.generation, int)
        self.assertGreaterEqual(diagnostic.generation, 1)
        self.assertEqual(diagnostic.generation, canvas._generation)
        self.assertEqual(canvas.last_diagnostics, result.diagnostics)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
