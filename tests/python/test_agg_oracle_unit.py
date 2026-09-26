"""Focused Agg-oracle tests for the calibrated-unit fixtures (LP-MPL-022).

The committed fixtures pin two bounded calibrated-unit axes-on frames
sharing one pinned cell: Figure-authoritative converted numeric data on
the x-calibrated scene and on the y-calibrated scene, default
``AutoLocator`` / ``ScalarFormatter`` results, visible major ticks with
solid major gridlines on both axes, four visible spine edges, and plain
numeric label glyphs.

The semantic checks run without the compiled extension.  The pixel
comparisons are deliberately separate strict native tests: each is
skipped with an explicit setup reason when
``lumenplot_mpl._native.render_frame_png`` is unavailable and never
substitutes a stub or Agg fallback as parity evidence.

Unrepresentable-conversion refusal behavior is covered by
``tests/python/test_phase3b_unit_data.py`` and is not re-derived here.
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
        from .generate_agg_oracle_unit import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            MANIFEST_PATHS,
            ORACLE_MATPLOTLIB_VERSION,
            SCENE_KEYS,
            SCENES,
            X_PLAIN,
            Y_PLAIN,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
    except ImportError:  # ``unittest discover -s tests/python``
        from generate_agg_oracle_unit import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            MANIFEST_PATHS,
            ORACLE_MATPLOTLIB_VERSION,
            SCENE_KEYS,
            SCENES,
            X_PLAIN,
            Y_PLAIN,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
else:
    EFFECTIVE_DPI = 0.0
    FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
    MANIFEST_PATHS = {}
    ORACLE_MATPLOTLIB_VERSION = "3.11.1"
    SCENE_KEYS = ()
    SCENES = {}
    X_PLAIN = ()
    Y_PLAIN = ()

# Shared converted geometry: both scenes convert to the same finite
# floats, so these pins hold for the x-calibrated and y-calibrated
# scenes alike.
EXPECTED_CONVERTED_X = [0.0, 5.0, 10.0]
EXPECTED_CONVERTED_Y = [1.0, 3.0, 2.0]
EXPECTED_VERTICES = [[0.0, 1.0], [5.0, 3.0], [10.0, 2.0]]
EXPECTED_XTICKLOCS = [0.0, 5.0, 10.0]
EXPECTED_XTICKLABELS = ["0", "5", "10"]
EXPECTED_YTICKLOCS = [0.0, 2.0, 4.0]
EXPECTED_YTICKLABELS = ["0", "2", "4"]
EXPECTED_DISPLAY_VERTICES = [[20.0, 30.0], [100.0, 70.0], [180.0, 50.0]]
EXPECTED_LABEL_ORDER = ["0", "5", "10", "0", "2", "4"]

EXPECTED_SCENES = {
    "unit-x-line": {
        "fixture_id": "unit-x-calibrated-line-decorated",
        "calibrated_axis": "x",
        "converters": {"x": "_CalibratedConverter", "y": None},
        "direct_x": [0.0, 5.0, 10.0],
        "direct_y": [],
        "xlim_source": "calibrated",
        "ylim_source": "plain",
        "line_construction": (
            "axes.plot([_CalibratedValue(0.0), _CalibratedValue(5.0), "
            "_CalibratedValue(10.0)], [1.0, 3.0, 2.0], color='red', "
            "linewidth=2.0, solid_capstyle='butt', solid_joinstyle='miter')"
        ),
        "cases": {
            "unit-x-line": {
                "artist": "matplotlib.lines.Line2D",
                "construction": "axes.plot(calibrated_x, y)",
                "converter": "calibrated",
                "locator": "matplotlib.ticker.AutoLocator",
                "formatter": "matplotlib.ticker.ScalarFormatter",
            },
        },
    },
    "unit-y-line": {
        "fixture_id": "unit-y-calibrated-line-decorated",
        "calibrated_axis": "y",
        "converters": {"x": "NoneType", "y": "_CalibratedConverter"},
        "direct_x": [],
        "direct_y": [1.0, 3.0, 2.0],
        "xlim_source": "plain",
        "ylim_source": "calibrated",
        "line_construction": (
            "axes.plot([0.0, 5.0, 10.0], [_CalibratedValue(1.0), "
            "_CalibratedValue(3.0), _CalibratedValue(2.0)], color='red', "
            "linewidth=2.0, solid_capstyle='butt', "
            "solid_joinstyle='miter')"
        ),
        "cases": {
            "unit-y-line": {
                "artist": "matplotlib.lines.Line2D",
                "construction": "axes.plot(x, calibrated_y)",
                "converter": "calibrated",
                "locator": "matplotlib.ticker.AutoLocator",
                "formatter": "matplotlib.ticker.ScalarFormatter",
            },
        },
    },
}


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


class TestCommittedUnitFixtures(unittest.TestCase):
    """The committed fixtures are generated and checked without native code."""

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixtures = {
            scene_key: load_reference_fixture(MANIFEST_PATHS[scene_key])
            for scene_key in SCENE_KEYS
        }

    def test_manifest_records_pinned_render_contract_and_digests(self):
        for scene_key in SCENE_KEYS:
            expected = EXPECTED_SCENES[scene_key]
            with self.subTest(scene=scene_key):
                manifest = self.fixtures[scene_key].manifest
                self.assertEqual(
                    manifest["fixture_id"], expected["fixture_id"]
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
                self.assertEqual(
                    manifest["dimensions"], {"width": 200, "height": 100}
                )
                self.assertEqual(manifest["orientation"], "top-to-bottom")
                self.assertEqual(manifest["channels"], "RGBA8")
                self.assertEqual(
                    manifest["artist_class"], "matplotlib.lines.Line2D"
                )
                self.assertEqual(
                    manifest["font"]["bytes_sha256"],
                    manifest["font_bytes_sha256"],
                )
                self.assertEqual(
                    hashlib.sha256(
                        self.fixtures[scene_key].reference_png
                    ).hexdigest(),
                    manifest["reference_png_sha256"],
                )
                self.assertEqual(
                    hashlib.sha256(
                        (FIXTURE_DIR / manifest["mask_file"]).read_bytes()
                    ).hexdigest(),
                    manifest["mask_sha256"],
                )
                self.assertEqual(
                    manifest["input_data"]["cases"], expected["cases"]
                )
                self.assertEqual(
                    manifest["figure"]["options"]["line_construction"],
                    expected["line_construction"],
                )
                self.assertEqual(
                    manifest["figure"]["options"]["xlim_source"],
                    expected["xlim_source"],
                )
                self.assertEqual(
                    manifest["figure"]["options"]["ylim_source"],
                    expected["ylim_source"],
                )
                self.assertTrue(manifest["figure"]["options"]["axis_on"])
                # Fixed S15.1 contract values are pinned verbatim; this
                # test guards against any tolerance widening in the
                # committed manifests.
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
        for scene_key in SCENE_KEYS:
            with self.subTest(scene=scene_key):
                generated = render_reference(scene_key)
                generated_png, generated_mask, generated_topology, dimensions = (
                    generated
                )
                self.assertEqual(
                    generated_png, self.fixtures[scene_key].reference_png
                )
                self.assertTrue(
                    np.array_equal(
                        generated_mask, self.fixtures[scene_key].mask.labels
                    )
                )
                self.assertEqual(dimensions, (200, 100))
                self.assertEqual(
                    generated_topology,
                    self.fixtures[scene_key].manifest["topology"],
                )

    def test_converted_data_matches_direct_converter_route(self):
        """LP-MPL-022: the committed data is the public converted route."""

        for scene_key in SCENE_KEYS:
            expected = EXPECTED_SCENES[scene_key]
            with self.subTest(scene=scene_key):
                topology = self.fixtures[scene_key].manifest["topology"]
                self.assertEqual(topology["scene"], scene_key)
                self.assertEqual(
                    topology["line_api"],
                    "line.get_xdata(orig=False)/line.get_ydata(orig=False)",
                )
                self.assertEqual(
                    topology["calibrated_axis"], expected["calibrated_axis"]
                )
                self.assertEqual(topology["converted_x"], EXPECTED_CONVERTED_X)
                self.assertEqual(topology["converted_y"], EXPECTED_CONVERTED_Y)
                # The converter resolved upstream on the calibrated axis:
                # converted floats equal the direct converter route exactly,
                # and the plain axis carries no converter.
                self.assertEqual(
                    topology["conversion_cross_check"]["direct_x"],
                    expected["direct_x"],
                )
                self.assertEqual(
                    topology["conversion_cross_check"]["direct_y"],
                    expected["direct_y"],
                )
                if expected["calibrated_axis"] == "x":
                    self.assertEqual(
                        topology["converted_x"],
                        topology["conversion_cross_check"]["direct_x"],
                    )
                else:
                    self.assertEqual(
                        topology["converted_y"],
                        topology["conversion_cross_check"]["direct_y"],
                    )
                self.assertEqual(
                    topology["converters"], expected["converters"]
                )
                for value in topology["converted_x"] + topology["converted_y"]:
                    self.assertTrue(np.isfinite(value))
                # One finite run: no gap splits on this all-finite
                # calibrated input, and no silent replacement primitive.
                self.assertEqual(topology["segment_count"], 3)
                self.assertEqual(topology["subpath_count"], 1)
                self.assertEqual(topology["moveto_count"], 1)
                self.assertEqual(topology["lineto_count"], 2)
                self.assertEqual(topology["segment_codes"], [1, 2, 2])
                self.assertEqual(topology["vertices"], EXPECTED_VERTICES)

    def test_locator_formatter_outputs_are_pinned(self):
        """Default locator/formatter results equal Agg's outputs."""

        for scene_key in SCENE_KEYS:
            with self.subTest(scene=scene_key):
                topology = self.fixtures[scene_key].manifest["topology"]
                self.assertEqual(
                    topology["locators"]["x"]["class"], "AutoLocator"
                )
                self.assertEqual(
                    topology["locators"]["y"]["class"], "AutoLocator"
                )
                self.assertEqual(
                    topology["formatters"]["x"], "ScalarFormatter"
                )
                self.assertEqual(
                    topology["formatters"]["y"], "ScalarFormatter"
                )
                self.assertEqual(topology["xticklocs"], EXPECTED_XTICKLOCS)
                self.assertEqual(
                    topology["xticklabels"], EXPECTED_XTICKLABELS
                )
                self.assertEqual(topology["yticklocs"], EXPECTED_YTICKLOCS)
                self.assertEqual(
                    topology["yticklabels"], EXPECTED_YTICKLABELS
                )
                # Plain numeric label glyphs only: no mathtext markers, no
                # blank-padded labels, no offset text on either axis.
                for text in topology["xticklabels"] + topology["yticklabels"]:
                    self.assertNotIn("$", text)
                    self.assertEqual(text, text.strip())
                    self.assertNotIn("\n", text)
                with fixture_rc_context():
                    _figure, axes, _line = build_fixture_figure(scene_key)
                    from matplotlib.backends.backend_agg import FigureCanvasAgg

                    FigureCanvasAgg(_figure)
                    _figure.draw_without_rendering()
                    self.assertEqual(axes.xaxis.get_offset_text().get_text(), "")
                    self.assertEqual(axes.yaxis.get_offset_text().get_text(), "")
                # Display geometry is the public transData projection of
                # the converted data with Figure-authoritative limits.
                self.assertEqual(
                    topology["display_vertices"], EXPECTED_DISPLAY_VERTICES
                )
                self.assertEqual(
                    topology["limits"],
                    {"xlim": [0.0, 10.0], "ylim": [0.0, 4.0]},
                )

    def test_strict_render_preserves_figure_authority(self):
        """LP-MPL-022: rendering never mutates limits or raw unit objects."""

        backend = importlib.import_module("lumenplot_mpl.backend")
        captured: dict[str, object] = {}

        def capture_spec(spec, _generation):
            captured.update(spec)
            return b"native-spec-only"

        for scene_key in SCENE_KEYS:
            with self.subTest(scene=scene_key):
                with fixture_rc_context():
                    figure, axes, line = build_fixture_figure(scene_key)
                    raw_before = list(line.get_xdata(orig=True)), list(
                        line.get_ydata(orig=True)
                    )
                    limits_before = (axes.get_xlim(), axes.get_ylim())
                    canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
                    with unittest.mock.patch.object(
                        canvas, "_call_native", side_effect=capture_spec
                    ):
                        result = canvas.render_png(dpi=EFFECTIVE_DPI)
                self.assertEqual(result.diagnostics, ())
                self.assertEqual(
                    (axes.get_xlim(), axes.get_ylim()), limits_before
                )
                raw_after = list(line.get_xdata(orig=True)), list(
                    line.get_ydata(orig=True)
                )
                self.assertEqual(len(raw_after[0]), len(raw_before[0]))
                self.assertEqual(len(raw_after[1]), len(raw_before[1]))
                for before, after in zip(
                    raw_before[0] + raw_before[1], raw_after[0] + raw_after[1]
                ):
                    self.assertIs(type(after), type(before))

    def test_decoration_surface_is_pinned(self):
        """Grid, spine, and mask facts travel with the committed fixtures."""

        for scene_key in SCENE_KEYS:
            with self.subTest(scene=scene_key):
                topology = self.fixtures[scene_key].manifest["topology"]
                for side in ("x", "y"):
                    self.assertEqual(len(topology["grid"][side]), 3)
                    for entry in topology["grid"][side]:
                        self.assertTrue(entry["visible"])
                        self.assertEqual(entry["linestyle"], "-")
                        self.assertEqual(entry["linewidth"], 0.8)
                for side in ("bottom", "top", "left", "right"):
                    self.assertTrue(topology["spines"][side]["visible"])
                    self.assertEqual(topology["spines"][side]["linewidth"], 0.8)
                counts = {
                    name: int(
                        (self.fixtures[scene_key].mask.labels == code).sum()
                    )
                    for name, code in PIXEL_CLASS_CODES.items()
                }
                self.assertGreater(counts["background"], 0)
                self.assertGreater(counts["fully-covered"], 0)
                self.assertGreater(counts["antialias-fringe"], 0)
                self.assertEqual(counts["text-or-outline"], 0)


