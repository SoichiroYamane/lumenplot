"""B-2a axis-label contract tests (LP-MPL-020, R2 subset).

Covers the four per-class mechanics for the visible non-empty
``xlabel``/``ylabel`` pair rendered natively as one kind:image
coverage-blit command per label (axis-label slice: ADR 0015
section 4b route; xlabel/ylabel eligible, titles refused):

- M1 whitelist: a default decorated axes with visible xlabel/ylabel is
  strict-eligible; the ``_check_axis_label_static`` surface (shared
  ``_check_tick_label_static`` contract plus hyperlink refusal) keeps
  refusing titles (center/left/right), offset text, multi-line labels,
  leading/trailing whitespace, math/TeX text, path effects,
  non-positive font size, sketch, snap, custom clipping, and
  hyperlinks.
- M2 collector trace: the stage-two ``draw_text`` queue observes labels
  in draw order (x-ticks, xlabel, y-ticks, ylabel) and the emitted spec
  carries one kind:image command per label in that order with the
  ``axis_label`` decoration marker (never outline keys); empty or
  invisible axis labels draw nothing.
- M3 style contract: the label's own public ``FontProperties``
  (family/style/weight) and resolved size flow into the coverage mask
  through ``lumenplot_mpl.textpath._label_coverage_mask`` at the output
  DPI with the hinting flag; faces change the mask, anchored by the
  same Matplotlib-provided anchor math and composited agg_srgb.
- M4 strict behavior: a refused label raises before any native write and
  hybrid mode falls back whole-frame with exactly one diagnostic.

Pixel parity against the pinned Agg oracle lives in
``test_agg_oracle_axislabels.py``; this module needs only the stub seam.
No strict native pixel gate is asserted here (spine-fringe red).
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

    real = importlib.import_module("lumenplot_mpl.backend_strict")
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

    def test_center_title_is_strict_eligible(self):
        # B-2a (R3) Q1-remainder ruling: the visible non-empty center
        # title is eligible; left/right titles stay refused below.
        fig, ax = _labeled_figure()
        ax.set_title("hello")
        result = _strict_render(fig)
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(ax.get_title("center"), "hello")

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
        ax.set_title("bad title", loc="left")
        backend = _load_backend()
        with self.assertRaises(backend.LumenPlotUnsupportedError):
            _strict_render(fig)
        self.assertIsNone(_StubNativeModule.last_spec)

    def test_hybrid_refused_label_falls_back_with_one_diagnostic(self):
        """M4: hybrid renders refused labels once through whole-frame Agg."""
        fig, ax = _labeled_figure()
        ax.set_title("bad title", loc="left")
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

    def test_spec_carries_one_blit_command_per_label_in_order(self):
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)
        fig, _ax = _labeled_figure()
        result = _strict_render(fig)
        self.assertEqual(result.diagnostics, ())
        commands = _StubNativeModule.last_spec["commands"]
        blits = [c for c in commands if c.get("decoration") == "axis_label"]
        self.assertEqual(len(blits), 2)
        # Representation pin: coverage-blit image commands, never an
        # outline path and never outline keys on an image command.
        for command in blits:
            self.assertEqual(command["kind"], "image")
            for absent in ("codes", "vertices", "fill_rgba", "stroke_rgba"):
                self.assertNotIn(absent, command)
        ticks = [c for c in commands if c.get("decoration") == "tick_label"]
        self.assertEqual(len(ticks), 4)
        # Blit commands paint after every axes content command: the text
        # wire-up owns the emission position (backend.py z-order contract).
        last_content = max(
            index
            for index, command in enumerate(commands)
            if command.get("decoration") not in ("tick_label", "axis_label")
        )
        first_blit = min(
            index
            for index, command in enumerate(commands)
            if command.get("decoration") in ("tick_label", "axis_label")
        )
        self.assertGreater(first_blit, last_content)
        # Draw-order pin: the xlabel blit queues after the x-tick blits
        # and before the y-tick blits; the ylabel blit queues last.
        order = [c.get("decoration") for c in commands
                 if c.get("decoration") in ("tick_label", "axis_label")]
        self.assertEqual(
            order,
            ["tick_label", "tick_label", "axis_label",
             "tick_label", "tick_label", "axis_label"],
        )

    def test_spec_empty_and_invisible_axis_labels_draw_nothing(self):
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)
        fig, ax = _labeled_figure()
        ax.set_xlabel("")
        ax.set_ylabel("")
        result = _strict_render(fig)
        self.assertEqual(result.diagnostics, ())
        commands = _StubNativeModule.last_spec["commands"]
        self.assertEqual(
            [c for c in commands if c.get("decoration") == "axis_label"], []
        )
        fig, ax = _labeled_figure()
        ax.xaxis.get_label().set_visible(False)
        ax.yaxis.get_label().set_visible(False)
        result = _strict_render(fig)
        self.assertEqual(result.diagnostics, ())
        commands = _StubNativeModule.last_spec["commands"]
        self.assertEqual(
            [c for c in commands if c.get("decoration") == "axis_label"], []
        )


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
        blits = [
            c
            for c in _StubNativeModule.last_spec["commands"]
            if c.get("decoration") == "axis_label"
        ]
        self.assertEqual(len(blits), 2)
        for command in blits:
            self.assertEqual(command["kind"], "image")

    def test_face_changes_coverage_mask(self):
        """The face must flow into the coverage mask (catches prop drift)."""
        textpath = _load_textpath()
        normal = textpath._label_coverage_mask(
            "xlab",
            100.0,
            20.0,
            100.0,
            0.0,
            font_size_pt=10.0,
            prop=FontProperties(weight="normal", style="normal"),
            dpi=100.0,
        )
        bold = textpath._label_coverage_mask(
            "xlab",
            100.0,
            20.0,
            100.0,
            0.0,
            font_size_pt=10.0,
            prop=FontProperties(weight="bold", style="normal"),
            dpi=100.0,
        )
        italic = textpath._label_coverage_mask(
            "xlab",
            100.0,
            20.0,
            100.0,
            0.0,
            font_size_pt=10.0,
            prop=FontProperties(weight="normal", style="italic"),
            dpi=100.0,
        )
        self.assertNotEqual(bytes(bold[4]), bytes(normal[4]))
        self.assertNotEqual(bytes(italic[4]), bytes(normal[4]))

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

    def test_spec_axis_label_blits_carry_resolved_faces(self):
        """End to end: each spec axis-label blit rides its label face's mask."""
        import importlib

        textpath = _load_textpath()
        support = importlib.import_module("lumenplot_mpl.backend_support")
        preflight_mod = _load_preflight()
        fig, ax = _labeled_figure()
        ax.xaxis.get_label().set_weight("bold")
        preflight = preflight_mod._EligibilityPreflight()
        preflight.check_static(fig)
        self.assertEqual(preflight.reasons, [])
        preflight.collect(fig, width_px=200, height_px=100, dpi=100.0)
        self.assertEqual(preflight.reasons, [])
        real_mask = textpath._label_coverage_mask
        calls: list = []

        def recording_mask(*args, **kwargs):
            result = real_mask(*args, **kwargs)
            calls.append((args, kwargs, result))
            return result

        with unittest.mock.patch.object(
            textpath, "_label_coverage_mask", recording_mask
        ):
            spec = preflight.build_frame_spec(
                fig, width_px=200, height_px=100, output_dpi=100.0
            )
        self.assertEqual(preflight.reasons, [])
        blits = [c for c in spec["commands"]
                 if c.get("decoration") == "axis_label"]
        payloads = [p for p in preflight._observed_text_payloads
                    if p.get("kind") == "axis_label"]
        self.assertEqual(len(blits), len(payloads))
        self.assertEqual(len(blits), 2)
        # One coverage-helper call per axis label, in draw order: the
        # xlabel first, then the rotated ylabel (angle rides the existing
        # parameterization, pinned here rather than redesigned).
        label_calls = [call for call in calls
                       if call[0][0] in ("xlab", "ylab")]
        self.assertEqual([call[0][0] for call in label_calls],
                         ["xlab", "ylab"])
        for command, payload, call in zip(blits, payloads, label_calls):
            label = payload["artist"]
            args, kwargs, outcome = call
            self.assertEqual(args[0], str(label.get_text()))
            self.assertEqual(args[3], 100.0)
            self.assertEqual(args[4], float(label.get_rotation()))
            # Only finiteness is pinned on the anchor here while exact
            # geometry rides the command pins below.
            for anchor in (args[1], args[2]):
                self.assertTrue(anchor == anchor)
                self.assertLess(abs(float(anchor)), 1e9)
            self.assertEqual(kwargs["font_size_pt"], float(label.get_fontsize()))
            self.assertEqual(kwargs["dpi"], 100.0)
            label_prop = label.get_fontproperties()
            self.assertEqual(
                tuple(kwargs["prop"].get_family()),
                tuple(label_prop.get_family()),
            )
            self.assertEqual(
                kwargs["prop"].get_style(), label_prop.get_style()
            )
            self.assertEqual(
                kwargs["prop"].get_weight(), label_prop.get_weight()
            )
            self.assertEqual(
                kwargs["prop"].get_size_in_points(),
                float(label.get_fontsize()),
            )
            left_col, top_row, mask_w, mask_h, mask = outcome
            style = support._rgba8(label.get_color(), label.get_alpha())
            # Representation pin: coverage-blit image command, never an
            # outline path and never outline keys on an image command.
            self.assertEqual(command["kind"], "image")
            self.assertEqual(command["decoration"], "axis_label")
            for absent in ("codes", "vertices", "fill_rgba", "stroke_rgba"):
                self.assertNotIn(absent, command)
            self.assertEqual(command["x"], float(left_col))
            self.assertEqual(
                command["y"], float(100.0 - (top_row + mask_h))
            )
            self.assertEqual(command["width"], mask_w)
            self.assertEqual(command["height"], mask_h)
            self.assertEqual(command["clip_rect"], [0.0, 0.0, 200.0, 100.0])
            self.assertGreater(mask_w, 0)
            self.assertGreater(mask_h, 0)
            self.assertTrue(any(mask))
            # Wire pin: every blit pixel carries the label color with the
            # helper coverage folded into alpha, packed per the adapter.
            raw_rgba = bytes(command["rgba"])
            self.assertEqual(len(raw_rgba), 4 * mask_w * mask_h)
            expected_rgba = bytearray(4 * mask_w * mask_h)
            for index, cover in enumerate(mask):
                expected_rgba[4 * index] = style[0]
                expected_rgba[4 * index + 1] = style[1]
                expected_rgba[4 * index + 2] = style[2]
                expected_rgba[4 * index + 3] = textpath._agg_multiply_byte(
                    style[3], int(cover)
                )
            self.assertEqual(raw_rgba, bytes(expected_rgba))
