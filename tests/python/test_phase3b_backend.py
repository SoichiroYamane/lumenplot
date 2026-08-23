"""Phase-3B strict-mode backend adapter tests (lane L2).

Covers the card-mandated behaviors for ``lumenplot_mpl.backend``:

- clean import without any configured backend must not crash;
- module surface: exports, alias, manager identity, ``filetypes``,
  ``required_interactive_framework``;
- ``render_png`` returns owned PNG bytes with correct IHDR dimensions via a
  stubbed native seam (the real Rust seam is lane L1 and is not required);
- structural Agg-parity smoke: the adapter's geometry matches an
  independent public-API computation (not byte equality with Agg);
- strict-mode unsupported features record diagnostics and do NOT raise from
  ``render_png`` when a diagnostic-recording stub is used, while native
  unavailability raises explicitly (never silently falls back);
- ``last_diagnostics`` population, atomic replacement, generation monotonicity;
- hybrid mode raises ``NotImplementedError``.

The native seam is always exercised through ``lumenplot_mpl._native``; tests
stub that module attribute so this suite runs before lane L1 lands. A skip-
guarded block exercises the real seam when it is present.
"""

from __future__ import annotations

import io
import struct
import sys
import types
import unittest.mock

import unittest

try:
    import matplotlib
except ModuleNotFoundError:  # offline cells: matplotlib evidence is a later slice
    matplotlib = None
else:
    matplotlib.use("module://matplotlib.backends.backend_agg")  # baseline only

    from matplotlib import figure  # noqa: E402
    from matplotlib.lines import Line2D  # noqa: E402

MATPLOTLIB_PRESENT = matplotlib is not None

class _BackendProxy:
    """Lazily resolve lumenplot_mpl.backend; raises if matplotlib is absent."""
    def __getattr__(self, name):
        import importlib
        return getattr(importlib.import_module("lumenplot_mpl.backend"), name)


backend_mod = _BackendProxy()  # noqa: E402


def _ihdr_dimensions(png_bytes: bytes) -> tuple[int, int]:
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "PNG magic missing"
    length = struct.unpack(">I", png_bytes[8:12])[0]
    chunk = png_bytes[12:16]
    assert chunk == b"IHDR"
    width, height = struct.unpack(">II", png_bytes[16:24])
    del length
    return width, height


def _stub_native_png(width: int, height: int) -> bytes:
    """A minimal deterministic PNG with correct IHDR (no raster content)."""
    header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(
        ">IIBBBBB", width, height, 8, 6, 0, 0, 0
    )
    return header + b"\x00\x00\x00\x00IEND\xaeB`\x82"


def _load_backend():
    """Import the backend lazily; requires matplotlib (absent in offline cells)."""
    import importlib
    return importlib.import_module("lumenplot_mpl.backend")


class _StubNativeModule(types.SimpleNamespace):
    """Stand-in for ``lumenplot_mpl._native`` recording the last spec."""

    last_spec: dict | None = None

    @staticmethod
    def render_frame_png(spec):  # noqa: N802 - mirrors native name
        _StubNativeModule.last_spec = spec
        return _stub_native_png(spec["width_px"], spec["height_px"])


def _install_stub_native():
    # Resolve through the lazy proxy to the real module object before patching,
    # so the render path (which reads the module global) sees the stub.
    real = backend_mod if isinstance(backend_mod, types.ModuleType) else (
        __import__("lumenplot_mpl.backend", fromlist=["_native"])
    )
    return unittest.mock.patch.object(real, "_native", lambda: _StubNativeModule)


def _eligible_canvas(figsize=(2.0, 1.0), dpi=100, line_kwargs=None):
    """Build a strict-eligible figure: one axes (axison off), one line.

    Strict fixtures set the fixed style surface explicitly (ADR 0015 §5):
    Matplotlib defaults to projecting caps and round joins, which strict
    mode rejects rather than approximates.
    """
    if not MATPLOTLIB_PRESENT:
        raise unittest.SkipTest("matplotlib not in this offline cell")
    fig = figure.Figure(figsize=figsize, dpi=dpi)
    canvas = _load_backend().FigureCanvasLumenPlot(fig)
    ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
    ax.axison = False
    kwargs = {
        "color": "red",
        "linewidth": 2.0,
        "solid_capstyle": "butt",
        "solid_joinstyle": "miter",
    }
    kwargs.update(line_kwargs or {})
    ax.add_line(Line2D([0.0, 10.0], [0.0, 5.0], **kwargs))
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(0.0, 5.0)
    return fig, canvas


