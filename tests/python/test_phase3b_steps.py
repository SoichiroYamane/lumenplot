"""LP-FUNC-034 step drawstyles — Agg-parity contract tests.

Test-first lane card t_cf97d908 (W1-steps). The quality oracle is the
matplotlib Agg backend (parent W1 plan, parity draft §5.4): geometry
parity via public getters against Matplotlib's own ``cbook`` step
expansion, pixel parity on decoded RGBA8 output through the real native
seam, and Agg-identical style resolution (the fixed ADR 0015 §5 stroke
surface is unchanged).

The LP-MPL-020 eligibility-extension artifacts for this slice:

1. whitelist entry: unchanged — ``Line2D`` was already whitelisted; the
   *style contract* grows to admit the step drawstyles as exact vertex
   generation instead of refusing them;
2. collector-trace expectation: unchanged — steps stay one single-stroke
   ``draw_path`` per line;
3. style contract: ``steps-pre``/``steps-post``/``steps-mid`` (plus the
   ``steps`` alias) expand the line's data exactly like Matplotlib's
   ``STEP_LOOKUP_MAP`` before projection; every other non-default
   drawstyle value is still refused explicitly;
4. fixtures: strict-mode native rendering compared against Agg golden
   geometry plus decoded-pixel evidence for representative workloads,
   LOD topology recurrence on stepped data (flag C-3), and both profile
   modes pinned (strict native, hybrid native with no fallback
   diagnostic).

Offline cells without matplotlib skip cleanly. Pixel fixtures require
the real native seam and skip when it is absent; spec-level fixtures use
the stub seam like the existing backend suite.
"""

from __future__ import annotations

import struct
import unittest
import zlib

try:
    import matplotlib
except ModuleNotFoundError:  # offline cells: matplotlib evidence is a later slice
    matplotlib = None
else:
    matplotlib.use("module://matplotlib.backends.backend_agg")  # baseline only

    from matplotlib import cbook, figure  # noqa: E402
    from matplotlib.lines import Line2D  # noqa: E402

MATPLOTLIB_PRESENT = matplotlib is not None


class _BackendProxy:
    """Lazily resolve lumenplot_mpl.backend; raises if matplotlib is absent."""

    def __getattr__(self, name):
        import importlib

        return getattr(importlib.import_module("lumenplot_mpl.backend"), name)


backend_mod = _BackendProxy()


# ---------------------------------------------------------------------------
# Shared helpers (mirrors of the fill/bar suite scaffolding)
# ---------------------------------------------------------------------------


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


def _steps_canvas(
    figsize=(2.0, 1.0),
    dpi=100,
    x=(0.0, 2.5, 5.0, 7.5, 10.0),
    y=(1.0, 4.0, 2.0, 5.0, 3.0),
    drawstyle="steps-pre",
    mode="strict",
):
    """Strict-eligible figure whose only content is one step-style line.

    Mirrors ``_eligible_canvas`` of the backend suite: the fixed style
    surface (ADR 0015 §5) is explicit; axison stays off.
    """
    if not MATPLOTLIB_PRESENT:
        raise unittest.SkipTest("matplotlib not in this offline cell")
    fig = figure.Figure(figsize=figsize, dpi=dpi)
    canvas = _load_backend().FigureCanvasLumenPlot(fig, mode=mode)
    ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
    ax.axison = False
    ax.add_line(
        Line2D(
            list(x),
            list(y),
            drawstyle=drawstyle,
            color="red",
            linewidth=2.0,
            solid_capstyle="butt",
            solid_joinstyle="miter",
        )
    )
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(0.0, 6.0)
    return fig, canvas


def _agg_step_xy(line):
    """Agg oracle: the exact expanded vertices Matplotlib itself draws."""
    import numpy as np

    if line.get_drawstyle() == "default":
        return np.asarray(line.get_xydata(), dtype=float)
    step_func = cbook.STEP_LOOKUP_MAP[line.get_drawstyle()]
    xy = np.asarray(line.get_xydata(), dtype=float)
    return np.asarray(step_func(xy[:, 0], xy[:, 1])).T


