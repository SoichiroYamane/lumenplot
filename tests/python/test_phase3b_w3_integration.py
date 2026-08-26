"""W3 composition: interactive view history over base-10 log frames.

Integration card t_ae1c8eb0 (parent W3 plan). The W3 lanes landed two
capabilities independently:

- LP-FUNC-008/LP-UX-012 (view-history substrate): bounded viewport /
  canonical-view transactions over the API-0001 facade surface
  (``crates/lumenplot/tests/history.rs``). API-0001 keeps Home,
  Previous, and Next as transient runtime/UI state OUTSIDE
  ``PlotScene``, so the accepted composition shape is a facade-level
  history whose back/forward/reset resolve to a plain view assignment
  reflected through the Matplotlib authority -- exactly what this
  suite drives.
- LP-FUNC-004 (W3-log): strict-mode base-10 log axes -- scale-aware
  projection, explicit refusals for unsupported scales/labels/minor
  ticks, and full-frame pixel parity against the Agg oracle.

Composition contract pinned here:

- A pan/zoom/back/forward/reset sequence keeps rendering natively in
  strict mode with zero diagnostics on both linear AND log-scaled
  frames; every resolved view lands in the emitted frame-spec geometry
  (content vertices and projected gridline/tick decorations) exactly
  where the axis' own scale puts it.
- Back/forward/reset over a LOG frame land at log-projected positions,
  never at linear fractions of the restored interval.
- Restoring a view never bypasses eligibility gates: a frame whose
  scale became unsupported refuses explicitly even when the restored
  view itself is valid.
- Engine-level history semantics (no-op commits, canonical stability,
  atomic validation) are pinned by ``crates/lumenplot/tests/history.rs``
  and only mirrored where they become adapter-visible.

Offline cells without matplotlib or without the real native seam skip
cleanly, like the existing Phase-3B suites. Spec-level fixtures use the
stub seam; pixel fixtures require the real seam and measure against the
Agg oracle under the ratified numeric AA allowance.
"""

from __future__ import annotations

import io
import struct
import unittest
import zlib

try:
    import matplotlib
except ModuleNotFoundError:  # offline cells
    matplotlib = None
else:
    matplotlib.use("module://matplotlib.backends.backend_agg")  # baseline only

    from matplotlib import figure  # noqa: E402

MATPLOTLIB_PRESENT = matplotlib is not None

try:
    import numpy

    NUMPY_PRESENT = True
