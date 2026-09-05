"""LP-FUNC-040 gap-matrix fixtures and explicit fallback evidence.

The existing Line2D fixture is intentionally left as the bounded M0-M1-R2
fixture.  This module adds an axis-aware matrix: non-finite samples occur in
both x and y, while one committed FigureCanvasAgg render covers interior,
boundary, masked, and positive/negative-infinity cases in one reproducible
fixture.  The adapter-side assertions check that every source row survives as
an explicit pen lift instead of being filtered and reconnected.

Stepped lines are strict-eligible only while all samples are finite.  Their
non-finite path-cleaning semantics are not representable by the native step
expander, so the second suite pins the required explicit strict refusal and
whole-frame hybrid Agg fallback for every shipped step spelling.
"""

from __future__ import annotations

import hashlib
import io
import json
import unittest
from pathlib import Path
from typing import Any

import numpy as np

try:
    from ._agg_oracle import (
        PIXEL_CLASS_CODES,
        assert_png_parity,
        decode_png_rgba8,
        load_reference_fixture,
    )
except ImportError:  # ``unittest discover -s tests/python``
    from _agg_oracle import (
        PIXEL_CLASS_CODES,
        assert_png_parity,
        decode_png_rgba8,
        load_reference_fixture,
    )

try:
    import matplotlib
except ModuleNotFoundError:  # offline cells may omit the optional oracle stack
    matplotlib = None
    MATPLOTLIB_PRESENT = False
else:
    matplotlib.use("Agg")
    from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
    from matplotlib.colors import to_rgba  # noqa: E402
    from matplotlib.figure import Figure  # noqa: E402
    from matplotlib.font_manager import FontProperties, findfont  # noqa: E402
    from matplotlib.lines import Line2D  # noqa: E402
    from matplotlib.path import Path as MatplotlibPath  # noqa: E402

    MATPLOTLIB_PRESENT = True


FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
MANIFEST_PATH = FIXTURE_DIR / "line2d_gap_axes_manifest.json"
REFERENCE_PNG_PATH = FIXTURE_DIR / "line2d_gap_axes_reference.png"
MASK_PATH = FIXTURE_DIR / "line2d_gap_axes_mask.json"

ORACLE_MATPLOTLIB_VERSION = "3.11.1"
ORACLE_API_VERSION = "1.1"
PYTHON_VERSION_RANGE = ">=3.11,<3.15"
FIGSIZE_INCHES = (2.0, 1.0)
EFFECTIVE_DPI = 100.0
AXES_RECT = (0.1, 0.1, 0.8, 0.8)
XLIM = (-1.0, 22.0)
YLIM = (-1.0, 12.0)

# Gaps are deliberately distributed across both coordinates.  The masked row
# has a finite source value so the manifest records the exact data and mask;
# Matplotlib's public processed-data route exposes it as a non-finite path row.
X_DATA = (
    float("nan"),
    1.0,
    2.0,
    3.0,
    4.0,
    5.0,
    6.0,
    7.0,
    8.0,
    float("inf"),
    10.0,
    11.0,
    12.0,
    13.0,
    14.0,
    float("-inf"),
    16.0,
    17.0,
    18.0,
    19.0,
    20.0,
    float("nan"),
)
Y_DATA = (
    0.0,
    0.5,
    1.0,
    float("nan"),
    2.0,
    2.5,
    3.0,
    3.5,
    4.0,
    4.5,
    5.0,
    5.5,
    float("-inf"),
    6.5,
    7.0,
    7.5,
    8.0,
    8.5,
    9.0,
    9.5,
    10.0,
    10.5,
)
Y_MASK = tuple(index == 6 for index in range(len(Y_DATA)))