class TestUnitAdapterSemantics(unittest.TestCase):
    """The adapter spec reproduces the fixture surface without native code."""

    def setUp(self):
        _require_pinned_matplotlib()

    def _strict_commands(self, scene_key):
        backend = importlib.import_module("lumenplot_mpl.backend")
        captured: dict[str, object] = {}

        def capture_spec(spec, _generation):
            captured.update(spec)
            return b"native-spec-only"

        with fixture_rc_context():
            figure, _axes = build_fixture_figure(scene_key)[:2]
            canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
            with unittest.mock.patch.object(
                canvas, "_call_native", side_effect=capture_spec
            ):
                result = canvas.render_png(dpi=EFFECTIVE_DPI)
        self.assertEqual(result.diagnostics, ())
        commands = captured["commands"]
        self.assertIsInstance(commands, list)
        return commands

    def test_content_path_carries_converted_display_geometry(self):
        """The native spec holds one stroke on the converted projection."""

        from matplotlib.colors import to_rgba

        def rgba8(name):
            return [int(v) for v in np.rint(np.asarray(to_rgba(name)) * 255.0)]

        for scene_key in SCENE_KEYS:
            with self.subTest(scene=scene_key):
                commands = self._strict_commands(scene_key)
                content = [
                    c for c in commands if c.get("decoration") is None
                ]
                self.assertEqual(len(content), 1)
                command = content[0]
                self.assertEqual(command["kind"], "path")
                self.assertIsNone(command.get("fill_rgba"))
                self.assertEqual(command["stroke_rgba"], rgba8("red"))
                self.assertEqual(command["stroke_rgba"], [255, 0, 0, 255])
                self.assertEqual(command["line_width_pt"], 2.0)
                self.assertEqual(command["cap"], "butt")
                self.assertEqual(command["join"], "miter")
                self.assertIsNone(command["dashes"])
                self.assertIsNone(command["codes"])
                # The command vertices equal the committed display
                # projection of the converted data, which itself equals
                # the public transData oracle (not the adapter route).
                expected_display = np.asarray(
                    load_reference_fixture(
                        MANIFEST_PATHS[scene_key]
                    ).manifest["topology"]["display_vertices"],
                    dtype=float,
                )
                got = np.asarray(command["vertices"], dtype=float)
                self.assertEqual(got.shape, (3, 2))
                np.testing.assert_allclose(got, expected_display, atol=1e-9)
                self.assertEqual(
                    command["clip_rect"], [20.0, 10.0, 160.0, 80.0]
                )

    def test_strict_spec_carries_six_glyph_commands_in_draw_order(self):
        """One coverage-blit image command per visible major label, x first."""

        textpath = importlib.import_module("lumenplot_mpl.textpath")
        support = importlib.import_module("lumenplot_mpl.backend_support")
        real_mask = textpath._label_coverage_mask

        for scene_key in SCENE_KEYS:
            with self.subTest(scene=scene_key):
                calls: list = []

                def recording_mask(*args, **kwargs):
                    result = real_mask(*args, **kwargs)
                    calls.append((args, kwargs, result))
                    return result

                with unittest.mock.patch.object(
                    textpath, "_label_coverage_mask", recording_mask
                ):
                    commands = self._strict_commands(scene_key)
                glyphs = [
                    c for c in commands if c.get("decoration") == "tick_label"
                ]
                self.assertEqual(len(glyphs), 6)
                with fixture_rc_context():
                    _figure, axes = build_fixture_figure(scene_key)[:2]
                    labels = [
                        label
                        for axis in (axes.xaxis, axes.yaxis)
                        for label in axis.get_majorticklabels()
                        if label.get_visible() and label.get_text() != ""
                    ]
                self.assertEqual(
                    [label.get_text() for label in labels],
                    EXPECTED_LABEL_ORDER,
                )
                self.assertEqual(len(glyphs), len(labels))
                # One coverage-helper call per tick label, in draw order.
                self.assertEqual(len(calls), len(labels))
                for command, label, call in zip(glyphs, labels, calls):
                    args, kwargs, outcome = call
                    self.assertEqual(args[0], str(label.get_text()))
                    self.assertEqual(args[3], 100.0)
                    self.assertEqual(args[4], float(label.get_rotation()))
                    # Tick anchors may sit off-canvas (x labels below the
                    # axes); only finiteness is pinned here while exact
                    # geometry rides the command pins below.
                    for anchor in (args[1], args[2]):
                        self.assertTrue(anchor == anchor)
                        self.assertLess(abs(float(anchor)), 1e9)
                    self.assertEqual(
                        kwargs["font_size_pt"], float(label.get_fontsize())
                    )
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
                    # Representation pin: coverage-blit image command, never
                    # an outline path and never outline keys on an image
                    # command.
                    self.assertEqual(command["kind"], "image")
                    self.assertEqual(command["decoration"], "tick_label")
                    for absent in (
                        "codes",
                        "vertices",
                        "fill_rgba",
                        "stroke_rgba",
                    ):
                        self.assertNotIn(absent, command)
                    self.assertEqual(command["x"], float(left_col))
                    self.assertEqual(
                        command["y"], float(100.0 - (top_row + mask_h))
                    )
                    self.assertEqual(command["width"], mask_w)
                    self.assertEqual(command["height"], mask_h)
                    self.assertEqual(
                        command["clip_rect"], [0.0, 0.0, 200.0, 100.0]
                    )
                    self.assertGreater(mask_w, 0)
                    self.assertGreater(mask_h, 0)
                    self.assertTrue(any(mask))
                    # Wire pin: every blit pixel carries the label color
                    # with the helper coverage folded into alpha, packed
                    # per the adapter.
                    raw_rgba = bytes(command["rgba"])
                    self.assertEqual(len(raw_rgba), 4 * mask_w * mask_h)
                    expected_rgba = bytearray(4 * mask_w * mask_h)
                    for index, cover in enumerate(mask):
                        expected_rgba[4 * index] = style[0]
                        expected_rgba[4 * index + 1] = style[1]
                        expected_rgba[4 * index + 2] = style[2]
                        expected_rgba[4 * index + 3] = (
                            textpath._agg_multiply_byte(style[3], int(cover))
                        )
                    self.assertEqual(raw_rgba, bytes(expected_rgba))
                    for index in range(mask_w * mask_h):
                        self.assertEqual(
                            tuple(raw_rgba[4 * index:4 * index + 3]),
                            tuple(style[:3]),
                        )
                        self.assertEqual(
                            raw_rgba[4 * index + 3],
                            textpath._agg_multiply_byte(
                                style[3], int(mask[index])
                            ),
                        )

    def test_strict_spec_gridlines_ticks_and_spines(self):
        """Grid, tick, and spine strokes ride the fixed axes geometry."""

        for scene_key in SCENE_KEYS:
            with self.subTest(scene=scene_key):
                commands = self._strict_commands(scene_key)
                gridlines = [
                    c for c in commands if c.get("decoration") == "gridline"
                ]
                ticks = [c for c in commands if c.get("decoration") == "tick"]
                spines = [
                    c for c in commands if c.get("decoration") == "spine"
                ]
                # Three major ticks per axis carry one gridline and one
                # tick each.
                self.assertEqual(len(gridlines), 6)
                self.assertEqual(len(ticks), 6)
                for command in gridlines:
                    self.assertEqual(
                        command["stroke_rgba"], [176, 176, 176, 255]
                    )
                    self.assertIsNone(command["dashes"])
                for command in ticks:
                    self.assertEqual(command["stroke_rgba"], [0, 0, 0, 255])
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
                # Axes rect (0.1, 0.1, 0.8, 0.8) of 200x100px in seam
                # bottom-left px.
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
                    # Default spines carry the artist's projecting caps
                    # (Matplotlib Spine default; pinned Agg draw_path
                    # reports cap=projecting for every 0.8pt spine stroke),
                    # not butt.
                    self.assertEqual(command["cap"], "projecting")
                    self.assertEqual(command["join"], "miter")


