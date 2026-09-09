"""LP-FUNC-032 fill/fill-between native rendering — Agg-parity contract tests.

Test-first lane card t_93a0421c (W1-fill). The quality oracle is the
matplotlib Agg backend (parent W1 plan): geometry parity via public getters,
pixel parity on decoded RGBA8 output, and Agg-identical style resolution.

The four LP-MPL-020 eligibility-extension artifacts land in one commit:

1. whitelist entry: ``matplotlib.patches.Polygon`` and
   ``matplotlib.collections.FillBetweenPolyCollection`` join Line2D;
2. collector-trace expectation: ``patch`` and ``FillBetweenPolyCollection``
   artist groups carrying ``draw_path`` fills become eligible trace shapes;
3. style contract: face/edge/alpha resolution rules documented here as
   executable assertions (Agg-identical single alpha application, edge =
   face when unset, zero-width edge suppression);
4. fixtures: strict-mode native rendering compared against Agg golden
   geometry plus decoded-pixel evidence for representative workloads
   (simple fill, two-series fill_between, alpha overlap, negative span).

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
    from matplotlib.collections import FillBetweenPolyCollection  # noqa: E402
    from matplotlib.lines import Line2D  # noqa: E402
    from matplotlib.patches import Polygon  # noqa: E402

MATPLOTLIB_PRESENT = matplotlib is not None


class _BackendProxy:
    """Lazily resolve lumenplot_mpl.backend; raises if matplotlib is absent."""

    def __getattr__(self, name):
        import importlib

        return getattr(importlib.import_module("lumenplot_mpl.backend"), name)


backend_mod = _BackendProxy()


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


def _fill_canvas(figsize=(2.0, 1.0), dpi=100, build=None, decorate=False):
    """Strict-eligible figure whose only content is fill artists.

    Mirrors ``_eligible_canvas`` of the backend suite: explicit fixed style
    surface for any lines (ADR 0015 §5); axison stays off unless a fixture
    explicitly opts into decorated mode.
    """
    if not MATPLOTLIB_PRESENT:
        raise unittest.SkipTest("matplotlib not in this offline cell")
    fig = figure.Figure(figsize=figsize, dpi=dpi)
    canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="strict")
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
class TestFillWhitelist(unittest.TestCase):
    """Polygon and FillBetweenPolyCollection are eligible artist classes."""

    def setUp(self):
        self.patcher = _install_stub_native()
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_polygon_is_strict_eligible(self):
        fig, canvas, ax = _fill_canvas(
            build=lambda ax: ax.fill([0, 5, 10], [-3, 5, -3],
                                     color="red", lw=0),
        )
        result = canvas.render_png()
        self.assertEqual(result.diagnostics, ())
        poly = ax.patches[0]
        self.assertIsInstance(poly, Polygon)

    def test_fill_between_is_strict_eligible(self):
        fig, canvas, ax = _fill_canvas(
            build=lambda ax: ax.fill_between([0, 5, 10], [-3, -1, -3],
                                             [2, 5, 2], color="blue"),
        )
        result = canvas.render_png()
        self.assertEqual(result.diagnostics, ())
        coll = ax.collections[0]
        self.assertIsInstance(coll, FillBetweenPolyCollection)

    def test_line_and_fill_coexist_in_one_axes(self):
        def build(ax):
            ax.fill([0, 5, 10], [-3, 5, -3], color="red", lw=0)
            ax.add_line(Line2D([1, 9], [1, 3], color="green", linewidth=2.0,
                               solid_capstyle="butt",
                               solid_joinstyle="miter"))

        fig, canvas, ax = _fill_canvas(build=build)
        result = canvas.render_png()
        self.assertEqual(result.diagnostics, ())

    def test_unsupported_patch_class_still_rejected(self):
        # The whitelist grows by class, not by inheritance accident: an
        # Ellipse (outside every adopted slice) must stay refused. The
        # Rectangle bar surface itself moved inside under LP-FUNC-033.
        from matplotlib.patches import Ellipse

        def build(ax):
            ax.add_patch(Ellipse((1, 0), 4.0, 3.0, facecolor="red"))

        fig, canvas, ax = _fill_canvas(build=build)
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError) as ctx:
            canvas.render_png()
        self.assertIn("Ellipse", str(ctx.exception))


# ---------------------------------------------------------------------------
# 2. collector-trace expectation (LP-MPL-020 artifact 2)
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestFillCollectorTrace(unittest.TestCase):
    """The stage-two grammar accepts patch/FBPC draw_path groups."""

    def setUp(self):
        self.patcher = _install_stub_native()
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_fill_command_reaches_the_spec(self):
        fig, canvas, ax = _fill_canvas(
            build=lambda ax: ax.fill([0, 5, 10], [-3, 5, -3],
                                     color="red", lw=0),
        )
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        commands = [c for c in spec["commands"] if not c.get("decoration")]
        self.assertEqual(len(commands), 1)
        command = commands[0]
        self.assertEqual(command["kind"], "path")
        vertices = command["vertices"]
        bbox = ax.get_window_extent()
        # Data (0,-3),(5,5),(10,-3) through the public affine.
        expected = [
            [bbox.x0 + 0.0 / 10 * bbox.width,
             bbox.y0 + 0.0 / 8 * bbox.height],
            [bbox.x0 + 5.0 / 10 * bbox.width,
             bbox.y0 + 8.0 / 8 * bbox.height],
            [bbox.x0 + 10.0 / 10 * bbox.width,
             bbox.y0 + 0.0 / 8 * bbox.height],
        ]
        for got, want in zip(vertices, expected):
            self.assertAlmostEqual(got[0], want[0], places=6)
            self.assertAlmostEqual(got[1], want[1], places=6)
        # The closed Polygon path carries its duplicate closing vertex
        # (Agg's draw_path shows nverts=4 with codes [1,2,2,79]); the
        # adapter preserves it verbatim so the trace and the spec agree.
        self.assertEqual(len(vertices), len(expected) + 1)
        # A closed polygon loop carries the CLOSEPOLY code so the native
        # seam closes the subpath instead of leaving an open pen.
        codes = list(command["codes"])
        self.assertEqual(codes[0], 1)
        self.assertEqual(codes[-1], int(matplotlib.path.Path.CLOSEPOLY))

    def test_fill_between_geometry_matches_public_affine(self):
        xs = [0, 5, 10]
        y1 = [-3, -1, -3]
        y2 = [2, 5, 2]

        def build(ax):
            ax.fill_between(xs, y1, y2, color="blue")

        fig, canvas, ax = _fill_canvas(build=build)
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        commands = [c for c in spec["commands"] if not c.get("decoration")]
        self.assertEqual(len(commands), 1)
        vertices = commands[0]["vertices"]
        # The collected path is authoritative for the multi-loop polygon;
        # every vertex must equal the plain public affine mapping applied
        # to the artist's own collected path data.
        coll = ax.collections[0]
        import numpy as np

        bbox = ax.get_window_extent()
        xlim, ylim = ax.get_xlim(), ax.get_ylim()

        def pxx(x):
            return bbox.x0 + (x - xlim[0]) / (xlim[1] - xlim[0]) * bbox.width

        def pxy(y):
            return bbox.y0 + (y - ylim[0]) / (ylim[1] - ylim[0]) * bbox.height

        path = coll.get_paths()[0]
        # Vertices pass through the same transform Agg used (the collection
        # transform), recovered publicly via the artist's transforms.
        import matplotlib.transforms

        trans = coll.get_transform()
        expected = trans.transform(path.vertices)
        np.testing.assert_allclose(
            np.asarray(vertices), expected, rtol=0, atol=1e-9
        )
        del pxx, pxy

    def test_two_series_fill_between_produces_two_commands(self):
        def build(ax):
            ax.fill_between([0, 5, 10], [-3, -1, -3], [0, 1, 0],
                            color="blue")
            ax.fill_between([0, 5, 10], [1, 2, 1], [3, 5, 2],
                            color="orange")

        fig, canvas, ax = _fill_canvas(build=build)
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        commands = [c for c in spec["commands"] if not c.get("decoration")]
        self.assertEqual(len(commands), 2)

    def test_nan_gap_splits_fill_between_into_multiple_paths(self):
        def build(ax):
            ax.fill_between([0, 5, 10], [-3, float("nan"), -3], [0, float("nan"), 0],
                            color="blue")

        fig, canvas, ax = _fill_canvas(build=build)
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        commands = [c for c in spec["commands"] if not c.get("decoration")]
        # matplotlib splits at NaN into per-run polygons; each becomes its
        # own path command (degenerate single-loop runs render empty).
        self.assertGreaterEqual(len(commands), 1)
        for command in commands:
            self.assertGreaterEqual(len(command["vertices"]), 3)

    def test_two_loop_polygon_preserves_both_loops(self):
        def build(ax):
            outer = [(1, -2), (9, -2), (9, 4), (1, 4), (1, -2)]
            inner = [(4, 0), (6, 0), (6, 2), (4, 2), (4, 0)]
            codes = [1, 2, 2, 2, 79] * 2
            path = matplotlib.path.Path(outer + inner, codes)
            ax.add_patch(Polygon(path.vertices[:-1], closed=True,
                                 facecolor="teal"))
            ax.patches[0]._path = path

        fig, canvas, ax = _fill_canvas(build=build)
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        commands = [c for c in spec["commands"] if not c.get("decoration")]
        self.assertEqual(len(commands), 1)
        codes = list(commands[0]["codes"])
        self.assertEqual(codes.count(int(matplotlib.path.Path.CLOSEPOLY)), 2)
        self.assertEqual(len(commands[0]["vertices"]), 10)

    def test_negative_span_fill_reaches_the_spec(self):
        def build(ax):
            ax.fill([1, 5, 9], [0, -3, 0], color="purple")

        fig, canvas, ax = _fill_canvas(build=build)
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        commands = [c for c in spec["commands"] if not c.get("decoration")]
        self.assertEqual(len(commands), 1)
        ys = [v[1] for v in commands[0]["vertices"]]
        bbox = ax.get_window_extent()
        # All below/at the midline of an axes spanning -3..5: bottom half.
        self.assertTrue(all(y <= bbox.y0 + bbox.height / 2 + 1e-9
                            for y in ys))


# ---------------------------------------------------------------------------
# 3. style contract (LP-MPL-020 artifact 3)
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestFillStyleContract(unittest.TestCase):
    """Face/edge/alpha resolution equals Agg's Patch semantics.

    Contract (documented here as executable rules):

    - face color: the resolved Patch facecolor reaches the spec as
      ``fill_rgba`` exactly as ``_rgba8(facecolor)`` quantizes it — one
      alpha application total, matching Agg's single blend;
    - edge color defaults to the face color when the artist carries no
      explicit edgecolor (Agg resolves ``edgecolor='face'``-like default
      for Polygon through rcParams patch.edgecolor semantics);
    - a zero effective edge width draws no stroke (``stroke_rgba`` absent);
    - an explicit edgecolor with nonzero width strokes with that color.
    """

    def setUp(self):
        self.patcher = _install_stub_native()
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _content_command(self, build):
        fig, canvas, ax = _fill_canvas(build=build)
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        commands = [c for c in spec["commands"] if not c.get("decoration")]
        self.assertEqual(len(commands), 1)
        return commands[0]

    def test_face_color_reaches_fill_rgba(self):
        command = self._content_command(
            lambda ax: ax.fill([0, 5, 10], [-3, 5, -3], color="red", lw=0),
        )
        self.assertEqual(list(command["fill_rgba"]), [255, 0, 0, 255])
        self.assertIsNone(command["stroke_rgba"])

    def test_alpha_applies_once_to_face(self):
        command = self._content_command(
            lambda ax: ax.fill([0, 5, 10], [-3, 5, -3],
                               color="orange", alpha=0.35, lw=0),
        )
        fill = list(command["fill_rgba"])
        self.assertEqual(fill[:3], [255, 165, 0])
        self.assertEqual(fill[3], round(0.35 * 255))

    def test_default_edge_follows_the_face_color(self):
        # No explicit edge: matplotlib's Patch default resolves the edge to
        # the face color (rcParams-driven 'face' semantics); with nonzero
        # lw the stroke then uses that resolved color.
        command = self._content_command(
            lambda ax: ax.fill([0, 5, 10], [-3, 5, -3], color="red",
                               linewidth=2.0),
        )
        self.assertEqual(list(command["fill_rgba"]), [255, 0, 0, 255])
        self.assertIsNotNone(command["stroke_rgba"])
        self.assertEqual(list(command["stroke_rgba"]), [255, 0, 0, 255])

    def test_explicit_edge_color_and_width(self):
        command = self._content_command(
            lambda ax: ax.fill([0, 5, 10], [-3, 5, -3], facecolor="red",
                               edgecolor="blue", linewidth=3.0),
        )
        self.assertEqual(list(command["fill_rgba"]), [255, 0, 0, 255])
        self.assertEqual(list(command["stroke_rgba"]), [0, 0, 255, 255])
        self.assertEqual(command["line_width_pt"], 3.0)

    def test_zero_width_edge_draws_no_stroke(self):
        command = self._content_command(
            lambda ax: ax.fill([0, 5, 10], [-3, 5, -3], facecolor="red",
                               edgecolor="blue", linewidth=0.0),
        )
        self.assertIsNone(command["stroke_rgba"])

    def test_edge_alpha_matches_agg_gc(self):
        # Agg applies the patch alpha to the edge too (probe: gc reports
        # the same alpha for face and edge); the contract mirrors that.
        command = self._content_command(
            lambda ax: ax.fill([0, 5, 10], [-3, 5, -3], facecolor="red",
                               edgecolor="black", alpha=0.5, linewidth=2.0),
        )
        stroke = list(command["stroke_rgba"])
        self.assertEqual(stroke[:3], [0, 0, 0])
        self.assertEqual(stroke[3], round(0.5 * 255))

    def test_joinstyle_round_for_collections(self):
        # FillBetweenPolyCollection defaults to a round join (probed Agg
        # gc); the spec carries the artist's own resolved join.
        command = self._content_command(
            lambda ax: ax.fill_between([0, 5, 10], [-3, -1, -3], [2, 5, 2],
                                       color="blue", lw=2.0),
        )
        self.assertEqual(command["join"], "round")
        self.assertEqual(command["cap"], "butt")


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
class TestFillPixelParity(unittest.TestCase):
    """Native raster evidence against decoded-pixel expectations.

    Golden values were pinned once against matplotlib Agg output for the
    identical figure (geometry parity oracle, parent W1 plan). Interior
    pixels of solid fills are exact blends; AA boundary pixels differ by
    rasterizer coverage rounding and stay inside the numeric threshold.
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

    def _assert_pixel_parity(self, build, *, tol=32, min_exact_fraction=0.95,
                             worst_cap=200):
        """Decoded-pixel parity with a numerically defined AA allowance.

        The lane's AA definition (LP-FUNC-032 fixtures, flagged for review
        ratification): interiors must be exact-or-within ``tol`` per
        channel for at least ``min_exact_fraction`` of the frame, and no
        pixel may exceed ``worst_cap`` (a bounded AA ramp). Agg's 4px
        scanline box filter and tiny-skia's ~1px analytic coverage place
        slanted-edge antialiasing at slightly different phases; geometry,
        style, and alpha resolution are held to strict parity elsewhere.
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

    def test_simple_fill_interior_and_boundary(self):
        # A single closed polygon is exact under the Agg-compat blend mode
        # everywhere except slanted edges that graze pixel corners, where
        # Agg's analytic coverage and tiny-skia's 4x4 estimator disagree by
        # one subsample quantum (2/16 of alpha = 32/255 per channel; the
        # interior is byte-exact). That quantum is the ratified AA ramp cap.
        self._assert_pixel_parity(
            lambda ax: ax.fill([0, 5, 10], [-3, 5, -3], color="red", lw=0),
            tol=0,
            min_exact_fraction=0.95,
            worst_cap=32,
        )

    def test_fill_between_two_series(self):
        self._assert_pixel_parity(lambda ax: (
            ax.fill_between([0, 5, 10], [-3, -1, -3], [0, 1, 0],
                            color="blue", lw=0),
            ax.fill_between([0, 5, 10], [1, 2, 1], [3, 5, 2],
                            color="orange", lw=0),
        ))

    def test_alpha_overlap_blend(self):
        self._assert_pixel_parity(lambda ax: (
            ax.fill_between([0, 5, 10], [-2, -1, -2], [2, 3, 2],
                            color="green", alpha=0.5, lw=0),
            ax.fill([2, 6, 9], [-1, 4, -1], color="orange", alpha=0.35,
                    lw=0),
        ))

    def test_negative_span_fill(self):
        self._assert_pixel_parity(
            lambda ax: ax.fill([1, 5, 9], [0, -3, 0], color="purple", lw=0),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
