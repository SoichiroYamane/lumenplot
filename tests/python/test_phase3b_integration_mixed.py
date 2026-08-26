"""W1 integration: fill + bar + steps + default-line mixed workloads.

Integration card t_19ef7f10 (parent W1 plan). The three lane cards
(t_93a0421c LP-FUNC-032, t_d4ceb6af LP-FUNC-033, t_cf97d908 LP-FUNC-034)
landed eligibility extensions independently; this suite pins their
*composition*: one figure carrying artists from every family must keep
rendering natively in strict mode with zero diagnostics, hybrid mode must
stay a whole-frame contract (native when every artist is eligible,
exactly one whole-frame Agg fallback the moment one is not), and decoded
pixels of full mixed frames must stay inside the lanes' ratified numeric
AA allowance against the matplotlib Agg oracle.

The pixel workloads were chosen to exercise every family's interaction
band without stacking slanted fill boundaries on top of each other:
stacked slanted edges multiply the rasterizers' AA phase disagreement
beyond any single lane's measured ramp (measured 2026-08-26: two stacked
slanted fills reach worst=255 with only 93.0% of pixels within 32), so
the composed fixtures band the families instead -- the same documented
divergence (Agg 4px scanline box filter vs tiny-skia analytic coverage),
recorded per lane, now pinned at the frame level.

Offline cells without matplotlib skip cleanly. Pixel fixtures require
the real native seam and skip when it is absent; spec-level fixtures use
the stub seam like the existing backend suite.
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


def _install_stub_native(stub):
    import types
    import unittest.mock

    real = (
        backend_mod
        if isinstance(backend_mod, types.ModuleType)
        else __import__("lumenplot_mpl.backend", fromlist=["_native"])
    )
    return unittest.mock.patch.object(real, "_native", lambda: stub)


def _make_stub():
    """A fresh recording stand-in for ``lumenplot_mpl._native``."""
    import types

    class _StubNativeModule(types.SimpleNamespace):
        last_spec = None

        @staticmethod
        def render_frame_png(spec):  # noqa: N802 - mirrors native name
            _StubNativeModule.last_spec = spec
            return _stub_native_png(spec["width_px"], spec["height_px"])

    return _StubNativeModule


def _mixed_canvas(build, *, mode="strict"):
    """One axes carrying artists from all four eligible families.
    Deliberate interleaving mirrors a realistic dashboard build (band
    fill, bars, plain line, polygon fill, stepped line); Agg composes by
    z-order class -- collections, then patches, then lines, stable
    within each class -- and the native command list follows it.
    """
    if not MATPLOTLIB_PRESENT:
        raise unittest.SkipTest("matplotlib not in this offline cell")
    fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
    canvas = _load_backend().FigureCanvasLumenPlot(fig, mode=mode)
    ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
    ax.axison = False
    if build is not None:
        build(ax)
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(-3.0, 5.0)
    return fig, canvas, ax


def _dashboard_banded(ax):
    """All five families in disjoint y-bands; steps-mid has duplicate x.

    Bands: orange band fill (top), purple steps-mid line, red default
    line, steelblue bars (one negative), blue triangle fill (bottom).
    The duplicate-x sample pair exercises the step expansion boundary
    inside a mixed frame (LP-FUNC-034 fixture geometry).
    """
    ax.fill_between([0, 5, 10], [3.2, 3.8, 3.4], [4.2, 5.0, 4.6],
                    color="orange", lw=0)
    ax.bar([2, 7], [3, -1], width=1.0, color="steelblue")
    ax.plot([0, 10], [0.8, 2.8], color="red", lw=2.0,
            solid_capstyle="butt", solid_joinstyle="miter")
    ax.fill([1, 5, 9], [-2.8, -0.5, -2.2], color="blue", lw=0)
    ax.add_line(Line2D(
        [0, 2.5, 5, 5, 7.5, 10], [2.6, 1.6, 2.4, 2.4, 1.8, 2.5],
        drawstyle="steps-mid", color="purple", lw=2.0,
        solid_capstyle="butt", solid_joinstyle="miter"))


def _require_real_seam():
    try:
        from lumenplot_mpl import _native  # noqa: F401
    except (ImportError, AttributeError):
        raise unittest.SkipTest("native seam not built in this environment")
    if not hasattr(_native, "render_frame_png"):
        raise unittest.SkipTest("render_frame_png not present yet")


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


# ---------------------------------------------------------------------------
# 1. strict-mode native composition (spec-level, stub seam)
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestMixedStrictComposition(unittest.TestCase):
    """Every eligible family composes into one native frame."""

    def setUp(self):
        self.stub = _make_stub()
        self.patcher = _install_stub_native(self.stub)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_all_families_render_one_native_frame_without_diagnostics(self):
        fig, canvas, ax = _mixed_canvas(build=_dashboard_banded)
        result = canvas.render_png()
        self.assertIsNot(self.stub.last_spec, None)
        self.assertEqual(result.diagnostics, ())
        commands = [c for c in self.stub.last_spec["commands"]
                    if not c.get("decoration")]
        # Agg z-order: band fill, bar, bar, triangle fill, default line,
        # expanded steps-mid line (12 vertices from 5 samples incl. the
        # duplicate-x pair).
        self.assertEqual(len(commands), 6)
        fills = [c for c in commands if c.get("fill_rgba")]
        strokes = [c for c in commands if c.get("stroke_rgba")]
        self.assertEqual(len(fills), 4)
        self.assertEqual(len(strokes), 2)
    def test_mixed_frame_preserves_each_family_shape_and_style(self):
        fig, canvas, ax = _mixed_canvas(build=_dashboard_banded)
        canvas.render_png()
        commands = [c for c in self.stub.last_spec["commands"]
                    if not c.get("decoration")]
        band_fill, bar_neg, bar_pos, tri_fill, line, steps = commands
        # Band fill: FillBetweenPolyCollection carries closed codes and a
        # round join (probed Agg gc, LP-FUNC-032 style contract).
        self.assertEqual(band_fill["join"], "round")
        self.assertEqual(band_fill["fill_rgba"], [255, 165, 0, 255])
        # Bars stay axis-aligned Rectangles with miter joins (LP-FUNC-033).
        for bar in (bar_neg, bar_pos):
            self.assertEqual(bar["join"], "miter")
            self.assertEqual(bar["cap"], "butt")
            self.assertEqual(bar["codes"][0], 1)  # MOVETO
            self.assertEqual(bar["codes"][-1], 79)  # CLOSEPOLY
        self.assertEqual(bar_pos["fill_rgba"], [70, 130, 180, 255])
        self.assertEqual(bar_neg["fill_rgba"], [70, 130, 180, 255])
        # Triangle fill: closed Polygon path (LP-FUNC-032).
        self.assertEqual(tri_fill["fill_rgba"], [0, 0, 255, 255])
        self.assertEqual(len(tri_fill["vertices"]), 4)
        # Default line: single open stroke, no codes needed (LP-FUNC-031).
        self.assertIsNone(line["codes"])
        self.assertEqual(line["stroke_rgba"], [255, 0, 0, 255])
        # Steps-mid expands exactly like cbook (LP-FUNC-034): 5 samples
        # with one duplicate-x pair become 12 projected vertices.
        self.assertIsNone(steps["codes"])
        self.assertEqual(len(steps["vertices"]), 12)
        self.assertEqual(steps["stroke_rgba"], [128, 0, 128, 255])

    def test_artist_order_does_not_change_native_composition(self):
        """The same five families added in reverse still render six
        content commands (bar split included) with zero diagnostics --
        composition is order-independent at the eligibility level."""

        def reversed_build(ax):
            ax.add_line(Line2D(
                [0, 2.5, 5, 5, 7.5, 10], [2.6, 1.6, 2.4, 2.4, 1.8, 2.5],
                drawstyle="steps-mid", color="purple", lw=2.0,
                solid_capstyle="butt", solid_joinstyle="miter"))
            ax.fill([1, 5, 9], [-2.8, -0.5, -2.2], color="blue", lw=0)
            ax.plot([0, 10], [0.8, 2.8], color="red", lw=2.0,
                    solid_capstyle="butt", solid_joinstyle="miter")
            ax.bar([2, 7], [3, -1], width=1.0, color="steelblue")
            ax.fill_between([0, 5, 10], [3.2, 3.8, 3.4], [4.2, 5.0, 4.6],
                            color="orange", lw=0)

        fig, canvas, ax = _mixed_canvas(build=reversed_build)
        result = canvas.render_png()
        self.assertEqual(result.diagnostics, ())
        commands = [c for c in self.stub.last_spec["commands"]
                    if not c.get("decoration")]
        self.assertEqual(len(commands), 6)


# ---------------------------------------------------------------------------
# 2. hybrid profile stays a whole-frame contract on mixed content
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestMixedHybridContract(unittest.TestCase):
    """Hybrid is never a per-family mix on composed frames."""

    def setUp(self):
        self.stub = _make_stub()
        self.patcher = _install_stub_native(self.stub)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_hybrid_renders_eligible_mix_natively_without_diagnostic(self):
        fig, canvas, ax = _mixed_canvas(build=_dashboard_banded, mode="hybrid")
        result = canvas.render_png()
        self.assertIsNot(self.stub.last_spec, None)
        self.assertEqual(result.diagnostics, ())
        commands = [c for c in self.stub.last_spec["commands"]
                    if not c.get("decoration")]
        self.assertEqual(len(commands), 6)

    def test_one_ineligible_artist_falls_back_whole_frame_once(self):
        """Adding one ineligible artist (hatched Rectangle) to an
        otherwise eligible mixed frame yields exactly one whole-frame
        Agg fallback record; nothing reaches the native seam and the
        generation counter advances by one for the attempt."""

        def mostly_eligible(ax):
            _dashboard_banded(ax)
            ax.add_patch(matplotlib.patches.Rectangle(
                (4.0, 0.0), 2.0, 1.0, facecolor="red", hatch="//"))

        fig, canvas, ax = _mixed_canvas(build=mostly_eligible, mode="hybrid")
        before_generation = canvas._generation
        result = canvas.render_png()
        self.assertEqual(canvas._generation, before_generation + 1)
        self.assertIsNone(self.stub.last_spec)
        self.assertEqual(len(result.diagnostics), 1)
        diagnostic = result.diagnostics[0]
        self.assertIsInstance(
            diagnostic, backend_mod.LumenPlotFallbackDiagnostic
        )
        self.assertEqual(diagnostic.kind, "unsupported-capability")
        self.assertEqual(diagnostic.type, "Rectangle")
        self.assertEqual(diagnostic.scope, "whole-frame")
        self.assertEqual(diagnostic.representation, "raster")
        self.assertEqual(diagnostic.output_format, "png")
        self.assertEqual(diagnostic.fallback_type, "matplotlib-agg")
        self.assertEqual(diagnostic.generation, canvas._generation)
        self.assertEqual(canvas.last_diagnostics, result.diagnostics)

    def test_strict_refusal_on_mixed_frame_is_terminal_not_partial(self):
        """Strict mode refuses the whole mixed frame when any family is
        unsupported (marker on the plain line): no partial native frame,
        no silent substitution -- the stable token surfaces directly."""

        def marker_in_mix(ax):
            _dashboard_banded(ax)
            ax.plot([1, 2], [1, 2], color="red", marker="o")

        fig, canvas, ax = _mixed_canvas(build=marker_in_mix, mode="strict")
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError) as ctx:
            canvas.render_png()
        self.assertEqual(ctx.exception.code, "unsupported-capability")
        self.assertIsNone(self.stub.last_spec)


# ---------------------------------------------------------------------------
# 3. pixel parity of full mixed frames vs Agg (real seam)
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestMixedFramePixelParity(unittest.TestCase):
    """Native raster evidence for complete mixed frames against Agg.

    Thresholds were measured when these fixtures were built (2026-08-26,
    CPython 3.14 + matplotlib 3.11.1 + the lane's abi3 seam) and are
    re-measured whenever the renderer changes. ``tol``/``min_within``
    mirror the ratified lane definition (>= 95% of pixels within 32 per
    channel); ``worst_cap`` bounds the AA ramp at the largest value
    measured across these exact workloads (191, on a stepped-stroke
    edge under translucent fills). Stacked slanted fill boundaries are
    deliberately excluded: they multiply the documented rasterizer phase
    divergence beyond any single lane's ramp (worst=255 at 93.0% within
    32 when measured), which would pin nothing -- the banded workloads
    below carry every family's edge type once instead.
    """

    maxDiff = None

    def setUp(self):
        _require_real_seam()

    @staticmethod
    def _agg_reference(build):
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

    @staticmethod
    def _render_native(build):
        from lumenplot_mpl.backend import FigureCanvasLumenPlot

        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = FigureCanvasLumenPlot(fig)
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.axison = False
        build(ax)
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(-3.0, 5.0)
        return canvas.render_png()

    def _assert_pixel_parity(self, build, *, tol=32, min_within=0.95,
                             worst_cap=191):
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
        worst = int(deltas.max())
        within = float((deltas <= tol).mean())
        self.assertLessEqual(worst, worst_cap,
                             f"pixel delta {worst} exceeds the measured "
                             f"AA ramp cap {worst_cap}")
        self.assertGreaterEqual(
            within, min_within,
            f"only {within:.4f} of pixels within tolerance {tol} "
            f"(need {min_within}); worst {worst}",
        )

    def test_dashboard_banded_all_families(self):
        self._assert_pixel_parity(_dashboard_banded)

    def test_alpha_overlap_translucency(self):
        """Translucent fills over bars plus steps-pre risers: alpha
        composition across families matches Agg's single blend."""

        def build(ax):
            ax.fill_between([0, 5, 10], [-2, -1, -2], [2, 3, 2],
                            color="green", alpha=0.5, lw=0)
            ax.bar([2, 7], [3, 2], width=1.2, color="steelblue", alpha=0.35)
            ax.add_line(Line2D(
                [0, 5, 10], [4, 1, 3], drawstyle="steps-pre", color="red",
                lw=2.0, solid_capstyle="butt", solid_joinstyle="miter"))

        self._assert_pixel_parity(build)

    def test_negative_span_mixed_below_baseline(self):
        """Below-baseline bars under a triangular fill apex: negative
        extents compose exactly (byte-level agreement outside AA)."""

        def build(ax):
            ax.bar([2, 7], [-2, -3], width=1.0, color="teal")
            ax.fill([1, 5, 9], [0, 3, 0], color="orange", lw=0)
            ax.plot([0, 10], [-1, 2], color="red", lw=2.0,
                    solid_capstyle="butt", solid_joinstyle="miter")

        self._assert_pixel_parity(build)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