INPUT_CASES: dict[str, dict[str, Any]] = {
    "interior": {"axis": "y", "indices": [3], "tokens": ["NaN"]},
    "leading": {"axis": "x", "indices": [0], "tokens": ["NaN"]},
    "trailing": {"axis": "x", "indices": [21], "tokens": ["NaN"]},
    "masked": {"axis": "y", "indices": [6], "tokens": ["masked"]},
    "infinity": {
        "indices": [9, 12, 15],
        "tokens": ["+Inf", "-Inf", "-Inf"],
        "axes": ["x", "y", "x"],
    },
}

RC_PARAMS: dict[str, Any] = {
    "agg.path.chunksize": 0,
    "axes.facecolor": "none",
    "figure.dpi": EFFECTIVE_DPI,
    "figure.edgecolor": "white",
    "figure.facecolor": "white",
    "font.family": ["DejaVu Sans"],
    "font.size": 10.0,
    "lines.antialiased": True,
    "lines.color": "red",
    "lines.dash_capstyle": "butt",
    "lines.dash_joinstyle": "miter",
    "lines.linestyle": "-",
    "lines.linewidth": 2.0,
    "lines.solid_capstyle": "butt",
    "lines.solid_joinstyle": "miter",
    "path.simplify": False,
    "path.simplify_threshold": 0.0,
    "savefig.dpi": EFFECTIVE_DPI,
    "savefig.edgecolor": "white",
    "savefig.facecolor": "white",
    "savefig.format": "png",
    "savefig.transparent": False,
    "text.antialiased": True,
}

LINE_STYLE: dict[str, Any] = {
    "color": "red",
    "linewidth": 2.0,
    "linestyle": "-",
    "marker": "None",
    "drawstyle": "default",
    "solid_capstyle": "butt",
    "solid_joinstyle": "miter",
    "antialiased": True,
}

PIXEL_CLASSES = [
    "background",
    "fully-covered",
    "antialias-fringe",
    "text-or-outline",
]
PIXEL_CLASS_CODES = {name: index for index, name in enumerate(PIXEL_CLASSES)}


def _require_pinned_matplotlib() -> None:
    if not MATPLOTLIB_PRESENT:
        raise unittest.SkipTest("Matplotlib is not installed in this test cell")
    assert matplotlib is not None
    if matplotlib.__version__ != ORACLE_MATPLOTLIB_VERSION:
        raise unittest.SkipTest(
            "Agg fixture requires Matplotlib "
            f"{ORACLE_MATPLOTLIB_VERSION}; found {matplotlib.__version__}"
        )


def _json_number(value: float) -> float | str:
    """Encode non-finite source values without non-standard JSON literals."""

    value = float(value)
    if np.isnan(value):
        return "NaN"
    if np.isposinf(value):
        return "+Inf"
    if np.isneginf(value):
        return "-Inf"
    return value


def build_gap_figure(*, drawstyle: str = "default"):
    """Build the fixed public Figure/Line2D input for this module."""

    if not MATPLOTLIB_PRESENT:
        raise unittest.SkipTest("Matplotlib is not installed in this test cell")
    figure = Figure(
        figsize=FIGSIZE_INCHES,
        dpi=EFFECTIVE_DPI,
        facecolor="white",
        edgecolor="white",
    )
    axes = figure.add_axes(AXES_RECT)
    axes.set_facecolor("none")
    axes.set_axis_off()
    masked_y = np.ma.array(
        np.asarray(Y_DATA, dtype=float),
        mask=np.asarray(Y_MASK, dtype=bool),
    )
    style = dict(LINE_STYLE)
    style["drawstyle"] = drawstyle
    line = Line2D(np.asarray(X_DATA, dtype=float), masked_y, **style)
    axes.add_line(line)
    axes.set_xlim(*XLIM)
    axes.set_ylim(*YLIM)
    return figure, axes, line


def fixture_rc_context():
    """Return the pinned public Matplotlib rc-context for this fixture."""

    assert matplotlib is not None
    return matplotlib.rc_context(RC_PARAMS)


