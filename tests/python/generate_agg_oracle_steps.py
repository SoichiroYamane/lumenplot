"""Generate and validate the fixed Matplotlib Agg step-drawstyle fixture.

The reference is deliberately produced only with documented Matplotlib APIs:
``Figure``, ``Line2D`` (one line per step drawstyle), ``cbook.STEP_LOOKUP_MAP``
as the vertex oracle, ``FigureCanvasAgg.print_png``, public font-manager
lookups, and the public axes transform.  The committed mask is derived from
the reference image and the fixture's resolved background/stroke colors; it
never observes a candidate/native render.

Run from the repository root with::

    PYTHONPATH=python:tests/python python tests/python/generate_agg_oracle_steps.py

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
from matplotlib.cbook import STEP_LOOKUP_MAP  # noqa: E402
from matplotlib.colors import to_rgba  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.font_manager import FontProperties, findfont  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

try:
    from ._agg_oracle import decode_png_rgba8, load_reference_fixture
except ImportError:  # ``python tests/python/generate_...py`` / unittest discovery
    from _agg_oracle import decode_png_rgba8, load_reference_fixture


FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
MANIFEST_PATH = FIXTURE_DIR / "steps_manifest.json"
REFERENCE_PNG_PATH = FIXTURE_DIR / "steps_reference.png"
MASK_PATH = FIXTURE_DIR / "steps_mask.json"

ORACLE_MATPLOTLIB_VERSION = "3.11.1"
ORACLE_API_VERSION = "1.1"
PYTHON_VERSION_RANGE = ">=3.11,<3.15"
FIGSIZE_INCHES = (2.0, 1.0)
EFFECTIVE_DPI = 100.0
AXES_RECT = (0.1, 0.1, 0.8, 0.8)
XLIM = (0.0, 10.0)
YLIM = (0.0, 6.0)

# One shared abscissa; each drawstyle rides its own y band so the three
# strokes never overlap.  All samples are finite: Agg re-pairs step risers
# around a NaN gap, so non-finite samples have no step semantics and the
# adapter refuses them explicitly (LP-MPL-020 forbids approximation).
X_DATA = (0.0, 2.5, 5.0, 7.5, 10.0)
STEP_LINES: dict[str, dict[str, Any]] = {
    "steps-pre": {"y": (1.0, 2.0, 1.5, 2.0, 1.0), "color": "red"},
    "steps-post": {"y": (3.0, 4.0, 3.5, 4.0, 3.0), "color": "blue"},
    "steps-mid": {"y": (4.6, 5.4, 4.9, 5.4, 4.7), "color": "green"},
}
DRAWSTYLES = ("steps-pre", "steps-post", "steps-mid")

INPUT_CASES: dict[str, dict[str, Any]] = {
    drawstyle: {
        "artist": "matplotlib.lines.Line2D",
        "drawstyle": drawstyle,
        "color": spec["color"],
    }
    for drawstyle, spec in STEP_LINES.items()
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

LINE_STYLE_BASE: dict[str, Any] = {
    "linewidth": 2.0,
    "linestyle": "-",
    "marker": "None",
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


def build_fixture_figure() -> tuple[Figure, Any, dict[str, Line2D]]:
    """Build the exact fixed Figure/step-Line2D input used by every test path."""

    figure = Figure(
        figsize=FIGSIZE_INCHES,
        dpi=EFFECTIVE_DPI,
        facecolor="white",
        edgecolor="white",
    )
    axes = figure.add_axes(AXES_RECT)
    axes.set_facecolor("none")
    axes.set_axis_off()
    lines: dict[str, Line2D] = {}
    for drawstyle in DRAWSTYLES:
        spec = STEP_LINES[drawstyle]
        line = Line2D(
            np.asarray(X_DATA, dtype=float),
            np.asarray(spec["y"], dtype=float),
            drawstyle=drawstyle,
            color=spec["color"],
            **LINE_STYLE_BASE,
        )
        axes.add_line(line)
        lines[drawstyle] = line
    axes.set_xlim(*XLIM)
    axes.set_ylim(*YLIM)
    return figure, axes, lines


def fixture_rc_context():
    """Return the pinned public Matplotlib rc-context used by the fixture."""

    return matplotlib.rc_context(RC_PARAMS)


def oracle_step_vertices(
    drawstyle: str, x: Any, y: Any
) -> tuple[list[float], list[float]]:
    """Expand sampled data with Matplotlib's own public step oracle."""

    step_func = STEP_LOOKUP_MAP[drawstyle]
    expanded_x, expanded_y = (
        np.asarray(values, dtype=float)
        for values in step_func(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    )
    return (
        [float(value) for value in expanded_x],
        [float(value) for value in expanded_y],
    )


def public_step_topology(lines: dict[str, Line2D]) -> dict[str, Any]:
    """Return the exact step vertex sequence per drawstyle from the oracle."""

    per_style: dict[str, Any] = {}
    for drawstyle in DRAWSTYLES:
        line = lines[drawstyle]
        # The oracle is Matplotlib's own step expansion of the line's public
        # data, not the unexpanded Line2D.get_path(): get_path carries the
        # raw samples while Agg draws the expanded step polyline.
        assert line.get_drawstyle() == drawstyle
        xdata = [float(value) for value in np.asarray(line.get_xdata(), dtype=float)]
        ydata = [float(value) for value in np.asarray(line.get_ydata(), dtype=float)]
        expanded_x, expanded_y = oracle_step_vertices(drawstyle, xdata, ydata)
        per_style[drawstyle] = {
            "api": "matplotlib.cbook.STEP_LOOKUP_MAP[drawstyle](x, y)",
            "drawstyle": drawstyle,
            "color": str(line.get_color()),
            "input_x": xdata,
            "input_y": ydata,
            "expanded_x": expanded_x,
            "expanded_y": expanded_y,
            "expanded_count": len(expanded_x),
        }
    return {
        "api": "matplotlib.cbook.STEP_LOOKUP_MAP[drawstyle](x, y)",
        "per_drawstyle": per_style,
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


def _reference_mask(
    rgba: np.ndarray, figure: Figure, lines: dict[str, Line2D]
) -> np.ndarray:
    """Classify reference pixels from the fixed background and stroke colors."""

    background = _rgba8(figure.get_facecolor())
    background_pixels = np.all(rgba == background, axis=2)
    fully_covered_pixels = np.zeros(rgba.shape[:2], dtype=bool)
    for drawstyle in DRAWSTYLES:
        stroke = _rgba8(lines[drawstyle].get_color())
        fully_covered_pixels |= np.all(rgba == stroke, axis=2)
    fringe_pixels = ~(background_pixels | fully_covered_pixels)
    labels = np.full(
        rgba.shape[:2],
        PIXEL_CLASS_CODES["antialias-fringe"],
        dtype=np.uint8,
    )
    labels[background_pixels] = PIXEL_CLASS_CODES["background"]
    labels[fully_covered_pixels] = PIXEL_CLASS_CODES["fully-covered"]

    # This fixture has no text or outline artists.  Every non-background
    # reference pixel belongs to one of the three resolved Line2D strokes:
    # exact stroke color is fully covered and the remaining stroke pixels
    # are fringe.  The candidate/native image is deliberately not an input
    # to this operation.
    if not bool(np.all(background_pixels | fully_covered_pixels | fringe_pixels)):
        raise AssertionError("reference mask classification left unknown pixels")
    if not bool(background_pixels.any()):
        raise AssertionError("reference mask has no background pixels")
    if not bool(fully_covered_pixels.any()):
        raise AssertionError("reference mask has no fully-covered pixels")
    if not bool(fringe_pixels.any()):
        raise AssertionError("reference mask has no antialias-fringe pixels")
    return labels


def render_reference() -> tuple[bytes, np.ndarray, dict[str, Any], tuple[int, int]]:
    """Render the fixed input with public FigureCanvasAgg APIs."""

    with fixture_rc_context():
        figure, _axes, lines = build_fixture_figure()
        canvas = FigureCanvasAgg(figure)
        buffer = io.BytesIO()
        # Direct FigureCanvasAgg.print_png is the pinned oracle operation.
        canvas.print_png(buffer, metadata={})
        reference_png = buffer.getvalue()
        decoded = decode_png_rgba8(reference_png)
        topology = public_step_topology(lines)
        mask = _reference_mask(decoded.rgba, figure, lines)
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
        "fixture_id": "line2d-steps-pre-post-mid-exact-vertices",
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
            "count": len(DRAWSTYLES),
            "style": LINE_STYLE_BASE,
            "lines": [
                {
                    "drawstyle": drawstyle,
                    "color": STEP_LINES[drawstyle]["color"],
                    "input_x": list(X_DATA),
                    "input_y": list(STEP_LINES[drawstyle]["y"]),
                }
                for drawstyle in DRAWSTYLES
            ],
        },
        "input_data": {
            "x": list(X_DATA),
            "lines": {
                drawstyle: {
                    "y": list(STEP_LINES[drawstyle]["y"]),
                    "color": STEP_LINES[drawstyle]["color"],
                }
                for drawstyle in DRAWSTYLES
            },
            "cases": INPUT_CASES,
        },
        "topology": topology,
        "mask_generation": (
            "reference-only: figure facecolor and resolved Line2D stroke "
            "colors (steps-pre red, steps-post blue, steps-mid green); "
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
