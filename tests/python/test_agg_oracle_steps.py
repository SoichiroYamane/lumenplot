"""Focused Agg-oracle tests for the step-drawstyle fixture.

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
        from .generate_agg_oracle_steps import (
            DRAWSTYLES,
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            STEP_LINES,
            X_DATA,
            build_fixture_figure,
            fixture_rc_context,
            oracle_step_vertices,
            render_reference,
        )
    except ImportError:  # ``unittest discover -s tests/python``
        from generate_agg_oracle_steps import (
            DRAWSTYLES,
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            STEP_LINES,
            X_DATA,
            build_fixture_figure,
            fixture_rc_context,
            oracle_step_vertices,
            render_reference,
        )
else:
    DRAWSTYLES = ("steps-pre", "steps-post", "steps-mid")
    EFFECTIVE_DPI = 0.0
    FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
    MANIFEST_PATH = FIXTURE_DIR / "steps_manifest.json"
    ORACLE_MATPLOTLIB_VERSION = "3.11.1"
    STEP_LINES = {}
    X_DATA = ()


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


# The exact expanded vertex sequences Matplotlib 3.11.1 itself draws for the
# fixture input.  These literals are independent of the generator: they pin
# the oracle geometry so a generator regression cannot hide behind its own
# output.
EXPECTED_EXPANDED: dict[str, dict[str, list[float]]] = {
    "steps-pre": {
        "x": [0.0, 0.0, 2.5, 2.5, 5.0, 5.0, 7.5, 7.5, 10.0],
        "y": [1.0, 2.0, 2.0, 1.5, 1.5, 2.0, 2.0, 1.0, 1.0],
    },
    "steps-post": {
        "x": [0.0, 2.5, 2.5, 5.0, 5.0, 7.5, 7.5, 10.0, 10.0],
        "y": [3.0, 3.0, 4.0, 4.0, 3.5, 3.5, 4.0, 4.0, 3.0],
    },
    "steps-mid": {
        "x": [0.0, 1.25, 1.25, 3.75, 3.75, 6.25, 6.25, 8.75, 8.75, 10.0],
        "y": [4.6, 4.6, 5.4, 5.4, 4.9, 4.9, 5.4, 5.4, 4.7, 4.7],
    },
}


class TestCommittedStepsFixture(unittest.TestCase):
    """The committed fixture is generated and checked without native code."""

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixture = load_reference_fixture(MANIFEST_PATH)

    def test_manifest_records_pinned_render_contract_and_digests(self):
        manifest = self.fixture.manifest
        self.assertEqual(
            manifest["fixture_id"],
            "line2d-steps-pre-post-mid-exact-vertices",
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
        self.assertEqual(manifest["artist_class"], "matplotlib.lines.Line2D")
        self.assertEqual(
            manifest["primitive"]["class"], "matplotlib.lines.Line2D"
        )
        self.assertEqual(manifest["primitive"]["count"], 3)
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
            manifest["topology"]["api"],
            "matplotlib.cbook.STEP_LOOKUP_MAP[drawstyle](x, y)",
        )
        self.assertEqual(
            manifest["input_data"]["cases"],
            {
                "steps-pre": {
                    "artist": "matplotlib.lines.Line2D",
                    "drawstyle": "steps-pre",
                    "color": "red",
                },
                "steps-post": {
                    "artist": "matplotlib.lines.Line2D",
                    "drawstyle": "steps-post",
                    "color": "blue",
                },
                "steps-mid": {
                    "artist": "matplotlib.lines.Line2D",
                    "drawstyle": "steps-mid",
                    "color": "green",
                },
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

    def test_step_oracle_pins_exact_expanded_vertices(self):
        """Every drawstyle expands to its exact Agg vertex sequence."""

        topology = self.fixture.manifest["topology"]["per_drawstyle"]
        self.assertEqual(set(topology), set(DRAWSTYLES))
        with fixture_rc_context():
            _figure, _axes, lines = build_fixture_figure()
            for drawstyle in DRAWSTYLES:
                with self.subTest(drawstyle=drawstyle):
                    entry = topology[drawstyle]
                    self.assertEqual(entry["drawstyle"], drawstyle)
                    self.assertEqual(
                        entry["color"], STEP_LINES[drawstyle]["color"]
                    )
                    # The committed topology equals a fresh public-oracle
                    # expansion of the line's own data ...
                    expanded_x, expanded_y = oracle_step_vertices(
                        drawstyle,
                        list(lines[drawstyle].get_xdata()),
                        list(lines[drawstyle].get_ydata()),
                    )
                    self.assertEqual(entry["expanded_x"], expanded_x)
                    self.assertEqual(entry["expanded_y"], expanded_y)
                    # ... and that oracle output equals the pinned literals,
                    # so the fixture cannot drift with the generator.
                    self.assertEqual(
                        entry["expanded_x"], EXPECTED_EXPANDED[drawstyle]["x"]
                    )
                    self.assertEqual(
                        entry["expanded_y"], EXPECTED_EXPANDED[drawstyle]["y"]
                    )
                    self.assertEqual(
                        entry["expanded_count"],
                        len(EXPECTED_EXPANDED[drawstyle]["x"]),
                    )
        # Pre/post expand N samples to exactly 2N-1 vertices; mid walks
        # endpoint -> midpoint pairs for 2(N-1)+2 vertices.
        self.assertEqual(topology["steps-pre"]["expanded_count"], 2 * 5 - 1)
        self.assertEqual(topology["steps-post"]["expanded_count"], 2 * 5 - 1)
        self.assertEqual(topology["steps-mid"]["expanded_count"], 2 * (5 - 1) + 2)
        # The reference mask classifies background, fully-covered stroke
        # interiors, and antialias fringe; this stroke-only fixture carries
        # no text or outline pixels.
        self.assertEqual(
            set(np.unique(self.fixture.mask.labels)),
            {
                PIXEL_CLASS_CODES["background"],
                PIXEL_CLASS_CODES["fully-covered"],
                PIXEL_CLASS_CODES["antialias-fringe"],
            },
        )

    def test_adapter_commands_carry_exact_step_geometry_and_style(self):
        """The native spec holds three strokes on the Agg step polylines."""

        from matplotlib.colors import to_rgba

        def rgba8(name):
            return [int(v) for v in np.rint(np.asarray(to_rgba(name)) * 255.0)]

        backend = importlib.import_module("lumenplot_mpl.backend")
        captured: dict[str, object] = {}

        def capture_spec(spec, _generation):
            captured.update(spec)
            return b"native-spec-only"

        with fixture_rc_context():
            figure, axes, _lines = build_fixture_figure()
            canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
            with unittest.mock.patch.object(
                canvas, "_call_native", side_effect=capture_spec
            ):
                result = canvas.render_png(dpi=EFFECTIVE_DPI)

        self.assertEqual(result.diagnostics, ())
        commands = captured["commands"]
        self.assertIsInstance(commands, list)
        self.assertEqual(len(commands), 3)
        expected_strokes = [rgba8("red"), rgba8("blue"), rgba8("green")]
        self.assertEqual(
            expected_strokes,
            [[255, 0, 0, 255], [0, 0, 255, 255], [0, 128, 0, 255]],
        )
        for command, drawstyle, expected_stroke in zip(
            commands, DRAWSTYLES, expected_strokes
        ):
            with self.subTest(drawstyle=drawstyle):
                self.assertEqual(command["kind"], "path")
                self.assertIsNone(command.get("fill_rgba"))
                self.assertEqual(command["stroke_rgba"], expected_stroke)
                self.assertEqual(command["line_width_pt"], 2.0)
                self.assertEqual(command["cap"], "butt")
                self.assertEqual(command["join"], "miter")
                self.assertIsNone(command["dashes"])
                # ``codes=None`` is the accepted implicit MOVETO/LINETO form.
                self.assertIsNone(command["codes"])
                # The command vertices equal the oracle expansion pushed
                # through the public axes transform — the adapter's own
                # projection route is not the oracle here.
                expanded = np.column_stack([
                    np.asarray(
                        self.fixture.manifest["topology"]["per_drawstyle"][
                            drawstyle
                        ]["expanded_x"],
                        dtype=float,
                    ),
                    np.asarray(
                        self.fixture.manifest["topology"]["per_drawstyle"][
                            drawstyle
                        ]["expanded_y"],
                        dtype=float,
                    ),
                ])
                expected_display = axes.transData.transform(expanded)
                got = np.asarray(command["vertices"], dtype=float)
                self.assertEqual(got.shape, expected_display.shape)
                np.testing.assert_allclose(got, expected_display, atol=1e-9)


class TestStepsNativeAggParity(unittest.TestCase):
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
            figure, _axes, _lines = build_fixture_figure()
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