def _expected_display_vertices(ax, line):
    """Project the Agg-oracle vertices with the adapter's own route."""
    bbox = ax.get_window_extent()
    xlim = ax.get_xlim()
    ylim = ax.get_ylim()

    def px(x):
        return bbox.x0 + (x - xlim[0]) / (xlim[1] - xlim[0]) * bbox.width

    def py(y):
        return bbox.y0 + (y - ylim[0]) / (ylim[1] - ylim[0]) * bbox.height

    return [
        [float(px(x)), float(py(y))]
        for x, y in _agg_step_xy(line)
    ]


def _decode_rgba8(png_bytes: bytes) -> tuple[int, int, list[list[int]]]:
    """Decode a truecolor+alpha PNG into rows of RGBA8 pixels."""
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "PNG magic missing"
    offset = 8
    width = height = 0
    idat = b""
    while offset < len(png_bytes):
        length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        kind = png_bytes[offset + 4 : offset + 8]
        payload = png_bytes[offset + 8 : offset + 8 + length]
        if kind == b"IHDR":
            width, height = struct.unpack(">II", payload[:8])
        elif kind == b"IDAT":
            idat += payload
        elif kind == b"IEND":
            break
        offset += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 4 + 1
    rows: list[list[int]] = []
    previous = [0] * (width * 4)
    for row_index in range(height):
        chunk = raw[row_index * stride : (row_index + 1) * stride]
        filter_kind = chunk[0]
        current = list(previous)
        line = chunk[1:]
        for i in range(width * 4):
            left = current[i - 4] if i >= 4 else 0
            up = previous[i]
            # Upper-left lives in the reconstructed PREVIOUS row;
            # reading the current row here would alias "left" and
            # corrupt every Paeth-filtered scanline.
            upper_left = previous[i - 4] if (i >= 4 and row_index > 0) else 0
            if filter_kind == 0:
                value = line[i]
            elif filter_kind == 1:
                value = (line[i] + left) & 0xFF
            elif filter_kind == 2:
                value = (line[i] + up) & 0xFF
            elif filter_kind == 3:
                value = (line[i] + (left + up) // 2) & 0xFF
            elif filter_kind == 4:
                p = left + up - upper_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - upper_left)
                predictor = left if (pa <= pb and pa <= pc) else (
                    up if pb <= pc else upper_left
                )
                value = (line[i] + predictor) & 0xFF
            else:  # pragma: no cover - fixture data uses filters 0-4 only
                raise AssertionError(f"unexpected filter {filter_kind}")
            current[i] = value
        rows.append(current)
        previous = current
    return width, height, rows


def _pixel_delta(native_png: bytes, agg_png: bytes) -> int:
    """Maximum per-channel absolute difference between two RGBA8 frames."""
    w1, h1, a = _decode_rgba8(native_png)
    w2, h2, b = _decode_rgba8(agg_png)
    assert (w1, h1) == (w2, h2), "frame sizes differ"
    worst = 0
    for row_a, row_b in zip(a, b):
        for va, vb in zip(row_a, row_b):
            worst = max(worst, abs(va - vb))
    return worst


def _render_agg(fig):
    """Render the same figure through stock Agg and return PNG bytes."""
    import io

    from matplotlib.backends.backend_agg import FigureCanvasAgg

    buffer = io.BytesIO()
    FigureCanvasAgg(fig)
    fig.savefig(buffer, format="png")
    return buffer.getvalue()


def _step_stroke_commands(spec):
    """Line-stroke commands of one spec (fills excluded)."""
    return [
        command
        for command in spec["commands"]
        if command.get("kind") == "path"
        and command.get("fill_rgba") is None
    ]