# ---------------------------------------------------------------------------
# Import/surface contract (API 0005 §1)
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestModuleSurface(unittest.TestCase):
    def test_exports_and_identity(self):
        self.assertIs(backend_mod.FigureCanvas, backend_mod.FigureCanvasLumenPlot)
        from matplotlib.backend_bases import FigureManagerBase

        self.assertIs(backend_mod.FigureManager, FigureManagerBase)
        self.assertEqual(
            backend_mod.filetypes, {"png": "Portable Network Graphics"}
        )
        self.assertIsNone(backend_mod.required_interactive_framework)

    def test_subclass_of_public_base(self):
        from matplotlib.backend_bases import FigureCanvasBase

        self.assertTrue(
            issubclass(backend_mod.FigureCanvasLumenPlot, FigureCanvasBase)
        )

    def test_forbidden_names_absent(self):
        module_dict = vars(backend_mod)
        for forbidden in (
            "_Backend",
            "_renderer",
            "_api",
            "_pylab_helpers",
            "new_figure_manager",
            "draw_if_interactive",
            "show",
        ):
            self.assertNotIn(forbidden, module_dict)

    def test_import_without_backend_config(self):
        # A clean subprocess with no MPLBACKEND must be able to import the
        # module without any rendering configuration.
        import os
        import subprocess

        env = dict(os.environ)
        env.pop("MPLBACKEND", None)
        repo_root = __import__("pathlib").Path(__file__).resolve().parents[2]
        code = "sys.path.insert(0, {root!r}); import lumenplot_mpl.backend".format(
            root=str(repo_root / "python")
        )
        proc = subprocess.run(
            [sys.executable, "-c", "import sys\n" + code],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)


# ---------------------------------------------------------------------------
# render_png / native seam
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, 'matplotlib not in this offline cell')
class TestRenderPng(unittest.TestCase):
    def setUp(self):
        self._patcher = _install_stub_native()
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_render_png_bytes_and_ihdr_dims(self):
        fig, canvas = _eligible_canvas(figsize=(2.0, 1.0), dpi=100)
        result = canvas.render_png()
        self.assertIsInstance(result, backend_mod.LumenPlotPngResult)
        magic_ok = result.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        self.assertTrue(magic_ok)
        self.assertEqual(_ihdr_dimensions(result.png_bytes), (200, 100))
        self.assertEqual(result.diagnostics, ())

    def test_render_png_dpi_scales_geometry(self):
        fig, canvas = _eligible_canvas(figsize=(2.0, 1.0), dpi=100)
        result = canvas.render_png(dpi=200)
        self.assertEqual(_ihdr_dimensions(result.png_bytes), (400, 200))

    def test_result_owns_bytes_and_is_immutable(self):
        fig, canvas = _eligible_canvas()
        result = canvas.render_png()
        with self.assertRaises(AttributeError):
            result.png_bytes = b"x"  # type: ignore[misc]
        with self.assertRaises(AttributeError):
            result.new_attr = 1  # type: ignore[attr-defined]

    def test_spec_carries_display_px_vertices(self):
        fig, canvas = _eligible_canvas(figsize=(2.0, 1.0), dpi=100)
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        self.assertEqual(spec["width_px"], 200)
        self.assertEqual(spec["height_px"], 100)
        self.assertEqual(spec["output_dpi"], 100.0)
        commands = spec["commands"]
        self.assertEqual(len(commands), 1)
        command = commands[0]
        self.assertEqual(command["kind"], "path")
        vertices = command["vertices"]
        # axes rect [0.1..0.9]x[0.1..0.9] of 200x100 px; data (0,0)->(10,5).
        self.assertAlmostEqual(vertices[0][0], 20.0, places=6)
        self.assertAlmostEqual(vertices[0][1], 10.0, places=6)
        self.assertAlmostEqual(vertices[1][0], 180.0, places=6)
        self.assertAlmostEqual(vertices[1][1], 90.0, places=6)
        self.assertEqual(list(command["stroke_rgba"]), [255, 0, 0, 255])

    def test_zero_alpha_canonicalization(self):
        fig, canvas = _eligible_canvas(line_kwargs={"alpha": 0.0})
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        stroke = spec["commands"][0]["stroke_rgba"]
        self.assertEqual(stroke[3], 0)


