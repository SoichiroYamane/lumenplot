"""B-2a axis-label contract tests (LP-MPL-020, R2 subset).

Covers the four per-class mechanics for the visible non-empty
``xlabel``/``ylabel`` pair rendered natively as filled glyph-outline
path commands (B-2a R2: xlabel/ylabel eligible, titles refused):

- M1 whitelist: a default decorated axes with visible xlabel/ylabel is
  strict-eligible; the ``_check_axis_label_static`` surface (shared
  ``_check_tick_label_static`` contract plus hyperlink refusal) keeps
  refusing titles (center/left/right), offset text, multi-line labels,
  leading/trailing whitespace, math/TeX text, path effects,
  non-positive font size, sketch, snap, custom clipping, and
  hyperlinks.
- M2 collector trace: the stage-two ``draw_text`` queue observes labels
  in draw order (x-ticks, xlabel, y-ticks, ylabel) and the emitted spec
  carries one glyph command per label in that order with the
  ``axis_label`` decoration marker.
- M3 style contract: the label's own public ``FontProperties``
  (family/style/weight) and resolved size flow into the outline through
  ``lumenplot_mpl.textpath``; faces change geometry, and outlines agree
  with ``TextPath`` for the same properties within S15.1 part 3 (1e-6).
- M4 strict behavior: a refused label raises before any native write and
  hybrid mode falls back whole-frame with exactly one diagnostic.

Pixel parity against the pinned Agg oracle lives in
``test_agg_oracle_axislabels.py``; this module needs only the stub seam.
"""

from __future__ import annotations

import types
import unittest
import unittest.mock

try:
    import matplotlib
except ModuleNotFoundError:  # offline cells: axis-label evidence is a later slice
    matplotlib = None
else:
    matplotlib.use("module://matplotlib.backends.backend_agg")  # baseline only

    from matplotlib import figure  # noqa: E402
    from matplotlib.font_manager import FontProperties  # noqa: E402
    from matplotlib.lines import Line2D  # noqa: E402
    from matplotlib.textpath import TextPath  # noqa: E402

MATPLOTLIB_PRESENT = matplotlib is not None


def _load_backend():
    import importlib

    return importlib.import_module("lumenplot_mpl.backend")


def _load_preflight():
    import importlib

    return importlib.import_module("lumenplot_mpl.backend_preflight")


def _load_textpath():
    import importlib

    return importlib.import_module("lumenplot_mpl.textpath")


class _StubNativeModule(types.SimpleNamespace):
    """Stand-in for ``lumenplot_mpl._native`` recording the last spec."""

    last_spec: dict | None = None

    @staticmethod
    def render_frame_png(spec):  # noqa: N802 - mirrors native name
        _StubNativeModule.last_spec = spec
        import struct

        header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(
            ">IIBBBBB", spec["width_px"], spec["height_px"], 8, 6, 0, 0, 0
        )
        return header + b"\x00\x00\x00\x00IEND\xaeB`\x82"


def _install_stub_native():
    import importlib

    real = importlib.import_module("lumenplot_mpl.backend")
    return unittest.mock.patch.object(real, "_native", lambda: _StubNativeModule)


def _labeled_figure():
    """Build a strict-eligible figure with pinned tick + axis labels."""
    fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
    ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
    ax.set_facecolor("none")
    ax.add_line(
        Line2D(
            [0, 10],
            [0, 5],
            color="red",
            linewidth=2.0,
            solid_capstyle="butt",
            solid_joinstyle="miter",
        )
    )
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(0.0, 5.0)
    ax.set_xticks([0.0, 10.0])
    ax.set_xticklabels(["xa", "xb"])
    ax.set_yticks([0.0, 5.0])
    ax.set_yticklabels(["ya", "yb"])
    ax.set_xlabel("xlab")
    ax.set_ylabel("ylab")
    return fig, ax