def public_line_topology(line: Line2D) -> dict[str, Any]:
    """Return topology from the documented public Path iteration API."""

    segments = list(line.get_path().iter_segments(remove_nans=True))
    codes = [int(code) for _vertices, code in segments]
    vertices = [
        [float(value) for value in np.asarray(values).reshape(-1)]
        for values, _code in segments
    ]
    moveto = int(MatplotlibPath.MOVETO)
    lineto = int(MatplotlibPath.LINETO)
    return {
        "api": "line.get_path().iter_segments(remove_nans=True)",
        "segment_count": len(segments),
        "subpath_count": sum(code == moveto for code in codes),
        "moveto_count": sum(code == moveto for code in codes),
        "lineto_count": sum(code == lineto for code in codes),
        "segment_codes": codes,
        "vertices": vertices,
    }


def _font_identity() -> tuple[dict[str, Any], str]:
    """Resolve and hash the exact font bytes named by the fixture."""

    properties = FontProperties(
        family="DejaVu Sans",
        style="normal",
        variant="normal",
        weight="normal",
        stretch="normal",
        size=10.0,
    )
    font_path = Path(
        findfont(properties, fontext="ttf", fallback_to_default=False)
    )
    font_bytes = font_path.read_bytes()
    digest = hashlib.sha256(font_bytes).hexdigest()
    identity = {
        "family": "DejaVu Sans",
        "properties": {
            "style": "normal",
            "variant": "normal",
            "weight": "normal",
            "stretch": "normal",
            "size": 10.0,
        },
        "file": font_path.name,
        "bytes_sha256": digest,
    }
    return identity, digest


def _rgba8(color: Any) -> np.ndarray:
    channels = np.asarray(to_rgba(color), dtype=float)
    return np.asarray(np.rint(channels * 255.0), dtype=np.uint8)


def _reference_mask(rgba: np.ndarray, figure: Figure, line: Line2D) -> np.ndarray:
    """Classify reference pixels from fixed background and stroke colors."""

    background = _rgba8(figure.get_facecolor())
    stroke = _rgba8(line.get_color())
    background_pixels = np.all(rgba == background, axis=2)
    fully_covered_pixels = np.all(rgba == stroke, axis=2)
    fringe_pixels = ~(background_pixels | fully_covered_pixels)
    labels = np.full(
        rgba.shape[:2],
        PIXEL_CLASS_CODES["antialias-fringe"],
        dtype=np.uint8,
    )
    labels[background_pixels] = PIXEL_CLASS_CODES["background"]
    labels[fully_covered_pixels] = PIXEL_CLASS_CODES["fully-covered"]
    if not bool(np.all(background_pixels | fully_covered_pixels | fringe_pixels)):
        raise AssertionError("reference mask classification left unknown pixels")
    return labels


def render_reference() -> tuple[bytes, np.ndarray, dict[str, Any], tuple[int, int]]:
    """Render the fixed input through public FigureCanvasAgg APIs."""

    with fixture_rc_context():
        figure, _axes, line = build_gap_figure()
        canvas = FigureCanvasAgg(figure)
        buffer = io.BytesIO()
        canvas.print_png(buffer, metadata={})
        reference_png = buffer.getvalue()
        decoded = decode_png_rgba8(reference_png)
        topology = public_line_topology(line)
        mask = _reference_mask(decoded.rgba, figure, line)
        dimensions = tuple(int(value) for value in canvas.get_width_height())
    return reference_png, mask, topology, dimensions


