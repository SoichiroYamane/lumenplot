"""Focused Agg-oracle tests for the stackplot-only fixture.

LP-FUNC-032 stack semantics (LP-MPL-020 C2 stack surface): ``Axes.stackplot``
renders natively as one ``FillBetweenPolyCollection`` per layer, so this lane
proves parity instead of refusal.  The committed fixture isolates the stack
call from the combined fill/fill-between/span fixture so the parity result
is attributable to stack composition alone.

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
        from .generate_agg_oracle_stackplot import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            STACK_FACES,
            STACK_LAYERS,
            STACK_X,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
    except ImportError:  # ``unittest discover -s tests/python``
        from generate_agg_oracle_stackplot import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            STACK_FACES,
            STACK_LAYERS,
            STACK_X,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
else:
    EFFECTIVE_DPI = 0.0
    FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
    MANIFEST_PATH = FIXTURE_DIR / "stackplot_manifest.json"
    ORACLE_MATPLOTLIB_VERSION = "3.11.1"
    STACK_FACES = ("orange", "purple")
    STACK_LAYERS = ((1.0, 1.0, 1.0), (0.5, 0.5, 0.5))
    STACK_X = (8.0, 9.0, 10.0)


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


class TestCommittedStackplotFixture(unittest.TestCase):
    """The committed fixture is generated and checked without native code."""

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixture = load_reference_fixture(MANIFEST_PATH)

    def test_manifest_records_pinned_render_contract_and_digests(self):
        manifest = self.fixture.manifest
        self.assertEqual(
            manifest["fixture_id"], "stackplot-two-layer-opaque"
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
            manifest["input_data"]["cases"]["stack"],
            {
                "artist": "matplotlib.collections.FillBetweenPolyCollection",
                "faces": ["orange", "purple"],
                "layers": 2,
            },
        )
        self.assertEqual(
            manifest["input_data"]["stack"]["x"], [8.0, 9.0, 10.0]
        )
        self.assertEqual(
            manifest["input_data"]["stack"]["layers"],
            [[1.0, 1.0, 1.0], [0.5, 0.5, 0.5]],
        )
        self.assertEqual(
            manifest["input_data"]["stack"]["faces"], ["orange", "purple"]
        )
        # The fixed S15.1 pixel gate travels with the fixture; it is never
        # widened after a result.
        self.assertEqual(
            manifest["contract"]["fringe_max_channel_delta"], 1
        )
        self.assertEqual(
            manifest["contract"]["fringe_mismatch_rate_denominator"],
            "total-pixels",
        )
        self.assertEqual(
            manifest["contract"]["fringe_mismatch_rate_max"], 0.001
        )

    def test_generator_reproduces_committed_png_mask_and_topology(self):
        generated_png, generated_mask, generated_topology, dimensions = (
            render_reference()
        )
        self.assertEqual(generated_png, self.fixture.reference_png)
        self.assertTrue(np.array_equal(generated_mask, self.fixture.mask.labels))
        self.assertEqual(dimensions, (200, 100))
        self.assertEqual(generated_topology, self.fixture.manifest["topology"])

    def test_public_geometry_pins_two_layer_stack(self):
        """Both layers resolve via public getters with one shared baseline."""

        topology = self.fixture.manifest["topology"]
        stack = topology["stack"]
        self.assertEqual(
            stack["class"],
            "matplotlib.collections.FillBetweenPolyCollection",
        )
        self.assertEqual(stack["api"], "collection.get_paths()")
        self.assertEqual(len(stack["layers"]), 2)
        for layer in stack["layers"]:
            self.assertEqual(len(layer["loops"]), 1)
            self.assertEqual(layer["loops"][0]["codes"][0], 1)
            self.assertEqual(layer["loops"][0]["codes"][-1], 79)
        lower = {tuple(v) for v in stack["layers"][0]["loops"][0]["vertices"]}
        upper = {tuple(v) for v in stack["layers"][1]["loops"][0]["vertices"]}
        # Stack geometry shares one baseline: the lower layer's top edge is
        # the upper layer's bottom edge at every sampled x.
        self.assertTrue({(8.0, 0.0), (9.0, 0.0), (10.0, 0.0)} <= lower)
        self.assertTrue({(8.0, 1.0), (9.0, 1.0), (10.0, 1.0)} <= lower)
        self.assertTrue({(8.0, 1.0), (9.0, 1.0), (10.0, 1.0)} <= upper)
        self.assertTrue({(8.0, 1.5), (9.0, 1.5), (10.0, 1.5)} <= upper)
        # All edges are axis-aligned on integer display coordinates, so Agg
        # coverage is binary: every committed pixel is background or a
        # byte-equal face interior, and the fringe class is empty.
        self.assertEqual(
            set(np.unique(self.fixture.mask.labels)),
            {
                PIXEL_CLASS_CODES["background"],
                PIXEL_CLASS_CODES["fully-covered"],
            },
        )


class TestStackplotCollectorTrace(unittest.TestCase):
    """Each stack layer reaches the spec as one ordered fill command."""

    def setUp(self):
        _require_pinned_matplotlib()

    def _strict_commands(self, build=None):
        backend = importlib.import_module("lumenplot_mpl.backend")
        captured: dict[str, object] = {}

        def capture_spec(spec, _generation):
            captured.update(spec)
            return b"native-spec-only"

        with fixture_rc_context():
            if build is None:
                figure, _axes, _artists = build_fixture_figure()
            else:
                from matplotlib.figure import Figure

                figure = Figure(figsize=(2.0, 1.0), dpi=EFFECTIVE_DPI)
                axes = figure.add_axes((0.1, 0.1, 0.8, 0.8))
                axes.set_axis_off()
                build(axes)
                axes.set_xlim(0.0, 10.0)
                axes.set_ylim(-2.0, 6.0)
            canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
            with unittest.mock.patch.object(
                canvas, "_call_native", side_effect=capture_spec
            ):
                result = canvas.render_png(dpi=EFFECTIVE_DPI)
        self.assertEqual(result.diagnostics, ())
        commands = captured["commands"]
        self.assertIsInstance(commands, list)
        return [c for c in commands if not c.get("decoration")]

    def test_two_layers_produce_two_commands_in_layer_order(self):
        """The FillBetweenPolyCollection draw path keeps Agg paint order."""

        commands = self._strict_commands()
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0]["fill_rgba"], [255, 165, 0, 255])
        self.assertEqual(commands[1]["fill_rgba"], [128, 0, 128, 255])
        for command in commands:
            self.assertEqual(command["kind"], "path")
            codes = list(command["codes"])
            self.assertGreaterEqual(len(codes), 4)
            self.assertEqual(codes[0], 1)
            self.assertEqual(codes[-1], 79)
        lower_ys = [v[1] for v in commands[0]["vertices"]]
        upper_ys = [v[1] for v in commands[1]["vertices"]]
        # Lower layer spans display y 30..40, upper layer 40..45, sharing
        # the y=40 baseline exactly.
        self.assertEqual((min(lower_ys), max(lower_ys)), (30.0, 40.0))
        self.assertEqual((min(upper_ys), max(upper_ys)), (40.0, 45.0))

    def test_stack_geometry_matches_public_affine(self):
        with fixture_rc_context():
            figure, _axes, artists = build_fixture_figure()
        layers = artists["stack"]
        self.assertEqual(len(layers), 2)
        for layer in layers:
            self.assertEqual(
                type(layer).__name__, "FillBetweenPolyCollection"
            )
        commands = self._strict_commands()
        self.assertEqual(len(commands), 2)
        for command, layer in zip(commands, layers):
            path = layer.get_paths()[0]
            expected = layer.get_transform().transform(path.vertices)
            np.testing.assert_allclose(
                np.asarray(command["vertices"]), expected, rtol=0, atol=1e-9
            )


class TestStackplotStyleContract(unittest.TestCase):
    """Stack face/edge styling resolves exactly as Agg resolves it."""

    def setUp(self):
        _require_pinned_matplotlib()

    def _strict_commands(self, build):
        backend = importlib.import_module("lumenplot_mpl.backend")
        captured: dict[str, object] = {}

        def capture_spec(spec, _generation):
            captured.update(spec)
            return b"native-spec-only"

        from matplotlib.figure import Figure

        with fixture_rc_context():
            figure = Figure(figsize=(2.0, 1.0), dpi=EFFECTIVE_DPI)
            axes = figure.add_axes((0.1, 0.1, 0.8, 0.8))
            axes.set_axis_off()
            build(axes)
            axes.set_xlim(0.0, 10.0)
            axes.set_ylim(-2.0, 6.0)
            canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
            with unittest.mock.patch.object(
                canvas, "_call_native", side_effect=capture_spec
            ):
                result = canvas.render_png(dpi=EFFECTIVE_DPI)
        self.assertEqual(result.diagnostics, ())
        commands = captured["commands"]
        return [c for c in commands if not c.get("decoration")]

    def test_stack_faces_reach_fill_rgba_with_no_stroke(self):
        """``edgecolor="none"`` plus zero width draws no stroke."""

        def build(axes):
            axes.stackplot(
                list(STACK_X),
                [list(layer) for layer in STACK_LAYERS],
                colors=list(STACK_FACES),
                edgecolor="none",
                linewidth=0.0,
            )

        commands = self._strict_commands(build)
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0]["fill_rgba"], [255, 165, 0, 255])
        self.assertEqual(commands[1]["fill_rgba"], [128, 0, 128, 255])
        for command in commands:
            self.assertIsNone(command["stroke_rgba"])
        # FillBetweenPolyCollection carries Agg's round join / butt cap.
        self.assertEqual(commands[0]["join"], "round")
        self.assertEqual(commands[0]["cap"], "butt")

    def test_explicit_alpha_applies_once(self):
        """Agg bakes the explicit alpha into the resolved face exactly once."""

        def build(axes):
            axes.stackplot(
                list(STACK_X),
                [list(layer) for layer in STACK_LAYERS],
                colors=list(STACK_FACES),
                edgecolor="none",
                linewidth=0.0,
                alpha=0.5,
            )

        commands = self._strict_commands(build)
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0]["fill_rgba"], [255, 165, 0, 128])
        self.assertEqual(commands[1]["fill_rgba"], [128, 0, 128, 128])
        for command in commands:
            self.assertIsNone(command["stroke_rgba"])

    def test_explicit_edge_color_and_width_strokes(self):
        def build(axes):
            axes.stackplot(
                list(STACK_X),
                [list(STACK_LAYERS[0])],
                colors=[STACK_FACES[0]],
                edgecolor="black",
                linewidth=2.0,
            )

        commands = self._strict_commands(build)
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0]["fill_rgba"], [255, 165, 0, 255])
        self.assertEqual(commands[0]["stroke_rgba"], [0, 0, 0, 255])
        self.assertEqual(commands[0]["line_width_pt"], 2.0)


class TestStackplotNativeAggParity(unittest.TestCase):
    """Compare the fixed stack input through the real adapter/native seam only."""

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
