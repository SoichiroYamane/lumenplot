"""Focused Agg-oracle tests for the base-10 log-frame fixture.

The semantic checks run without the compiled extension.  The pixel comparison
is deliberately a separate strict native test: it is skipped with an explicit
setup reason when ``lumenplot_mpl._native.render_frame_png`` is unavailable and
never substitutes a stub or Agg fallback as parity evidence.
"""

from __future__ import annotations

import hashlib
import importlib
import math
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
        from .generate_agg_oracle_log import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            LOG_BASE,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            X_DATA,
            XLIM,
            XSCALE,
            Y_DATA,
            YLIM,
            YSCALE,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
    except ImportError:  # ``unittest discover -s tests/python``
        from generate_agg_oracle_log import (
            EFFECTIVE_DPI,
            FIXTURE_DIR,
            LOG_BASE,
            MANIFEST_PATH,
            ORACLE_MATPLOTLIB_VERSION,
            X_DATA,
            XLIM,
            XSCALE,
            Y_DATA,
            YLIM,
            YSCALE,
            build_fixture_figure,
            fixture_rc_context,
            render_reference,
        )
else:
    EFFECTIVE_DPI = 0.0
    FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
    LOG_BASE = 10
    MANIFEST_PATH = FIXTURE_DIR / "log_axis_manifest.json"
    ORACLE_MATPLOTLIB_VERSION = "3.11.1"
    X_DATA = ()
    XLIM = (0.0, 1.0)
    XSCALE = "linear"
    Y_DATA = ()
    YLIM = (1.0, 1000.0)
    YSCALE = "log"


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