class TestUnitNativeAggParity(unittest.TestCase):
    """Compare the fixed calibrated inputs through the real adapter seam.

    Measured green on origin/main cdf9d0c6 with a locally built
    ``_native`` from the same source (CPython 3.14.7 + matplotlib
    3.11.1): both scenes render ``200x100 top-to-bottom`` with
    ``max_delta=0, mean_delta=0.0, mismatches=0`` against the fixed
    budget (exact classes byte-equal, fringe max delta 1, total-pixel
    fringe rate <= 0.001).  The gate stays fixed; this test is the
    green evidence, not a tunable threshold.
    """

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixtures = {
            scene_key: load_reference_fixture(MANIFEST_PATHS[scene_key])
            for scene_key in SCENE_KEYS
        }
        # This must remain a real-extension check.  No recording stub or
        # hybrid/Agg fallback is permitted to make the pixel assertion pass.
        self.native = _require_real_native_seam()

    def test_strict_native_render_matches_fixed_agg_reference(self):
        backend = importlib.import_module("lumenplot_mpl.backend")
        for scene_key in SCENE_KEYS:
            with self.subTest(scene=scene_key):
                with fixture_rc_context():
                    figure, _axes, _line = build_fixture_figure(scene_key)
                    canvas = backend.FigureCanvasLumenPlot(
                        figure, mode="strict"
                    )
                    result = canvas.render_png(dpi=EFFECTIVE_DPI)
                self.assertEqual(result.diagnostics, ())
                report = assert_png_parity(
                    self.fixtures[scene_key].reference_png,
                    result.png_bytes,
                    self.fixtures[scene_key].mask,
                    manifest=self.fixtures[scene_key].manifest,
                )
                self.assertTrue(report.passed, report.summary())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
