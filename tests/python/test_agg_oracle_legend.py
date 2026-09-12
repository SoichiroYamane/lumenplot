"""Focused Agg-oracle tests for the line-handle legend fixture.

The semantic checks run without the compiled extension.  The pixel comparison
is deliberately a separate strict native test: it is skipped with an explicit
setup reason when ``lumenplot_mpl._native.render_frame_png`` is unavailable and
never substitutes a stub or Agg fallback as parity evidence.
"""

from __future__ import annotations

import hashlib
import importlib
import unittest
import unittest.mock
from pathlib import Path

import numpy as np

try:
    from ._agg_oracle import (
        PIXEL_CLASS_CODES,
        assert_png_parity,
        load_reference_fixture,
    )
except ImportError:  # ``unittest discover -s tests/python``
    from _agg_oracle import (
        PIXEL_CLASS_CODES,
        assert_png_parity,
        load_reference_fixture,
    )

try:
    import matplotlib
except ModuleNotFoundError:  # offline cells may omit the optional oracle stack
    matplotlib = None
    MATPLOTLIB_PRESENT = False
else:
    MATPLOTLIB_PRESENT = True

if MATPLOTLIB_PRESENT:
    try:
        from .generate_agg_oracle_legend import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            XLIM,
            YLIM,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
    except ImportError:  # ``unittest discover -s tests/python``
        from generate_agg_oracle_legend import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            XLIM,
            YLIM,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
else:
    EFFECTIVE_DPI = 0.0
    FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
    MANIFEST_PATH = FIXTURE_DIR / "legend_manifest.json"
    ORACLE_MATPLOTLIB_VERSION = "3.11.1"
    XLIM = (0.0, 10.0)
    YLIM = (0.0, 5.0)


def _require_pinned_matplotlib() -> None:
    if not MATPLOTLIB_PRESENT:
        raise unittest.SkipTest("Matplotlib is not installed in this test cell")
    assert matplotlib is not None
    if matplotlib.__version__ != ORACLE_MATPLOTLIB_VERSION:
        raise unittest.SkipTest(
            "Agg fixture requires Matplotlib "
            f"{ORACLE_MATPLOTLIB_VERSION}; found {matplotlib.__version__}"
        )


def _require_real_native_seam():
    """Return the compiled frame seam or skip for an environment setup gap."""

    try:
        native = importlib.import_module("lumenplot_mpl._native")
    except (ImportError, AttributeError) as error:
        raise unittest.SkipTest(
            f"compiled native seam unavailable: {error}"
        ) from error
    render_frame_png = getattr(native, "render_frame_png", None)
    if not callable(render_frame_png):
        raise unittest.SkipTest(
            "compiled native seam unavailable: "
            "lumenplot_mpl._native.render_frame_png is missing"
        )
    return native