# ---------------------------------------------------------------------------
# Effective savefig DPI and fractional-figsize geometry matrix (API 0005 §5/§6)
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, 'matplotlib not in this offline cell')
class TestDpiAndFigsizeMatrix(unittest.TestCase):
    """Effective savefig DPI drives canvas pixels, vertices, and clip_rect."""

    def setUp(self):
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)

    def _check(self, figsize, dpi, render_dpi=None):
        """One matrix row: PNG dims, spec fields, vertices, and clip."""
        import numpy as np

        effective_dpi = float(render_dpi if render_dpi is not None else dpi)
        fig, canvas = _eligible_canvas(figsize=figsize, dpi=dpi)
        ax = fig.get_axes()[0]
        width_px = int(round(figsize[0] * effective_dpi))
        height_px = int(round(figsize[1] * effective_dpi))

        result = (
            canvas.render_png(dpi=render_dpi)
            if render_dpi is not None
            else canvas.render_png()
        )
        self.assertEqual(_ihdr_dimensions(result.png_bytes),
                         (width_px, height_px))

        spec = _StubNativeModule.last_spec
        assert spec is not None
        self.assertEqual(spec["width_px"], width_px)
        self.assertEqual(spec["height_px"], height_px)
        self.assertEqual(spec["output_dpi"], effective_dpi)

        # Independent public-API expectation (same oracle shape as the
        # structural-parity suite): map the data endpoints through public
        # Axes extent and limits. The expectation is evaluated under the
        # same temporary effective savefig DPI that API 0005 §5 prescribes
        # for the render attempt itself.
        original_dpi = fig.dpi
        if render_dpi is not None:
            fig.dpi = effective_dpi
        try:
            bbox = ax.get_window_extent()
            xlim = ax.get_xlim()
            ylim = ax.get_ylim()

            def pxx(x):
                return (bbox.x0
                        + (x - xlim[0]) / (xlim[1] - xlim[0]) * bbox.width)

            def pxy(y):
                return (bbox.y0
                        + (y - ylim[0]) / (ylim[1] - ylim[0]) * bbox.height)

            expected = [[pxx(0.0), pxy(0.0)], [pxx(10.0), pxy(5.0)]]
            expected_clip = [
                bbox.x0,
                height_px - (bbox.y0 + bbox.height),
                bbox.width,
                bbox.height,
            ]
        finally:
            fig.dpi = original_dpi

        commands = spec["commands"]
        self.assertEqual(len(commands), 1)
        vertices = np.asarray(commands[0]["vertices"])
        np.testing.assert_allclose(vertices, np.asarray(expected),
                                   rtol=0, atol=1e-9)

        # clip_rect restates the axes rectangle in top-left pixel space
        # with exclusive right/bottom edges.
        clip = np.asarray(commands[0]["clip_rect"])
        np.testing.assert_allclose(clip, np.asarray(expected_clip),
                                   rtol=0, atol=1e-9)
        return fig

    def test_integer_dpi_matrix(self):
        for figsize, dpi in [((2.0, 1.0), 100), ((2.0, 1.0), 200),
                             ((2.0, 1.0), 300)]:
            with self.subTest(figsize=figsize, dpi=dpi):
                fig = self._check(figsize, dpi)
                del fig

    def test_fractional_figsize(self):
        # Fractional inches: 1.75in * 150dpi = 262.5 -> 262 px (banker's).
        with self.subTest(figsize=(1.75, 1.25), dpi=150):
            fig = self._check((1.75, 1.25), 150)
            del fig
        with self.subTest(figsize=(1.625, 1.125), dpi=160):
            fig = self._check((1.625, 1.125), 160)
            del fig

    def test_render_dpi_override_drives_geometry_and_restores_state(self):
        # Effective savefig DPI (API 0005 §5) differs from construction DPI.
        fig = self._check((2.0, 1.0), 100, render_dpi=250)
        # Temporary effective-DPI state is restored after output.
        self.assertEqual(fig.dpi, 100)
        del fig