def _manifest(
    *,
    reference_digest: str,
    mask_digest: str,
    font_digest: str,
    topology: dict[str, Any],
    dimensions: tuple[int, int],
) -> dict[str, Any]:
    width, height = dimensions
    font_identity, _ = _font_identity()
    return {
        "schema_version": "agg-oracle-manifest-v1",
        "fixture_id": (
            "line2d-gap-axes-interior-leading-trailing-masked-"
            "positive-negative-infinity"
        ),
        "oracle": {
            "backend": "FigureCanvasAgg",
            "matplotlib_version": ORACLE_MATPLOTLIB_VERSION,
            "api_version": ORACLE_API_VERSION,
            "canvas_construction": (
                "matplotlib.backends.backend_agg.FigureCanvasAgg(figure)"
            ),
            "render_call": "canvas.print_png(buffer, metadata={})",
        },
        "python_version": PYTHON_VERSION_RANGE,
        "figure": {
            "construction": (
                "matplotlib.figure.Figure(figsize=(2.0, 1.0), dpi=100.0, "
                "facecolor='white', edgecolor='white')"
            ),
            "options": {
                "figsize_inches": list(FIGSIZE_INCHES),
                "dpi": EFFECTIVE_DPI,
                "facecolor": "white",
                "edgecolor": "white",
                "axes_construction": "figure.add_axes((0.1, 0.1, 0.8, 0.8))",
                "axes_rect": list(AXES_RECT),
                "axes_facecolor": "none",
                "axis_on": False,
                "xlim": list(XLIM),
                "ylim": list(YLIM),
                "savefig_format": "png",
                "print_png_metadata": {},
            },
        },
        "effective_dpi": EFFECTIVE_DPI,
        "dimensions": {"width": width, "height": height},
        "orientation": "top-to-bottom",
        "channels": "RGBA8",
        "rcparams": RC_PARAMS,
        "font": font_identity,
        "font_bytes_sha256": font_digest,
        "artist_class": "matplotlib.lines.Line2D",
        "primitive": {
            "class": "matplotlib.lines.Line2D",
            "style": LINE_STYLE,
            "input_data": {
                "x": [_json_number(value) for value in X_DATA],
                "y": [_json_number(value) for value in Y_DATA],
                "y_mask": list(Y_MASK),
                "cases": INPUT_CASES,
            },
        },
        "input_data": {
            "x": [_json_number(value) for value in X_DATA],
            "y": [_json_number(value) for value in Y_DATA],
            "y_mask": list(Y_MASK),
            "cases": INPUT_CASES,
            "nan_indices": {"x": [0, 21], "y": [3]},
            "masked_indices": [6],
            "positive_infinity_indices": {"x": [9], "y": []},
            "negative_infinity_indices": {"x": [15], "y": [12]},
        },
        "topology": topology,
        "mask_generation": (
            "reference-only: figure facecolor and resolved Line2D stroke; "
            "candidate/native pixels are not observed"
        ),
        "reference_png_file": REFERENCE_PNG_PATH.name,
        "reference_png_sha256": reference_digest,
        "mask_file": MASK_PATH.name,
        "mask_sha256": mask_digest,
        "pixel_classes": PIXEL_CLASSES,
        "contract": {
            "orientation": "top-to-bottom",
            "channels": "RGBA8",
            "background": "byte-equal",
            "fully-covered": "byte-equal",
            "fringe_max_channel_delta": 1,
            "fringe_mismatch_rate_denominator": "total-pixels",
            "fringe_mismatch_rate_max": 0.001,
        },
    }


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=False) + "\n").encode("utf-8")


def _mask_bytes(mask: np.ndarray) -> bytes:
    lines = [
        "{",
        '  "schema_version": "agg-oracle-mask-v1",',
        '  "orientation": "top-to-bottom",',
        f'  "shape": [{int(mask.shape[0])}, {int(mask.shape[1])}],',
        '  "classes": [',
        '    "background",',
        '    "fully-covered",',
        '    "antialias-fringe",',
        '    "text-or-outline"',
        "  ],",
        '  "data": [',
    ]
    rows = [
        "    " + json.dumps(row.tolist(), separators=(",", ": "))
        for row in np.asarray(mask, dtype=np.uint8)
    ]
    lines.extend(
        row + ("," if index + 1 < len(rows) else "")
        for index, row in enumerate(rows)
    )
    lines.extend(["  ]", "}", ""])
    return "\n".join(lines).encode("utf-8")


