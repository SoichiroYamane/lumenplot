"""M5-TEXT-1B shaped-layout slice tests (tests a-f, Phase-A spec).

Scope: NEW adapter-level coverage only, against the EXISTING retained
shaping types (engine ``text.rs``) and the EXISTING outline/placement
routes (``python/lumenplot_mpl/textpath.py`` + ``backend_preflight``).
ZERO production-code change: no edits to ``text.rs`` / scene / bridge /
frame / export, no new types, no public API change.

Mapping to the t_be3c8b40 slice-1 tests (adapter half; the engine half
lives in ``crates/lumenplot-engine/tests/text_layout_units.rs``):

- (a) shared-shaping determinism: identical outline inputs produce
  byte-identical commands on every call;
- (b) 1e-6 agreement: the public outline route agrees with ``TextPath``
  for the same ``FontProperties`` within S15.1 part 3, and the declared
  display transform (``p_display = R(angle) @ S(dpi/72) @ p_outline +
  anchor``) re-applied to a strict-render spec glyph agrees within 1e-6
  logical points -- the shared result is projected, never remeasured;
- (c) no-remeasurement gate: ``render-api`` + ``export`` sources contain
  no text measurement/shaping calls, and ``textpath`` never imports the
  private extension module;
- (d) missing-glyph diagnostic: empty / whitespace-only / non-string /
  non-finite inputs raise ``ValueError`` with the stable
  ``unsupported-text-path`` token (never a silent empty command), while
  a representable non-ASCII label yields a deterministic non-blank
  outline;
- (e) clip retention: strict-render label glyph commands carry an
  explicit full-canvas ``clip_rect`` (never dropped), and the outline
  route always carries the explicit ``clip_rect`` key;
- (f) fallback provenance: the label's exact public ``FontProperties``
  flow into the outline (faces change geometry), and a non-
  ``FontProperties`` ``prop`` is refused explicitly instead of falling
  back silently to a system face.

Full-backend cases reuse the stub-native pattern of
``test_phase3b_ticklabels.py`` (no compiled extension required); every
``TextPath`` comparison needs the installed Matplotlib and skips
otherwise.
"""

from __future__ import annotations

import math
import os
import struct
import sys
import types
import unittest
import unittest.mock

try:
    import matplotlib
except ModuleNotFoundError:  # offline cells: shaped-layout evidence is a later slice
    matplotlib = None
else:
    matplotlib.use("module://matplotlib.backends.backend_agg")  # baseline only
    from matplotlib import figure  # noqa: E402
    from matplotlib.font_manager import FontProperties  # noqa: E402
    from matplotlib.lines import Line2D  # noqa: E402
    from matplotlib.textpath import TextPath  # noqa: E402

MATPLOTLIB_PRESENT = matplotlib is not None

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

FORBIDDEN_SINK_TOKENS = (
    "parley",
    "fontique",
    "harfbuzz",
    "harfrust",
    "rustybuzz",
    "swash::",
    "skrifa",
    "fontdb",
    "cosmic_text",
    "ab_glyph",
    "ttf_parser",
    "rusttype",
    "freetype",
    "font_kit",
    "TextPath",
    "FT2Font",
    "set_text",
    "load_glyph",
    "get_char_index",
    "get_path",
    "get_text_width",
    "text_extent",
    "measure_text",
    "shape_text",
    "layout_text",
    "shape_run",
    "measure_run",
    ".measure(",
    "measure_glyph",
    "shaper",
    "reshap",
    "hinting",
    "subsetter",
    "load_font",
    "query_font",
    "font_loader",
)

SINK_SOURCES = (
    ("crates/lumenplot-render-api/src", ("frame.rs", "lib.rs", "packet.rs", "resources.rs")),
    (
        "crates/lumenplot-export/src",
        ("compositor.rs", "error.rs", "lib.rs", "pdf.rs", "png.rs", "raster.rs"),
    ),
)


def _load_textpath():
    import importlib

    return importlib.import_module("lumenplot_mpl.textpath")


def _load_backend():
    import importlib

    return importlib.import_module("lumenplot_mpl.backend")


class _StubNativeModule(types.SimpleNamespace):
    """Stand-in for ``lumenplot_mpl._native`` recording the last spec."""

    last_spec: dict | None = None

    @staticmethod
    def render_frame_png(spec):  # noqa: N802 - mirrors native name
        _StubNativeModule.last_spec = spec
        header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(
            ">IIBBBBB", spec["width_px"], spec["height_px"], 8, 6, 0, 0, 0
        )
        return header + b"\x00\x00\x00\x00IEND\xaeB`\x82"