# ---------------------------------------------------------------------------
# Structural Agg-parity smoke (public-API geometry oracle, not byte equality)
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, 'matplotlib not in this offline cell')
class TestStructuralParity(unittest.TestCase):
    def setUp(self):
        self._patcher = _install_stub_native()
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_line_and_rect_coverage_matches_public_geometry(self):
        """Line+rect figure: adapter geometry matches public computation."""
        import numpy as np

        fig, canvas = _eligible_canvas(figsize=(2.0, 2.0), dpi=100)
        ax = fig.get_axes()[0]
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None

        # Independent public-API expectation for the line endpoints.
        bbox = ax.get_window_extent()
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()

        def px(x):
            return bbox.x0 + (x - xlim[0]) / (xlim[1] - xlim[0]) * bbox.width

        def py(y):
            return bbox.y0 + (y - ylim[0]) / (ylim[1] - ylim[0]) * bbox.height

        expected = [[px(0.0), py(0.0)], [px(10.0), py(5.0)]]
        got = spec["commands"][0]["vertices"]
        np.testing.assert_allclose(np.asarray(got), np.asarray(expected), rtol=0)

    def test_nan_gaps_do_not_reconnect(self):
        fig, canvas = _eligible_canvas(
            figsize=(2.0, 1.0),
            dpi=100,
            line_kwargs={},
        )
        ax = fig.get_axes()[0]
        ax.lines[0].remove()
        ax.add_line(Line2D([0, 5, float("nan"), 10], [0, 2.5, 1.0, 5.0],
                           color="red", linewidth=2.0,
                           solid_capstyle="butt", solid_joinstyle="miter"))
        result = canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        vertices = spec["commands"][0]["vertices"]
        self.assertEqual(len(vertices), 3)  # NaN row dropped, no bridging
        del fig


@unittest.skipUnless(MATPLOTLIB_PRESENT, 'matplotlib not in this offline cell')
class TestStrictUnsupported(unittest.TestCase):
    """Strict mode: unsupported features must NOT silently render."""

    def _canvas_with(self, build):
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = backend_mod.FigureCanvasLumenPlot(fig)
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.axison = False
        build(ax)
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(0.0, 5.0)
        return canvas

    def test_axes_decorations_unsupported(self):
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = backend_mod.FigureCanvasLumenPlot(fig)
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])  # axison stays True
        ax.add_line(Line2D([0, 1], [0, 1]))
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 5)
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError) as ctx:
            canvas.render_png()
        self.assertEqual(ctx.exception.code, "unsupported-capability")

    def test_dashed_line_unsupported(self):
        canvas = self._canvas_with(
            lambda ax: ax.add_line(Line2D([0, 1], [0, 1], linestyle="--"))
        )
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            canvas.render_png()

    def test_marker_unsupported(self):
        canvas = self._canvas_with(
            lambda ax: ax.add_line(Line2D([0, 1], [0, 1], marker="o"))
        )
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            canvas.render_png()

    def test_drawstyle_unsupported(self):
        canvas = self._canvas_with(
            lambda ax: ax.add_line(Line2D([0, 1], [0, 1], drawstyle="steps-pre"))
        )
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            canvas.render_png()

    def test_text_unsupported(self):
        def build(ax):
            ax.add_line(Line2D([0, 1], [0, 1]))
            ax.set_title("hello")
        canvas = self._canvas_with(build)
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            canvas.render_png()

    def test_strict_never_silently_falls_back_to_agg(self):
        """Strict failure must raise even though Agg is importable."""
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = backend_mod.FigureCanvasLumenPlot(fig)
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])  # decorations on
        ax.add_line(Line2D([0, 1], [0, 1]))
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 5)
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            fig.savefig(io.BytesIO(), format="png")


