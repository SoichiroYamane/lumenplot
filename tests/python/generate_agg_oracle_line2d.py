"""Generate and validate the fixed Matplotlib Agg Line2D gap fixture.

The reference is deliberately produced only with documented Matplotlib APIs:
``Figure``, ``Line2D``, ``FigureCanvasAgg.print_png``, public font-manager
lookups, and ``Path.iter_segments``.  The committed mask is derived from the
reference image and the fixture's resolved background/stroke colors; it never
observes a candidate/native render.

Run from the repository root with::

    PYTHONPATH=python:tests/python python tests/python/generate_agg_oracle_line2d.py

Use ``--check`` in a test or verification job to prove the committed PNG and
mask are byte-stable for the pinned Matplotlib cell.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

# This helper does not import pyplot.  Selecting the documented Agg backend
# before importing FigureCanvasAgg keeps the generator headless and explicit.
matplotlib.use("Agg")

from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.colors import to_rgba  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.font_manager import FontProperties, findfont  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.path import Path as MatplotlibPath  # noqa: E402

try:
    from ._agg_oracle import decode_png_rgba8, load_reference_fixture
except ImportError:  # ``python tests/python/generate_...py`` / unittest discovery
    from _agg_oracle import decode_png_rgba8, load_reference_fixture


FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
MANIFEST_PATH = FIXTURE_DIR / "line2d_gap_manifest.json"
REFERENCE_PNG_PATH = FIXTURE_DIR / "line2d_gap_reference.png"
MASK_PATH = FIXTURE_DIR / "line2d_gap_mask.json"

ORACLE_MATPLOTLIB_VERSION = "3.11.1"
ORACLE_API_VERSION = "1.1"
PYTHON_VERSION_RANGE = ">=3.11,<3.15"
FIGSIZE_INCHES = (2.0, 1.0)
EFFECTIVE_DPI = 100.0
AXES_RECT = (0.1, 0.1, 0.8, 0.8)
XLIM = (-1.0, 16.0)
YLIM = (-1.0, 11.0)

# The masked sample has a finite underlying value so the manifest can record
# the exact source array plus its mask.  Line2D's public processed-data route
# converts that masked row to a NaN before its public Path is iterated.  The
# leading and trailing NaNs make those boundary cases explicit instead of
# relying only on interior gaps.
X_DATA = tuple(float(value) for value in range(16))
Y_DATA = (
    float("nan"),
    0.0,
    1.0,
    float("nan"),
    2.0,
    3.0,
    4.0,
    5.0,
    6.0,
    float("inf"),
    7.0,
    8.0,
    float("-inf"),
    9.0,
    10.0,
    float("nan"),
)
Y_MASK = tuple(index == 6 for index in range(len(Y_DATA)))

INPUT_CASES: dict[str, dict[str, Any]] = {
    "interior": {"indices": [3], "tokens": ["NaN"]},
    "leading": {"indices": [0], "tokens": ["NaN"]},
    "trailing": {"indices": [15], "tokens": ["NaN"]},
    "masked": {"indices": [6], "tokens": ["masked"]},
    "infinity": {
        "indices": [9, 12],
        "tokens": ["+Inf", "-Inf"],
    },
}

# These values are intentionally explicit rather than inherited from a moving
# Matplotlib default.  They are also the relevant rcParams recorded in the
# manifest.  The Figure and Line2D constructors repeat the style values whose
# public artist getters are part of the adapter eligibility contract.
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


def build_fixture_figure() -> tuple[Figure, Any, Line2D]:
    """Build the exact fixed Figure/Line2D input used by every test path."""

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
    line = Line2D(
        np.asarray(X_DATA, dtype=float),
        masked_y,
        **LINE_STYLE,
    )
    axes.add_line(line)
    axes.set_xlim(*XLIM)
    axes.set_ylim(*YLIM)
    return figure, axes, line


def fixture_rc_context():
    """Return the pinned public Matplotlib rc-context used by the fixture."""

    return matplotlib.rc_context(RC_PARAMS)


def public_line_topology(line: Line2D) -> dict[str, Any]:
    """Return topology from the documented public Path iteration API."""

    # Matplotlib 3.11.1 exposes this on the public Path returned by
    # Line2D.get_path(), not as a Line2D method.  Keep the exact call visible:
    # no private recache/transformed-path helper is needed here.
    segments = list(line.get_path().iter_segments(remove_nans=True))
    codes = [int(code) for _vertices, code in segments]
    vertices = [
        [float(value) for value in np.asarray(segment_vertices).reshape(-1)]
        for segment_vertices, _code in segments
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
    """Resolve a public Matplotlib color to the Agg RGBA8 channel tuple."""

    channels = np.asarray(to_rgba(color), dtype=float)
    return np.asarray(np.rint(channels * 255.0), dtype=np.uint8)


def _reference_mask(rgba: np.ndarray, figure: Figure, line: Line2D) -> np.ndarray:
    """Classify reference pixels from the fixed background and line geometry."""

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

    # This fixture has no text or outline artists.  Every non-background
    # reference pixel belongs to the resolved Line2D stroke: exact stroke
    # color is fully covered and the remaining stroke pixels are fringe.  The
    # candidate/native image is deliberately not an input to this operation.
    if not bool(np.all(background_pixels | fully_covered_pixels | fringe_pixels)):
        raise AssertionError("reference mask classification left unknown pixels")
    return labels


def render_reference() -> tuple[bytes, np.ndarray, dict[str, Any], tuple[int, int]]:
    """Render the fixed input with public FigureCanvasAgg APIs."""

    with fixture_rc_context():
        figure, _axes, line = build_fixture_figure()
        canvas = FigureCanvasAgg(figure)
        buffer = io.BytesIO()
        # Direct FigureCanvasAgg.print_png is the pinned oracle operation.
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
            "line2d-gap-interior-leading-trailing-masked-"
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
            "nan_indices": [0, 3, 15],
            "masked_indices": [6],
            "positive_infinity_indices": [9],
            "negative_infinity_indices": [12],
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
    """Encode one compact, deterministic JSON row per mask scanline."""

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
    """Generate the PNG/mask/manifest files and validate their digests."""

    reference_png, mask, topology, dimensions = render_reference()
    font_identity, font_digest = _font_identity()
    del font_identity
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
    # The same loader used by the focused tests verifies image/mask dimensions
    # and both committed SHA-256 values after generation.
    load_reference_fixture(MANIFEST_PATH)
    return manifest


def check_fixture() -> dict[str, Any]:
    """Regenerate in memory and require exact committed bytes and metadata."""

    fixture = load_reference_fixture(MANIFEST_PATH)
    reference_png, mask, topology, dimensions = render_reference()
    if reference_png != fixture.reference_png:
        raise AssertionError("committed Agg reference differs from regeneration")
    if not np.array_equal(mask, fixture.mask.labels):
        raise AssertionError("committed Agg mask differs from regeneration")
    if dimensions != (
        int(fixture.manifest["dimensions"]["width"]),
        int(fixture.manifest["dimensions"]["height"]),
    ):
        raise AssertionError("committed dimensions differ from regeneration")
    if topology != fixture.manifest["topology"]:
        raise AssertionError("committed topology differs from regeneration")
    return {
        "reference_png_sha256": hashlib.sha256(reference_png).hexdigest(),
        "mask_sha256": hashlib.sha256(MASK_PATH.read_bytes()).hexdigest(),
        "dimensions": {"width": dimensions[0], "height": dimensions[1]},
        "topology": topology,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="regenerate in memory and compare exact committed bytes",
    )
    args = parser.parse_args()
    result = check_fixture() if args.check else write_fixture()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - command-line helper
    raise SystemExit(main())
