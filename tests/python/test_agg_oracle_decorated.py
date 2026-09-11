"""Focused Agg-oracle tests for the decorated-frame fixture.

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
        from .generate_agg_oracle_decorated import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            GRID_COLOR,
            GRID_LINEWIDTH,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            SPINE_COLOR,
            SPINE_LINEWIDTH,
            TICK_WIDTH,
            XTICKS,
            YTICKS,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
    except ImportError:  # ``unittest discover -s tests/python``
        from generate_agg_oracle_decorated import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            GRID_COLOR,
            GRID_LINEWIDTH,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            SPINE_COLOR,
            SPINE_LINEWIDTH,
            TICK_WIDTH,
            XTICKS,
            YTICKS,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
else:
    EFFECTIVE_DPI = 0.0
    FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
    GRID_COLOR = "#808080"
    GRID_LINEWIDTH = 0.8
    MANIFEST_PATH = FIXTURE_DIR / "decorated_frame_manifest.json"
    ORACLE_MATPLOTLIB_VERSION = "3.11.1"
    SPINE_COLOR = "black"
    SPINE_LINEWIDTH = 1.0
    TICK_WIDTH = 0.8
    XTICKS = ()
    YTICKS = ()


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


class TestCommittedDecoratedFixture(unittest.TestCase):
    """The committed fixture is generated and checked without native code."""

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixture = load_reference_fixture(MANIFEST_PATH)

    def test_manifest_records_pinned_render_contract_and_digests(self):
        manifest = self.fixture.manifest
        self.assertEqual(
            manifest["fixture_id"], "decorated-frame-ticklabels-grid-spines"
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
            manifest["artist_class"], "matplotlib.axes.Axes"
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
            manifest["input_data"]["cases"]["content_line"],
            {"artist": "matplotlib.lines.Line2D", "color": "red"},
        )
        self.assertEqual(
            manifest["input_data"]["cases"]["tick_labels"],
            {"artist": "matplotlib.text.Text", "count": 6},
        )
        self.assertEqual(
            manifest["input_data"]["cases"]["grid"],
            {"artist": "matplotlib.lines.Line2D", "which": "major"},
        )
        self.assertEqual(
            manifest["input_data"]["cases"]["spines"],
            {
                "artist": "matplotlib.spines.Spine",
                "sides": ["left", "right", "top", "bottom"],
            },
        )
        self.assertEqual(manifest["input_data"]["xticks"], [0.0, 5.0, 10.0])
        self.assertEqual(manifest["input_data"]["yticks"], [0.0, 2.5, 5.0])
        self.assertEqual(manifest["input_data"]["line"]["color"], "red")
        self.assertEqual(manifest["figure"]["options"]["axis_on"], True)
        self.assertEqual(manifest["figure"]["options"]["xlim"], [0.0, 10.0])
        self.assertEqual(manifest["figure"]["options"]["ylim"], [0.0, 5.0])
        # The tick stroke the adapter emits inherits rc lines.linewidth
        # while Agg draws ticks at the tick width: the pinned cell keeps
        # both at the same value so the fixture cannot drift apart.
        self.assertEqual(manifest["rcparams"]["lines.linewidth"], TICK_WIDTH)
        self.assertEqual(manifest["rcparams"]["grid.color"], GRID_COLOR)
        self.assertEqual(manifest["rcparams"]["grid.linewidth"], GRID_LINEWIDTH)
        self.assertEqual(manifest["rcparams"]["axes.edgecolor"], SPINE_COLOR)
        self.assertEqual(manifest["rcparams"]["axes.linewidth"], SPINE_LINEWIDTH)

    def test_generator_reproduces_committed_png_mask_and_topology(self):
        generated_png, generated_mask, generated_topology, dimensions = (
            render_reference()
        )
        self.assertEqual(generated_png, self.fixture.reference_png)
        self.assertTrue(np.array_equal(generated_mask, self.fixture.mask.labels))
        self.assertEqual(dimensions, (200, 100))
        self.assertEqual(generated_topology, self.fixture.manifest["topology"])

    def test_public_geometry_pins_decorated_frame(self):
        """Tick labels, box/spines, and major grid resolve via public getters."""

        topology = self.fixture.manifest["topology"]
        axes = topology["axes"]
        self.assertEqual(axes["rect"], [0.1, 0.1, 0.8, 0.8])
        self.assertEqual(axes["xlim"], [0.0, 10.0])
        self.assertEqual(axes["ylim"], [0.0, 5.0])
        self.assertTrue(axes["axis_on"])

        line = topology["line"]
        self.assertEqual(line["class"], "matplotlib.lines.Line2D")
        self.assertEqual(line["xdata"], [0.0, 10.0])
        self.assertEqual(line["ydata"], [0.0, 5.0])
        self.assertEqual(line["color"], "red")
        self.assertEqual(line["linewidth"], 2.0)
        self.assertEqual(line["marker"], "None")
        self.assertEqual(line["drawstyle"], "default")
        self.assertEqual(line["solid_capstyle"], "butt")
        self.assertEqual(line["solid_joinstyle"], "miter")
        self.assertEqual(line["segment_codes"], [1, 2])

        ticks = topology["ticks"]
        self.assertEqual(ticks["x_ticklocs"], [0.0, 5.0, 10.0])
        self.assertEqual(ticks["y_ticklocs"], [0.0, 2.5, 5.0])
        self.assertEqual(ticks["x_labels"], ["0", "5", "10"])
        self.assertEqual(ticks["y_labels"], ["0.0", "2.5", "5.0"])
        self.assertEqual(ticks["x_label_visible"], [True, True, True])
        self.assertEqual(ticks["y_label_visible"], [True, True, True])
        for text in ticks["x_labels"] + ticks["y_labels"]:
            self.assertEqual(text, text.strip())
            self.assertNotIn("\n", text)
            self.assertNotIn("$", text)

        grid = topology["grid"]
        self.assertEqual(grid["which"], "major")
        self.assertEqual(len(grid["entries"]), 6)
        for entry in grid["entries"]:
            self.assertTrue(entry["visible"])
            self.assertEqual(entry["color"], GRID_COLOR)
            self.assertEqual(entry["linewidth"], GRID_LINEWIDTH)
            self.assertEqual(entry["linestyle"], "-")

        spines = topology["spines"]["sides"]
        self.assertEqual(set(spines), {"left", "right", "top", "bottom"})
        for side in ("left", "right", "top", "bottom"):
            self.assertTrue(spines[side]["visible"])
            self.assertEqual(spines[side]["linewidth"], SPINE_LINEWIDTH)

        # Six labels, six gridlines, four spines: the frame is fully
        # decorated, and the mask covers background, exact interiors,
        # and antialiased fringe without an unused catch-all.
        self.assertEqual(
            set(np.unique(self.fixture.mask.labels)),
            {
                PIXEL_CLASS_CODES["background"],
                PIXEL_CLASS_CODES["fully-covered"],
                PIXEL_CLASS_CODES["antialias-fringe"],
            },
        )

    def test_adapter_commands_carry_exact_decorated_geometry(self):
        """The native spec holds content plus grid/tick/spine/label groups."""

        backend = importlib.import_module("lumenplot_mpl.backend")
        captured: dict[str, object] = {}

        def capture_spec(spec, _generation):
            captured.update(spec)
            return b"native-spec-only"

        with fixture_rc_context():
            figure, axes, _artists = build_fixture_figure()
            canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
            with unittest.mock.patch.object(
                canvas, "_call_native", side_effect=capture_spec
            ):
                result = canvas.render_png(dpi=EFFECTIVE_DPI)

        self.assertEqual(result.diagnostics, ())
        commands = captured["commands"]
        self.assertIsInstance(commands, list)
        grids = [c for c in commands if c.get("decoration") == "gridline"]
        ticks = [c for c in commands if c.get("decoration") == "tick"]
        spines = [c for c in commands if c.get("decoration") == "spine"]
        labels = [c for c in commands if c.get("decoration") == "tick_label"]
        content = [c for c in commands if "decoration" not in c]
        # Three in-view major ticks per axis drive three vertical plus
        # three horizontal solid gridlines; bottom/left edges drive six
        # outward tick strokes; the box keeps four spine edges; every
        # visible label contributes one glyph path; one content line.
        self.assertEqual(len(grids), 6)
        self.assertEqual(len(ticks), 6)
        self.assertEqual(len(spines), 4)
        self.assertEqual(len(labels), 6)
        self.assertEqual(len(content), 1)
        self.assertEqual(len(commands), 23)
        for command in grids:
            self.assertEqual(command["kind"], "path")
            self.assertEqual(command["stroke_rgba"], _rgba8(GRID_COLOR))
            self.assertIsNone(command.get("fill_rgba"))
            self.assertEqual(command["line_width_pt"], GRID_LINEWIDTH)
        for command in ticks:
            self.assertEqual(command["kind"], "path")
            self.assertEqual(command["stroke_rgba"], [0, 0, 0, 255])
            self.assertEqual(command["line_width_pt"], TICK_WIDTH)
            self.assertEqual(command["cap"], "butt")
        for command in spines:
            self.assertEqual(command["kind"], "path")
            self.assertEqual(command["stroke_rgba"], _rgba8(SPINE_COLOR))
            self.assertEqual(command["line_width_pt"], SPINE_LINEWIDTH)
            self.assertEqual(command["cap"], "butt")
            self.assertEqual(command["join"], "miter")
        for command in labels:
            self.assertEqual(command["kind"], "path")
            self.assertEqual(command["fill_rgba"], [0, 0, 0, 255])
            self.assertIsNone(command["stroke_rgba"])
            self.assertEqual(command["line_width_pt"], 0.0)
            self.assertEqual(command["cap"], "butt")
            self.assertEqual(command["join"], "miter")
        stroke = content[0]
        self.assertEqual(stroke["kind"], "path")
        self.assertEqual(stroke["stroke_rgba"], _rgba8("red"))
        self.assertEqual(stroke["line_width_pt"], 2.0)
        expected_vertices = axes.transData.transform([(0.0, 0.0), (10.0, 5.0)])
        np.testing.assert_allclose(
            np.asarray(stroke["vertices"], dtype=float),
            np.asarray(expected_vertices, dtype=float),
            atol=1e-9,
        )

    def test_tick_labels_are_non_vacuous(self):
        """Hiding the labels changes the Agg reference, proving coverage."""

        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure
        from matplotlib.lines import Line2D

        with fixture_rc_context():
            reference_png, _mask, _topology, _dimensions = render_reference()
            figure = Figure(figsize=(2.0, 1.0), dpi=EFFECTIVE_DPI)
            axes = figure.add_axes((0.1, 0.1, 0.8, 0.8))
            axes.set_facecolor("none")
            axes.add_line(Line2D([0.0, 10.0], [0.0, 5.0], **{
                "color": "red",
                "linewidth": 2.0,
                "linestyle": "-",
                "marker": "None",
                "drawstyle": "default",
                "solid_capstyle": "butt",
                "solid_joinstyle": "miter",
                "antialiased": True,
            }))
            axes.set_xticks([0.0, 5.0, 10.0])
            axes.set_yticks([0.0, 2.5, 5.0])
            axes.tick_params(labelbottom=False, labelleft=False)
            axes.grid(
                True,
                which="major",
                axis="both",
                color=GRID_COLOR,
                linewidth=GRID_LINEWIDTH,
                linestyle="-",
                alpha=1.0,
            )
            axes.set_xlim(0.0, 10.0)
            axes.set_ylim(0.0, 5.0)
            canvas = FigureCanvasAgg(figure)
            import io

            buffer = io.BytesIO()
            canvas.print_png(buffer, metadata={})
            labels_off_png = buffer.getvalue()
        self.assertNotEqual(labels_off_png, reference_png)


class TestDecoratedNativeAggParity(unittest.TestCase):
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
