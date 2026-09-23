"""Focused Agg-oracle tests for the center-title + axes-box fixture (B-2a R3).

The semantic checks run without the compiled extension.  A strict native
pixel comparison is deliberately NOT asserted here: tick ink rides as
coverage-blit image commands (per-label helper pins below) while the
title glyph keeps its per-face topology pin below, but the
0.8pt spine/tick-stroke antialiased fringe exceeds the fixed S15.1 fringe
budget on the current native rasterizer, while tolerances, spine geometry
paths, and native crates are all frozen for this lane.  The committed
reference, mask, and manifest below pin the oracle side so a future
native spine-stroke lane can add the pixel gate without regenerating
evidence.  The manifest contract (schema ``agg-oracle-manifest-v1``,
byte-equal background/fully-covered, fringe delta 1, mismatch rate
0.001) is UNCHANGED from the tick-label fixture.
"""

from __future__ import annotations

import hashlib
import importlib
import unittest
import unittest.mock
from pathlib import Path
from typing import Any

import numpy as np

try:
    from ._agg_oracle import (
        PIXEL_CLASS_CODES,
        load_reference_fixture,
    )
except ImportError:  # ``unittest discover -s tests/python``
    from _agg_oracle import (
        PIXEL_CLASS_CODES,
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
        from .generate_agg_oracle_titles import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            TITLE,
            XTICKLABELS,
            YTICKLABELS,
            build_fixture_figure,
            fixture_rc_context,
            public_axis_topology,
            render_reference,
        )
    except ImportError:  # ``unittest discover -s tests/python``
        from generate_agg_oracle_titles import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            TITLE,
            XTICKLABELS,
            YTICKLABELS,
            build_fixture_figure,
            fixture_rc_context,
            public_axis_topology,
            render_reference,
        )
else:
    EFFECTIVE_DPI = 0.0
    FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
    MANIFEST_PATH = FIXTURE_DIR / "title_manifest.json"
    ORACLE_MATPLOTLIB_VERSION = "3.11.1"
    TITLE = "ctitle"
    XTICKLABELS = ("0", "5", "10")
    YTICKLABELS = ("0", "5")


def _require_pinned_matplotlib() -> None:
    if not MATPLOTLIB_PRESENT:
        raise unittest.SkipTest("Matplotlib is not installed in this test cell")
    assert matplotlib is not None
    if matplotlib.__version__ != ORACLE_MATPLOTLIB_VERSION:
        raise unittest.SkipTest(
            "Agg fixture requires Matplotlib "
            f"{ORACLE_MATPLOTLIB_VERSION}; found {matplotlib.__version__}"
        )


class TestCommittedTitleFixture(unittest.TestCase):
    """The committed fixture is generated and checked without native code."""

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixture = load_reference_fixture(MANIFEST_PATH)

    def test_manifest_records_pinned_render_contract_and_digests(self):
        manifest = self.fixture.manifest
        self.assertEqual(
            manifest["fixture_id"],
            "center-title-axes-box-spines",
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
        self.assertEqual(manifest["artist_class"], "matplotlib.text.Text")
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
            manifest["primitive"]["ticklabels"],
            {
                "xticks": [0.0, 5.0, 10.0],
                "xticklabels": ["0", "5", "10"],
                "yticks": [0.0, 5.0],
                "yticklabels": ["0", "5"],
            },
        )
        self.assertEqual(
            manifest["primitive"]["title"],
            {"center": "ctitle", "left": "", "right": ""},
        )
        # UNCHANGED manifest contract: same schema and thresholds as the
        # tick-label fixture.
        self.assertEqual(manifest["schema_version"], "agg-oracle-manifest-v1")
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

    def test_public_axis_surface_matches_manifest(self):
        """Boundary tick texts/title come from public getters only."""

        with fixture_rc_context():
            _figure, axes = build_fixture_figure()
            topology = public_axis_topology(axes)
        self.assertEqual(topology["xticklocs"], [0.0, 5.0, 10.0])
        self.assertEqual(topology["xticklabels"], ["0", "5", "10"])
        self.assertEqual(topology["yticklocs"], [0.0, 5.0])
        self.assertEqual(topology["yticklabels"], ["0", "5"])
        self.assertEqual(topology["title_center"], "ctitle")
        self.assertEqual(topology["title_left"], "")
        self.assertEqual(topology["title_right"], "")
        self.assertEqual(topology, self.fixture.manifest["topology"])
        self.assertEqual(
            set(np.unique(self.fixture.mask.labels)),
            {
                PIXEL_CLASS_CODES["background"],
                PIXEL_CLASS_CODES["fully-covered"],
                PIXEL_CLASS_CODES["antialias-fringe"],
            },
        )