# ---------------------------------------------------------------------------
# AT-FUNC-DRAWSTYLE: exact vertex-generation semantics (geometry parity)
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestStepGeometryParity(unittest.TestCase):
    """The emitted command carries exactly Agg's expanded step polyline."""

    def setUp(self):
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)

    def _command_for(self, drawstyle):
        fig, canvas = _steps_canvas(drawstyle=drawstyle)
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        self.assertIsNotNone(spec)
        strokes = _step_stroke_commands(spec)
        self.assertEqual(len(strokes), 1)
        del fig
        return strokes[0]

    def test_steps_pre_vertex_sequence_matches_agg(self):
        command = self._command_for("steps-pre")
        fig, _ = _steps_canvas(drawstyle="steps-pre")
        ax = fig.get_axes()[0]
        expected = _expected_display_vertices(ax, ax.lines[0])
        self.assertEqual(len(command["vertices"]), len(expected))
        for got, want in zip(command["vertices"], expected):
            self.assertAlmostEqual(got[0], want[0], places=9)
            self.assertAlmostEqual(got[1], want[1], places=9)
        del fig

    def test_steps_post_vertex_sequence_matches_agg(self):
        command = self._command_for("steps-post")
        fig, _ = _steps_canvas(drawstyle="steps-post")
        ax = fig.get_axes()[0]
        expected = _expected_display_vertices(ax, ax.lines[0])
        self.assertEqual(len(command["vertices"]), len(expected))
        for got, want in zip(command["vertices"], expected):
            self.assertAlmostEqual(got[0], want[0], places=9)
            self.assertAlmostEqual(got[1], want[1], places=9)
        del fig

    def test_steps_mid_vertex_sequence_matches_agg(self):
        command = self._command_for("steps-mid")
        fig, _ = _steps_canvas(drawstyle="steps-mid")
        ax = fig.get_axes()[0]
        expected = _expected_display_vertices(ax, ax.lines[0])
        self.assertEqual(len(command["vertices"]), len(expected))
        for got, want in zip(command["vertices"], expected):
            self.assertAlmostEqual(got[0], want[0], places=9)
            self.assertAlmostEqual(got[1], want[1], places=9)
        del fig

    def test_steps_alias_resolves_like_steps_pre(self):
        """The bare ``steps`` alias is Matplotlib's pre-step spelling."""
        alias_command = self._command_for("steps")
        pre_command = self._command_for("steps-pre")
        self.assertEqual(alias_command["vertices"], pre_command["vertices"])

    def test_expansion_is_two_n_minus_one_points(self):
        """N input points become exactly 2N-1 output points for pre/post."""
        for drawstyle in ("steps-pre", "steps-post"):
            command = self._command_for(drawstyle)
            self.assertEqual(len(command["vertices"]), 2 * 5 - 1)

    def test_single_point_line_stays_degenerate_refusal(self):
        """One point cannot form a stroke; refusal is preserved verbatim."""
        fig, canvas = _steps_canvas(x=(5.0,), y=(3.0,))
        with self.assertRaises(
            backend_mod.LumenPlotUnsupportedError
        ):
            canvas.render_png()
        del fig

    def test_non_finite_rows_refused_under_steps(self):
        """Stepped lines refuse non-finite samples instead of guessing.

        Agg's path cleaning re-pairs step risers around a NaN gap, so
        neither dropping the row nor bridging it reproduces the oracle
        geometry; LP-MPL-020 forbids silent approximation, so the slice
        refuses explicitly and hybrid mode falls back whole-frame.
        """
        fig, canvas = _steps_canvas()
        ax = fig.get_axes()[0]
        ax.lines[0].remove()
        x = [0.0, 2.5, float("nan"), 7.5, 10.0]
        y = [1.0, 4.0, 99.0, 5.0, 3.0]
        ax.add_line(
            Line2D(
                x,
                y,
                drawstyle="steps-mid",
                color="red",
                linewidth=2.0,
                solid_capstyle="butt",
                solid_joinstyle="miter",
            )
        )
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            canvas.render_png()
        del fig

    def test_single_sided_nan_refused_under_steps(self):
        """A NaN in one coordinate is still a non-finite sample.

        The refusal must not depend on which axis carries it (an earlier
        draft filtered each axis independently and desynced the polyline
        axes); the whole row is non-renderable under a step drawstyle.
        """
        fig, canvas = _steps_canvas()
        ax = fig.get_axes()[0]
        ax.lines[0].remove()
        x = [0.0, 2.5, 5.0, 7.5, 10.0]
        y = [1.0, float("nan"), 2.0, 5.0, 3.0]
        ax.add_line(
            Line2D(
                x,
                y,
                drawstyle="steps-pre",
                color="red",
                linewidth=2.0,
                solid_capstyle="butt",
                solid_joinstyle="miter",
            )
        )
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            canvas.render_png()
        del fig

    def test_default_drawstyle_keeps_historical_row_filtering(self):
        """The default drawstyle's NaN row-drop behavior is unchanged.

        LP-FUNC-034 widens eligibility for finite stepped data only; the
        pre-existing default-style subslice filtering stays exactly as
        shipped (rows with a non-finite coordinate vanish).
        """
        fig, canvas = _steps_canvas(drawstyle="default")
        ax = fig.get_axes()[0]
        ax.lines[0].remove()
        x = [0.0, 2.5, float("nan"), 7.5, 10.0]
        y = [1.0, float("nan"), 99.0, 5.0, 3.0]
        ax.add_line(
            Line2D(
                x,
                y,
                color="red",
                linewidth=2.0,
                solid_capstyle="butt",
                solid_joinstyle="miter",
            )
        )
        canvas.render_png()
        spec = _StubNativeModule.last_spec
        assert spec is not None
        strokes = _step_stroke_commands(spec)
        self.assertEqual(len(strokes), 1)
        # Rows 1 and 2 drop -> 3 kept samples stay unexpanded.
        self.assertEqual(len(strokes[0]["vertices"]), 3)
        import numpy as np

        expected_x = np.asarray([x[i] for i in (0, 3, 4)])
        expected_y = np.asarray([y[i] for i in (0, 3, 4)])
        got = np.asarray(strokes[0]["vertices"])
        bbox = ax.get_window_extent()
        xlim, ylim = ax.get_xlim(), ax.get_ylim()
        want = np.column_stack([
            bbox.x0 + (expected_x - xlim[0]) / (xlim[1] - xlim[0])
            * bbox.width,
            bbox.y0 + (expected_y - ylim[0]) / (ylim[1] - ylim[0])
            * bbox.height,
        ])
        np.testing.assert_allclose(got, want, atol=1e-9)
        del fig

    def test_all_non_finite_rows_stay_degenerate_refusal(self):
        """Every sample non-finite: fewer than two points, still refused."""
        fig, canvas = _steps_canvas()
        ax = fig.get_axes()[0]
        ax.lines[0].remove()
        ax.add_line(
            Line2D(
                [float("nan"), float("nan"), float("nan")],
                [1.0, 4.0, 2.0],
                drawstyle="steps-mid",
                color="red",
                linewidth=2.0,
                solid_capstyle="butt",
                solid_joinstyle="miter",
            )
        )
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            canvas.render_png()
        del fig


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestStepStyleContract(unittest.TestCase):
    """Style surface stays the fixed ADR 0015 §5 set under steps."""

    def setUp(self):
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unknown_drawstyles_stay_rejected(self):
        """Only the step family joins; other values are still refused.

        The static gate is probed directly because Matplotlib's own
        constructor already validates spellings; a hand-set private
        attribute stands in for any future unknown value.
        """
        backend = _load_backend()

        preflight = backend._EligibilityPreflight()
        line = Line2D([0, 1], [0, 1], color="red")
        line._drawstyle = "steps-diagonal"
        preflight._check_line2d_static(line)
        reasons = [reason for _, reason in preflight.reasons]
        self.assertTrue(
            any("drawstyle" in reason for reason in reasons),
            f"unknown drawstyle not refused: {reasons}",
        )

    def test_style_resolution_unchanged_under_steps(self):
        """Stroke color/width/cap/join resolve identically with steps on."""
        fig, canvas = _steps_canvas(drawstyle="steps-post")
        canvas.render_png()
        command = _StubNativeModule.last_spec["commands"][0]
        self.assertEqual(command["cap"], "butt")
        self.assertEqual(command["join"], "miter")
        self.assertEqual(command["stroke_rgba"], [255, 0, 0, 255])
        self.assertEqual(command["line_width_pt"], 2.0)
        self.assertIsNone(command["dashes"])
        del fig

    def test_markers_still_unsupported_on_step_lines(self):
        fig, canvas = _steps_canvas(drawstyle="steps-mid")
        ax = fig.get_axes()[0]
        ax.lines[0].set_marker("o")
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            canvas.render_png()
        del fig


