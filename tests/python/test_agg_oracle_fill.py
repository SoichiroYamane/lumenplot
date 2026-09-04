"""Focused Agg-oracle tests for fill/fill-between/span/stack fixtures.

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
        from .generate_agg_oracle_fill import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
    except ImportError:  # ``unittest discover -s tests/python``
        from generate_agg_oracle_fill import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
else:
    EFFECTIVE_DPI = 0.0
    FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
    MANIFEST_PATH = FIXTURE_DIR / "fill_manifest.json"
    ORACLE_MATPLOTLIB_VERSION = "3.11.1"


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


class TestCommittedFillFixture(unittest.TestCase):
    """The committed fixture is generated and checked without native code."""

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixture = load_reference_fixture(MANIFEST_PATH)

    def test_manifest_records_pinned_render_contract_and_digests(self):
        manifest = self.fixture.manifest
        self.assertEqual(
            manifest["fixture_id"], "fill-fill-between-span-stack-opaque"
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
            manifest["input_data"]["cases"]["fill"],
            {"artist": "matplotlib.patches.Polygon", "face": "red"},
        )
        self.assertEqual(
            manifest["input_data"]["cases"]["fill_between"],
            {
                "artist": "matplotlib.collections.FillBetweenPolyCollection",
                "face": "blue",
            },
        )
        self.assertEqual(
            manifest["input_data"]["cases"]["vspan"],
            {"artist": "matplotlib.patches.Rectangle", "face": "green"},
        )
        self.assertEqual(
            manifest["input_data"]["cases"]["hspan"],
            {"artist": "matplotlib.patches.Rectangle", "face": "yellow"},
        )
        self.assertEqual(
            manifest["input_data"]["cases"]["stack"],
            {
                "artist": "matplotlib.collections.FillBetweenPolyCollection",
                "faces": ["orange", "purple"],
                "layers": 2,
            },
        )
        self.assertEqual(
            manifest["input_data"]["stack"]["layers"],
            [[1.0, 1.5, 1.0], [1.0, 0.5, 1.0]],
        )

    def test_generator_reproduces_committed_png_mask_and_topology(self):
        generated_png, generated_mask, generated_topology, dimensions = (
            render_reference()
        )
        self.assertEqual(generated_png, self.fixture.reference_png)
        self.assertTrue(np.array_equal(generated_mask, self.fixture.mask.labels))
        self.assertEqual(dimensions, (200, 100))
        self.assertEqual(generated_topology, self.fixture.manifest["topology"])

    def test_public_geometry_pins_all_four_fill_families(self):
        """Fill, band, span, and stack geometry resolve via public getters."""

        topology = self.fixture.manifest["topology"]
        fill = topology["fill"]
        self.assertEqual(fill["class"], "matplotlib.patches.Polygon")
        self.assertEqual(fill["path"]["codes"], [1, 2, 2, 79])
        self.assertEqual(
            fill["path"]["vertices"],
            [[0.5, 0.0], [1.5, 2.0], [2.5, 0.0], [0.5, 0.0]],
        )
        band = topology["fill_between"]
        self.assertEqual(len(band["loops"]), 1)
        self.assertEqual(band["loops"][0]["codes"][-1], 79)
        band_vertices = {tuple(vertex) for vertex in band["loops"][0]["vertices"]}
        self.assertIn((4.0, 2.0), band_vertices)
        self.assertIn((3.0, 0.0), band_vertices)
        vspan = topology["vspan"]
        self.assertEqual(vspan["class"], "matplotlib.patches.Rectangle")
        self.assertEqual(vspan["xy"], [6.0, 0.0])
        self.assertEqual(vspan["width"], 1.5)
        hspan = topology["hspan"]
        self.assertEqual(hspan["xy"], [0.0, -1.5])
        self.assertEqual(hspan["height"], 1.0)
        stack = topology["stack"]
        self.assertEqual(len(stack["layers"]), 2)
        lower = {tuple(v) for v in stack["layers"][0]["loops"][0]["vertices"]}
        upper = {tuple(v) for v in stack["layers"][1]["loops"][0]["vertices"]}
        # Stack geometry shares one baseline: the lower layer's top edge is
        # the upper layer's bottom edge at every sampled x.
        self.assertTrue({(8.0, 1.0), (9.0, 1.5), (10.0, 1.0)} <= lower)
        self.assertTrue({(8.0, 1.0), (9.0, 1.5), (10.0, 1.0)} <= upper)
        self.assertEqual(
            set(np.unique(self.fixture.mask.labels)),
            {
                PIXEL_CLASS_CODES["background"],
                PIXEL_CLASS_CODES["fully-covered"],
                PIXEL_CLASS_CODES["antialias-fringe"],
            },
        )

    def test_adapter_commands_carry_exact_fill_geometry_and_style(self):
        """The native spec holds six stroked-off fills in Agg draw order."""

        from matplotlib.colors import to_rgba

        def rgba8(name):
            return [int(v) for v in np.rint(np.asarray(to_rgba(name)) * 255.0)]

        backend = importlib.import_module("lumenplot_mpl.backend")
        captured: dict[str, object] = {}

        def capture_spec(spec, _generation):
            captured.update(spec)
            return b"native-spec-only"

        with fixture_rc_context():
            figure, _axes, _artists = build_fixture_figure()
            canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
            with unittest.mock.patch.object(
                canvas, "_call_native", side_effect=capture_spec
            ):
                result = canvas.render_png(dpi=EFFECTIVE_DPI)

        self.assertEqual(result.diagnostics, ())
        commands = captured["commands"]
        self.assertIsInstance(commands, list)
        self.assertEqual(len(commands), 6)
        expected_faces = [
            rgba8("red"),
            rgba8("blue"),
            rgba8("green"),
            rgba8("yellow"),
            rgba8("orange"),
            rgba8("purple"),
        ]
        self.assertEqual(
            [rgba8("green"), rgba8("yellow"), rgba8("orange"), rgba8("purple")],
            [[0, 128, 0, 255], [255, 255, 0, 255], [255, 165, 0, 255], [128, 0, 128, 255]],
        )
        for command, expected in zip(commands, expected_faces):
            self.assertEqual(command["kind"], "path")
            self.assertEqual(command["fill_rgba"], expected)
            # ``edgecolor="none"`` plus zero width draws no stroke.
            self.assertIsNone(command["stroke_rgba"])
            codes = list(command["codes"])
            self.assertGreaterEqual(len(codes), 4)
            self.assertEqual(codes[0], 1)
            self.assertEqual(codes[-1], 79)
        vertices = [np.asarray(command["vertices"], dtype=float) for command in commands]
        # Triangle, band, and stack layers keep data-route display geometry.
        self.assertEqual((vertices[0][:, 0].min(), vertices[0][:, 0].max()), (28.0, 60.0))
        self.assertEqual((vertices[1][:, 0].min(), vertices[1][:, 0].max()), (68.0, 100.0))
        # The vspan covers the full axes height; the hspan the full width.
        self.assertEqual((vertices[2][:, 0].min(), vertices[2][:, 0].max()), (116.0, 140.0))
        self.assertEqual((vertices[2][:, 1].min(), vertices[2][:, 1].max()), (10.0, 90.0))
        self.assertEqual((vertices[3][:, 0].min(), vertices[3][:, 0].max()), (20.0, 180.0))
        self.assertEqual((vertices[4][:, 1].min(), vertices[4][:, 1].max()), (30.0, 45.0))
        self.assertEqual((vertices[5][:, 1].min(), vertices[5][:, 1].max()), (40.0, 50.0))

    def test_explicit_alpha_applies_once_and_edge_none_draws_no_stroke(self):
        """Detached style probe for the LP-FUNC-032 face/edge/alpha rule."""

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
            axes.fill(
                [0.0, 1.0, 2.0],
                [0.0, 1.0, 0.0],
                facecolor="red",
                edgecolor="none",
                linewidth=0.0,
                alpha=0.5,
            )
            axes.set_xlim(0.0, 10.0)
            axes.set_ylim(-2.0, 6.0)
            canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
            with unittest.mock.patch.object(
                canvas, "_call_native", side_effect=capture_spec
            ):
                result = canvas.render_png(dpi=EFFECTIVE_DPI)

        self.assertEqual(result.diagnostics, ())
        commands = captured["commands"]
        self.assertEqual(len(commands), 1)
        # Agg bakes the explicit alpha into the resolved face exactly once.
        self.assertEqual(commands[0]["fill_rgba"], [255, 0, 0, 128])
        self.assertIsNone(commands[0]["stroke_rgba"])


class TestFillNativeAggParity(unittest.TestCase):
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