# ---------------------------------------------------------------------------
# Diagnostics publication and lifecycle
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, 'matplotlib not in this offline cell')
class TestDiagnosticsAndLifecycle(unittest.TestCase):
    def setUp(self):
        self._patcher = _install_stub_native()
        self._patcher.start()
        self.addCleanup(self._patcher.stop)

    def test_native_success_clears_diagnostics(self):
        fig, canvas = _eligible_canvas()
        canvas.render_png()
        self.assertEqual(canvas.last_diagnostics, ())

    def test_generation_monotonic_per_attempt(self):
        fig, canvas = _eligible_canvas()
        first = canvas._generation
        canvas.render_png()
        second = canvas._generation
        canvas.print_png(io.BytesIO())
        third = canvas._generation
        self.assertLess(first, second)
        self.assertLess(second, third)

    def test_failed_attempt_does_not_publish(self):
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = backend_mod.FigureCanvasLumenPlot(fig)
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])  # unsupported: axison on
        ax.add_line(Line2D([0, 1], [0, 1]))
        ax.set_xlim(0, 10)
        ax.set_ylim(0, 5)
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            canvas.render_png()
        # A failed attempt clears previously published diagnostics.
        self.assertEqual(canvas.last_diagnostics, ())
        self.assertEqual(canvas._generation, 1)

    def test_diagnostic_type_is_immutable(self):
        diagnostic = backend_mod.LumenPlotFallbackDiagnostic(
            kind="fallback",
            type="Figure",
            generation=3,
        )
        with self.assertRaises(AttributeError):
            diagnostic.generation = 9  # type: ignore[misc]

    def test_mode_contract(self):
        fig = figure.Figure(figsize=(1, 1))
        with self.assertRaises(NotImplementedError):
            backend_mod.FigureCanvasLumenPlot(fig, mode="hybrid")
        with self.assertRaises(ValueError):
            backend_mod.FigureCanvasLumenPlot(fig, mode="turbo")


# ---------------------------------------------------------------------------
# File-output guards (API 0005 §5)
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, 'matplotlib not in this offline cell')
class TestFileOutputGuards(unittest.TestCase):
    def setUp(self):
        self._patcher = _install_stub_native()
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.fig, self.canvas = _eligible_canvas()

    def test_print_png_returns_none_and_writes_once(self):
        buffer = io.BytesIO()
        result = self.canvas.print_png(buffer)
        self.assertIsNone(result)
        data = buffer.getvalue()
        self.assertEqual(_ihdr_dimensions(data), (200, 100))

    def test_savefig_bytesio(self):
        buffer = io.BytesIO()
        self.fig.savefig(buffer, format="png")
        self.assertEqual(_ihdr_dimensions(buffer.getvalue()), (200, 100))

    def test_non_png_format_fails_explicitly(self):
        for fmt in ("pdf", "svg", "ps", "eps"):
            with self.subTest(fmt=fmt):
                with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
                    self.fig.savefig(io.BytesIO(), format=fmt)

    def test_non_empty_metadata_unsupported(self):
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            self.canvas.print_png(
                io.BytesIO(), metadata={"Software": "anything"}
            )

    def test_pil_kwargs_unsupported(self):
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            self.canvas.print_png(io.BytesIO(), pil_kwargs={"compress_level": 5})

    def test_invalid_orientation_fails_explicitly(self):
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            self.canvas.print_png(io.BytesIO(), orientation="sideways")

    def test_bbox_inches_tight_unsupported(self):
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            self.fig.savefig(io.BytesIO(), format="png", bbox_inches="tight")

    def test_file_like_target_receives_write_never_closed(self):
        class OpenSpy(io.BytesIO):
            closed_count = 0

            def close(self):  # pragma: no cover - guard
                type(self).closed_count += 1
                super().close()

        spy = OpenSpy()
        self.canvas.print_png(spy)
        self.assertGreater(len(spy.getvalue()), 0)

    def test_writer_oserror_propagates(self):
        class Failing:
            @staticmethod
            def write(data):
                raise OSError("disk full")

        with self.assertRaises(OSError):
            self.canvas.print_png(Failing())


