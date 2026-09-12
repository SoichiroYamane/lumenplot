"""Phase-3B fail-closed pins for general collections, images, and annotate.

Covers the remaining PARITY-MATRIX audit (t_055fc3d3 comment 1509, item 6)
refusal-test gaps. Polar/quiver (LP-FUNC-036/038) and errorbar/
secondary-axis (LP-FUNC-019/020) already carry dedicated pins on main;
this file adds only the still-missing per-class pins:

- ``LP-FUNC-017`` (scatter, ``AT-FUNC-SCATTER``): v1 non-blocking SHOULD,
  Phase-5; traceability row: Not implemented. ``Axes.scatter`` emits a
  ``PathCollection`` outside the static whitelist.
- ``LP-MPL-023`` (general collections, ``AT-MPL-COLLECTIONS``): SHOULD,
  post-v1 W-lane; traceability row: Not implemented. The contract allows
  each ineligible collection class to be refused explicitly, so this file
  pins ``LineCollection`` (standalone) and ``QuadMesh`` (``pcolormesh``)
  representatives next to the scatter ``PathCollection``.
- ``LP-FUNC-023`` (images, ``AT-REVIEW-SCOPE``): MAY, future; traceability
  row: Not implemented. ``Axes.imshow`` emits an ``AxesImage`` outside the
  static whitelist.
- ``LP-FUNC-012`` (annotations, ``AT-FUNC-ANNOTATION``): MUST, v1 Phase-2
  native Plot-State (separate surface, still Not implemented). On the
  adapter side only ``ax.text``/titles carry refusal pins today
  (``test_phase3b_backend.py`` Text checks); this file adds the dedicated
  ``ax.annotate`` (``Annotation``) pin.

Deliberately out of scope: ``LP-FUNC-032`` stackplot composition. The
audit lists it as an oracle-closure candidate, but a live probe on main
shows real ``Axes.stackplot`` emits eligible ``FillBetweenPolyCollection``
artists and strict mode renders them natively (stub seam called, zero
diagnostics) -- there is no refusal to pin, so no stackplot test belongs
in this fail-closed file. Disposition (oracle fixture lane vs. accepted
rendered behavior) is left to the architecture authority / commander.

These tests pin the existing fail-closed behavior only; they do not claim
support, Agg parity, tolerance, performance, platform, WCAG, or release
closure. Each representative class uses the documented public Matplotlib
construction and asserts the existing documented outcome: strict mode
raises the stable ``unsupported-capability`` ``LumenPlotUnsupportedError``
before any target write or native publication, and hybrid mode succeeds
with the documented whole-frame ``matplotlib-agg`` fallback plus exactly
one ``unsupported-capability`` diagnostic, a valid nonzero PNG, and no
silent degradation.

All fixtures exercise the public ``lumenplot_mpl.backend`` surface with a
stubbed ``lumenplot_mpl._native`` seam, exactly like
``tests/python/test_phase3b_polar_quiver_refusal.py``; the real Rust seam
is not required here.

Governing sources: requirements ``LP-FUNC-012``/``LP-FUNC-017``/
``LP-FUNC-023``/``LP-FUNC-032``/``LP-MPL-023``, API 0005 §3/§5, ADR 0015
§4/§12, API 0002 taxonomy.
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


def _check_hybrid_fallback_envelope(testcase, result, canvas, type_name):
    """Assert the documented whole-frame fallback envelope for one refusal."""
    testcase.assertEqual(result.png_bytes[:8], b"\x89PNG\r\n\x1a\n")
    width, height = _ihdr_dimensions(result.png_bytes)
    testcase.assertEqual((width, height), (200, 100))
    testcase.assertGreater(width, 0)
    testcase.assertGreater(height, 0)
    testcase.assertEqual(len(result.diagnostics), 1)
    diagnostic = result.diagnostics[0]
    testcase.assertIsInstance(
        diagnostic, backend_mod.LumenPlotFallbackDiagnostic
    )
    testcase.assertEqual(diagnostic.kind, "unsupported-capability")
    testcase.assertEqual(diagnostic.type, type_name)
    testcase.assertEqual(diagnostic.scope, "whole-frame")
    testcase.assertEqual(diagnostic.representation, "raster")
    testcase.assertEqual(diagnostic.output_format, "png")
    testcase.assertEqual(diagnostic.fallback_type, "matplotlib-agg")
    testcase.assertIsInstance(diagnostic.generation, int)
    testcase.assertGreaterEqual(diagnostic.generation, 1)
    testcase.assertEqual(diagnostic.generation, canvas._generation)
    testcase.assertEqual(canvas.last_diagnostics, result.diagnostics)


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and NUMPY_PRESENT,
    "matplotlib/numpy not in this offline cell",
)
class TestScatterPathCollectionRefusal(unittest.TestCase):
    """LP-FUNC-017 scatter stays fail-closed via PathCollection refusal."""

    def setUp(self):
        _StubNativeModule.last_spec = None
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_strict_scatter_refused(self):
        """LP-FUNC-017: ``Axes.scatter`` fails explicitly in strict mode."""
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="strict")
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.axison = False
        artist = ax.scatter([0.0, 1.0, 2.0], [0.0, 1.0, 0.0])
        # Non-vacuous guards: the fixture really carries a PathCollection.
        self.assertEqual(type(artist).__name__, "PathCollection")
        self.assertIn(artist, list(ax.collections))
        ax.set_xlim(0.0, 2.0)
        ax.set_ylim(-0.5, 1.5)
        with self.assertRaises(
            backend_mod.LumenPlotUnsupportedError
        ) as ctx:
            canvas.render_png()
        self.assertEqual(ctx.exception.code, "unsupported-capability")
        self.assertEqual(ctx.exception.type_context, "PathCollection")
        self.assertIn("PathCollection", str(ctx.exception))
        self.assertIs(_StubNativeModule.last_spec, None)
        self.assertEqual(canvas.last_diagnostics, ())

    def test_hybrid_scatter_falls_back_whole_frame(self):
        """LP-FUNC-017: hybrid renders scatter via one whole-frame fallback."""
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="hybrid")
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.axison = False
        artist = ax.scatter([0.0, 1.0, 2.0], [0.0, 1.0, 0.0])
        self.assertEqual(type(artist).__name__, "PathCollection")
        self.assertIn(artist, list(ax.collections))
        ax.set_xlim(0.0, 2.0)
        ax.set_ylim(-0.5, 1.5)
        before_generation = canvas._generation
        result = canvas.render_png()
        self.assertEqual(canvas._generation, before_generation + 1)
        # No silent native publication: the whole frame went through Agg.
        self.assertIs(_StubNativeModule.last_spec, None)
        _check_hybrid_fallback_envelope(
            self, result, canvas, "PathCollection"
        )


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and NUMPY_PRESENT,
    "matplotlib/numpy not in this offline cell",
)
class TestLineCollectionRefusal(unittest.TestCase):
    """LP-MPL-023: standalone LineCollection stays fail-closed."""

    def setUp(self):
        _StubNativeModule.last_spec = None
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _build(ax):
        from matplotlib.collections import LineCollection

        ax.axison = False
        artist = LineCollection([[(0.0, 0.0), (1.0, 1.0)],
                                 [(1.0, 0.0), (2.0, 1.0)]])
        ax.add_collection(artist)
        ax.set_xlim(0.0, 2.0)
        ax.set_ylim(0.0, 1.5)
        return artist

    def test_strict_line_collection_refused(self):
        """A standalone ``LineCollection`` fails explicitly in strict mode."""
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="strict")
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        artist = self._build(ax)
        # Non-vacuous guards: the fixture really carries a LineCollection.
        self.assertEqual(type(artist).__name__, "LineCollection")
        self.assertIn(artist, list(ax.collections))
        with self.assertRaises(
            backend_mod.LumenPlotUnsupportedError
        ) as ctx:
            canvas.render_png()
        self.assertEqual(ctx.exception.code, "unsupported-capability")
        self.assertEqual(ctx.exception.type_context, "LineCollection")
        self.assertIn("LineCollection", str(ctx.exception))
        self.assertIs(_StubNativeModule.last_spec, None)
        self.assertEqual(canvas.last_diagnostics, ())

    def test_hybrid_line_collection_falls_back_whole_frame(self):
        """Hybrid renders a LineCollection via one whole-frame fallback."""
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="hybrid")
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        artist = self._build(ax)
        self.assertEqual(type(artist).__name__, "LineCollection")
        self.assertIn(artist, list(ax.collections))
        before_generation = canvas._generation
        result = canvas.render_png()
        self.assertEqual(canvas._generation, before_generation + 1)
        self.assertIs(_StubNativeModule.last_spec, None)
        _check_hybrid_fallback_envelope(
            self, result, canvas, "LineCollection"
        )


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and NUMPY_PRESENT,
    "matplotlib/numpy not in this offline cell",
)
class TestQuadMeshRefusal(unittest.TestCase):
    """LP-MPL-023: QuadMesh (pcolormesh) stays fail-closed."""

    def setUp(self):
        _StubNativeModule.last_spec = None
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _build(ax):
        ax.axison = False
        artist = ax.pcolormesh(
            [0.0, 1.0, 2.0],
            [0.0, 1.0],
            numpy.array([[0.0, 1.0]]),
        )
        ax.set_xlim(0.0, 2.0)
        ax.set_ylim(0.0, 1.0)
        return artist

    def test_strict_quadmesh_refused(self):
        """A ``pcolormesh`` QuadMesh fails explicitly in strict mode."""
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="strict")
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        artist = self._build(ax)
        # Non-vacuous guards: the fixture really carries a QuadMesh.
        self.assertEqual(type(artist).__name__, "QuadMesh")
        self.assertIn(artist, list(ax.collections))
        with self.assertRaises(
            backend_mod.LumenPlotUnsupportedError
        ) as ctx:
            canvas.render_png()
        self.assertEqual(ctx.exception.code, "unsupported-capability")
        self.assertEqual(ctx.exception.type_context, "QuadMesh")
        self.assertIn("QuadMesh", str(ctx.exception))
        self.assertIs(_StubNativeModule.last_spec, None)
        self.assertEqual(canvas.last_diagnostics, ())

    def test_hybrid_quadmesh_falls_back_whole_frame(self):
        """Hybrid renders a QuadMesh via one whole-frame fallback."""
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="hybrid")
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        artist = self._build(ax)
        self.assertEqual(type(artist).__name__, "QuadMesh")
        self.assertIn(artist, list(ax.collections))
        before_generation = canvas._generation
        result = canvas.render_png()
        self.assertEqual(canvas._generation, before_generation + 1)
        self.assertIs(_StubNativeModule.last_spec, None)
        _check_hybrid_fallback_envelope(self, result, canvas, "QuadMesh")


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and NUMPY_PRESENT,
    "matplotlib/numpy not in this offline cell",
)
class TestAxesImageRefusal(unittest.TestCase):
    """LP-FUNC-023 images stay fail-closed via AxesImage refusal."""

    def setUp(self):
        _StubNativeModule.last_spec = None
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _build(ax):
        ax.axison = False
        return ax.imshow(numpy.array([[0.0, 1.0], [1.0, 0.0]]))

    def test_strict_imshow_refused(self):
        """LP-FUNC-023: ``Axes.imshow`` fails explicitly in strict mode."""
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="strict")
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        artist = self._build(ax)
        # Non-vacuous guards: the fixture really carries an AxesImage.
        self.assertEqual(type(artist).__name__, "AxesImage")
        self.assertIn(artist, list(ax.images))
        with self.assertRaises(
            backend_mod.LumenPlotUnsupportedError
        ) as ctx:
            canvas.render_png()
        self.assertEqual(ctx.exception.code, "unsupported-capability")
        self.assertEqual(ctx.exception.type_context, "AxesImage")
        self.assertIn("AxesImage", str(ctx.exception))
        self.assertIs(_StubNativeModule.last_spec, None)
        self.assertEqual(canvas.last_diagnostics, ())

    def test_hybrid_imshow_falls_back_whole_frame(self):
        """LP-FUNC-023: hybrid renders imshow via one whole-frame fallback."""
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="hybrid")
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        artist = self._build(ax)
        self.assertEqual(type(artist).__name__, "AxesImage")
        self.assertIn(artist, list(ax.images))
        before_generation = canvas._generation
        result = canvas.render_png()
        self.assertEqual(canvas._generation, before_generation + 1)
        self.assertIs(_StubNativeModule.last_spec, None)
        _check_hybrid_fallback_envelope(self, result, canvas, "AxesImage")


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and NUMPY_PRESENT,
    "matplotlib/numpy not in this offline cell",
)
class TestAnnotationRefusal(unittest.TestCase):
    """LP-FUNC-012: ``ax.annotate`` stays fail-closed via Annotation refusal.

    Existing pins cover ``ax.text``/titles (``Text``) only; no dedicated
    ``Annotation`` coverage exists on main.
    """

    def setUp(self):
        _StubNativeModule.last_spec = None
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _build(ax):
        ax.axison = False
        artist = ax.annotate(
            "note",
            xy=(1.0, 0.5),
            xytext=(1.5, 1.0),
            arrowprops=dict(arrowstyle="->"),
        )
        ax.set_xlim(0.0, 2.0)
        ax.set_ylim(0.0, 1.5)
        return artist

    def test_strict_annotate_refused(self):
        """An ``ax.annotate`` artist fails explicitly in strict mode."""
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="strict")
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        artist = self._build(ax)
        # Non-vacuous guards: the fixture really carries one Annotation
        # attached to these axes (not a plain Text).
        self.assertEqual(type(artist).__name__, "Annotation")
        self.assertEqual(artist.get_text(), "note")
        self.assertIs(artist.axes, ax)
        with self.assertRaises(
            backend_mod.LumenPlotUnsupportedError
        ) as ctx:
            canvas.render_png()
        self.assertEqual(ctx.exception.code, "unsupported-capability")
        self.assertEqual(ctx.exception.type_context, "Annotation")
        self.assertIn("Annotation", str(ctx.exception))
        self.assertIs(_StubNativeModule.last_spec, None)
        self.assertEqual(canvas.last_diagnostics, ())

    def test_hybrid_annotate_falls_back_whole_frame(self):
        """Hybrid renders an annotation via one whole-frame fallback."""
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="hybrid")
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        artist = self._build(ax)
        self.assertEqual(type(artist).__name__, "Annotation")
        self.assertEqual(artist.get_text(), "note")
        self.assertIs(artist.axes, ax)
        before_generation = canvas._generation
        result = canvas.render_png()
        self.assertEqual(canvas._generation, before_generation + 1)
        self.assertIs(_StubNativeModule.last_spec, None)
        _check_hybrid_fallback_envelope(self, result, canvas, "Annotation")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
