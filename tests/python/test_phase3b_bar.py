"""LP-FUNC-033 bar rendering — Agg-parity contract tests.

Test-first lane card t_d4ceb6af (W1-bar), the second W1 serial lane
stacked on LP-FUNC-032 (fill, t_93a0421c). The quality oracle is the
matplotlib Agg backend: geometry parity via public getters, pixel parity
on decoded RGBA8 output, and Agg-identical style resolution.

The four LP-MPL-020 eligibility-extension artifacts land in one commit:

1. whitelist entry: ``matplotlib.patches.Rectangle`` (``Axes.bar`` and
   ``Axes.barh`` bars) joins Line2D, Polygon, and
   FillBetweenPolyCollection;
2. collector-trace expectation: bars arrive through the existing
   ``patch`` artist group (``Patch.draw`` opens one ``patch`` group for
   every Patch subclass), so no new trace shape is required — this is
   asserted here as executable evidence;
3. style contract: face/edge/alpha resolution rules documented here as
   executable assertions (Agg-identical single alpha application,
   transparent default edge draws no stroke despite a positive line
   width, explicit edgecolor strokes with that color);
4. fixtures: strict-mode native rendering compared against Agg golden
   geometry plus decoded-pixel evidence for representative workloads
   (simple bar, negative height, bottom baseline, stacked two-series).

Offline cells without matplotlib skip cleanly. Pixel fixtures require the
real native seam and skip when it is absent; spec-level fixtures use the
stub seam like the existing backend suite.
"""

from __future__ import annotations

import io
import struct
import unittest
import zlib

try:
    import matplotlib
except ModuleNotFoundError:  # offline cells: matplotlib evidence is a later slice
    matplotlib = None
else:
    matplotlib.use("module://matplotlib.backends.backend_agg")  # baseline only

    from matplotlib import figure  # noqa: E402
    from matplotlib.lines import Line2D  # noqa: E402
    from matplotlib.patches import Polygon  # noqa: E402
    from matplotlib.patches import Rectangle  # noqa: E402

MATPLOTLIB_PRESENT = matplotlib is not None


class _BackendProxy:
    """Lazily resolve lumenplot_mpl.backend; raises if matplotlib is absent."""

    def __getattr__(self, name):
        import importlib

        return getattr(importlib.import_module("lumenplot_mpl.backend"), name)


backend_mod = _BackendProxy()


def _stub_native_png(width: int, height: int) -> bytes:
    """A minimal deterministic PNG with correct IHDR (no raster content)."""
    header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(
        ">IIBBBBB", width, height, 8, 6, 0, 0, 0
    )
    return header + b"\x00\x00\x00\x00IEND\xaeB`\x82"


def _load_backend():
    import importlib

    return importlib.import_module("lumenplot_mpl.backend")


class _StubNativeModule(__import__("types").SimpleNamespace):
    """Stand-in for ``lumenplot_mpl._native`` recording the last spec."""

    last_spec: dict | None = None

    @staticmethod
    def render_frame_png(spec):  # noqa: N802 - mirrors native name
        _StubNativeModule.last_spec = spec
        return _stub_native_png(spec["width_px"], spec["height_px"])


def _install_stub_native():
    import types
    import unittest.mock

    real = (
        backend_mod
        if isinstance(backend_mod, types.ModuleType)
        else __import__("lumenplot_mpl.backend", fromlist=["_native"])
    )
    return unittest.mock.patch.object(real, "_native", lambda: _StubNativeModule)


def _bar_canvas(figsize=(2.0, 1.0), dpi=100, build=None, decorate=False):
    """Strict-eligible figure whose only content is bar rectangles.

    Mirrors ``_fill_canvas`` of the fill suite: explicit fixed style
    surface for any lines (ADR 0015 §5); axison stays off unless a
    fixture explicitly opts into decorated mode.
    """
    if not MATPLOTLIB_PRESENT:
        raise unittest.SkipTest("matplotlib not in this offline cell")
    fig = figure.Figure(figsize=figsize, dpi=dpi)
    canvas = _load_backend().FigureCanvasLumenPlot(fig)
    ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
    ax.axison = bool(decorate)
    if build is not None:
        build(ax)
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(-3.0, 5.0)
    return fig, canvas, ax