class TestCommittedLogAxisFixture(unittest.TestCase):
    """The committed fixture is generated and checked without native code."""

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixture = load_reference_fixture(MANIFEST_PATH)

    def test_manifest_records_pinned_render_contract_and_digests(self):
        manifest = self.fixture.manifest
        self.assertEqual(
            manifest["fixture_id"],
            "log-axis-base10-line-decades-span",
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
        self.assertEqual(
            manifest["primitive"]["scales"],
            {"x": "linear", "y": "log", "log_base": 10},
        )
        self.assertEqual(
            manifest["figure"]["options"]["xscale"], "linear"
        )
        self.assertEqual(manifest["figure"]["options"]["yscale"], "log")
        self.assertEqual(manifest["figure"]["options"]["log_base"], 10)
        self.assertEqual(manifest["figure"]["options"]["axis_on"], False)
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
            "line.get_path().iter_segments(remove_nans=True)",
        )
        self.assertEqual(
            manifest["topology"]["display_api"],
            "axes.transData.transform(data)",
        )
        self.assertEqual(
            manifest["input_data"]["cases"],
            {
                "log-y-line": {
                    "artist": "matplotlib.lines.Line2D",
                    "xscale": "linear",
                    "yscale": "log",
                    "log_base": 10,
                },
            },
        )
        self.assertEqual(manifest["input_data"]["xscale"], XSCALE)
        self.assertEqual(manifest["input_data"]["yscale"], YSCALE)
        self.assertEqual(manifest["input_data"]["log_base"], LOG_BASE)
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

    def test_log_topology_pins_base10_fraction_and_display(self):
        """The committed topology carries the exact base-10 log projection."""

        topology = self.fixture.manifest["topology"]
        self.assertEqual(topology["scales"], {"x": "linear", "y": "log", "log_base": 10})
        self.assertEqual(topology["limits"], {"xlim": [0.0, 1.0], "ylim": [1.0, 1000.0]})
        self.assertEqual(topology["segment_count"], 5)
        self.assertEqual(topology["subpath_count"], 1)
        self.assertEqual(topology["moveto_count"], 1)
        self.assertEqual(topology["lineto_count"], 4)
        self.assertEqual(topology["segment_codes"], [1, 2, 2, 2, 2])
        # One finite run: no gap splits on this all-positive log-domain input.
        self.assertEqual(
            topology["vertices"],
            [[0.1, 2.0], [0.3, 12.0], [0.5, 60.0], [0.7, 250.0], [0.9, 800.0]],
        )
        # Base-10 fractions are exact: (log10(v)-log10(lo))/(log10(hi)-log10(lo)).
        expected_fractions = [
            (math.log10(y) - math.log10(YLIM[0]))
            / (math.log10(YLIM[1]) - math.log10(YLIM[0]))
            for y in Y_DATA
        ]
        for got, want in zip(topology["log_fractions_y"], expected_fractions):
            self.assertAlmostEqual(got, want, places=12)
        # Display vertices equal the public transData projection of the data.
        with fixture_rc_context():
            _figure, axes, _line = build_fixture_figure()
            self.assertEqual(str(axes.get_xscale()), "linear")
            self.assertEqual(str(axes.get_yscale()), "log")
            data = np.column_stack(
                [np.asarray(X_DATA, dtype=float), np.asarray(Y_DATA, dtype=float)]
            )
            expected_display = axes.transData.transform(data).tolist()
        self.assertEqual(len(topology["display_vertices"]), 5)
        np.testing.assert_allclose(
            np.asarray(topology["display_vertices"], dtype=float),
            np.asarray(expected_display, dtype=float),
            atol=1e-9,
        )
        # The y display row follows the fractional placement through the
        # fixed axes box (x0=20, y0=10, w=160, h=80 for this figure).
        for (dx, dy), frac in zip(topology["display_vertices"], expected_fractions):
            self.assertAlmostEqual(dy, 10.0 + frac * 80.0, places=6)
        for (dx, _dy), x in zip(topology["display_vertices"], X_DATA):
            self.assertAlmostEqual(dx, 20.0 + (x - 0.0) / 1.0 * 160.0, places=6)
        # The data spans more than two decades: a non-vacuous log workload.
        span_decades = math.log10(max(Y_DATA)) - math.log10(min(Y_DATA))
        self.assertGreater(span_decades, 2.0)
        # This stroke-only axis-off fixture carries no text or outline pixels.
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

    def test_adapter_commands_carry_exact_log_geometry_and_style(self):
        """The native spec holds one stroke on the Agg log-projected polyline."""

        from matplotlib.colors import to_rgba

        def rgba8(name):
            return [int(v) for v in np.rint(np.asarray(to_rgba(name)) * 255.0)]

        backend = importlib.import_module("lumenplot_mpl.backend")
        captured: dict[str, object] = {}

        def capture_spec(spec, _generation):
            captured.update(spec)
            return b"native-spec-only"

        with fixture_rc_context():
            figure, axes, _line = build_fixture_figure()
            canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
            with unittest.mock.patch.object(
                canvas, "_call_native", side_effect=capture_spec
            ):
                result = canvas.render_png(dpi=EFFECTIVE_DPI)

        self.assertEqual(result.diagnostics, ())
        commands = captured["commands"]
        self.assertIsInstance(commands, list)
        self.assertEqual(len(commands), 1)
        command = commands[0]
        self.assertEqual(command["kind"], "path")
        self.assertIsNone(command.get("fill_rgba"))
        self.assertEqual(command["stroke_rgba"], rgba8("red"))
        self.assertEqual(command["stroke_rgba"], [255, 0, 0, 255])
        self.assertEqual(command["line_width_pt"], 2.0)
        self.assertEqual(command["cap"], "butt")
        self.assertEqual(command["join"], "miter")
        self.assertIsNone(command["dashes"])
        # ``codes=None`` is the accepted implicit MOVETO/LINETO form.
        self.assertIsNone(command["codes"])
        # The command vertices equal the committed display projection, which
        # itself equals the public transData oracle (not the adapter route).
        expected_display = np.asarray(
            self.fixture.manifest["topology"]["display_vertices"], dtype=float
        )
        got = np.asarray(command["vertices"], dtype=float)
        self.assertEqual(got.shape, (5, 2))
        self.assertEqual(got.shape, expected_display.shape)
        np.testing.assert_allclose(got, expected_display, atol=1e-9)
        with fixture_rc_context():
            _figure2, axes2, _line2 = build_fixture_figure()
            oracle_display = axes2.transData.transform(
                np.column_stack(
                    [np.asarray(X_DATA, dtype=float), np.asarray(Y_DATA, dtype=float)]
                )
            )
        np.testing.assert_allclose(got, np.asarray(oracle_display), atol=1e-9)
        # Fixed axes box for figsize (2.0, 1.0) at 100 dpi with rect
        # (0.1, 0.1, 0.8, 0.8): the adapter clips to the same rect Agg uses.
        self.assertEqual(command["clip_rect"], [20.0, 10.0, 160.0, 80.0])

    def test_adapter_preserves_clip_floor_for_nonpositive_data(self):
        """Non-positive samples project to the -1000 clip floor (LP-FUNC-004)."""

        backend = importlib.import_module("lumenplot_mpl.backend")
        captured: dict[str, object] = {}

        def capture_spec(spec, _generation):
            captured.update(spec)
            return b"native-spec-only"

        with fixture_rc_context():
            from matplotlib.figure import Figure as _Figure

            fig = _Figure(figsize=(2.0, 1.0), dpi=100)
            ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
            ax.set_facecolor("none")
            ax.plot(
                [-1.0, 1.0],
                [-5.0, 500.0],
                color="red",
                linewidth=2.0,
                solid_capstyle="butt",
                solid_joinstyle="miter",
            )
            ax.set_xscale("linear")
            ax.set_yscale("log", base=10)
            ax.set_xlim(-1.0, 1.0)
            ax.set_ylim(1.0, 1000.0)
            ax.set_axis_off()
            canvas = backend.FigureCanvasLumenPlot(fig, mode="strict")
            with unittest.mock.patch.object(
                canvas, "_call_native", side_effect=capture_spec
            ):
                result = canvas.render_png(dpi=EFFECTIVE_DPI)

        self.assertEqual(result.diagnostics, ())
        commands = [
            c for c in captured["commands"] if c.get("decoration") is None
        ]
        self.assertEqual(len(commands), 1)
        vertices = commands[0]["vertices"]
        self.assertEqual(len(vertices), 2)
        # The clipped endpoint lands far below the axes bottom edge in
        # bottom-left pixel space (Agg clips it out of the raster).
        self.assertLess(vertices[0][1], 10.0 - 50.0)
        self.assertEqual(commands[0]["clip_rect"], [20.0, 10.0, 160.0, 80.0])


class TestLogAxisNativeAggParity(unittest.TestCase):
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