class TestCommittedLegendFixture(unittest.TestCase):
    """The committed fixture is generated and checked without native code."""

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixture = load_reference_fixture(MANIFEST_PATH)

    def test_manifest_records_pinned_render_contract_and_digests(self):
        manifest = self.fixture.manifest
        self.assertEqual(
            manifest["fixture_id"],
            "legend-line-handles-framed-single-column",
        )
        self.assertEqual(manifest["oracle"]["backend"], "FigureCanvasAgg")
        self.assertEqual(manifest["oracle"]["matplotlib_version"], "3.11.1")
        self.assertEqual(manifest["oracle"]["api_version"], "1.1")
        self.assertEqual(
            manifest["oracle"]["canvas_construction"],
            "matplotlib.backends.backend_agg.FigureCanvasAgg(figure)",
        )
        self.assertEqual(
            manifest["oracle"]["render_call"],
            "canvas.print_png(buffer, metadata={})",
        )
        self.assertEqual(
            manifest["figure"]["construction"],
            "matplotlib.figure.Figure(figsize=(2.0, 1.0), dpi=100.0, "
            "facecolor='white', edgecolor='white')",
        )
        self.assertEqual(manifest["effective_dpi"], EFFECTIVE_DPI)
        self.assertEqual(manifest["dimensions"], {"width": 200, "height": 100})
        self.assertEqual(manifest["orientation"], "top-to-bottom")
        self.assertEqual(manifest["channels"], "RGBA8")
        self.assertEqual(manifest["artist_class"], "matplotlib.legend.Legend")
        self.assertEqual(
            manifest["primitive"]["class"], "matplotlib.legend.Legend"
        )
        self.assertEqual(
            manifest["primitive"]["legend"],
            {
                "loc": "upper right",
                "frameon": True,
                "labels": ["alpha", "beta"],
            },
        )
        self.assertEqual(
            manifest["figure"]["options"]["axis_on"], True
        )
        self.assertEqual(manifest["figure"]["options"]["legend_loc"], "upper right")
        self.assertEqual(manifest["figure"]["options"]["legend_frameon"], True)
        self.assertEqual(manifest["figure"]["options"]["xticks"], [])
        self.assertEqual(manifest["figure"]["options"]["yticks"], [])
        self.assertEqual(
            manifest["font"]["bytes_sha256"], manifest["font_bytes_sha256"]
        )
        self.assertEqual(
            hashlib.sha256(self.fixture.reference_png).hexdigest(),
            manifest["reference_png_sha256"],
        )
        self.assertEqual(
            hashlib.sha256((FIXTURE_DIR / manifest["mask_file"]).read_bytes()).hexdigest(),
            manifest["mask_sha256"],
        )
        self.assertEqual(
            manifest["input_data"]["cases"],
            {
                "alpha": {
                    "artist": "matplotlib.lines.Line2D",
                    "color": "red",
                    "label": "alpha",
                },
                "beta": {
                    "artist": "matplotlib.lines.Line2D",
                    "color": "blue",
                    "label": "beta",
                },
            },
        )
        # Fixed S15.1 contract values are pinned verbatim; this test guards
        # against any tolerance widening in the committed manifest.
        self.assertEqual(
            manifest["contract"],
            {
                "orientation": "top-to-bottom",
                "channels": "RGBA8",
                "background": "byte-equal",
                "fully-covered": "byte-equal",
                "fringe_max_channel_delta": 1,
                "fringe_mismatch_rate_denominator": "total-pixels",
                "fringe_mismatch_rate_max": 0.001,
            },
        )

    def test_generator_reproduces_committed_png_mask_and_topology(self):
        generated_png, generated_mask, generated_topology, dimensions = (
            render_reference()
        )
        self.assertEqual(generated_png, self.fixture.reference_png)
        self.assertTrue(np.array_equal(generated_mask, self.fixture.mask.labels))
        self.assertEqual(dimensions, (200, 100))
        self.assertEqual(generated_topology, self.fixture.manifest["topology"])

    def test_legend_topology_pins_handles_frame_and_labels(self):
        """The committed topology carries the exact legend surface."""

        topology = self.fixture.manifest["topology"]
        self.assertEqual(topology["scales"], {"x": "linear", "y": "linear"})
        self.assertEqual(topology["limits"], {"xlim": [0.0, 10.0], "ylim": [0.0, 5.0]})
        self.assertTrue(topology["axis_on"])
        self.assertEqual(topology["xticks"], [])
        self.assertEqual(topology["yticks"], [])
        content = topology["content_lines"]
        self.assertEqual(len(content), 2)
        self.assertEqual([c["label"] for c in content], ["alpha", "beta"])
        self.assertEqual([c["color"] for c in content], ["red", "blue"])
        for entry in content:
            self.assertEqual(entry["linewidth"], 2.0)
            self.assertEqual(entry["linestyle"], "-")
            self.assertEqual(entry["drawstyle"], "default")
            self.assertEqual(entry["marker"], "None")
            self.assertEqual(entry["segment_count"], 2)
            self.assertEqual(entry["segment_codes"], [1, 2])
        self.assertEqual(
            content[0]["vertices"], [[0.0, 0.0], [10.0, 5.0]]
        )
        self.assertEqual(
            content[1]["vertices"], [[0.0, 5.0], [10.0, 0.0]]
        )
        # Display vertices equal the public transData projection of the data
        # through the fixed axes box (x0=20, y0=10, w=160, h=80).
        for (dx, _dy), x in zip(content[0]["display_vertices"], (0.0, 10.0)):
            self.assertAlmostEqual(dx, 20.0 + (x - 0.0) / 10.0 * 160.0, places=6)
        for (_dx, dy), y in zip(content[0]["display_vertices"], (0.0, 5.0)):
            self.assertAlmostEqual(dy, 10.0 + (y - 0.0) / 5.0 * 80.0, places=6)
        with fixture_rc_context():
            _figure, axes, _legend, lines = build_fixture_figure()
            data_alpha = np.column_stack(
                [np.asarray((0.0, 10.0)), np.asarray((0.0, 5.0))]
            )
            expected_alpha = axes.transData.transform(data_alpha).tolist()
            data_beta = np.column_stack(
                [np.asarray((0.0, 10.0)), np.asarray((5.0, 0.0))]
            )
            expected_beta = axes.transData.transform(data_beta).tolist()
            del lines
        np.testing.assert_allclose(
            np.asarray(content[0]["display_vertices"], dtype=float),
            np.asarray(expected_alpha, dtype=float),
            atol=1e-9,
        )
        np.testing.assert_allclose(
            np.asarray(content[1]["display_vertices"], dtype=float),
            np.asarray(expected_beta, dtype=float),
            atol=1e-9,
        )
        legend = topology["legend"]
        self.assertEqual(
            legend["class"], "matplotlib.legend.Legend"
        )
        self.assertEqual(legend["loc"], "upper right")
        self.assertTrue(legend["frameon"])
        self.assertEqual(legend["entry_count"], 2)
        self.assertEqual(legend["handle_count"], 2)
        self.assertEqual(legend["label_texts"], ["alpha", "beta"])
        frame = legend["frame"]
        self.assertEqual(
            frame["class"], "matplotlib.patches.FancyBboxPatch"
        )
        self.assertTrue(frame["boxstyle"].endswith(".Round"))
        self.assertEqual(frame["facecolor"], [1.0, 1.0, 1.0, 1.0])
        self.assertEqual(frame["edgecolor"], [0.0, 0.0, 0.0, 1.0])
        self.assertEqual(frame["linewidth"], 1.0)
        self.assertTrue(frame["fill"])
        self.assertEqual(
            [e["label"] for e in legend["entries"]], ["alpha", "beta"]
        )
        self.assertEqual(
            [e["handle_color"] for e in legend["entries"]], ["red", "blue"]
        )
        for entry in legend["entries"]:
            self.assertEqual(entry["handle_linewidth"], 2.0)
            self.assertEqual(entry["handle_linestyle"], "-")
            self.assertEqual(entry["handle_drawstyle"], "default")
            self.assertEqual(entry["label_fontsize"], 10.0)
        # Spines stay visible on this axes-on fixture with default width.
        for side in ("bottom", "top", "left", "right"):
            self.assertTrue(topology["spines"][side]["visible"])
            self.assertEqual(topology["spines"][side]["linewidth"], 0.8)
        # Non-vacuous pixel classes: background, ink, and fringe all present;
        # this axes-on legend frame carries no text-or-outline class.
        self.assertEqual(
            set(np.unique(self.fixture.mask.labels)),
            {
                PIXEL_CLASS_CODES["background"],
                PIXEL_CLASS_CODES["fully-covered"],
                PIXEL_CLASS_CODES["antialias-fringe"],
            },
        )
        counts = {
            name: int((self.fixture.mask.labels == code).sum())
            for name, code in PIXEL_CLASS_CODES.items()
        }
        self.assertGreater(counts["background"], 0)
        self.assertGreater(counts["fully-covered"], 0)
        self.assertGreater(counts["antialias-fringe"], 0)
        self.assertEqual(counts["text-or-outline"], 0)