# ---------------------------------------------------------------------------
# 1. whitelist entry (LP-MPL-020 artifact 1)
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestBarWhitelist(unittest.TestCase):
    """Rectangle (the Axes.bar surface) is an eligible artist class."""

    def setUp(self):
        self.patcher = _install_stub_native()
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_bar_is_strict_eligible(self):
        fig, canvas, ax = _bar_canvas(
            build=lambda ax: ax.bar([2], [4], width=1.0, color="red"),
        )
        result = canvas.render_png()
        self.assertEqual(result.diagnostics, ())
        patch = ax.patches[0]
        self.assertIsInstance(patch, Rectangle)

    def test_barh_is_strict_eligible(self):
        # barh stores its geometry in Rectangle form too; eligibility is
        # class-based, not call-based.
        fig, canvas, ax = _bar_canvas(
            build=lambda ax: ax.barh([2], [4], color="green"),
        )
        result = canvas.render_png()
        self.assertEqual(result.diagnostics, ())
        patch = ax.patches[0]
        self.assertIsInstance(patch, Rectangle)

    def test_line_and_bar_coexist_in_one_axes(self):
        def build(ax):
            ax.bar([3], [6], width=2.0, color="red")
            ax.add_line(Line2D([1, 9], [1, 3], color="blue", linewidth=2.0,
                               solid_capstyle="butt",
                               solid_joinstyle="miter"))

        fig, canvas, ax = _bar_canvas(build=build)
        result = canvas.render_png()
        self.assertEqual(result.diagnostics, ())

    def test_unsupported_patch_class_still_rejected(self):
        # The whitelist grows by exact class family: a Polygon stays on the
        # LP-FUNC-032 lane and every other Patch subclass remains outside.
        from matplotlib.patches import Ellipse

        def build(ax):
            ax.add_patch(Ellipse((5, 1), 4, 2, facecolor="red"))

        fig, canvas, ax = _bar_canvas(build=build)
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError) as ctx:
            canvas.render_png()
        self.assertIn("Ellipse", str(ctx.exception))

    def test_rotated_rectangle_is_refused(self):
        # angle != 0 leaves the axis-aligned rectangle contract; the refusal
        # must be explicit rather than a silent skew approximation.
        def build(ax):
            ax.add_patch(Rectangle((2, 0), 3, 4, angle=30.0,
                                   facecolor="red"))

        fig, canvas, ax = _bar_canvas(build=build)
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError) as ctx:
            canvas.render_png()
        self.assertIn("angle", str(ctx.exception))


# ---------------------------------------------------------------------------
# 2. collector-trace expectation (LP-MPL-020 artifact 2)
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestBarCollectorTrace(unittest.TestCase):
    """Bars reach the spec through the existing patch-shaped trace."""

    def setUp(self):
        self.patcher = _install_stub_native()
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_bar_command_geometry_matches_public_affine(self):
        fig, canvas, ax = _bar_canvas(
            build=lambda ax: ax.bar([2, 8], [4, -2], width=1.0,
                                    color="steelblue"),
        )
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        commands = [c for c in spec["commands"] if not c.get("decoration")]
        self.assertEqual(len(commands), 2)
        bbox = ax.get_window_extent()
        xlim, ylim = ax.get_xlim(), ax.get_ylim()

        def pxx(x):
            return bbox.x0 + (x - xlim[0]) / (xlim[1] - xlim[0]) * bbox.width

        def pxy(y):
            return bbox.y0 + (y - ylim[0]) / (ylim[1] - ylim[0]) * bbox.height

        for command, (cx, height) in zip(commands, ((2, 4), (8, -2))):
            vertices = list(command["vertices"])
            codes = list(command["codes"])
            # One closed loop: MOVETO, three LINETO, CLOSEPOLY.
            self.assertEqual(codes[0], int(matplotlib.path.Path.MOVETO))
            self.assertEqual(codes[-1], int(matplotlib.path.Path.CLOSEPOLY))
            real = [v for v, c in zip(vertices, codes)
                    if c != int(matplotlib.path.Path.CLOSEPOLY)]
            self.assertEqual(len(real), 4)
            # Corners repeat edge coordinates: dedupe to the two
            # distinct extents per axis.
            xs = sorted({v[0] for v in real})
            ys = sorted({v[1] for v in real})
            self.assertEqual(len(xs), 2)
            self.assertEqual(len(ys), 2)
            self.assertAlmostEqual(xs[0], pxx(cx - 0.5), places=6)
            self.assertAlmostEqual(xs[1], pxx(cx + 0.5), places=6)
            lo, hi = sorted((pxy(0.0), pxy(height)))
            self.assertAlmostEqual(ys[0], lo, places=6)
            self.assertAlmostEqual(ys[1], hi, places=6)

    def test_bottom_baseline_shifts_the_anchor(self):
        def build(ax):
            ax.bar([4], [2], bottom=1.0, width=2.0, color="teal")

        fig, canvas, ax = _bar_canvas(build=build)
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        commands = [c for c in spec["commands"] if not c.get("decoration")]
        self.assertEqual(len(commands), 1)
        bbox = ax.get_window_extent()
        xlim, ylim = ax.get_xlim(), ax.get_ylim()

        def pxy(y):
            return bbox.y0 + (y - ylim[0]) / (ylim[1] - ylim[0]) * bbox.height

        ys = sorted({v[1] for v in commands[0]["vertices"][:4]})
        self.assertEqual(len(ys), 2)
        self.assertAlmostEqual(ys[0], pxy(1.0), places=6)
        self.assertAlmostEqual(ys[1], pxy(3.0), places=6)

    def test_stacked_two_series_produces_two_commands(self):
        def build(ax):
            ax.bar([2, 7], [3, 4], width=1.0, color="steelblue")
            ax.bar([2, 7], [1, 2], bottom=[3, 4], width=1.0,
                   color="orange")

        fig, canvas, ax = _bar_canvas(build=build)
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        commands = [c for c in spec["commands"] if not c.get("decoration")]
        self.assertEqual(len(commands), 4)

    def test_zero_height_bar_is_skipped_like_agg(self):
        # A zero-area rectangle paints nothing in Agg (no coverage); the
        # adapter skips it instead of emitting an empty stroke/fill.
        def build(ax):
            ax.bar([2, 7], [0, 4], width=1.0, color="steelblue")

        fig, canvas, ax = _bar_canvas(build=build)
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        commands = [c for c in spec["commands"] if not c.get("decoration")]
        self.assertEqual(len(commands), 1)


