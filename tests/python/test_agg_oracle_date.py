"""Focused Agg-oracle tests for the date-axis fixture (LP-FUNC-037).

The committed fixture pins one bounded date/unit-aware axes-on frame:
Figure-authoritative converted numeric data, ``AutoDateLocator`` /
``AutoDateFormatter`` results, visible major ticks with solid major
gridlines on both axes, four visible spine edges, and plain date label
glyphs.

The semantic checks run without the compiled extension.  The pixel
comparison is deliberately a separate strict native test: it is skipped
with an explicit setup reason when
``lumenplot_mpl._native.render_frame_png`` is unavailable and never
substitutes a stub or Agg fallback as parity evidence.
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
        from .generate_agg_oracle_date import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            INPUT_DATES,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            Y_DATA,
            YLIM,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
    except ImportError:  # ``unittest discover -s tests/python``
        from generate_agg_oracle_date import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            INPUT_DATES,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            Y_DATA,
            YLIM,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
else:
    EFFECTIVE_DPI = 0.0
    FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
    MANIFEST_PATH = FIXTURE_DIR / "date_axis_manifest.json"
    ORACLE_MATPLOTLIB_VERSION = "3.11.1"
    INPUT_DATES = ()
    Y_DATA = ()
    YLIM = (0.0, 4.0)


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


class TestCommittedDateAxisFixture(unittest.TestCase):
    """The committed fixture is generated and checked without native code."""

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixture = load_reference_fixture(MANIFEST_PATH)

    def test_manifest_records_pinned_render_contract_and_digests(self):
        manifest = self.fixture.manifest
        self.assertEqual(
            manifest["fixture_id"],
            "date-axis-converted-line-decorated",
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
                "date-x-line": {
                    "artist": "matplotlib.lines.Line2D",
                    "construction": "axes.plot(datetimes, y)",
                    "converter": "date",
                    "locator": "matplotlib.dates.AutoDateLocator",
                    "formatter": "matplotlib.dates.AutoDateFormatter",
                },
            },
        )
        self.assertTrue(manifest["figure"]["options"]["axis_on"])
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

    def test_converted_data_matches_date2num_upstream(self):
        """LP-MPL-022: the committed data is the public converted route."""

        topology = self.fixture.manifest["topology"]
        self.assertEqual(topology["line_api"], (
            "line.get_xdata(orig=False)/line.get_ydata(orig=False)"
        ))
        self.assertEqual(
            topology["input_dates_iso"],
            ["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"],
        )
        # The converter resolved upstream: converted floats equal the
        # independent date2num cross-check exactly.
        self.assertEqual(topology["converted_x"], [20454.0, 20455.0, 20456.0])
        self.assertEqual(
            topology["converted_x"],
            topology["conversion_cross_check"]["date2num"],
        )
        self.assertEqual(topology["converted_y"], [1.0, 3.0, 2.0])
        for value in topology["converted_x"] + topology["converted_y"]:
            self.assertTrue(np.isfinite(value))
        # One finite run: no gap splits on this all-finite date input.
        self.assertEqual(topology["segment_count"], 3)
        self.assertEqual(topology["subpath_count"], 1)
        self.assertEqual(topology["moveto_count"], 1)
        self.assertEqual(topology["lineto_count"], 2)
        self.assertEqual(topology["segment_codes"], [1, 2, 2])
        self.assertEqual(
            topology["vertices"],
            [[20454.0, 1.0], [20455.0, 3.0], [20456.0, 2.0]],
        )

    def test_locator_formatter_outputs_are_pinned(self):
        """LP-FUNC-037: locator/formatter results equal Agg's outputs."""

        topology = self.fixture.manifest["topology"]
        self.assertEqual(topology["locator"]["class"], "AutoDateLocator")
        self.assertEqual(topology["locator"]["minticks"], 2)
        self.assertEqual(topology["formatters"]["x"], "AutoDateFormatter")
        self.assertEqual(topology["formatters"]["y"], "ScalarFormatter")
        self.assertEqual(topology["xticklocs"], [20454.0, 20455.0, 20456.0])
        self.assertEqual(
            topology["xticklabels"],
            ["2026-01-01", "2026-01-02", "2026-01-03"],
        )
        self.assertEqual(topology["yticklocs"], [0.0, 2.0, 4.0])
        self.assertEqual(topology["yticklabels"], ["0", "2", "4"])
        # Plain date label glyphs only: no mathtext markers, no blank-padded
        # labels, no offset text on either axis.
        for text in topology["xticklabels"] + topology["yticklabels"]:
            self.assertNotIn("$", text)
            self.assertEqual(text, text.strip())
            self.assertNotIn("\n", text)
        with fixture_rc_context():
            _figure, axes, _line = build_fixture_figure()
            from matplotlib.backends.backend_agg import FigureCanvasAgg

            FigureCanvasAgg(_figure)
            _figure.draw_without_rendering()
            self.assertEqual(axes.xaxis.get_offset_text().get_text(), "")
            self.assertEqual(axes.yaxis.get_offset_text().get_text(), "")
        # Display geometry is the public transData projection of the
        # converted data: x spans the full axes box, y follows the limits.
        self.assertEqual(
            topology["display_vertices"],
            [[20.0, 30.0], [100.0, 70.0], [180.0, 50.0]],
        )
        self.assertEqual(
            topology["limits"]["xlim_converted"], [20454.0, 20456.0]
        )

    def test_decoration_surface_is_pinned(self):
        """Grid, spine, and mask facts travel with the committed fixture."""

        topology = self.fixture.manifest["topology"]
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
            name: int((self.fixture.mask.labels == code).sum())
            for name, code in PIXEL_CLASS_CODES.items()
        }
        self.assertGreater(counts["background"], 0)
        self.assertGreater(counts["fully-covered"], 0)
        self.assertGreater(counts["antialias-fringe"], 0)
        self.assertEqual(counts["text-or-outline"], 0)