except ModuleNotFoundError:  # pragma: no cover - offline cells
    NUMPY_PRESENT = False


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
        (length,) = struct.unpack(">I", png_bytes[pos : pos + 4])
        ctype = png_bytes[pos + 4 : pos + 8]
        data = png_bytes[pos + 8 : pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(
                ">IIBB", data[:10]
            )
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
        line = bytearray(raw[y * stride + 1 : (y + 1) * stride])
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
# facade-level view history (the accepted API-0001 policy shape)
# ---------------------------------------------------------------------------


class ViewHistory:
    """Transient runtime/UI view history over Matplotlib-owned limits.

    API-0001 keeps Home/Previous/Next outside ``PlotScene``; the accepted
    substrate evidence (``crates/lumenplot/tests/history.rs``) pins
    viewport/canonical-view transactions instead. This harness is the
    corresponding runtime-boundary policy: interactions commit view
    snapshots, ``back``/``forward`` walk them, ``reset`` re-homes onto the
    stored canonical (Home) view, and every resolution becomes a plain
    ``set_xlim``/``set_ylim`` assignment on the Matplotlib axes -- the
    adapter then reads those limits back at draw time. Policy details
    mirrored from the engine evidence:

    - committing the currently-active view is a no-op entry (the engine
      treats an effective no-op as unchanged);
    - a fresh interaction discards the forward (redo) branch;
    - ``reset`` routes through the same commit path, so it is undoable;
    - back/forward at an empty stack are no-ops that leave the view.
    """

    def __init__(self, ax, home):
        self._ax = ax
        self._home = tuple(home)
        self._current = tuple(home)
        self._undo: list[tuple[float, ...]] = []
        self._redo: list[tuple[float, ...]] = []

    @property
    def current(self):
        return self._current

    def _reflect(self, view):
        self._ax.set_xlim(view[0], view[1])
        self._ax.set_ylim(view[2], view[3])

    def commit(self, view):
        """Apply a user pan/zoom; records history unless it is a no-op."""
        view = tuple(view)
        if view == self._current:
            return False
        self._undo.append(self._current)
        self._redo.clear()
        self._current = view
        self._reflect(view)
        return True

    def back(self):
        if not self._undo:
            return False
        self._redo.append(self._current)
        self._current = self._undo.pop()
        self._reflect(self._current)
        return True

    def forward(self):
        if not self._redo:
            return False
        self._undo.append(self._current)
        self._current = self._redo.pop()
        self._reflect(self._current)
        return True

    def reset(self):
        """Home/Reset: restore the stored canonical view (undoable)."""
        if self._current == self._home:
            return False
        return self.commit(self._home)


# ---------------------------------------------------------------------------
# shared fixtures
# ---------------------------------------------------------------------------

HOME = (0.0, 1.0, 1.0, 1000.0)
ZOOM1 = (0.25, 0.95, 5.0, 500.0)
ZOOM2 = (0.4, 0.8, 20.0, 200.0)

XDATA = [0.1, 0.35, 0.6, 0.9]
YDATA = [2.0, 15.0, 120.0, 800.0]


def _compose_line(ax, *, yscale="linear"):
    """One strict-eligible content line; optional base-10 log y axis."""
    ax.set_facecolor("none")
    ax.plot(
        XDATA,
        YDATA,
        color="red",
        linewidth=2.0,
        solid_capstyle="butt",
        solid_joinstyle="miter",
    )
    if yscale == "log":
        # set_yscale precedes limit assignments: matplotlib clamps view
        # requests through the installed scale (axis.py ``_set_lim``),
        # so fixtures exercise the real user order (W3-log lesson).
        ax.set_yscale("log")
    ax.set_xlim(HOME[0], HOME[1])
    ax.set_ylim(HOME[2], HOME[3])


def _decorate(ax):
    """Keep the frame strictly eligible while carrying y-grid decorations."""
    ax.grid(True, axis="y")
    ax.minorticks_off()
    from matplotlib.ticker import ScalarFormatter

    ax.yaxis.set_major_formatter(ScalarFormatter())


def _history_canvas(yscale="linear", *, decorate=True, mode="strict"):
    fig = figure.Figure(figsize=(3.0, 2.0), dpi=100)
    canvas = backend_mod.FigureCanvasLumenPlot(fig, mode=mode)
    ax = fig.add_axes([0.1, 0.1, 0.85, 0.85])
    _compose_line(ax, yscale=yscale)
    if decorate:
        _decorate(ax)
    history = ViewHistory(ax, HOME)
    return fig, canvas, ax, history


def _content_commands(spec):
    return [
        c
        for c in spec["commands"]
        if c.get("decoration") is None and c.get("kind") == "path"
    ]


def _grid_rows(spec):
    grids = [
        c for c in spec["commands"] if c.get("decoration") == "gridline"
    ]
    return sorted(round(c["vertices"][0][1], 6) for c in grids)


def _expected_grid_rows(ax):
    """Projected in-view y-tick rows under the axis' own scale (y-up)."""
    import math

    bbox = ax.get_window_extent()
    lo, hi = ax.get_ylim()
    locs = [v for v in ax.yaxis.get_ticklocs() if lo <= v <= hi]
    if str(ax.get_yscale()) == "log":
        frac = lambda v: (math.log10(v) - math.log10(lo)) / (
            math.log10(hi) - math.log10(lo)
        )  # noqa: E731 - local projection mirror
    else:
        frac = lambda v: (v - lo) / (hi - lo)  # noqa: E731
    return sorted(round(bbox.y0 + frac(v) * bbox.height, 6) for v in locs)


# ---------------------------------------------------------------------------
# 1. history over a linear frame (spec-level, stub seam)
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestHistoryLinearComposition(unittest.TestCase):
    def setUp(self):
        self.stub = _make_stub()
        self.patcher = _install_stub_native(self.stub)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _render_vertices(self, canvas, ax):
        result = canvas.render_png()
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(canvas.last_diagnostics, ())
        commands = _content_commands(self.stub.last_spec)
        self.assertEqual(len(commands), 1)
        return commands[0]["vertices"]

    def _assert_matches_transdata(self, canvas, ax):
        """Emitted vertices equal Axes.transData for the active view."""
        emitted = self._render_vertices(canvas, ax)
        display = ax.transData.transform(
            [[x, y] for x, y in zip(XDATA, YDATA)]
        )
        expected = [[float(dx), float(dy)] for dx, dy in display]
        self.assertEqual(len(emitted), len(expected))
        for got, want in zip(emitted, expected):
            self.assertAlmostEqual(got[0], want[0], places=6)
            self.assertAlmostEqual(got[1], want[1], places=6)

    def test_pan_zoom_back_forward_reset_tracks_resolved_views(self):
        """The full interaction cycle renders natively at every step and
        the frame geometry follows the RESOLVED view of each step."""
        fig, canvas, ax, history = _history_canvas("linear")
        self._assert_matches_transdata(canvas, ax)  # home

        history.commit(ZOOM1)
        self._assert_matches_transdata(canvas, ax)
        zoom1_spec = self.stub.last_spec

        history.commit(ZOOM2)
        self._assert_matches_transdata(canvas, ax)
        zoom2_spec = self.stub.last_spec

        self.assertTrue(history.back())
        self._assert_matches_transdata(canvas, ax)
        self.assertEqual(
            self.stub.last_spec["commands"], zoom1_spec["commands"]
        )

        self.assertTrue(history.forward())
        self._assert_matches_transdata(canvas, ax)
        self.assertEqual(
            self.stub.last_spec["commands"], zoom2_spec["commands"]
        )

        self.assertTrue(history.reset())
        self._assert_matches_transdata(canvas, ax)
        self.assertEqual(history.current, HOME)
        self.assertEqual(ax.get_xlim(), HOME[:2])
        self.assertEqual(ax.get_ylim(), HOME[2:])
        # Reset routed through the commit path: it is undoable.
        self.assertTrue(history.back())
        self.assertEqual(history.current, ZOOM2)
        self.assertTrue(history.forward())
        self.assertEqual(history.current, HOME)

    def test_noop_interaction_creates_no_history_entry(self):
        """Committing the active view is a no-op (engine no-op rule made
        adapter-visible): back skips past it to the last DISTINCT view."""
        fig, canvas, ax, history = _history_canvas("linear")
        self._render_vertices(canvas, ax)
        home_spec = self.stub.last_spec

        # back/forward on an empty stack are no-ops: the view is
        # unchanged and a re-render stays spec-identical to home.
        self.assertFalse(history.back())
        self.assertFalse(history.forward())
        result = canvas.render_png()
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(
            self.stub.last_spec["commands"], home_spec["commands"]
        )

        history.commit(ZOOM1)
        self._render_vertices(canvas, ax)

        # Committing the ACTIVE view is a no-op entry (engine no-op rule
        # made adapter-visible), so back skips past it to the last
        # DISTINCT view.
        self.assertFalse(history.commit(ZOOM1))
        self.assertTrue(history.back())
        self._assert_matches_transdata(canvas, ax)
        self.assertEqual(history.current, HOME)
        self.assertEqual(
            self.stub.last_spec["commands"], home_spec["commands"]
        )


# ---------------------------------------------------------------------------
# 2. history over a base-10 log frame (spec-level, stub seam)
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestHistoryLogComposition(unittest.TestCase):
    def setUp(self):
        self.stub = _make_stub()
        self.patcher = _install_stub_native(self.stub)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _assert_log_projection(self, canvas, ax):
        """Content vertices AND gridline rows sit at log-projected spots."""
        result = canvas.render_png()
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(canvas.last_diagnostics, ())
        commands = _content_commands(self.stub.last_spec)
        self.assertEqual(len(commands), 1)
        emitted = commands[0]["vertices"]
        display = ax.transData.transform(
            [[x, y] for x, y in zip(XDATA, YDATA)]
        )
        for got, want in zip(emitted, display):
            self.assertAlmostEqual(got[0], float(want[0]), places=6)
            self.assertAlmostEqual(got[1], float(want[1]), places=6)
        self.assertEqual(_grid_rows(self.stub.last_spec),
                         _expected_grid_rows(ax))

    def test_history_over_log_frame_stays_log_projected(self):
        """Back/forward/reset over a log frame land at log-projected
        positions -- never at linear fractions of the restored interval."""
        fig, canvas, ax, history = _history_canvas("log")

        self._assert_log_projection(canvas, ax)  # home
        home_rows = _grid_rows(self.stub.last_spec)

        history.commit(ZOOM1)
        self._assert_log_projection(canvas, ax)
        zoom1_spec = self.stub.last_spec

        history.commit(ZOOM2)
        self._assert_log_projection(canvas, ax)

        self.assertTrue(history.back())
        self._assert_log_projection(canvas, ax)
        self.assertEqual(
            self.stub.last_spec["commands"], zoom1_spec["commands"]
        )

        self.assertTrue(history.reset())
        self._assert_log_projection(canvas, ax)
        self.assertEqual(_grid_rows(self.stub.last_spec), home_rows)

        # Pin one concrete divergence: under HOME, the y=10 decade grid
        # row is NOT at its linear fraction of the interval (the whole
        # point of composing history with the log lane).
        bbox = ax.get_window_extent()
        locs = [v for v in ax.yaxis.get_ticklocs() if 1.0 <= v <= 1000.0]
        decade_row = next(
            r for r, v in zip(sorted(home_rows), sorted(locs))
            if v == 10.0
        )
        linear_row = bbox.y0 + (10.0 - 1.0) / (1000.0 - 1.0) * bbox.height
        self.assertGreater(abs(decade_row - linear_row), 5.0)

    def test_decorated_log_history_renders_without_diagnostics(self):
        """Zero-diagnostics contract holds at EVERY history step on a
        decorated, strictly-eligible log frame (last_diagnostics is
        republished per attempt, so it tracks the latest step)."""
        fig, canvas, ax, history = _history_canvas("log")
        for step in ("home", ZOOM1, ZOOM2, "back", "back", "forward",
                     "reset"):
            if step == "home":
                pass
            elif step == "back":
                history.back()
            elif step == "forward":
                history.forward()
            elif isinstance(step, tuple):
                history.commit(step)
            else:  # reset
                history.reset()
            result = canvas.render_png()
            self.assertEqual(result.diagnostics, ())
            self.assertEqual(canvas.last_diagnostics, ())
            kinds = [c.get("decoration") for c in self.stub.last_spec
                     ["commands"]]
            self.assertIn("gridline", kinds)
            self.assertIn("tick", kinds)
            self.assertIn("spine", kinds)

    def test_restored_view_never_bypasses_scale_gates(self):
        """Restoring a valid historical view cannot resurrect eligibility:
        once the y scale leaves the supported set, the next render refuses
        explicitly even though the restored VIEW itself is fine."""
        fig, canvas, ax, history = _history_canvas("log")
        history.commit(ZOOM1)
        canvas.render_png()

        history.back()
        # ``set_yscale`` reinstates the new scale's own (mathtext) label
        # formatter, so suppression happens AFTER the scale change --
        # exactly as the W3-log lane's symlog fixture does -- leaving
        # the scale gate as the first refusal.
        ax.set_yscale("symlog")
        ax.tick_params(labelbottom=False, labelleft=False)
        with self.assertRaisesRegex(
            backend_mod.LumenPlotUnsupportedError, "scale"
        ):
            canvas.render_png()


# ---------------------------------------------------------------------------
# 3. refusals stay terminal on composed history frames
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestHistoryHybridContract(unittest.TestCase):
    def setUp(self):
        self.stub = _make_stub()
        self.patcher = _install_stub_native(self.stub)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_hybrid_log_history_falls_back_whole_frame_once(self):
        """On hybrid, a refusal discovered mid-history converts to exactly
        one whole-frame Agg fallback diagnostic -- the whole-frame
        contract survives the history composition."""
        fig, canvas, ax, history = _history_canvas("log", mode="hybrid")
        history.commit(ZOOM1)
        result = canvas.render_png()
        self.assertEqual(result.diagnostics, ())
        self.assertIsNotNone(self.stub.last_spec)  # rendered natively
        self.stub.last_spec = None  # drop the successful native attempt
        ax.set_yscale("symlog")  # becomes ineligible at the next step
        result = canvas.render_png()
        self.assertIsNone(self.stub.last_spec)
        self.assertEqual(len(result.diagnostics), 1)
        diagnostic = result.diagnostics[0]
        self.assertIsInstance(
            diagnostic, backend_mod.LumenPlotFallbackDiagnostic
        )
        self.assertEqual(diagnostic.kind, "unsupported-capability")
        self.assertEqual(diagnostic.scope, "whole-frame")

    def test_strict_refusal_mid_history_is_terminal_not_partial(self):
        fig, canvas, ax, history = _history_canvas("log")
        history.commit(ZOOM1)
        canvas.render_png()
        history.reset()
        self.stub.last_spec = None  # drop the successful native attempt
        ax.plot([0.3], [40.0], color="red", marker="o",
                solid_capstyle="butt", solid_joinstyle="miter")
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            canvas.render_png()
        self.assertIsNone(self.stub.last_spec)


# ---------------------------------------------------------------------------
# 4. pixel parity of history-resolved log frames vs Agg (real seam)
# ---------------------------------------------------------------------------


def _log_frame_at(view):
    """Builder factory: decorated log-y frame viewed through ``view``."""

    def build(ax):
        _compose_line(ax, yscale="log")
        _decorate(ax)
        ax.set_xlim(view[0], view[1])
        ax.set_ylim(view[2], view[3])

    build.__name__ = f"_log_frame_at({view})"
    return build


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and NUMPY_PRESENT, "matplotlib/numpy offline cell"
)
class TestHistoryFramePixelParity(unittest.TestCase):
    """Native raster evidence for history-resolved log frames vs Agg.

    Threshold methodology follows the ratified W1/W2/W3 lane definition
    (>= 95% of pixels within 32/channel); ``worst_cap`` pins the AA ramp
    at the largest value measured across these exact workloads on this
    stack. Values re-measure whenever the renderer changes; they bound
    regression, not exactness -- stroke edges carry the documented
    engine-wide AA-phase trait (Agg 4px scanline box filter vs tiny-skia
    analytic coverage).
    """

    maxDiff = None

    def setUp(self):
        _require_real_seam()

    @staticmethod
    def _agg_reference(build):
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        fig = figure.Figure(figsize=(3.0, 2.0), dpi=100)
        ax = fig.add_axes([0.1, 0.1, 0.85, 0.85])
        build(ax)
        FigureCanvasAgg(fig)
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=100)
        return buffer.getvalue()

    @staticmethod
    def _render_native(build, mode="strict"):
        fig = figure.Figure(figsize=(3.0, 2.0), dpi=100)
        canvas = backend_mod.FigureCanvasLumenPlot(fig, mode=mode)
        ax = fig.add_axes([0.1, 0.1, 0.85, 0.85])
        build(ax)
        return canvas.render_png()

    def _measure(self, build):
        agg_bytes = self._agg_reference(build)
        result = self._render_native(build)
        aw, ah, arows = _decode_rgba8(agg_bytes)
        nw, nh, nrows = _decode_rgba8(result.png_bytes)
        self.assertEqual((aw, ah), (nw, nh))

        flat_agg = numpy.frombuffer(
            b"".join(arows), dtype=numpy.uint8
        ).astype(int).reshape(-1, 4)
        flat_nat = numpy.frombuffer(
            b"".join(nrows), dtype=numpy.uint8
        ).astype(int).reshape(-1, 4)
        deltas = numpy.abs(flat_agg - flat_nat).max(axis=1)
        return float((deltas <= 32).mean()), int(deltas.max())

    def _assert_pixel_parity(self, build, *, tol=32, min_within=0.95,
                             worst_cap=None):
        within, worst = self._measure(build)
        cap = worst_cap if worst_cap is not None else 255
        print(f"\n[measured] {build.__name__}: within32={within:.4f} "
              f"worst={worst} (cap={cap})")
        self.assertGreaterEqual(within, min_within)
        self.assertLessEqual(worst, cap)
        return within, worst

    def test_home_view_log_frame_matches_agg(self):
        # Measured 2026-08-26: within32=0.9605, worst=255.
        self._assert_pixel_parity(_log_frame_at(HOME))

    def test_zoomed_view_log_frame_matches_agg(self):
        """A mid-history zoomed view composes identically: same oracle
        band as the home frame (projection, decorations, glyphs)."""
        # Measured 2026-08-26: within32=0.9723, worst=255.
        self._assert_pixel_parity(_log_frame_at(ZOOM1))

    def test_reset_to_home_is_byte_identical_to_fresh_home(self):
        """Driving the history (zoom, then Home) reproduces the fresh
        home frame EXACTLY at the native seam -- the restored state is
        indistinguishable from never having interacted."""
        _, _, nrows_home = _decode_rgba8(
            self._render_native(_log_frame_at(HOME)).png_bytes
        )

        fig = figure.Figure(figsize=(3.0, 2.0), dpi=100)
        canvas = backend_mod.FigureCanvasLumenPlot(fig)
        ax = fig.add_axes([0.1, 0.1, 0.85, 0.85])
        _compose_line(ax, yscale="log")
        _decorate(ax)
        history = ViewHistory(ax, HOME)
        history.commit(ZOOM1)
        canvas.render_png()
        history.reset()
        _, _, nrows_after = _decode_rgba8(canvas.render_png().png_bytes)
        self.assertEqual(nrows_home, nrows_after)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