# ---------------------------------------------------------------------------
# 3. style contract (LP-MPL-020 artifact 3)
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestBarStyleContract(unittest.TestCase):
    """Face/edge/alpha resolution equals Agg's Patch semantics.

    Contract (documented here as executable rules):

    - face color: the resolved Patch facecolor reaches the spec as
      ``fill_rgba`` exactly as ``_rgba8(facecolor)`` quantizes it — one
      alpha application total, matching Agg's single blend;
    - edge: matplotlib's Rectangle default resolves to a fully
      transparent edge ('none') even though the line width defaults to
      1.0 — such a bar carries ``stroke_rgba=None`` exactly like Agg,
      which inks nothing for a zero-alpha stroke;
    - an explicit nonzero-alpha edgecolor with positive width strokes
      the outline with that color;
    - cap/join resolve butt/miter (Rectangle defaults, observed via the
      collector probe).
    """

    def setUp(self):
        self.patcher = _install_stub_native()
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _content_command(self, build):
        fig, canvas, ax = _bar_canvas(build=build)
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        commands = [c for c in spec["commands"] if not c.get("decoration")]
        self.assertEqual(len(commands), 1)
        return commands[0]

    def test_face_color_reaches_fill_rgba(self):
        command = self._content_command(
            lambda ax: ax.bar([2], [4], width=1.0, color="red"),
        )
        self.assertEqual(list(command["fill_rgba"]), [255, 0, 0, 255])
        self.assertIsNone(command["stroke_rgba"])

    def test_alpha_applies_once_to_face(self):
        command = self._content_command(
            lambda ax: ax.bar([2], [4], width=1.0, color="orange",
                              alpha=0.35),
        )
        fill = list(command["fill_rgba"])
        self.assertEqual(fill[:3], [255, 165, 0])
        self.assertEqual(fill[3], round(0.35 * 255))
        self.assertIsNone(command["stroke_rgba"])

    def test_explicit_edge_color_and_width(self):
        command = self._content_command(
            lambda ax: ax.bar([2], [4], width=1.0, facecolor="red",
                              edgecolor="blue", linewidth=3.0),
        )
        self.assertEqual(list(command["fill_rgba"]), [255, 0, 0, 255])
        self.assertIsNotNone(command["stroke_rgba"])
        self.assertEqual(list(command["stroke_rgba"]), [0, 0, 255, 255])
        self.assertEqual(command["line_width_pt"], 3.0)
        self.assertEqual(command["cap"], "butt")
        self.assertEqual(command["join"], "miter")

    def test_default_transparent_edge_draws_no_stroke_despite_width(self):
        # Probe evidence: a plain ax.bar Rectangle carries edgecolor
        # (0,0,0,0) with linewidth 1.0. Agg inks nothing; neither do we.
        command = self._content_command(
            lambda ax: ax.bar([2], [4], width=1.0, facecolor="red"),
        )
        self.assertIsNone(command["stroke_rgba"])
        self.assertEqual(command["line_width_pt"], 1.0)

    def test_zero_width_edge_draws_no_stroke(self):
        command = self._content_command(
            lambda ax: ax.bar([2], [4], width=1.0, facecolor="red",
                              edgecolor="blue", linewidth=0.0),
        )
        self.assertIsNone(command["stroke_rgba"])

    def test_edge_alpha_matches_agg_gc(self):
        command = self._content_command(
            lambda ax: ax.bar([2], [4], width=1.0, facecolor="red",
                              edgecolor="black", alpha=0.5, linewidth=2.0),
        )
        stroke = list(command["stroke_rgba"])
        self.assertEqual(stroke[:3], [0, 0, 0])
        self.assertEqual(stroke[3], round(0.5 * 255))


