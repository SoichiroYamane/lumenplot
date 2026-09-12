"""Focused Agg-oracle tests for the tick-label + axes-box fixture.

The semantic checks run without the compiled extension.  A strict native
pixel comparison is deliberately NOT asserted here: glyph outline
placement resolves exactly (zero-offset, per-face topology below) but the
0.8pt spine/tick-stroke antialiased fringe exceeds the fixed S15.1 fringe
budget on the current native rasterizer, while tolerances, spine geometry
paths, and native crates are all frozen for this lane.  The committed
reference, mask, and manifest below pin the oracle side so a future
native spine-stroke lane can add the pixel gate without regenerating
evidence.  Measured local evidence (current-base seam): glyph-only ink
93% overlap at zero offset with good core fill; spine/tick thin-stroke
fringe mismatches ~1100px over the 20px budget; no tolerance, API, or
schema change was made to accommodate it.
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
        from .generate_agg_oracle_ticklabels import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            XTICKLABELS,
            YTICKLABELS,
            build_fixture_figure,
            fixture_rc_context,
            public_tick_topology,
            render_reference,
        )
    except ImportError:  # ``unittest discover -s tests/python``
        from generate_agg_oracle_ticklabels import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            XTICKLABELS,
            YTICKLABELS,
            build_fixture_figure,
            fixture_rc_context,
            public_tick_topology,
            render_reference,
        )
else:
    EFFECTIVE_DPI = 0.0
    FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
    MANIFEST_PATH = FIXTURE_DIR / "ticklabels_manifest.json"
    ORACLE_MATPLOTLIB_VERSION = "3.11.1"
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


class TestCommittedTickLabelFixture(unittest.TestCase):
    """The committed fixture is generated and checked without native code."""

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixture = load_reference_fixture(MANIFEST_PATH)

    def test_manifest_records_pinned_render_contract_and_digests(self):
        manifest = self.fixture.manifest
        self.assertEqual(
            manifest["fixture_id"],
            "tick-labels-major-xticks-yticks-axes-box-spines",
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

    def test_generator_reproduces_committed_png_mask_and_topology(self):
        generated_png, generated_mask, generated_topology, dimensions = (
            render_reference()
        )
        self.assertEqual(generated_png, self.fixture.reference_png)
        self.assertTrue(np.array_equal(generated_mask, self.fixture.mask.labels))
        self.assertEqual(dimensions, (200, 100))
        self.assertEqual(generated_topology, self.fixture.manifest["topology"])

    def test_public_tick_surface_matches_manifest(self):
        """Boundary tick texts/locations come from public getters only."""

        with fixture_rc_context():
            _figure, axes = build_fixture_figure()
            topology = public_tick_topology(axes)
        self.assertEqual(topology["xticklocs"], [0.0, 5.0, 10.0])
        self.assertEqual(topology["xticklabels"], ["0", "5", "10"])
        self.assertEqual(topology["yticklocs"], [0.0, 5.0])
        self.assertEqual(topology["yticklabels"], ["0", "5"])
        self.assertEqual(topology, self.fixture.manifest["topology"])
        self.assertEqual(
            set(np.unique(self.fixture.mask.labels)),
            {
                PIXEL_CLASS_CODES["background"],
                PIXEL_CLASS_CODES["fully-covered"],
                PIXEL_CLASS_CODES["antialias-fringe"],
            },
        )


class TestTickLabelAdapterSemantics(unittest.TestCase):
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

    def test_strict_spec_carries_five_glyph_commands_in_draw_order(self):
        """One resolved-face glyph command per visible major label, x first."""

        textpath = importlib.import_module("lumenplot_mpl.textpath")
        commands = self._capture_spec()
        glyphs = [c for c in commands if c.get("decoration") == "tick_label"]
        self.assertEqual(len(glyphs), len(XTICKLABELS) + len(YTICKLABELS))
        with fixture_rc_context():
            _figure, axes = build_fixture_figure()
            labels = [
                label
                for axis in (axes.xaxis, axes.yaxis)
                for label in axis.get_majorticklabels()
                if label.get_visible() and label.get_text() != ""
            ]
        self.assertEqual(
            [label.get_text() for label in labels],
            ["0", "5", "10", "0", "5"],
        )
        self.assertEqual(len(glyphs), len(labels))
        for command, label in zip(glyphs, labels):
            expected = textpath.glyph_outline_commands(
                str(label.get_text()),
                (0.0, 0.0),
                1.0,
                0.0,
                font_size_pt=float(label.get_fontsize()),
                prop=label.get_fontproperties(),
            )[0]
            # Placement is affine-only: topology is the resolved face's own.
            self.assertEqual(command["codes"], expected["codes"])
            self.assertEqual(len(command["vertices"]), len(expected["vertices"]))
            self.assertEqual(command["fill_rgba"], [0, 0, 0, 255])
            self.assertIsNone(command["stroke_rgba"])

    def test_strict_spec_spines_trace_the_axes_box(self):
        """All four visible spine edges ride the 200x100 axes rectangle."""

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
        # Axes rect (0.1, 0.1, 0.8, 0.8) of 200x100px in seam bottom-left px.
        self.assertEqual(
            segments,
            {
                (20.0, 10.0, 180.0, 10.0),
                (20.0, 90.0, 180.0, 90.0),
                (20.0, 10.0, 20.0, 90.0),
                (180.0, 10.0, 180.0, 90.0),
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
        # Data (2,1)-(8,4) through axes (0.1,0.1,0.8,0.8) at 200x100px:
        # x = 20 + value/10*160, y = 10 + value/5*80.
        self.assertAlmostEqual(min(xs), 52.0, places=6)
        self.assertAlmostEqual(max(xs), 148.0, places=6)
        self.assertAlmostEqual(min(ys), 26.0, places=6)
        self.assertAlmostEqual(max(ys), 74.0, places=6)