def _install_stub_native():
    import importlib

    real = importlib.import_module("lumenplot_mpl.backend")
    return unittest.mock.patch.object(real, "_native", lambda: _StubNativeModule)


def _labeled_figure():
    """Build a strict-eligible figure with pinned explicit tick labels."""
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
    return fig, ax


def _strict_render(fig):
    backend = _load_backend()
    return backend.FigureCanvasLumenPlot(fig, mode="strict").render_png()


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestShapedLayoutDeterminism(unittest.TestCase):
    """(a) One shaping result: identical inputs, identical commands."""

    def test_identical_outline_inputs_are_byte_identical(self):
        textpath = _load_textpath()
        prop = FontProperties(family="DejaVu Sans", weight="bold", size=12.0)
        first = textpath.glyph_outline_commands(
            "series-0", (16.0, 16.0), 1.0, 0.0, font_size_pt=12.0, prop=prop
        )
        second = textpath.glyph_outline_commands(
            "series-0", (16.0, 16.0), 1.0, 0.0, font_size_pt=12.0, prop=prop
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        self.assertTrue(first[0]["vertices"])
        self.assertTrue(first[0]["codes"])

    def test_distinct_inputs_stay_distinct(self):
        textpath = _load_textpath()
        prop = FontProperties(family="DejaVu Sans", size=10.0)
        base = textpath.glyph_outline_commands(
            "xa", (0.0, 0.0), 1.0, 0.0, font_size_pt=10.0, prop=prop
        )[0]
        scaled = textpath.glyph_outline_commands(
            "xa", (0.0, 0.0), 2.0, 0.0, font_size_pt=10.0, prop=prop
        )[0]
        moved = textpath.glyph_outline_commands(
            "xa", (5.0, 5.0), 1.0, 0.0, font_size_pt=10.0, prop=prop
        )[0]
        other = textpath.glyph_outline_commands(
            "xb", (0.0, 0.0), 1.0, 0.0, font_size_pt=10.0, prop=prop
        )[0]
        self.assertNotEqual(base["vertices"], scaled["vertices"])
        self.assertNotEqual(base["vertices"], moved["vertices"])
        self.assertNotEqual(base["vertices"], other["vertices"])


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestShapedLayoutAgreement(unittest.TestCase):
    """(b) 1e-6 agreement: outline vs TextPath, spec vs declared transform."""

    def setUp(self):
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)
        _StubNativeModule.last_spec = None

    def test_outline_agrees_with_textpath_within_1e6(self):
        """S15.1 part 3: same FontProperties, 1e-6 logical points."""
        textpath = _load_textpath()
        prop = FontProperties(
            family="DejaVu Sans", style="normal", weight="bold", size=12.0
        )
        got = textpath.glyph_outline_commands(
            "yg", (0.0, 0.0), 1.0, 0.0, font_size_pt=12.0, prop=prop
        )[0]
        reference = TextPath((0.0, 0.0), "yg", size=12.0, prop=prop)
        self.assertEqual(len(got["vertices"]), len(reference.vertices))
        self.assertEqual(len(got["codes"]), len(reference.codes))
        for (gx, gy), (rx, ry) in zip(got["vertices"], reference.vertices):
            self.assertAlmostEqual(gx, float(rx), places=6)
            # The module negates TextPath's y-up sign once per vertex.
            self.assertAlmostEqual(gy, -float(ry), places=6)

    def test_spec_glyphs_agree_with_declared_transform_within_1e6(self):
        """Projected labels match R(angle) @ S(dpi/72) @ outline + anchor.

        The outline is consumed without remeasurement: re-applying the
        one declared matrix to the outline command reproduces the spec
        glyph vertices within 1e-6 logical points.
        """
        textpath = _load_textpath()
        fig, _ax = _labeled_figure()
        result = _strict_render(fig)
        self.assertEqual(result.diagnostics, ())
        commands = _StubNativeModule.last_spec["commands"]
        glyphs = [c for c in commands if c.get("decoration") == "tick_label"]
        self.assertEqual(len(glyphs), 4)
        # Re-derive the expected vertices from the outline route plus the
        # anchor/angle the collector payloads recorded, mirroring
        # ``_tick_label_commands`` without calling it.
        import importlib

        preflight_mod = importlib.import_module("lumenplot_mpl.backend_preflight")
        preflight = preflight_mod._EligibilityPreflight()
        preflight.check_static(fig)
        self.assertEqual(preflight.reasons, [])
        preflight.collect(fig, width_px=200, height_px=100, dpi=100.0)
        self.assertEqual(preflight.reasons, [])
        dpi = preflight._effective_dpi
        scale = dpi / 72.0
        height_px = float(preflight._height_px)
        self.assertEqual(len(preflight._observed_text_payloads), len(glyphs))
        for command, payload in zip(glyphs, preflight._observed_text_payloads):
            label = payload["artist"]
            outline = textpath._writer_glyph_outline_commands(
                str(label.get_text()),
                (0.0, 0.0),
                1.0,
                0.0,
                font_size_pt=float(label.get_fontsize()),
                prop=label.get_fontproperties(),
                dpi=dpi,
            )[0]
            theta = math.radians(float(payload["angle"]))
            cos_t, sin_t = math.cos(theta), math.sin(theta)
            anchor_x, anchor_y = float(payload["x"]), float(payload["y"])
            self.assertEqual(len(command["vertices"]), len(outline["vertices"]))
            for (cx, cy), (vx, vy) in zip(command["vertices"], outline["vertices"]):
                px, py = vx * scale, vy * scale
                expected_x = anchor_x + px * cos_t + py * sin_t
                expected_y = height_px - (anchor_y - px * sin_t + py * cos_t)
                self.assertAlmostEqual(cx, expected_x, places=6)
                self.assertAlmostEqual(cy, expected_y, places=6)


