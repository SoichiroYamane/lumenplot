"""Focused Agg-oracle tests for the decorated-frame fixture.

The semantic checks run without the compiled extension.  The pixel comparison
is deliberately a separate strict native test: it is skipped with an explicit
setup reason when ``lumenplot_mpl._native.render_frame_png`` is unavailable and
never substitutes a stub or Agg fallback as parity evidence.  The strict test
encodes a documented, P3-owned glyph quarantine (pinned label-box geometry
that fails loud on drift); the fixed S15.1 manifest contract is unchanged.
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
        FRINGE_MAX_CHANNEL_DELTA,
        PIXEL_CLASS_CODES,
        compare_pngs,
        compare_rgba8,
        decode_png_rgba8,
        load_reference_fixture,
    )
except ImportError:  # ``unittest discover -s tests/python``
    from _agg_oracle import (
        FRINGE_MAX_CHANNEL_DELTA,
        PIXEL_CLASS_CODES,
        compare_pngs,
        compare_rgba8,
        decode_png_rgba8,
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
            # Agg draws spines with the spine's own capstyle (public
            # getter: 'projecting' on every default spine).
            self.assertEqual(command["cap"], "projecting")
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


# Documented glyph quarantine for the strict decorated parity test below.
#
# PARKED scope, P3 writer-track owned. The renderer lane (absorbed main
# fixes: spine canvas-clip plus cap passthrough, emit-always edge-stroke
# clip, projecting-cap exact route, native glyph fill coverage) delivers
# background/fully-covered byte-exact pixels, zero oversized pixels outside
# the six tick-label boxes below, and a single all-delta-1 renderer fringe
# pixel. The remaining in-box residual is glyph-shaping scope: measured 156
# quarantined px (of which 119 oversized, max channel delta 19) on the
# landing lane (successor 5a79f43 of PR156 25fd8f9 onto origin/main
# 0f94986; residual evidence t_bf22c7f7; ruling t_6ad7772c(b); P3 writer
# lane t_71585976; landing t_5bd5f106). That remainder moves only with the
# P3 writer lane, which owns this quarantine's removal.
#
# The quarantine excludes ONLY the six tick-label glyph boxes below (plus
# a fixed 2 px pad). It pins their Agg-measured geometry verbatim and
# fails LOUD if that geometry changes, so no renderer regression can hide
# inside it. If P3 ever clears the glyph residual, the parked-residual
# assertion fails LOUD as well, forcing this quarantine's removal instead
# of letting a dead exclusion linger silently. The fixed S15.1 manifest
# contract itself is unchanged: background/fully-covered byte-exact,
# fringe max channel delta 1, fringe rate over total pixels <= 0.001. The
# de-quarantined image passes that contract in full (the single renderer
# px sits inside the 20 px budget), so the quarantine's only content is
# the pinned exclusion set below.
_GLYPH_QUARANTINE_PAD_PX = 2
# Agg-measured tick-label boxes in display points (bottom-left origin)
# for Matplotlib 3.11.1, DejaVu Sans 10pt, under the fixture rc-params,
# in x-label then y-label order. Pinned verbatim: any drift fails LOUD
# (see the strict test).
_PINNED_LABEL_BOXES = (
    ("0", 15.5, -13.611111111111112, 24.5, 0.2777777777777768),
    ("5", 95.5, -13.611111111111112, 104.5, 0.2777777777777768),
    ("10", 171.0, -13.611111111111112, 189.0, 0.2777777777777768),
    (
        "0.0",
        -11.722222222222223,
        1.3872612847222214,
        10.277777777777777,
        15.27615017361111,
    ),
    (
        "2.5",
        -11.722222222222223,
        41.38726128472222,
        10.277777777777777,
        55.276150173611114,
    ),
    (
        "5.0",
        -11.722222222222223,
        81.38726128472223,
        10.277777777777777,
        95.27615017361111,
    ),
)
# Integer quarantine rects as (label, x0, top_row0, x1, top_row1) with
#   x in [floor(x0) - pad, ceil(x1) + pad) and
#   top-to-bottom rows in [floor(H - y1) - pad, ceil(H - y0) + pad)
# on the fixed 200x100 frame. Pinned verbatim with the boxes above.
_PINNED_QUARANTINE_RECTS = (
    ("0", 13, 97, 27, 100),
    ("5", 93, 97, 107, 100),
    ("10", 169, 97, 191, 100),
    ("0.0", 0, 82, 13, 100),
    ("2.5", 0, 42, 13, 61),
    ("5.0", 0, 2, 13, 21),
)
_PINNED_QUARANTINE_PIXELS = 878
# Renderer-lane residual OUTSIDE the quarantine, measured on the landing
# lane: 1 antialias-fringe px at (179, 11) with channel delta exactly 1,
# zero oversized, zero background/fully-covered. Growth fails LOUD;
# shrinkage from genuine renderer progress stays green and is reported.
_RENDERER_FRINGE_CAP_PX = 1


def _label_quarantine_mask(width, height):
    """Return the pinned glyph-box quarantine as a top-to-bottom bool grid."""

    mask = np.zeros((height, width), dtype=bool)
    for _label, x0, row0, x1, row1 in _PINNED_QUARANTINE_RECTS:
        mask[row0:row1, x0:x1] = True
    return mask


class TestDecoratedNativeAggParity(unittest.TestCase):
    """Compare the fixed input through the real adapter/native seam only."""

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixture = load_reference_fixture(MANIFEST_PATH)
        # This must remain a real-extension check.  No recording stub or
        # hybrid/Agg fallback is permitted to make the pixel assertion pass.
        self.native = _require_real_native_seam()

    def test_strict_native_render_matches_fixed_agg_reference(self):
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        quarantine_owner = (
            "PARKED glyph scope, P3 writer-track owned "
            "(writer lane t_71585976; residual t_bf22c7f7; ruling "
            "t_6ad7772c(b); landing t_5bd5f106): "
        )
        # Live label geometry comes from a dedicated Agg figure built from
        # the same pinned inputs, so the strict render figure below is
        # never perturbed by the geometry probe.
        with fixture_rc_context():
            geometry_figure, geometry_axes, _gartists = build_fixture_figure()
            geometry_canvas = FigureCanvasAgg(geometry_figure)
            geometry_canvas.draw()
            live_boxes = [
                (
                    text.get_text(),
                    text.get_window_extent(
                        renderer=geometry_canvas.get_renderer()
                    ),
                )
                for text in [
                    *geometry_axes.get_xticklabels(),
                    *geometry_axes.get_yticklabels(),
                ]
            ]
        # 1. LOUD geometry pin: the quarantine is only valid for the exact
        # label boxes it documents. Any drift fails here, never silently.
        self.assertEqual(
            [name for name, _box in live_boxes],
            [name for name, *_rest in _PINNED_LABEL_BOXES],
            quarantine_owner + "tick-label identity changed",
        )
        for (name, box), pinned in zip(live_boxes, _PINNED_LABEL_BOXES):
            _exp_name, exp_x0, exp_y0, exp_x1, exp_y1 = pinned
            self.assertEqual(name, _exp_name, quarantine_owner + "label order changed")
            for corner, got, exp in (
                ("x0", box.x0, exp_x0),
                ("y0", box.y0, exp_y0),
                ("x1", box.x1, exp_x1),
                ("y1", box.y1, exp_y1),
            ):
                self.assertAlmostEqual(
                    float(got),
                    float(exp),
                    places=6,
                    msg=(
                        quarantine_owner
                        + f"label box {name!r} corner {corner} drifted "
                        f"({got!r} != {exp!r}); re-derive the quarantine "
                        "in the P3 writer lane instead of widening it here"
                    ),
                )
        backend = importlib.import_module("lumenplot_mpl.backend")
        with fixture_rc_context():
            figure, _axes, _artists = build_fixture_figure()
            canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
            result = canvas.render_png(dpi=EFFECTIVE_DPI)
        self.assertEqual(result.diagnostics, ())
        reference = decode_png_rgba8(self.fixture.reference_png).rgba
        candidate = decode_png_rgba8(result.png_bytes).rgba
        height, width = reference.shape[:2]
        self.assertEqual(
            (width, height),
            (200, 100),
            quarantine_owner + "frame geometry changed; pinned rects are stale",
        )
        # 2. Derive the integer quarantine from the LIVE boxes, then require
        # it to equal the pinned rects: the exclusion set can never drift
        # with unpinned geometry.
        pad = _GLYPH_QUARANTINE_PAD_PX
        derived_rects = []
        for name, box in live_boxes:
            derived_rects.append(
                (
                    name,
                    max(0, math.floor(float(box.x0)) - pad),
                    max(0, math.floor(float(height - box.y1)) - pad),
                    min(width, math.ceil(float(box.x1)) + pad),
                    min(height, math.ceil(float(height - box.y0)) + pad),
                )
            )
        self.assertEqual(
            derived_rects,
            list(_PINNED_QUARANTINE_RECTS),
            quarantine_owner + "quarantine rects drifted with live geometry",
        )
        quarantine = _label_quarantine_mask(width, height)
        self.assertEqual(
            int(quarantine.sum()),
            _PINNED_QUARANTINE_PIXELS,
            quarantine_owner + "quarantine pixel count changed",
        )
        # 3. Full-frame report under the unchanged S15.1 manifest contract.
        full = compare_pngs(
            self.fixture.reference_png,
            result.png_bytes,
            self.fixture.mask,
            manifest=self.fixture.manifest,
        )
        delta = np.abs(
            candidate.astype(np.int16) - reference.astype(np.int16)
        ).max(axis=2)
        mismatched = delta != 0
        oversized = delta > FRINGE_MAX_CHANNEL_DELTA
        in_quarantine = mismatched & quarantine
        out_quarantine = mismatched & ~quarantine
        in_oversized = oversized & quarantine
        out_oversized = oversized & ~quarantine
        where = (
            f"full=[{full.summary()}] quarantined_mismatches={int(in_quarantine.sum())} "
            f"quarantined_oversized={int(in_oversized.sum())} "
            f"renderer_mismatches={int(out_quarantine.sum())} "
            f"renderer_oversized={int(out_oversized.sum())} "
            f"renderer_max_delta={int(delta[~quarantine].max())}"
        )
        # 4a. S15.1 background/fully-covered clauses hold frame-wide: the
        # renderer lane cleared every exact-class pixel, quarantine or not.
        self.assertEqual(
            full.exact_mismatch_count, 0, "background/fully-covered must be byte-exact; " + where
        )
        # 4b. Every oversized pixel sits inside the quarantine: the renderer
        # lane contributes no delta>1 anywhere.
        self.assertEqual(
            int(out_oversized.sum()),
            0,
            "oversized pixels outside the glyph quarantine are renderer scope; " + where,
        )
        self.assertEqual(
            int(in_oversized.sum()),
            full.fringe_oversized_count,
            "quarantine must cover every oversized pixel; " + where,
        )
        self.assertEqual(
            int(in_quarantine.sum()) + int(out_quarantine.sum()),
            full.mismatch_count,
            "quarantine partition must cover the full residual; " + where,
        )
        # 4c. Outside the quarantine the fringe-delta clause holds and the
        # renderer fringe stays within its documented cap. Growth fails
        # LOUD; genuine shrinkage stays green and is reported above.
        self.assertLessEqual(
            int(delta[~quarantine].max()),
            1,
            "non-quarantined max channel delta exceeds the S15.1 fringe allowance; " + where,
        )
        out_exact = (self.fixture.mask.labels != PIXEL_CLASS_CODES["antialias-fringe"]) & out_quarantine
        self.assertEqual(
            int(out_exact.sum()),
            0,
            "non-quarantined mismatches must all be antialias-fringe; " + where,
        )
        self.assertLessEqual(
            int(out_quarantine.sum()),
            _RENDERER_FRINGE_CAP_PX,
            "renderer fringe grew past its documented cap; " + where,
        )
        # 4d. The parked residual is still present: if P3 ever clears the
        # glyphs, this fails LOUD and forces the quarantine's removal.
        self.assertGreater(
            int(in_quarantine.sum()),
            0,
            quarantine_owner
            + "glyph residual cleared; remove this quarantine in the P3 lane "
            "instead of carrying a dead exclusion; " + where,
        )
        # 5. The unchanged oracle comparator (manifest-validated) over the
        # de-quarantined image: every S15.1 clause holds in full, rate
        # included (the single renderer px sits inside the 20 px budget).
        # The quarantine's only content is the pinned exclusion set above,
        # and it is removed in full when the P3 lane clears the glyphs.
        masked = candidate.copy()
        masked[quarantine] = reference[quarantine]
        gated = compare_rgba8(
            reference,
            masked,
            self.fixture.mask,
            manifest=self.fixture.manifest,
        )
        self.assertTrue(
            gated.passed,
            "de-quarantined image must pass the unchanged S15.1 contract; "
            + gated.summary()
            + "; "
            + where,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