def write_fixture() -> dict[str, Any]:
    """Generate the committed fixture files for a reviewed oracle refresh."""

    reference_png, mask, topology, dimensions = render_reference()
    _font, font_digest = _font_identity()
    mask_bytes = _mask_bytes(mask)
    reference_digest = hashlib.sha256(reference_png).hexdigest()
    mask_digest = hashlib.sha256(mask_bytes).hexdigest()
    manifest = _manifest(
        reference_digest=reference_digest,
        mask_digest=mask_digest,
        font_digest=font_digest,
        topology=topology,
        dimensions=dimensions,
    )
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    REFERENCE_PNG_PATH.write_bytes(reference_png)
    MASK_PATH.write_bytes(mask_bytes)
    MANIFEST_PATH.write_bytes(_json_bytes(manifest))
    load_reference_fixture(MANIFEST_PATH)
    return manifest


@unittest.skipUnless(MATPLOTLIB_PRESENT, "Matplotlib is not installed")
class TestCommittedGapAxesFixture(unittest.TestCase):
    """Committed bytes and public topology remain fixed under regeneration."""

    def setUp(self):
        _require_pinned_matplotlib()
        self.fixture = load_reference_fixture(MANIFEST_PATH)

    def test_manifest_records_all_gap_cases_and_both_coordinates(self):
        manifest = self.fixture.manifest
        self.assertEqual(
            manifest["fixture_id"],
            "line2d-gap-axes-interior-leading-trailing-masked-"
            "positive-negative-infinity",
        )
        self.assertEqual(manifest["oracle"]["backend"], "FigureCanvasAgg")
        self.assertEqual(manifest["oracle"]["matplotlib_version"], "3.11.1")
        self.assertEqual(manifest["oracle"]["api_version"], "1.1")
        self.assertEqual(manifest["dimensions"], {"width": 200, "height": 100})
        self.assertEqual(manifest["input_data"]["cases"], INPUT_CASES)
        self.assertEqual(
            manifest["input_data"]["nan_indices"],
            {"x": [0, 21], "y": [3]},
        )
        self.assertEqual(manifest["input_data"]["masked_indices"], [6])
        self.assertEqual(
            manifest["input_data"]["positive_infinity_indices"],
            {"x": [9], "y": []},
        )
        self.assertEqual(
            manifest["input_data"]["negative_infinity_indices"],
            {"x": [15], "y": [12]},
        )
        self.assertEqual(
            hashlib.sha256(self.fixture.reference_png).hexdigest(),
            manifest["reference_png_sha256"],
        )
        self.assertEqual(
            hashlib.sha256((FIXTURE_DIR / manifest["mask_file"]).read_bytes()).hexdigest(),
            manifest["mask_sha256"],
        )

    def test_regeneration_reproduces_committed_png_mask_and_topology(self):
        generated_png, generated_mask, generated_topology, dimensions = (
            render_reference()
        )
        self.assertEqual(generated_png, self.fixture.reference_png)
        self.assertTrue(np.array_equal(generated_mask, self.fixture.mask.labels))
        report = assert_png_parity(
            self.fixture.reference_png,
            generated_png,
            self.fixture.mask,
            manifest=self.fixture.manifest,
        )
        self.assertTrue(report.passed, report.summary())
        self.assertEqual(dimensions, (200, 100))
        self.assertEqual(generated_topology, self.fixture.manifest["topology"])

    def test_public_path_starts_new_subpath_after_every_gap(self):
        with fixture_rc_context():
            _figure, _axes, line = build_gap_figure()
            topology = public_line_topology(line)
        self.assertEqual(topology["api"], "line.get_path().iter_segments(remove_nans=True)")
        self.assertEqual(topology["subpath_count"], 6)
        self.assertEqual(topology["moveto_count"], 6)
        self.assertEqual(topology["lineto_count"], 9)
        self.assertEqual(
            topology["vertices"],
            [
                [1.0, 0.5],
                [2.0, 1.0],
                [4.0, 2.0],
                [5.0, 2.5],
                [7.0, 3.5],
                [8.0, 4.0],
                [10.0, 5.0],
                [11.0, 5.5],
                [13.0, 6.5],
                [14.0, 7.0],
                [16.0, 8.0],
                [17.0, 8.5],
                [18.0, 9.0],
                [19.0, 9.5],
                [20.0, 10.0],
            ],
        )
        self.assertEqual(
            set(np.unique(self.fixture.mask.labels)),
            {
                PIXEL_CLASS_CODES["background"],
                PIXEL_CLASS_CODES["fully-covered"],
                PIXEL_CLASS_CODES["antialias-fringe"],
            },
        )