# ---------------------------------------------------------------------------
# 4. pixel parity fixtures vs Agg (LP-MPL-020 artifact 4)
# ---------------------------------------------------------------------------


def _decode_rgba8(png_bytes: bytes):
    """Decode an RGBA8 PNG (stdlib only). Returns (width, height, rows)."""
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    idat = b""
    width = height = None
    while pos < len(png_bytes):
        (length,) = struct.unpack(">I", png_bytes[pos:pos + 4])
        ctype = png_bytes[pos + 4:pos + 8]
        data = png_bytes[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB",
                                                                 data[:10])
            assert bit_depth == 8 and color_type == 6
        elif ctype == b"IDAT":
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

    rows = []
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


def _require_real_seam():
    try:
        from lumenplot_mpl import _native  # noqa: F401
    except (ImportError, AttributeError):
        raise unittest.SkipTest("native seam not built in this environment")
    if not hasattr(_native, "render_frame_png"):
        raise unittest.SkipTest("render_frame_png not present yet")


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestBarPixelParity(unittest.TestCase):
    """Native raster evidence against decoded-pixel expectations.

    Golden values are pinned live against matplotlib Agg output for the
    identical figure (geometry parity oracle, parent W1 plan): bars are
    axis-aligned rectangles, so both rasterizers see identical coverage
    ramps and interiors are byte-exact under the Agg-compat blend mode.
    """

    maxDiff = None

    def setUp(self):
        _require_real_seam()

    def _agg_reference(self, build):
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.axison = False
        build(ax)
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(-3.0, 5.0)
        FigureCanvasAgg(fig)
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=100)
        return buffer.getvalue()

    def _render_native(self, build):
        from lumenplot_mpl.backend import FigureCanvasLumenPlot

        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = FigureCanvasLumenPlot(fig)
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.axison = False
        build(ax)
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(-3.0, 5.0)
        return canvas.render_png()

    def _assert_pixel_parity(self, build, *, tol=0, min_exact_fraction=0.95,
                             worst_cap=32):
        """Decoded-pixel parity with a numerically defined AA allowance.

        Axis-aligned rectangle edges have no slanted AA phase difference:
        interiors and edges must be byte-exact except where a bar boundary
        lands inside a pixel row/column, where tiny-skia's 4x4 subsample
        estimator may disagree with Agg's analytic coverage by one quantum
        (32/255 per channel — the same ratified ramp as LP-FUNC-032).
        """
        agg_bytes = self._agg_reference(build)
        result = self._render_native(build)
        aw, ah, arows = _decode_rgba8(agg_bytes)
        nw, nh, nrows = _decode_rgba8(result.png_bytes)
        self.assertEqual((aw, ah), (nw, nh))
        import numpy as np

        flat_agg = np.frombuffer(b"".join(arows), dtype=np.uint8).astype(
            int
        ).reshape(-1, 4)
        flat_nat = np.frombuffer(b"".join(nrows), dtype=np.uint8).astype(
            int
        ).reshape(-1, 4)
        deltas = np.abs(flat_agg - flat_nat).max(axis=1)
        self.assertLessEqual(int(deltas.max()), worst_cap,
                             f"pixel delta {int(deltas.max())} exceeds "
                             f"the AA ramp cap {worst_cap}")
        within = int((deltas <= tol).sum())
        fraction = within / deltas.size
        self.assertGreaterEqual(
            fraction, min_exact_fraction,
            f"only {fraction:.4f} of pixels within tolerance {tol} "
            f"(need {min_exact_fraction})",
        )

    def test_simple_bar_interior_and_edges(self):
        self._assert_pixel_parity(
            lambda ax: ax.bar([2, 8], [4, 2], width=1.0, color="red"),
        )

    def test_negative_height_bar(self):
        self._assert_pixel_parity(
            lambda ax: ax.bar([3], [-2.5], width=2.0, color="purple"),
        )

    def test_bottom_baseline_bar(self):
        self._assert_pixel_parity(
            lambda ax: ax.bar([5], [3], bottom=-2.0, width=2.0,
                              color="teal"),
        )

    def test_stacked_two_series_bars(self):
        self._assert_pixel_parity(lambda ax: (
            ax.bar([3, 7], [3, 4], width=1.5, color="steelblue", lw=0),
            ax.bar([3, 7], [1, 2], bottom=[3, 4], width=1.5,
                   color="orange", lw=0),
        ))