class TestLegendAdapterSemantics(unittest.TestCase):
    """The adapter spec reproduces the fixture surface without native code."""

    def setUp(self):
        _require_pinned_matplotlib()

    def _capture_spec(self):
        backend = importlib.import_module("lumenplot_mpl.backend")
        captured: dict = {}

        def capture_spec(spec, _generation):
            captured.update(spec)
            return b"native-spec-only"

        with fixture_rc_context():
            figure, _axes, _legend, _lines = build_fixture_figure()
            canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
            with unittest.mock.patch.object(
                canvas, "_call_native", side_effect=capture_spec
            ):
                result = canvas.render_png(dpi=EFFECTIVE_DPI)
        self.assertEqual(result.diagnostics, ())
        commands = captured["commands"]
        self.assertIsInstance(commands, list)
        return commands

    def test_strict_spec_carries_two_content_strokes_on_agg_projection(self):
        """The native spec holds two strokes on the Agg-projected polylines."""

        from matplotlib.colors import to_rgba

        def rgba8(name):
            return [int(v) for v in np.rint(np.asarray(to_rgba(name)) * 255.0)]

        commands = self._capture_spec()
        content = [c for c in commands if c.get("decoration") is None]
        self.assertEqual(len(content), 2)
        by_stroke = {tuple(c["stroke_rgba"]): c for c in content}
        self.assertEqual(set(by_stroke), {(255, 0, 0, 255), (0, 0, 255, 255)})
        for command in content:
            self.assertEqual(command["kind"], "path")
            self.assertIsNone(command.get("fill_rgba"))
            self.assertEqual(command["line_width_pt"], 2.0)
            self.assertEqual(command["cap"], "butt")
            self.assertEqual(command["join"], "miter")
            self.assertIsNone(command["dashes"])
            self.assertIsNone(command["codes"])
            self.assertEqual(command["clip_rect"], [20.0, 10.0, 160.0, 80.0])
        self.assertEqual(by_stroke[(255, 0, 0, 255)]["stroke_rgba"], rgba8("red"))
        self.assertEqual(by_stroke[(0, 0, 255, 255)]["stroke_rgba"], rgba8("blue"))
        topology = load_reference_fixture(MANIFEST_PATH).manifest["topology"]
        expected = {
            spec["color"]: np.asarray(
                next(
                    line["display_vertices"]
                    for line in topology["content_lines"]
                    if line["color"] == spec["color"]
                ),
                dtype=float,
            )
            for spec in ({"color": "red"}, {"color": "blue"})
        }
        for command in content:
            key = (
                "red"
                if tuple(command["stroke_rgba"]) == (255, 0, 0, 255)
                else "blue"
            )
            got = np.asarray(command["vertices"], dtype=float)
            self.assertEqual(got.shape, (2, 2))
            np.testing.assert_allclose(got, expected[key], atol=1e-9)

    def test_strict_spec_carries_framed_legend_surface(self):
        """One frame, two handles, and two labels ride the legend group."""

        commands = self._capture_spec()
        frames = [c for c in commands if c.get("decoration") == "legend_frame"]
        handles = [c for c in commands if c.get("decoration") == "legend_handle"]
        labels = [c for c in commands if c.get("decoration") == "legend_label"]
        self.assertEqual(len(frames), 1)
        self.assertEqual(len(handles), 2)
        self.assertEqual(len(labels), 2)
        frame = frames[0]
        self.assertEqual(frame["fill_rgba"], [255, 255, 255, 255])
        self.assertEqual(frame["stroke_rgba"], [0, 0, 0, 255])
        self.assertEqual(frame["line_width_pt"], 1.0)
        self.assertEqual(frame["clip_rect"], [0.0, 0.0, 200.0, 100.0])
        codes = {int(code) for code in frame["codes"]}
        self.assertIn(3, codes)
        by_stroke = {tuple(c["stroke_rgba"]): c for c in handles}
        self.assertEqual(set(by_stroke), {(255, 0, 0, 255), (0, 0, 255, 255)})
        for command in handles:
            self.assertIsNone(command.get("fill_rgba"))
            self.assertEqual(command["line_width_pt"], 2.0)
            self.assertEqual(command["cap"], "butt")
            self.assertEqual(command["join"], "miter")
        # No tick strokes on this empty-tick fixture; spines carry the axes.
        ticks = [c for c in commands if c.get("decoration") == "tick"]
        self.assertEqual(ticks, [])
        spines = [c for c in commands if c.get("decoration") == "spine"]
        self.assertEqual(len(spines), 4)
        segments = {
            (
                round(command["vertices"][0][0], 6),
                round(command["vertices"][0][1], 6),
                round(command["vertices"][1][0], 6),
                round(command["vertices"][1][1], 6),
            )
            for command in spines
        }
        self.assertEqual(
            segments,
            {
                (20.0, 10.0, 180.0, 10.0),
                (20.0, 90.0, 180.0, 90.0),
                (20.0, 10.0, 20.0, 90.0),
                (180.0, 10.0, 180.0, 90.0),
            },
        )

    def test_strict_spec_legend_labels_match_textpath_extraction(self):
        """Each legend label glyph matches the public textpath outline."""

        textpath = importlib.import_module("lumenplot_mpl.textpath")
        commands = self._capture_spec()
        labels = [c for c in commands if c.get("decoration") == "legend_label"]
        self.assertEqual(len(labels), 2)
        with fixture_rc_context():
            _figure, _axes, legend, _lines = build_fixture_figure()
            texts = list(legend.get_texts())
        self.assertEqual([t.get_text() for t in texts], ["alpha", "beta"])
        self.assertEqual(len(labels), len(texts))
        for command, label in zip(labels, texts):
            expected = textpath.glyph_outline_commands(
                str(label.get_text()),
                (0.0, 0.0),
                1.0,
                0.0,
                font_size_pt=float(label.get_fontsize()),
                prop=label.get_fontproperties(),
            )[0]
            self.assertEqual(command["codes"], expected["codes"])
            self.assertEqual(len(command["vertices"]), len(expected["vertices"]))
            self.assertEqual(command["fill_rgba"], [0, 0, 0, 255])
            self.assertIsNone(command["stroke_rgba"])


class TestLegendNativeAggParity(unittest.TestCase):
    """Compare the fixed input through the real adapter/native seam only."""

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixture = load_reference_fixture(MANIFEST_PATH)
        # This must remain a real-extension check.  No recording stub or
        # hybrid/Agg fallback is permitted to make the pixel assertion pass.
        self.native = _require_real_native_seam()

    def test_strict_native_render_matches_fixed_agg_reference(self):
        backend = importlib.import_module("lumenplot_mpl.backend")
        with fixture_rc_context():
            figure, _axes, _legend, _lines = build_fixture_figure()
            canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
            result = canvas.render_png(dpi=EFFECTIVE_DPI)
        self.assertEqual(result.diagnostics, ())
        report = assert_png_parity(
            self.fixture.reference_png,
            result.png_bytes,
            self.fixture.mask,
            manifest=self.fixture.manifest,
        )
        self.assertTrue(report.passed, report.summary())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
