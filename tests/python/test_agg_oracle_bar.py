"""Focused Agg-oracle tests for bar/barh/stacked/histogram fixtures.

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
        from .generate_agg_oracle_bar import (
            BAR_BASELINE,
            BARH_BASELINE,
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            HIST_BINS,
            HIST_DATA,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            STACK_LAYERS,
            ZERO_BASELINE,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
    except ImportError:  # ``unittest discover -s tests/python``
        from generate_agg_oracle_bar import (
            BAR_BASELINE,
            BARH_BASELINE,
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            HIST_BINS,
            HIST_DATA,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            STACK_LAYERS,
            ZERO_BASELINE,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
else:
    BAR_BASELINE = 0.0
    BARH_BASELINE = 0.0
    ZERO_BASELINE = 0.0
    EFFECTIVE_DPI = 0.0
    FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
    HIST_BINS = ()
    HIST_DATA = ()
    MANIFEST_PATH = FIXTURE_DIR / "bar_manifest.json"
    ORACLE_MATPLOTLIB_VERSION = "3.11.1"
    STACK_LAYERS = ()


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


def _rgba8(name):
    from matplotlib.colors import to_rgba

    return [int(v) for v in np.rint(np.asarray(to_rgba(name)) * 255.0)]


class TestCommittedBarFixture(unittest.TestCase):
    """The committed fixture is generated and checked without native code."""

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixture = load_reference_fixture(MANIFEST_PATH)

    def test_manifest_records_pinned_render_contract_and_digests(self):
        manifest = self.fixture.manifest
        self.assertEqual(
            manifest["fixture_id"], "bar-barh-stack-histogram-stroked"
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
        self.assertEqual(
            manifest["artist_class"], "matplotlib.patches.Rectangle"
        )
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
            manifest["input_data"]["cases"]["bar"],
            {"artist": "matplotlib.patches.Rectangle", "face": "steelblue"},
        )
        self.assertEqual(
            manifest["input_data"]["cases"]["stack"],
            {
                "artist": "matplotlib.patches.Rectangle",
                "faces": ["orange", "purple"],
                "layers": 2,
            },
        )
        self.assertEqual(
            manifest["input_data"]["cases"]["barh"],
            {"artist": "matplotlib.patches.Rectangle", "face": "red"},
        )
        self.assertEqual(
            manifest["input_data"]["cases"]["histogram"],
            {
                "artist": "matplotlib.patches.Rectangle",
                "bins": [5.0, 5.5, 6.0, 6.5, 7.0],
                "face": "green",
            },
        )
        self.assertEqual(
            manifest["input_data"]["cases"]["zero_area"],
            {
                "artist": "matplotlib.patches.Rectangle",
                "face": "steelblue",
                "paints": False,
            },
        )
        self.assertEqual(
            manifest["input_data"]["histogram"]["counts"], [2.0, 1.0, 2.0, 1.0]
        )
        self.assertEqual(manifest["input_data"]["bar"]["bottom"], BAR_BASELINE)
        self.assertEqual(manifest["input_data"]["barh"]["left"], BARH_BASELINE)
        self.assertEqual(
            manifest["input_data"]["zero_area"]["bottom"], ZERO_BASELINE
        )

    def test_generator_reproduces_committed_png_mask_and_topology(self):
        generated_png, generated_mask, generated_topology, dimensions = (
            render_reference()
        )
        self.assertEqual(generated_png, self.fixture.reference_png)
        self.assertTrue(np.array_equal(generated_mask, self.fixture.mask.labels))
        self.assertEqual(dimensions, (200, 100))
        self.assertEqual(generated_topology, self.fixture.manifest["topology"])

    def test_public_geometry_pins_baselines_stacking_and_bins(self):
        """Anchored rectangles resolve via public getters in data coords."""

        topology = self.fixture.manifest["topology"]
        bar = topology["bar"]
        self.assertEqual(bar["x"], [1.0, 2.5])
        self.assertEqual(bar["height"], [2.0, -1.0])
        self.assertEqual(bar["bottom"], BAR_BASELINE)
        positive, negative = bar["rectangles"]
        self.assertEqual(positive["xy"], [0.6, 0.0])
        self.assertEqual(positive["width"], 0.8)
        self.assertEqual(positive["height"], 2.0)
        # The negative bar hangs below the declared baseline, verbatim.
        self.assertEqual(negative["xy"], [2.1, 0.0])
        self.assertEqual(negative["height"], -1.0)
        self.assertEqual(negative["baseline"], BAR_BASELINE)
        self.assertEqual(positive["angle"], 0.0)
        self.assertEqual(negative["angle"], 0.0)

        stack = topology["stack"]
        self.assertEqual(len(stack["layers"]), 2)
        lower, upper = stack["layers"]
        self.assertEqual(
            [(layer["height"], layer["bottom"]) for layer in (lower, upper)],
            [(height, bottom) for height, bottom, _face in STACK_LAYERS],
        )
        # Stack geometry shares one baseline: the lower layer's top edge is
        # the upper layer's bottom edge.
        self.assertEqual(lower["bottom"] + lower["height"], upper["bottom"])
        self.assertEqual(upper["bottom"], 1.5)
        lower_rect = lower["rectangles"][0]
        upper_rect = upper["rectangles"][0]
        self.assertEqual(lower_rect["xy"][1], 0.0)
        self.assertEqual(upper_rect["xy"][1], 1.5)
        self.assertAlmostEqual(
            lower_rect["xy"][1] + lower_rect["height"], upper_rect["xy"][1]
        )

        barh = topology["barh"]
        self.assertEqual(barh["y"], [-2.0])
        self.assertEqual(barh["width"], [2.5])
        self.assertEqual(barh["left"], BARH_BASELINE)
        horizontal = barh["rectangles"][0]
        self.assertEqual(horizontal["xy"], [0.0, -2.4])
        self.assertEqual(horizontal["width"], 2.5)
        self.assertEqual(horizontal["height"], 0.8)

        histogram = topology["histogram"]
        self.assertEqual(histogram["bins"], list(HIST_BINS))
        self.assertEqual(
            self.fixture.manifest["input_data"]["histogram"]["counts"],
            [2.0, 1.0, 2.0, 1.0],
        )
        self.assertEqual(
            sum(self.fixture.manifest["input_data"]["histogram"]["counts"]),
            float(len(HIST_DATA)),
        )
        self.assertEqual(len(histogram["rectangles"]), len(HIST_BINS) - 1)
        for rect, left, count in zip(
            histogram["rectangles"],
            HIST_BINS[:-1],
            [2.0, 1.0, 2.0, 1.0],
        ):
            self.assertEqual(rect["xy"], [left, 0.0])
            self.assertEqual(rect["height"], count)
            self.assertEqual(rect["width"], 0.5)

        zero = topology["zero_area"]["rectangles"][0]
        self.assertEqual(zero["height"], 0.0)
        self.assertEqual(zero["baseline"], ZERO_BASELINE)

        self.assertEqual(
            set(np.unique(self.fixture.mask.labels)),
            {
                PIXEL_CLASS_CODES["background"],
                PIXEL_CLASS_CODES["fully-covered"],
                PIXEL_CLASS_CODES["antialias-fringe"],
            },
        )

    def test_adapter_commands_carry_exact_bar_geometry_and_style(self):
        """The native spec holds nine stroked bars in Agg draw order."""

        backend = importlib.import_module("lumenplot_mpl.backend")
        captured: dict[str, object] = {}

        def capture_spec(spec, _generation):
            captured.update(spec)
            return b"native-spec-only"

        with fixture_rc_context():
            figure, axes, _artists = build_fixture_figure()
            # Ten Rectangle patches reach the adapter; the zero-area bar
            # paints nothing in Agg and is skipped at emission.
            self.assertEqual(len(axes.patches), 10)
            canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
            with unittest.mock.patch.object(
                canvas, "_call_native", side_effect=capture_spec
            ):
                result = canvas.render_png(dpi=EFFECTIVE_DPI)

        self.assertEqual(result.diagnostics, ())
        commands = captured["commands"]
        self.assertIsInstance(commands, list)
        self.assertEqual(len(commands), 9)
        expected_faces = [
            _rgba8("steelblue"),
            _rgba8("steelblue"),
            _rgba8("orange"),
            _rgba8("purple"),
            _rgba8("red"),
            _rgba8("green"),
            _rgba8("green"),
            _rgba8("green"),
            _rgba8("green"),
        ]
        self.assertEqual(
            [_rgba8("steelblue"), _rgba8("orange"), _rgba8("purple")],
            [[70, 130, 180, 255], [255, 165, 0, 255], [128, 0, 128, 255]],
        )
        # Data-space anchor corners per command, in emission order: two
        # vertical bars, two stack layers, one horizontal bar, four hist bars.
        data_anchors = [
            [(0.6, 0.0), 0.8, 2.0],
            [(2.1, 0.0), 0.8, -1.0],
            [(4.1, 0.0), 0.8, 1.5],
            [(4.1, 1.5), 0.8, 1.0],
            [(0.0, -2.4), 2.5, 0.8],
            [(5.0, 0.0), 0.5, 2.0],
            [(5.5, 0.0), 0.5, 1.0],
            [(6.0, 0.0), 0.5, 2.0],
            [(6.5, 0.0), 0.5, 1.0],
        ]
        for command, expected, (anchor, width, height) in zip(
            commands, expected_faces, data_anchors
        ):
            self.assertEqual(command["kind"], "path")
            self.assertEqual(command["fill_rgba"], expected)
            # Every bar is filled-and-stroked: the explicit black edge at
            # positive width strokes the outline.
            self.assertEqual(command["stroke_rgba"], [0, 0, 0, 255])
            self.assertTrue(command["rectilinear_snap"])
            codes = list(command["codes"])
            self.assertEqual(codes, [1, 2, 2, 2, 79])
            x0, y0 = anchor
            corners = [
                (x0, y0),
                (x0 + width, y0),
                (x0 + width, y0 + height),
                (x0, y0 + height),
                (x0, y0),
            ]
            expected_vertices = axes.transData.transform(corners).tolist()
            np.testing.assert_allclose(
                np.asarray(command["vertices"], dtype=float),
                np.asarray(expected_vertices, dtype=float),
                atol=1e-9,
            )
        vertices = [np.asarray(command["vertices"], dtype=float) for command in commands]
        # Positive bar, negative bar hanging below the baseline, and the
        # shared stack baseline resolve to exact display pixels.
        self.assertEqual((vertices[0][:, 0].min(), vertices[0][:, 0].max()), (32.0, 48.0))
        self.assertEqual((vertices[0][:, 1].min(), vertices[0][:, 1].max()), (40.0, 60.0))
        self.assertEqual((vertices[1][:, 1].min(), vertices[1][:, 1].max()), (30.0, 40.0))
        self.assertEqual((vertices[2][:, 1].min(), vertices[2][:, 1].max()), (40.0, 55.0))
        self.assertEqual((vertices[3][:, 1].min(), vertices[3][:, 1].max()), (55.0, 65.0))
        self.assertEqual((vertices[2][:, 1].max(), vertices[3][:, 1].min()), (55.0, 55.0))
        self.assertEqual((vertices[4][:, 0].min(), vertices[4][:, 0].max()), (20.0, 70.0))
        self.assertEqual((vertices[4][:, 1].min(), vertices[4][:, 1].max()), (16.0, 24.0))
        self.assertEqual((vertices[5][:, 0].min(), vertices[5][:, 0].max()), (120.0, 130.0))
        self.assertEqual((vertices[8][:, 0].min(), vertices[8][:, 0].max()), (150.0, 160.0))

    def test_per_bar_color_list_resolves_per_command_fill(self):
        """Detached style probe: one bar call, per-bar face resolution."""

        from matplotlib.figure import Figure

        backend = importlib.import_module("lumenplot_mpl.backend")
        captured: dict[str, object] = {}

        def capture_spec(spec, _generation):
            captured.update(spec)
            return b"native-spec-only"

        with fixture_rc_context():
            figure = Figure(figsize=(2.0, 1.0), dpi=EFFECTIVE_DPI)
            axes = figure.add_axes((0.1, 0.1, 0.8, 0.8))
            axes.set_axis_off()
            axes.bar(
                [0.0, 1.0],
                [1.0, 2.0],
                width=0.8,
                bottom=0.0,
                color=["red", "blue"],
                edgecolor="black",
                linewidth=1.0,
            )
            axes.set_xlim(0.0, 8.0)
            axes.set_ylim(-3.0, 5.0)
            canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
            with unittest.mock.patch.object(
                canvas, "_call_native", side_effect=capture_spec
            ):
                result = canvas.render_png(dpi=EFFECTIVE_DPI)

        self.assertEqual(result.diagnostics, ())
        commands = captured["commands"]
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0]["fill_rgba"], _rgba8("red"))
        self.assertEqual(commands[1]["fill_rgba"], _rgba8("blue"))
        for command in commands:
            self.assertEqual(command["stroke_rgba"], [0, 0, 0, 255])
            self.assertEqual(list(command["codes"]), [1, 2, 2, 2, 79])


class TestBarNativeAggParity(unittest.TestCase):
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
            figure, _axes, _artists = build_fixture_figure()
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