def _decode_rgba8(png_bytes: bytes):
    """Decode an RGBA8 PNG (stdlib only). Returns (width, height, rows)."""
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    idat = b""
    width = height = None
    while pos < len(png_bytes):
        (length,) = struct.unpack(">I", png_bytes[pos:pos + 4])
        ctype = png_bytes[pos + 4:pos + 8]
        data = png_bytes[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB",
                                                                 data[:10])
            assert bit_depth == 8 and color_type == 6
        elif ctype == b"IDAT":
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

    rows = []
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


def _require_real_seam():
    try:
        from lumenplot_mpl import _native  # noqa: F401
    except (ImportError, AttributeError):
        raise unittest.SkipTest("native seam not built in this environment")
    if not hasattr(_native, "render_frame_png"):
        raise unittest.SkipTest("render_frame_png not present yet")


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestBarPixelParity(unittest.TestCase):
    """Native raster evidence vs decoded Agg pixels (LP-FUNC-033).

    Mirrors the LP-FUNC-032 fixture contract: interiors must match within
    ``tol`` per channel for at least ``min_exact_fraction`` of the frame,
    and no pixel may exceed ``worst_cap``. Bar edges are axis aligned, so
    the AA surface is smaller than the fill lane's slanted polygons -- the
    same ratified 4x4 subsample quantum (32/255) caps the boundary ramp.
    """

    maxDiff = None

    def setUp(self):
        _require_real_seam()

    def _agg_reference(self, build):
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.axison = False
        build(ax)
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(-3.0, 5.0)
        FigureCanvasAgg(fig)
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=100)
        return buffer.getvalue()

    def _render_native(self, build):
        from lumenplot_mpl.backend import FigureCanvasLumenPlot

        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = FigureCanvasLumenPlot(fig)
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.axison = False
        build(ax)
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(-3.0, 5.0)
        return canvas.render_png()

    def _assert_pixel_parity(self, build, *, tol=0, min_exact_fraction=0.95,
                             worst_cap=32):
        """Decoded-pixel parity against the Agg oracle.

        Defaults are stricter than the fill lane because every bar edge is
        horizontal or vertical: interiors byte-exact, boundaries inside the
        ratified one-subsample-quantum ramp.
        """
        agg_bytes = self._agg_reference(build)
        result = self._render_native(build)
        aw, ah, arows = _decode_rgba8(agg_bytes)
        nw, nh, nrows = _decode_rgba8(result.png_bytes)
        self.assertEqual((aw, ah), (nw, nh))
        import numpy as np

        flat_agg = np.frombuffer(b"".join(arows), dtype=np.uint8).astype(
            int
        ).reshape(-1, 4)
        flat_nat = np.frombuffer(b"".join(nrows), dtype=np.uint8).astype(
            int
        ).reshape(-1, 4)
        deltas = np.abs(flat_agg - flat_nat).max(axis=1)
        self.assertLessEqual(int(deltas.max()), worst_cap,
                             f"pixel delta {int(deltas.max())} exceeds "
                             f"the AA ramp cap {worst_cap}")
        within = int((deltas <= tol).sum())
        fraction = within / deltas.size
        self.assertGreaterEqual(
            fraction, min_exact_fraction,
            f"only {fraction:.4f} of pixels within tolerance {tol} "
            f"(need {min_exact_fraction})",
        )

    def test_simple_bars_interior_and_edges(self):
        self._assert_pixel_parity(
            lambda ax: ax.bar([2, 8], [4, -2], width=1.0,
                              color="steelblue"),
        )

    def test_negative_and_stacked_bars(self):
        def build(ax):
            ax.bar([2, 7], [3, 4], width=1.0, color="steelblue")
            ax.bar([2, 7], [1, -2], bottom=[3, 0], width=1.0,
                   color="orange")

        self._assert_pixel_parity(build)

    def test_alpha_bar_blend(self):
        def build(ax):
            ax.bar([3], [4], width=1.5, color="green", alpha=0.5)
            ax.bar([7], [2], bottom=-3, width=1.5, color="orange",
                   alpha=0.35)

        self._assert_pixel_parity(build)

    def test_bottom_baseline_bars(self):
        self._assert_pixel_parity(
            lambda ax: ax.bar([4], [2], bottom=1.0, width=2.0,
                              color="teal"),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