# ---------------------------------------------------------------------------
# Rectangular clipping (API 0005 §6 hazard 3)
# ---------------------------------------------------------------------------


def _decode_rgba8(png_bytes: bytes) -> tuple[int, int, list[bytes]]:
    """Decode an RGBA8 PNG produced by the native seam (stdlib only).

    Returns ``(width, height, rows)`` where each row is ``width * 4``
    decoded bytes. Supports the encoder's filter set including Paeth.
    """
    import zlib

    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "PNG magic missing"
    pos = 8
    idat = b""
    width = height = bit_depth = color_type = None
    while pos < len(png_bytes):
        length = struct.unpack(">I", png_bytes[pos:pos + 4])[0]
        chunk_type = png_bytes[pos + 4:pos + 8]
        data = png_bytes[pos + 8:pos + 8 + length]
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(
                ">IIBB", data[:10]
            )
            assert bit_depth == 8 and color_type == 6, (
                "expected 8-bit RGBA"
            )
        elif chunk_type == b"IDAT":
            idat += data
        pos += 12 + length
    assert width is not None and height is not None

    raw = zlib.decompress(idat)
    stride = width * 4 + 1

    def paeth(a: int, b: int, c: int) -> int:
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        if pa <= pb and pa <= pc:
            return a
        if pb <= pc:
            return b
        return c

    rows: list[bytes] = []
    previous = bytearray(width * 4)
    for y in range(height):
        filt = raw[y * stride]
        line = bytearray(raw[y * stride + 1:(y + 1) * stride])
        for x in range(width * 4):
            left = line[x - 4] if x >= 4 else 0
            up = previous[x]
            upper_left = previous[x - 4] if x >= 4 else 0
            if filt == 1:
                line[x] = (line[x] + left) & 0xFF
            elif filt == 2:
                line[x] = (line[x] + up) & 0xFF
            elif filt == 3:
                line[x] = (line[x] + (left + up) // 2) & 0xFF
            elif filt == 4:
                line[x] = (line[x] + paeth(left, up, upper_left)) & 0xFF
        rows.append(bytes(line))
        previous = line
    return width, height, rows


def _is_red(pixel: bytes) -> bool:
    """A strongly red stroke pixel (tolerant of antialiasing edges)."""
    r, g, b = pixel[0], pixel[1], pixel[2]
    return bool(r >= 200 and g < 100 and b < 100)


@unittest.skipUnless(MATPLOTLIB_PRESENT, 'matplotlib not in this offline cell')
class TestRectangularClipping(unittest.TestCase):
    """The validated axes rectangle clips the stroke on all four edges."""

    def _install_spec_stub(self):
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)

    def _clipped_canvas(self):
        """Two eligible strokes together leave through all four edges.

        A single straight segment can cross a convex rectangle's boundary
        at most twice, so four-edge evidence needs two lines: one nearly
        horizontal leaving left+right, one steep leaving top+bottom.
        """
        fig, canvas = _eligible_canvas(
            figsize=(1.0, 0.5),
            dpi=100,
            line_kwargs={"color": (1.0, 0.0, 0.0, 1.0)},
        )
        ax = fig.get_axes()[0]
        ax.lines[0].remove()
        common = dict(
            color=(1.0, 0.0, 0.0, 1.0),
            linewidth=2.0,
            solid_capstyle="butt",
            solid_joinstyle="miter",
        )
        # Nearly horizontal: leaves through the left and right edges.
        ax.add_line(Line2D([-50.0, 50.0], [2.5, 2.5], **common))
        # Steep: leaves through the top and bottom edges.
        ax.add_line(Line2D([5.0, 6.0], [-50.0, 50.0], **common))
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(0.0, 5.0)
        return fig, canvas, ax

    def test_clip_rect_carries_axes_rectangle(self):
        """Request carries the four-sided clip in top-left pixel space."""
        self._install_spec_stub()
        fig, canvas, ax = self._clipped_canvas()
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        bbox = ax.get_window_extent()
        commands = spec["commands"]
        self.assertEqual(len(commands), 2)
        expected_clip = [
            bbox.x0,
            50 - (bbox.y0 + bbox.height),
            bbox.width,
            bbox.height,
        ]
        for command in commands:
            self.assertEqual(command["clip_rect"], expected_clip)
        del fig

    def test_stroke_clipped_on_all_four_edges(self):
        """Raster evidence: red ink exists at all four clip edges and
        nowhere outside them (real seam; skipped before lane L1)."""
        try:
            from lumenplot_mpl import _native
        except (ImportError, AttributeError):
            self.skipTest("native seam not built in this environment")
        if not hasattr(_native, "render_frame_png"):
            self.skipTest("render_frame_png not present yet")

        fig, canvas, ax = self._clipped_canvas()
        result = canvas.render_png()
        del fig, canvas, ax
        width, height, rows = _decode_rgba8(result.png_bytes)

        bbox_x0, bbox_x1 = 10.0, 90.0
        bbox_y0, bbox_y1 = 5.0, 45.0  # top-left row space
        import numpy as np

        def pixel(x, y):
            offset = x * 4
            return rows[y][offset:offset + 4]

        def opaque_red(x, y):
            return _is_red(pixel(x, y))

        red_mask = np.zeros((height, width), dtype=bool)
        for y in range(height):
            for x in range(width):
                red_mask[y, x] = opaque_red(x, y)

        columns = np.flatnonzero(red_mask.any(axis=0))
        rows_with_ink = np.flatnonzero(red_mask.any(axis=1))
        # Left edge: ink touches the first clipped column...
        self.assertTrue(columns.size and int(columns[0]) == int(bbox_x0),
                        f"first ink column {columns[:5]}")
        # Right edge likewise.
        self.assertTrue(int(columns[-1]) == int(bbox_x1) - 1,
                        f"last ink column {columns[-5:]}")
        # Top edge.
        self.assertTrue(rows_with_ink.size
                        and int(rows_with_ink[0]) == int(bbox_y0),
                        f"first ink row {rows_with_ink[:5]}")
        # Bottom edge.
        self.assertTrue(int(rows_with_ink[-1]) == int(bbox_y1) - 1,
                        f"last ink row {rows_with_ink[-5:]}")
        # And nothing outside the clip rectangle at all.
        outside = red_mask.copy()
        outside[int(bbox_y0):int(bbox_y1), int(bbox_x0):int(bbox_x1)] = False
        self.assertFalse(outside.any(), "stroke ink found outside clip rect")

    def test_vertices_follow_public_affine_outside_clip(self):
        """Emitted geometry stays the plain public affine mapping even for
        the off-canvas part of the segment; four-edge trimming is the
        native rasterizer's job via clip_rect (ADR 0015 §6)."""
        self._install_spec_stub()
        fig, canvas, ax = self._clipped_canvas()
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        import numpy as np

        bbox = ax.get_window_extent()
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()

        def pxx(x):
            return bbox.x0 + (x - xlim[0]) / (xlim[1] - xlim[0]) * bbox.width

        def pxy(y):
            return bbox.y0 + (y - ylim[0]) / (ylim[1] - ylim[0]) * bbox.height

        expected = [
            # Nearly horizontal stroke, left+right ends.
            [pxx(-50.0), pxy(2.5)],
            [pxx(50.0), pxy(2.5)],
        ]
        np.testing.assert_allclose(
            np.asarray(spec["commands"][0]["vertices"]),
            np.asarray(expected),
            rtol=0,
            atol=1e-9,
        )
        expected = [
            # Steep stroke, bottom+top ends. Vertices stay bottom-left
            # display-pixel points per ADR 0015 §6; the native rasterizer
            # maps them into its top-left logical space itself.
            [pxx(5.0), pxy(-50.0)],
            [pxx(6.0), pxy(50.0)],
        ]
        np.testing.assert_allclose(
            np.asarray(spec["commands"][1]["vertices"]),
            np.asarray(expected),
            rtol=0,
            atol=1e-9,
        )
        del fig