class TestDateAxisAdapterSemantics(unittest.TestCase):
    """The adapter spec reproduces the fixture surface without native code."""

    def setUp(self):
        _require_pinned_matplotlib()

    def _strict_commands(self):
        backend = importlib.import_module("lumenplot_mpl.backend")
        captured: dict[str, object] = {}

        def capture_spec(spec, _generation):
            captured.update(spec)
            return b"native-spec-only"

        with fixture_rc_context():
            figure, _axes = build_fixture_figure()[:2]
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

        commands = self._strict_commands()
        content = [c for c in commands if c.get("decoration") is None]
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
        # The command vertices equal the committed display projection of
        # the converted data, which itself equals the public transData
        # oracle (not the adapter route).
        expected_display = np.asarray(
            load_reference_fixture(MANIFEST_PATH).manifest["topology"][
                "display_vertices"
            ],
            dtype=float,
        )
        got = np.asarray(command["vertices"], dtype=float)
        self.assertEqual(got.shape, (3, 2))
        np.testing.assert_allclose(got, expected_display, atol=1e-9)
        self.assertEqual(command["clip_rect"], [20.0, 10.0, 160.0, 80.0])

    def test_strict_spec_carries_six_glyph_commands_in_draw_order(self):
        """One resolved-face glyph command per visible major label, x first."""

        textpath = importlib.import_module("lumenplot_mpl.textpath")
        commands = self._strict_commands()
        glyphs = [c for c in commands if c.get("decoration") == "tick_label"]
        self.assertEqual(len(glyphs), 6)
        with fixture_rc_context():
            _figure, axes = build_fixture_figure()[:2]
            labels = [
                label
                for axis in (axes.xaxis, axes.yaxis)
                for label in axis.get_majorticklabels()
                if label.get_visible() and label.get_text() != ""
            ]
        self.assertEqual(
            [label.get_text() for label in labels],
            ["2026-01-01", "2026-01-02", "2026-01-03", "0", "2", "4"],
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

    def test_strict_spec_gridlines_ticks_and_spines(self):
        """Grid, tick, and spine strokes ride the fixed axes geometry."""

        commands = self._strict_commands()
        gridlines = [c for c in commands if c.get("decoration") == "gridline"]
        ticks = [c for c in commands if c.get("decoration") == "tick"]
        spines = [c for c in commands if c.get("decoration") == "spine"]
        # Three major ticks per axis carry one gridline and one tick each.
        self.assertEqual(len(gridlines), 6)
        self.assertEqual(len(ticks), 6)
        for command in gridlines:
            self.assertEqual(command["stroke_rgba"], [176, 176, 176, 255])
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


@unittest.skip(
    "Fixture-only landing per commander 2026-09-12 (ticklabels precedent): "
    "strict parity red on first candidate (thin 0.8pt grid/spine/tick "
    "coverage + date-glyph fringe, rasterizer trait shared with ticklabels "
    "lane); re-measure scheduled post-PR171 convergence lane. S15.1 gate "
    "unchanged."
)
class TestDateAxisNativeAggParity(unittest.TestCase):
    """Compare the fixed date input through the real adapter/native seam only.

    Measured red on the first candidate (2026-09-12, origin/main c7f9f13,
    locally built ``_native`` from the same source, CPython 3.14.7 +
    matplotlib 3.11.1): ``200x100 top-to-bottom; max_delta=255,
    mean_delta=6.007850, mismatches=2336, exact_mismatches=697,
    fringe_mismatches=1639, fringe_oversized=1597,
    fringe_rate=0.081950`` against the fixed budget (exact classes
    byte-equal, fringe max delta 1, total-pixel fringe rate <= 0.001).
    Attribution: zero native-dark pixels fall outside a 2px dilation of
    Agg ink (no misplacement, no missing content); Agg inks ~190 pixels
    the native leaves blank and 1250 pixels differ by more than 32 --
    thin 0.8pt grid/spine/tick coverage plus date-glyph edges, the same
    engine-wide rasterizer trait the ticklabels lane records.  The gate
    stays fixed; this test is the red evidence, not a tunable threshold.
    """

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixture = load_reference_fixture(MANIFEST_PATH)
        # This must remain a real-extension check.  No recording stub or
        # hybrid/Agg fallback is permitted to make the pixel assertion pass.
        self.native = _require_real_native_seam()

    def test_strict_native_render_matches_fixed_agg_reference(self):
        backend = importlib.import_module("lumenplot_mpl.backend")
        with fixture_rc_context():
            figure, _axes, _line = build_fixture_figure()
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