class TestNoRemeasurementGate(unittest.TestCase):
    """(c) Sinks never remeasure: static source gate + seam hygiene."""

    def test_render_api_and_export_have_no_shaping_calls(self):
        scanned_files = 0
        scanned_lines = 0
        for crate_dir, sources in SINK_SOURCES:
            for source in sources:
                path = os.path.join(REPO_ROOT, crate_dir, source)
                self.assertTrue(
                    os.path.isfile(path), f"gate source missing: {path}"
                )
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                scanned_files += 1
                for lineno, line in enumerate(text.splitlines(), start=1):
                    code = line.lstrip()
                    if code.startswith("//"):
                        continue
                    scanned_lines += 1
                    for token in FORBIDDEN_SINK_TOKENS:
                        self.assertNotIn(
                            token,
                            code,
                            f"{path}:{lineno}: sink remeasurement spelling "
                            f"{token!r} in {code!r}",
                        )
        self.assertEqual(scanned_files, 10, "gate must cover all 10 sink sources")
        self.assertGreater(
            scanned_lines,
            1000,
            f"gate scanned only {scanned_lines} code lines; refusing a vacuous pass",
        )

    def test_textpath_never_imports_the_private_seam(self):
        path = os.path.join(REPO_ROOT, "python", "lumenplot_mpl", "textpath.py")
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("_native", text)


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestMissingGlyphDiagnostic(unittest.TestCase):
    """(d) No silent blank: explicit diagnostic or deterministic outline."""

    def test_blank_inputs_raise_the_stable_token(self):
        textpath = _load_textpath()
        for bad in ("", "   ", "\t\n"):
            with self.subTest(text=repr(bad)):
                with self.assertRaises(ValueError) as ctx:
                    textpath.glyph_outline_commands(bad, (0.0, 0.0), 1.0, 0.0)
                self.assertIn("unsupported-text-path", str(ctx.exception))

    def test_non_string_and_non_finite_inputs_raise_only_valueerror(self):
        textpath = _load_textpath()
        with self.assertRaises(ValueError) as ctx:
            textpath.glyph_outline_commands(None, (0.0, 0.0), 1.0, 0.0)  # type: ignore[arg-type]
        self.assertIn("unsupported-text-path", str(ctx.exception))
        for origin, scale, shear, size in (
            ((float("nan"), 0.0), 1.0, 0.0, 10.0),
            ((0.0, float("inf")), 1.0, 0.0, 10.0),
            ((0.0, 0.0), float("nan"), 0.0, 10.0),
            ((0.0, 0.0), 1.0, float("inf"), 10.0),
        ):
            with self.subTest(origin=origin, scale=scale, shear=shear, size=size):
                # Every non-finite argument fails closed through _as_float.
                with self.assertRaises(ValueError) as ctx:
                    textpath.glyph_outline_commands(
                        "xa", origin, scale, shear, font_size_pt=size
                    )
                self.assertIn("unsupported-text-path", str(ctx.exception))

    def test_representable_non_ascii_label_yields_deterministic_outline(self):
        textpath = _load_textpath()
        prop = FontProperties(family="DejaVu Sans", size=10.0)
        first = textpath.glyph_outline_commands(
            "caf\u00e9", (0.0, 0.0), 1.0, 0.0, font_size_pt=10.0, prop=prop
        )
        second = textpath.glyph_outline_commands(
            "caf\u00e9", (0.0, 0.0), 1.0, 0.0, font_size_pt=10.0, prop=prop
        )
        self.assertEqual(first, second)
        self.assertTrue(first[0]["vertices"], "never a silent blank")
        self.assertTrue(first[0]["codes"])


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestClipRetention(unittest.TestCase):
    """(e) Clip/stack retention: explicit clip on every label glyph."""

    def setUp(self):
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)
        _StubNativeModule.last_spec = None

    def test_outline_route_carries_the_explicit_clip_key(self):
        textpath = _load_textpath()
        command = textpath.glyph_outline_commands(
            "xa", (0.0, 0.0), 1.0, 0.0, font_size_pt=10.0
        )[0]
        self.assertIn("clip_rect", command)
        # Clip is applied by the frame assembler; the outline route
        # records that explicitly instead of dropping the field.
        self.assertIsNone(command["clip_rect"])

    def test_strict_spec_glyphs_carry_full_canvas_clip(self):
        fig, _ax = _labeled_figure()
        result = _strict_render(fig)
        self.assertEqual(result.diagnostics, ())
        spec = _StubNativeModule.last_spec
        width_px, height_px = spec["width_px"], spec["height_px"]
        glyphs = [c for c in spec["commands"] if c.get("decoration") == "tick_label"]
        self.assertEqual(len(glyphs), 4)
        for command in glyphs:
            self.assertIn("clip_rect", command)
            clip = command["clip_rect"]
            self.assertIsNotNone(clip, "label clip must survive, never drop")
            self.assertEqual(
                [float(v) for v in clip],
                [0.0, 0.0, float(width_px), float(height_px)],
            )


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestFallbackProvenance(unittest.TestCase):
    """(f) Provenance recorded: exact face in, explicit refusal out."""

    def test_label_face_flows_into_the_outline(self):
        textpath = _load_textpath()
        normal = textpath.glyph_outline_commands(
            "xa",
            (0.0, 0.0),
            1.0,
            0.0,
            font_size_pt=10.0,
            prop=FontProperties(weight="normal", style="normal"),
        )[0]
        bold = textpath.glyph_outline_commands(
            "xa",
            (0.0, 0.0),
            1.0,
            0.0,
            font_size_pt=10.0,
            prop=FontProperties(weight="bold", style="normal"),
        )[0]
        italic = textpath.glyph_outline_commands(
            "xa",
            (0.0, 0.0),
            1.0,
            0.0,
            font_size_pt=10.0,
            prop=FontProperties(weight="normal", style="italic"),
        )[0]
        self.assertNotEqual(bold["vertices"], normal["vertices"])
        self.assertNotEqual(italic["vertices"], normal["vertices"])

    def test_non_fontproperties_prop_is_refused_explicitly(self):
        textpath = _load_textpath()
        with self.assertRaises(ValueError) as ctx:
            textpath.glyph_outline_commands(
                "xa",
                (0.0, 0.0),
                1.0,
                0.0,
                font_size_pt=10.0,
                prop="bold",  # type: ignore[arg-type]
            )
        # No silent system-face fallback: the refusal names its reason.
        self.assertIn("unsupported-text-path", str(ctx.exception))

    def test_tex_math_label_is_strict_unsupported(self):
        backend = _load_backend()
        fig, ax = _labeled_figure()
        ax.set_xticklabels(["$xa$", "xb"])
        with self.assertRaises(backend.LumenPlotUnsupportedError) as ctx:
            _strict_render(fig)
        # TeX takes the explicit-fallback-or-unsupported route only.
        self.assertIn("math/TeX", str(ctx.exception))


if __name__ == "__main__":
    sys.path.insert(0, REPO_ROOT)
    unittest.main()