def _strict_render(fig):
    backend = _load_backend()
    return backend.FigureCanvasLumenPlot(fig, mode="strict").render_png()


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestAxisLabelWhitelist(unittest.TestCase):
    """M1 whitelist entry plus the negative surface (B-2a R2)."""

    def setUp(self):
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)
        _StubNativeModule.last_spec = None

    def test_xlabel_ylabel_are_strict_eligible(self):
        fig, ax = _labeled_figure()
        result = _strict_render(fig)
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(ax.get_xlabel(), "xlab")
        self.assertEqual(ax.get_ylabel(), "ylab")

    def test_empty_labels_stay_eligible(self):
        fig, ax = _labeled_figure()
        ax.set_xlabel("")
        ax.set_ylabel("")
        result = _strict_render(fig)
        self.assertEqual(result.diagnostics, ())

    def test_center_title_refused(self):
        fig, ax = _labeled_figure()
        ax.set_title("hello")
        backend = _load_backend()
        with self.assertRaises(backend.LumenPlotUnsupportedError):
            _strict_render(fig)

    def test_left_and_right_titles_refused(self):
        for loc in ("left", "right"):
            with self.subTest(loc=loc):
                fig, ax = _labeled_figure()
                ax.set_title("hello", loc=loc)
                backend = _load_backend()
                with self.assertRaises(backend.LumenPlotUnsupportedError):
                    _strict_render(fig)

    def test_offset_text_refused(self):
        # Natural offset: large limits with the default scalar formatter
        # materialize a non-empty offset text at draw time.
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.set_facecolor("none")
        ax.add_line(
            Line2D(
                [1e9, 1e9 + 10],
                [0, 5],
                color="red",
                linewidth=2.0,
                solid_capstyle="butt",
                solid_joinstyle="miter",
            )
        )
        ax.set_xlim(1e9, 1e9 + 10)
        ax.set_ylim(0.0, 5.0)
        backend = _load_backend()
        with self.assertRaises(backend.LumenPlotUnsupportedError):
            _strict_render(fig)

    def test_multiline_axis_label_refused(self):
        fig, ax = _labeled_figure()
        ax.set_xlabel("xa\nxb")
        backend = _load_backend()
        with self.assertRaises(backend.LumenPlotUnsupportedError):
            _strict_render(fig)
        preflight_mod = _load_preflight()
        preflight = preflight_mod._EligibilityPreflight()
        preflight._check_axis_label_static(ax.xaxis.get_label())
        self.assertTrue(
            any("multi-line" in reason for _, reason in preflight.reasons),
            f"multi-line guard did not fire: {preflight.reasons!r}",
        )

    def test_leading_trailing_whitespace_refused(self):
        for text in (" xlab", "xlab ", " xlab "):
            with self.subTest(text=text):
                fig, ax = _labeled_figure()
                ax.set_xlabel(text)
                backend = _load_backend()
                with self.assertRaises(backend.LumenPlotUnsupportedError) as ctx:
                    _strict_render(fig)
                self.assertIn("whitespace", str(ctx.exception))

    def test_math_text_refused(self):
        fig, ax = _labeled_figure()
        ax.set_xlabel("$xlab$")
        backend = _load_backend()
        with self.assertRaises(backend.LumenPlotUnsupportedError) as ctx:
            _strict_render(fig)
        self.assertIn("math/TeX", str(ctx.exception))

    def test_path_effects_refused(self):
        from matplotlib import patheffects

        fig, ax = _labeled_figure()
        label = ax.xaxis.get_label()
        label.set_path_effects(
            [patheffects.withStroke(linewidth=2, foreground="red")]
        )
        preflight_mod = _load_preflight()
        preflight = preflight_mod._EligibilityPreflight()
        preflight._check_axis_label_static(label)
        self.assertTrue(
            any("path effects" in reason for _, reason in preflight.reasons),
            f"path-effects guard did not fire: {preflight.reasons!r}",
        )

    def test_non_positive_font_size_refused(self):
        fig, ax = _labeled_figure()
        label = ax.xaxis.get_label()
        preflight_mod = _load_preflight()
        preflight = preflight_mod._EligibilityPreflight()
        with unittest.mock.patch.object(label, "get_fontsize", return_value=0):
            preflight._check_axis_label_static(label)
        self.assertTrue(
            any("font size" in reason for _, reason in preflight.reasons),
            f"font-size guard did not fire: {preflight.reasons!r}",
        )

    def test_sketch_refused(self):
        fig, ax = _labeled_figure()
        ax.xaxis.get_label().set_sketch_params(
            scale=1.0, length=128.0, randomness=16.0
        )
        backend = _load_backend()
        with self.assertRaises(backend.LumenPlotUnsupportedError) as ctx:
            _strict_render(fig)
        self.assertIn("sketch", str(ctx.exception))

    def test_explicit_snap_refused(self):
        fig, ax = _labeled_figure()
        ax.xaxis.get_label().set_snap(True)
        backend = _load_backend()
        with self.assertRaises(backend.LumenPlotUnsupportedError) as ctx:
            _strict_render(fig)
        self.assertIn("snap", str(ctx.exception))

    def test_custom_clip_refused(self):
        from matplotlib.transforms import Bbox

        fig, ax = _labeled_figure()
        ax.xaxis.get_label().set_clip_box(
            Bbox([[0.0, 0.0], [10.0, 10.0]])
        )
        backend = _load_backend()
        with self.assertRaises(backend.LumenPlotUnsupportedError) as ctx:
            _strict_render(fig)
        self.assertIn("clipping", str(ctx.exception))

    def test_hyperlink_refused(self):
        fig, ax = _labeled_figure()
        ax.xaxis.get_label().set_url("https://example.invalid/")
        preflight_mod = _load_preflight()
        preflight = preflight_mod._EligibilityPreflight()
        preflight._check_axis_label_static(ax.xaxis.get_label())
        self.assertTrue(
            any("hyperlink" in reason for _, reason in preflight.reasons),
            f"hyperlink guard did not fire: {preflight.reasons!r}",
        )

    def test_refusal_writes_nothing_to_native_seam(self):
        """M4: strict mode fails before writing (no partial publication)."""
        fig, ax = _labeled_figure()
        ax.set_title("bad title")
        backend = _load_backend()
        with self.assertRaises(backend.LumenPlotUnsupportedError):
            _strict_render(fig)
        self.assertIsNone(_StubNativeModule.last_spec)

    def test_hybrid_refused_label_falls_back_with_one_diagnostic(self):
        """M4: hybrid renders refused labels once through whole-frame Agg."""
        fig, ax = _labeled_figure()
        ax.set_title("bad title")
        backend = _load_backend()
        canvas = backend.FigureCanvasLumenPlot(fig, mode="hybrid")
        result = canvas.render_png()
        self.assertEqual(len(result.diagnostics), 1)
        diagnostic = result.diagnostics[0]
        self.assertEqual(diagnostic.kind, "unsupported-capability")
        self.assertEqual(diagnostic.scope, "whole-frame")
        self.assertEqual(diagnostic.fallback_type, "matplotlib-agg")


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestAxisLabelDrawOrder(unittest.TestCase):
    """M2 collector-trace expectation: labels queue in draw order."""

    def _collect_texts(self, fig):
        preflight_mod = _load_preflight()
        preflight = preflight_mod._EligibilityPreflight()
        preflight.check_static(fig)
        self.assertEqual(preflight.reasons, [])
        preflight.collect(fig, width_px=200, height_px=100, dpi=100.0)
        self.assertEqual(preflight.reasons, [])
        return [
            (p["artist"].get_text(), p.get("kind", "tick_label"))
            for p in preflight._observed_text_payloads
        ]

    def test_xlabel_after_xticks_before_yticks(self):
        fig, _ax = _labeled_figure()
        self.assertEqual(
            self._collect_texts(fig),
            [
                ("xa", "tick_label"),
                ("xb", "tick_label"),
                ("xlab", "axis_label"),
                ("ya", "tick_label"),
                ("yb", "tick_label"),
                ("ylab", "axis_label"),
            ],
        )

    def test_xlabel_only_queues_after_xticks(self):
        fig, ax = _labeled_figure()
        ax.set_ylabel("")
        self.assertEqual(
            self._collect_texts(fig),
            [
                ("xa", "tick_label"),
                ("xb", "tick_label"),
                ("xlab", "axis_label"),
                ("ya", "tick_label"),
                ("yb", "tick_label"),
            ],
        )

    def test_spec_carries_one_glyph_command_per_label_in_order(self):
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)
        fig, _ax = _labeled_figure()
        result = _strict_render(fig)
        self.assertEqual(result.diagnostics, ())
        commands = _StubNativeModule.last_spec["commands"]
        glyphs = [c for c in commands if c.get("decoration") == "axis_label"]
        self.assertEqual(len(glyphs), 2)
        ticks = [c for c in commands if c.get("decoration") == "tick_label"]
        self.assertEqual(len(ticks), 4)
        # Glyph commands paint after every axes content command: the text
        # wire-up owns the emission position (backend.py z-order contract).
        last_content = max(
            index
            for index, command in enumerate(commands)
            if command.get("decoration") not in ("tick_label", "axis_label")
        )
        first_glyph = min(
            index
            for index, command in enumerate(commands)
            if command.get("decoration") in ("tick_label", "axis_label")
        )
        self.assertGreater(first_glyph, last_content)


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestAxisLabelStyleContract(unittest.TestCase):
    """M3 style contract: the label face resolves into the outline."""

    def setUp(self):
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)
        _StubNativeModule.last_spec = None

    def test_bold_and_italic_labels_are_eligible(self):
        fig, ax = _labeled_figure()
        ax.xaxis.get_label().set_weight("bold")
        ax.yaxis.get_label().set_style("italic")
        result = _strict_render(fig)
        self.assertEqual(result.diagnostics, ())
        glyphs = [
            c
            for c in _StubNativeModule.last_spec["commands"]
            if c.get("decoration") == "axis_label"
        ]
        self.assertEqual(len(glyphs), 2)

    def test_face_changes_outline_geometry(self):
        """The face must flow into the outline (catches prop=None drift)."""
        textpath = _load_textpath()
        normal = textpath.glyph_outline_commands(
            "xlab",
            (0.0, 0.0),
            1.0,
            0.0,
            font_size_pt=10.0,
            prop=FontProperties(weight="normal", style="normal"),
        )[0]
        bold = textpath.glyph_outline_commands(
            "xlab",
            (0.0, 0.0),
            1.0,
            0.0,
            font_size_pt=10.0,
            prop=FontProperties(weight="bold", style="normal"),
        )[0]
        italic = textpath.glyph_outline_commands(
            "xlab",
            (0.0, 0.0),
            1.0,
            0.0,
            font_size_pt=10.0,
            prop=FontProperties(weight="normal", style="italic"),
        )[0]
        self.assertNotEqual(bold["vertices"], normal["vertices"])
        self.assertNotEqual(italic["vertices"], normal["vertices"])

    def test_outline_matches_textpath_within_s151(self):
        """S15.1 part 3: outline vertices agree within 1e-6 logical points."""
        textpath = _load_textpath()
        prop = FontProperties(family="DejaVu Sans", style="normal",
                              weight="bold", size=12.0)
        got = textpath.glyph_outline_commands(
            "yg", (0.0, 0.0), 1.0, 0.0, font_size_pt=12.0, prop=prop
        )[0]
        reference = TextPath((0.0, 0.0), "yg", size=12.0, prop=prop)
        self.assertEqual(len(got["vertices"]), len(reference.vertices))
        self.assertEqual(
            [int(code) for code in reference.codes],
            [self._seam_to_path(code) for code in got["codes"]],
        )
        for (gx, gy), (rx, ry) in zip(got["vertices"], reference.vertices):
            self.assertAlmostEqual(gx, float(rx), places=6)
            # The module negates TextPath's y-up sign once per vertex.
            self.assertAlmostEqual(gy, -float(ry), places=6)

    @staticmethod
    def _seam_to_path(code: int) -> int:
        from matplotlib.path import Path

        return {
            0: Path.STOP,
            1: Path.MOVETO,
            2: Path.LINETO,
            3: Path.CURVE3,
            4: Path.CURVE4,
            79: Path.CLOSEPOLY,
        }[code]

    def test_non_fontproperties_prop_refused(self):
        textpath = _load_textpath()
        with self.assertRaises(ValueError) as ctx:
            textpath.glyph_outline_commands(
                "xlab", (0.0, 0.0), 1.0, 0.0, font_size_pt=10.0,
                prop="bold",  # type: ignore[arg-type]
            )
        self.assertIn("unsupported-text-path", str(ctx.exception))

    def test_spec_glyph_topology_matches_resolved_face(self):
        """End to end: each spec glyph keeps its label face's topology."""
        from matplotlib.path import Path

        textpath = _load_textpath()
        preflight_mod = _load_preflight()
        fig, ax = _labeled_figure()
        ax.xaxis.get_label().set_weight("bold")
        preflight = preflight_mod._EligibilityPreflight()
        preflight.check_static(fig)
        self.assertEqual(preflight.reasons, [])
        preflight.collect(fig, width_px=200, height_px=100, dpi=100.0)
        self.assertEqual(preflight.reasons, [])
        spec = preflight.build_frame_spec(
            fig, width_px=200, height_px=100, output_dpi=100.0
        )
        self.assertEqual(preflight.reasons, [])
        glyphs = [c for c in spec["commands"] if c.get("decoration") == "axis_label"]
        payloads = [p for p in preflight._observed_text_payloads
                    if p.get("kind") == "axis_label"]
        self.assertEqual(len(glyphs), len(payloads))
        self.assertEqual(len(glyphs), 2)
        for command, payload in zip(glyphs, payloads):
            label = payload["artist"]
            expected = textpath.glyph_outline_commands(
                str(label.get_text()),
                (0.0, 0.0),
                1.0,
                0.0,
                font_size_pt=float(label.get_fontsize()),
                prop=label.get_fontproperties(),
            )[0]
            # An affine placement never changes topology: same codes and
            # vertex count as the resolved-face outline.
            self.assertEqual(command["codes"], expected["codes"])
            self.assertEqual(len(command["vertices"]), len(expected["vertices"]))
            reference = TextPath(
                (0.0, 0.0),
                str(label.get_text()),
                size=float(label.get_fontsize()),
                prop=label.get_fontproperties(),
            )
            # The seam vocabulary reuses the Path code numerics, so the
            # resolved-face outline must carry the TextPath codes verbatim.
            self.assertEqual(expected["codes"], [int(code) for code in reference.codes])