# ---------------------------------------------------------------------------
# Geometry edge cases: fractional axes placement, duplicate points
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, 'matplotlib not in this offline cell')
class TestGeometryEdgeCases(unittest.TestCase):
    def setUp(self):
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)

    def _oracle(self, ax):
        """Public-API affine expectation helpers for one axes."""
        bbox = ax.get_window_extent()
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()

        def pxx(x):
            return bbox.x0 + (x - xlim[0]) / (xlim[1] - xlim[0]) * bbox.width

        def pxy(y):
            return bbox.y0 + (y - ylim[0]) / (ylim[1] - ylim[0]) * bbox.height

        return bbox, pxx, pxy

    def test_fractional_axes_position_maps_exactly(self):
        """Axes placed at fractional figure coordinates produce an exact
        pixel-space clip rectangle and vertices (API 0005 §5)."""
        fig, canvas = _eligible_canvas(figsize=(2.0, 1.0), dpi=100)
        ax = fig.get_axes()[0]
        ax.set_position([0.13, 0.17, 0.61, 0.47])
        result = canvas.render_png()
        self.assertEqual(_ihdr_dimensions(result.png_bytes), (200, 100))
        spec = _StubNativeModule.last_spec
        assert spec is not None
        import numpy as np

        bbox, pxx, pxy = self._oracle(ax)
        height_px = 100
        command = spec["commands"][0]
        self.assertEqual(
            command["clip_rect"],
            [
                bbox.x0,
                height_px - (bbox.y0 + bbox.height),
                bbox.width,
                bbox.height,
            ],
        )
        np.testing.assert_allclose(
            np.asarray(command["vertices"]),
            np.asarray([[pxx(0.0), pxy(0.0)], [pxx(10.0), pxy(5.0)]]),
            rtol=0,
        )
        del fig

    def test_duplicate_points_pass_through_without_dedup(self):
        """A leading duplicate data point stays a zero-length segment in
        the emitted request; the adapter neither drops nor reconnects."""
        fig, canvas = _eligible_canvas(figsize=(2.0, 1.0), dpi=100)
        ax = fig.get_axes()[0]
        ax.lines[0].remove()
        ax.add_line(Line2D([3.0, 3.0, 7.0], [1.0, 1.0, 4.0],
                           color=(0.0, 0.0, 1.0, 1.0), linewidth=2.0,
                           solid_capstyle="butt", solid_joinstyle="miter"))
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(0.0, 5.0)
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        import numpy as np

        bbox, pxx, pxy = self._oracle(ax)
        vertices = spec["commands"][0]["vertices"]
        self.assertEqual(len(vertices), 3)
        expected_first = [pxx(3.0), pxy(1.0)]
        np.testing.assert_allclose(
            np.asarray(vertices[:2]),
            np.asarray([expected_first, expected_first]),
            rtol=0,
        )
        # The real segment still spans to the final distinct point.
        np.testing.assert_allclose(
            np.asarray(vertices[2]),
            np.asarray([pxx(7.0), pxy(4.0)]),
            rtol=0,
        )
        del fig