# ---------------------------------------------------------------------------
# Flag C-3: monotonic-topology eligibility survives step expansion
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestStepTopologyRecurrence(unittest.TestCase):
    """Flag C-3: step vertices are exact polyline points, so any topology
    property the engine derives from them must be derivable from the
    original sample too — the expansion is a pure recurrence."""

    def test_expansion_recurrence_is_invertible_to_samples(self):
        """Expansion only inserts horizontal-riser duplicates at constant
        y plus mid-step half-interval points; dropping inserted vertices
        recovers the source samples exactly, so MonotonicX classification
        (LP-LOD-002/004) is invariant under the step transform family."""
        import numpy as np

        x = np.array([0.0, 1.5, 3.0, 6.0, 7.0, 10.0])
        y = np.array([2.0, 5.0, 1.0, 4.0, 2.5, 5.5])
        for drawstyle in ("steps-pre", "steps-post", "steps-mid"):
            with self.subTest(drawstyle=drawstyle):
                step_func = cbook.STEP_LOOKUP_MAP[drawstyle]
                ex, ey = (np.asarray(v) for v in step_func(x, y))
                # The expansion is piecewise-constant between samples: it
                # only relocates each vertical riser (pre = at the left
                # sample, post = at the right sample, mid = halfway) and
                # never reorders or rescales the carried heights.
                for i in range(1, len(ex)):
                    if ex[i] == ex[i - 1]:
                        # A repeated x is the vertical riser carrying the
                        # jump between consecutive sample heights — the
                        # only place the polyline changes level off-sample.
                        pair = (float(ey[i - 1]), float(ey[i]))
                        allowed = {
                            (float(y[k]), float(y[k + 1]))
                            for k in range(len(y) - 1)
                        }
                        self.assertIn(
                            pair,
                            allowed,
                            f"{drawstyle}: riser jumps non-consecutive "
                            "sample heights",
                        )
                # Dropping inserted vertices must recover the source:
                # pre/post alternate sample/duplicate so even positions
                # are verbatim samples. Mid instead walks endpoint ->
                # midpoint pairs, so its ends are the end samples and its
                # interior x are exact half-interval midpoints (the mid
                # polyline never touches interior samples — Agg draws it
                # that way too).
                if drawstyle == "steps-mid":
                    self.assertEqual(float(ex[0]), float(x[0]))
                    self.assertEqual(float(ey[0]), float(y[0]))
                    self.assertEqual(float(ex[-1]), float(x[-1]))
                    self.assertEqual(float(ey[-1]), float(y[-1]))
                    midpoints = [
                        float((x[k] + x[k + 1]) / 2.0)
                        for k in range(len(x) - 1)
                        for _ in range(2)
                    ]
                    self.assertEqual(
                        [float(v) for v in ex[1:-1]], midpoints
                    )
                else:
                    keep = list(range(0, len(ex), 2))
                    recovered_x = [float(ex[i]) for i in keep]
                    recovered_y = [float(ey[i]) for i in keep]
                    self.assertEqual(recovered_x, [float(v) for v in x])
                    self.assertEqual(recovered_y, [float(v) for v in y])
                # Monotone-x sources stay monotone-x after expansion, and
                # the expanded x never decreases faster than the source:
                # this is the property MonotonicX classification leans on.
                differences = np.diff(ex)
                if (np.diff(x) >= 0).all():
                    self.assertGreaterEqual(float(differences.min()), 0.0)

    def test_decreasing_input_stays_decreasing_after_expansion(self):
        """Steps never repair decreasing x: the expansion of a decreasing
        run keeps it decreasing, matching MonotonicX's rejection input."""
        import numpy as np

        x = np.array([0.0, 2.0, 1.0])
        y = np.array([1.0, 2.0, 3.0])
        for drawstyle in ("steps-pre", "steps-post", "steps-mid"):
            with self.subTest(drawstyle=drawstyle):
                step_func = cbook.STEP_LOOKUP_MAP[drawstyle]
                ex = np.asarray(step_func(x, y))[0]
                differences = np.diff(ex)
                self.assertTrue((differences < 0).any())

    def test_engine_topology_accepts_stepped_series_like_source(self):
        """Rust-side recurrence pin (skips when the seam lacks a probe):
        a stepped series classifies exactly like its source samples."""
        try:
            import _native
        except ModuleNotFoundError:
            self.skipTest("real native seam not available")

        classifier = getattr(_native, "series_topology", None)
        if classifier is None:
            self.skipTest(
                "seam exposes no topology probe; C-3 evidence stays at "
                "the pure-recurrence fixtures above"
            )
        stepped_x = [0.0, 1.0, 1.0, 2.0]
        stepped_y = [1.0, 1.0, 3.0, 3.0]
        self.assertEqual(classifier(stepped_x, stepped_y), "monotonic-x")