@unittest.skipUnless(MATPLOTLIB_PRESENT, "Matplotlib is not installed")
class TestGapAdapterSemantics(unittest.TestCase):
    """The adapter keeps gap rows or takes the explicit fallback route."""

    def setUp(self):
        _require_pinned_matplotlib()

    def test_strict_spec_retains_x_and_y_gap_rows_as_pen_lifts(self):
        import importlib
        import unittest.mock

        backend = importlib.import_module("lumenplot_mpl.backend")
        captured: dict[str, Any] = {}

        def capture_spec(spec, _generation):
            captured.update(spec)
            return b"native-spec-only"

        with fixture_rc_context():
            figure, _axes, _line = build_gap_figure()
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
        vertices = np.asarray(command["vertices"], dtype=float)
        self.assertEqual(vertices.shape, (len(X_DATA), 2))
        gap_indices = [0, 3, 6, 9, 12, 15, 21]
        self.assertEqual(
            np.flatnonzero(~np.isfinite(vertices).all(axis=1)).tolist(),
            gap_indices,
        )
        self.assertTrue(
            np.all(np.isfinite(vertices[np.setdiff1d(np.arange(len(X_DATA)), gap_indices)]))
        )
        self.assertIsNone(command["codes"])

    def test_step_gap_strict_refusal_and_hybrid_agg_fallback(self):
        import importlib

        backend = importlib.import_module("lumenplot_mpl.backend")
        drawstyles = ("steps", "steps-pre", "steps-post", "steps-mid")
        for drawstyle in drawstyles:
            with self.subTest(drawstyle=drawstyle):
                with fixture_rc_context():
                    figure, _axes, _line = build_gap_figure(drawstyle=drawstyle)
                    strict = backend.FigureCanvasLumenPlot(figure, mode="strict")
                    target = io.BytesIO()
                    with self.assertRaises(
                        backend.LumenPlotUnsupportedError
                    ) as error:
                        strict.render_png(target)
                    self.assertEqual(error.exception.code, "unsupported-capability")
                    self.assertEqual(target.getvalue(), b"")

                    fallback_figure, _fallback_axes, _fallback_line = build_gap_figure(
                        drawstyle=drawstyle
                    )
                    hybrid = backend.FigureCanvasLumenPlot(
                        fallback_figure, mode="hybrid"
                    )
                    result = hybrid.render_png(dpi=EFFECTIVE_DPI)
                    expected_buffer = io.BytesIO()
                    FigureCanvasAgg(fallback_figure).print_png(
                        expected_buffer, metadata={}
                    )
                    expected_png = expected_buffer.getvalue()

                self.assertEqual(len(result.diagnostics), 1)
                diagnostic = result.diagnostics[0]
                self.assertEqual(diagnostic.kind, "unsupported-capability")
                self.assertEqual(diagnostic.scope, "whole-frame")
                self.assertEqual(diagnostic.fallback_type, "matplotlib-agg")
                self.assertEqual(result.png_bytes, expected_png)
                expected_rgba = decode_png_rgba8(expected_png).rgba
                actual_rgba = decode_png_rgba8(result.png_bytes).rgba
                np.testing.assert_array_equal(actual_rgba, expected_rgba)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