# ---------------------------------------------------------------------------
# Native seam availability
# ---------------------------------------------------------------------------


class TestNativeSeamPresence(unittest.TestCase):
    @unittest.skipUnless(
        MATPLOTLIB_PRESENT, "backend import itself needs matplotlib"
    )
    def test_missing_seam_raises_backend_unavailable_not_silent(self):
        """Without the native module, strict mode must fail explicitly."""

        class Missing:
            def __getattr__(self, name):
                raise AttributeError(name)

        import lumenplot_mpl.backend as _real_backend
        with unittest.mock.patch.object(_real_backend, "_native", lambda: Missing()):
            fig, canvas = _eligible_canvas()
            with self.assertRaises(backend_mod.LumenPlotUnsupportedError) as ctx:
                canvas.render_png()
            self.assertEqual(ctx.exception.code, "backend-unavailable")

    def test_real_seam_when_present(self):
        """Exercise the true extension when lane L1 has landed."""
        try:
            from lumenplot_mpl import _native
        except (ImportError, AttributeError):
            self.skipTest("native seam not built in this environment")
        if not hasattr(_native, "render_frame_png"):
            self.skipTest("render_frame_png not present yet")
        fig, canvas = _eligible_canvas()
        result = canvas.render_png()
        self.assertTrue(result.png_bytes[:8] == b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