class TestTitleAdapterSemantics(unittest.TestCase):
    """The adapter spec reproduces the fixture surface without native code."""

    def setUp(self):
        _require_pinned_matplotlib()

    def _capture_spec(self):
        backend = importlib.import_module("lumenplot_mpl.backend")
        captured: dict[str, Any] = {}

        def capture_spec(spec, _generation):
            captured.update(spec)
            return b"native-spec-only"

        with fixture_rc_context():
            figure, _axes = build_fixture_figure()
            canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
            with unittest.mock.patch.object(
                canvas, "_call_native", side_effect=capture_spec
            ):
                result = canvas.render_png(dpi=EFFECTIVE_DPI)
        self.assertEqual(result.diagnostics, ())
        commands = captured["commands"]
        self.assertIsInstance(commands, list)
        return commands

    def test_strict_spec_carries_six_glyph_commands_in_draw_order(self):
        """Tick blits + title outline queue x-ticks/y-ticks/title."""

        textpath = importlib.import_module("lumenplot_mpl.textpath")
        support = importlib.import_module("lumenplot_mpl.backend_support")
        real_mask = textpath._label_coverage_mask
        calls: list = []

        def recording_mask(*args, **kwargs):
            result = real_mask(*args, **kwargs)
            calls.append((args, kwargs, result))
            return result

        with unittest.mock.patch.object(
            textpath, "_label_coverage_mask", recording_mask
        ):
            commands = self._capture_spec()
        ticks = [c for c in commands if c.get("decoration") == "tick_label"]
        titles = [c for c in commands if c.get("decoration") == "title"]
        self.assertEqual(len(ticks), len(XTICKLABELS) + len(YTICKLABELS))
        self.assertEqual(len(titles), 1)
        with fixture_rc_context():
            _figure, axes = build_fixture_figure()
            expected_order = []
            for label in axes.xaxis.get_majorticklabels():
                if label.get_visible() and label.get_text() != "":
                    expected_order.append((label.get_text(), "tick_label"))
            for label in axes.yaxis.get_majorticklabels():
                if label.get_visible() and label.get_text() != "":
                    expected_order.append((label.get_text(), "tick_label"))
            expected_order.append((axes.get_title("center"), "title"))
            tick_labels = [
                label
                for axis in (axes.xaxis, axes.yaxis)
                for label in axis.get_majorticklabels()
                if label.get_visible() and label.get_text() != ""
            ]
        self.assertEqual(
            expected_order,
            [("0", "tick_label"), ("5", "tick_label"), ("10", "tick_label"),
             ("0", "tick_label"), ("5", "tick_label"),
             ("ctitle", "title")],
        )
        glyphs = [c for c in commands
                  if c.get("decoration") in ("tick_label", "title")]
        self.assertEqual(len(glyphs), len(expected_order))
        self.assertEqual(
            [label.get_text() for label in tick_labels],
            ["0", "5", "10", "0", "5"],
        )
        self.assertEqual(len(ticks), len(tick_labels))
        # One coverage-helper call per tick label, in draw order.
        self.assertEqual(len(calls), len(tick_labels))
        for command, label, call in zip(ticks, tick_labels, calls):
            args, kwargs, outcome = call
            self.assertEqual(args[0], str(label.get_text()))
            self.assertEqual(args[3], 100.0)
            self.assertEqual(args[4], float(label.get_rotation()))
            # Tick anchors may sit off-canvas (x labels below the axes);
            # only finiteness is pinned here while exact geometry rides
            # the command pins below.
            for anchor in (args[1], args[2]):
                self.assertTrue(anchor == anchor)
                self.assertLess(abs(float(anchor)), 1e9)
            self.assertEqual(kwargs["font_size_pt"], float(label.get_fontsize()))
            self.assertEqual(kwargs["dpi"], EFFECTIVE_DPI)
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
            self.assertEqual(command["decoration"], "tick_label")
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
            for index in range(mask_w * mask_h):
                self.assertEqual(
                    tuple(raw_rgba[4 * index:4 * index + 3]), tuple(style[:3])
                )
                self.assertEqual(
                    raw_rgba[4 * index + 3],
                    textpath._agg_multiply_byte(style[3], int(mask[index])),
                )
        # The title glyph keeps the outline route pins.
        for command in titles:
            self.assertEqual(command["fill_rgba"], [0, 0, 0, 255])
            self.assertIsNone(command["stroke_rgba"])
        # The title glyph keeps its own label face's topology.
        with fixture_rc_context():
            _figure, axes = build_fixture_figure()
            label = axes.title
        expected = textpath.glyph_outline_commands(
            str(label.get_text()),
            (0.0, 0.0),
            1.0,
            0.0,
            font_size_pt=float(label.get_fontsize()),
            prop=label.get_fontproperties(),
        )[0]
        self.assertEqual(titles[0]["codes"], expected["codes"])
        self.assertEqual(len(titles[0]["vertices"]), len(expected["vertices"]))

    def test_strict_spec_spines_trace_the_axes_box(self):
        """All four visible spine edges ride the fixture axes rectangle."""

        commands = self._capture_spec()
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
        # Axes rect (0.22, 0.25, 0.66, 0.45) of 200x100px in seam
        # bottom-left px: x0=44, y0=25, x1=176, y1=70.
        self.assertEqual(
            segments,
            {
                (44.0, 25.0, 176.0, 25.0),
                (44.0, 70.0, 176.0, 70.0),
                (44.0, 25.0, 44.0, 70.0),
                (176.0, 25.0, 176.0, 70.0),
            },
        )
        for command in spines:
            # Default spines carry the artist's projecting caps (Matplotlib
            # Spine default; pinned Agg draw_path reports cap=projecting
            # for every 0.8pt spine stroke), not butt.
            self.assertEqual(command["cap"], "projecting")
            self.assertEqual(command["join"], "miter")

    def test_strict_spec_carries_the_axis_aligned_fill(self):
        """The eligible polygon content fills exactly its data rectangle."""

        commands = self._capture_spec()
        fills = [
            c
            for c in commands
            if c.get("kind") == "path"
            and c.get("fill_rgba") == [255, 0, 0, 255]
        ]
        self.assertEqual(len(fills), 1)
        xs = [v[0] for v in fills[0]["vertices"]]
        ys = [v[1] for v in fills[0]["vertices"]]
        # Data (2,1)-(8,4) through axes (0.22,0.25,0.66,0.45) at 200x100:
        # x = 44 + value/10*132, y = 25 + value/5*45.
        self.assertAlmostEqual(min(xs), 70.4, places=6)
        self.assertAlmostEqual(max(xs), 149.6, places=6)
        self.assertAlmostEqual(min(ys), 34.0, places=6)
        self.assertAlmostEqual(max(ys), 61.0, places=6)