# ---------------------------------------------------------------------------
# 4. pixel parity vs Agg through the real native seam (LP-MPL-020 artifact 4)
# ---------------------------------------------------------------------------


def _require_real_seam():
    try:
        from lumenplot_mpl import _native  # noqa: F401
    except (ImportError, AttributeError):
        raise unittest.SkipTest("native seam not built in this environment")
    if not hasattr(_native, "render_frame_png"):
        raise unittest.SkipTest("render_frame_png not present yet")


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestStepPixelParity(unittest.TestCase):
    """Native raster evidence for stepped strokes against Agg.

    Thresholds were measured when these fixtures were built (2026-08-26,
    CPython 3.14 + matplotlib 3.11.1 + the lane's abi3 seam) and are
    re-measured whenever the renderer changes: interiors of axis-aligned
    runs match byte-exactly, and every >32 delta pixel sits on a stroke
    edge where Agg's 4px scanline box filter and tiny-skia's analytic
    coverage disagree about phase. The same divergence exists verbatim on
    ``default``-drawstyle strokes (pre-existing engine-wide stroke-AA
    characteristic; the merged fill lane's ratified fixtures pin fills,
    not strokes), so the steps slice records it instead of pretending a
    tighter bound.
    """

    maxDiff = None

    def setUp(self):
        _require_real_seam()

    def _agg_reference(self, drawstyle, y=(1.0, 4.0, 2.0, 5.0, 3.0)):
        import io

        from matplotlib.backends.backend_agg import FigureCanvasAgg

        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.axison = False
        ax.add_line(
            Line2D(
                [0.0, 2.5, 5.0, 7.5, 10.0],
                list(y),
                drawstyle=drawstyle,
                color="red",
                linewidth=2.0,
                solid_capstyle="butt",
                solid_joinstyle="miter",
            )
        )
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(0.0, 6.0)
        FigureCanvasAgg(fig)
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=100)
        return buffer.getvalue()

    def _render_native(self, mode, drawstyle,
                       y=(1.0, 4.0, 2.0, 5.0, 3.0)):
        canvas = _load_backend().FigureCanvasLumenPlot(
            figure.Figure(figsize=(2.0, 1.0), dpi=100), mode=mode
        )
        fig = canvas.figure
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.axison = False
        ax.add_line(
            Line2D(
                [0.0, 2.5, 5.0, 7.5, 10.0],
                list(y),
                drawstyle=drawstyle,
                color="red",
                linewidth=2.0,
                solid_capstyle="butt",
                solid_joinstyle="miter",
            )
        )
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(0.0, 6.0)
        return canvas.render_png()

    def _assert_pixel_parity(self, drawstyle, *, y=(1.0, 4.0, 2.0, 5.0, 3.0),
                             tol=32, min_within_fraction=0.95,
                             worst_cap=228):
        """Decoded-pixel parity with the lane's measured AA allowance.

        ``tol``/``min_within_fraction`` mirror the fill lane's ratified
        numeric definition (>= 95% of pixels within 32 per channel);
        ``worst_cap`` bounds the stroke-edge AA ramp at the largest value
        measured across these workloads (228, on a vertical riser edge).
        """
        agg_bytes = self._agg_reference(drawstyle, y=y)
        result = self._render_native("strict", drawstyle, y=y)
        aw, ah, arows = _decode_rgba8(agg_bytes)
        nw, nh, nrows = _decode_rgba8(result.png_bytes)
        self.assertEqual((aw, ah), (nw, nh))
        import numpy as np

        flat_agg = np.frombuffer(
            b"".join(bytes(r) for r in arows), dtype=np.uint8
        ).astype(int).reshape(-1, 4)
        flat_nat = np.frombuffer(
            b"".join(bytes(r) for r in nrows), dtype=np.uint8
        ).astype(int).reshape(-1, 4)
        deltas = np.abs(flat_agg - flat_nat).max(axis=1)
        worst = int(deltas.max())
        within = float((deltas <= tol).mean())
        self.assertLessEqual(worst, worst_cap)
        self.assertGreaterEqual(
            within, min_within_fraction,
            f"only {within:.4f} of pixels within tolerance {tol} "
            f"(need {min_within_fraction}); worst {worst}",
        )

    def test_steps_pre_pixel_parity(self):
        self._assert_pixel_parity("steps-pre")

    def test_steps_post_pixel_parity(self):
        self._assert_pixel_parity("steps-post")

    def test_steps_mid_pixel_parity(self):
        self._assert_pixel_parity("steps-mid")


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestStepNonFiniteFallback(unittest.TestCase):
    """The step NaN refusal converts to the whole-frame fallback in hybrid.

    The refusal is a stable ``unsupported-capability`` event, so hybrid
    mode must deliver the declared whole-frame Agg fallback with exactly
    one diagnostic -- the same contract every other strict refusal
    honors (ADR 0015 §12, profiles suite).
    """

    def setUp(self):
        _require_real_seam()

    def _nan_canvas(self):
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.axison = False
        ax.add_line(
            Line2D(
                [0.0, 2.5, float("nan"), 7.5, 10.0],
                [1.0, 4.0, 2.0, 5.0, 3.0],
                drawstyle="steps-pre",
                color="red",
                linewidth=2.0,
                solid_capstyle="butt",
                solid_joinstyle="miter",
            )
        )
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(0.0, 6.0)
        return fig

    def test_strict_raises_stable_token(self):
        canvas = _load_backend().FigureCanvasLumenPlot(
            self._nan_canvas(), mode="strict"
        )
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError) as ctx:
            canvas.render_png()
        self.assertEqual(ctx.exception.code, "unsupported-capability")

    def test_hybrid_converts_to_single_whole_frame_fallback(self):
        canvas = _load_backend().FigureCanvasLumenPlot(
            self._nan_canvas(), mode="hybrid"
        )
        result = canvas.render_png()
        self.assertTrue(result.png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(len(result.diagnostics), 1)
        diagnostic = result.diagnostics[0]
        self.assertIsInstance(
            diagnostic, backend_mod.LumenPlotFallbackDiagnostic
        )
        self.assertEqual(diagnostic.kind, "unsupported-capability")
        self.assertEqual(diagnostic.scope, "whole-frame")
        self.assertEqual(diagnostic.representation, "raster")
        self.assertEqual(diagnostic.fallback_type, "matplotlib-agg")


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestStepProfileModes(unittest.TestCase):
    """Both delivery profiles stay pinned on stepped content."""

    def setUp(self):
        _require_real_seam()

    def test_strict_native_renders_without_diagnostics(self):
        result = self._render("strict", "steps-pre")
        self.assertEqual(result.diagnostics, ())
        self.assertTrue(result.png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_hybrid_renders_natively_with_no_fallback_diagnostic(self):
        result = self._render("hybrid", "steps-mid")
        self.assertEqual(result.diagnostics, (),
                         "hybrid must not fall back for eligible steps")
        self.assertTrue(result.png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

    def _render(self, mode, drawstyle):
        canvas = _load_backend().FigureCanvasLumenPlot(
            figure.Figure(figsize=(2.0, 1.0), dpi=100), mode=mode
        )
        fig = canvas.figure
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.axison = False
        ax.add_line(
            Line2D(
                [0.0, 2.5, 5.0, 7.5, 10.0],
                [1.0, 4.0, 2.0, 5.0, 3.0],
                drawstyle=drawstyle,
                color="red",
                linewidth=2.0,
                solid_capstyle="butt",
                solid_joinstyle="miter",
            )
        )
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(0.0, 6.0)
        return canvas.render_png()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
