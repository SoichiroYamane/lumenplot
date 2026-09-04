"""Generate and validate the fixed Matplotlib Agg bar-primitive fixture.

The reference is deliberately produced only with documented Matplotlib APIs:
``Figure``, ``Axes.bar``, ``Axes.barh``, ``Axes.hist``,
``FigureCanvasAgg.print_png``, public font-manager lookups, and public
``Rectangle`` getters. The committed mask is derived from the reference image
and the fixture's resolved background/face/edge colors; it never observes a
candidate/native render.

Histogram binning stays adapter-side under Figure authority (there is no
engine data-binning requirement): the fixture records the declared bin edges
and the resulting counts, and pins the rendered pre-computed bars.

Run from the repository root with::

    PYTHONPATH=python:tests/python python tests/python/generate_agg_oracle_bar.py

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

try:
    from ._agg_oracle import decode_png_rgba8, load_reference_fixture
except ImportError:  # ``python tests/python/generate_...py`` / unittest discovery
    from _agg_oracle import decode_png_rgba8, load_reference_fixture


FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
MANIFEST_PATH = FIXTURE_DIR / "bar_manifest.json"
REFERENCE_PNG_PATH = FIXTURE_DIR / "bar_reference.png"
MASK_PATH = FIXTURE_DIR / "bar_mask.json"

ORACLE_MATPLOTLIB_VERSION = "3.11.1"
ORACLE_API_VERSION = "1.1"
PYTHON_VERSION_RANGE = ">=3.11,<3.15"
FIGSIZE_INCHES = (2.0, 1.0)
EFFECTIVE_DPI = 100.0
AXES_RECT = (0.1, 0.1, 0.8, 0.8)
XLIM = (0.0, 8.0)
YLIM = (-3.0, 5.0)

# Vertical bars anchored to an explicit bottom baseline: one positive bar and
# one negative bar hanging below the baseline.  All bars are disjoint so the
# fixed pixel-class contract stays meaningful.
BAR_X = (1.0, 2.5)
BAR_HEIGHT = (2.0, -1.0)
BAR_WIDTH = 0.8
BAR_BASELINE = 0.0
BAR_FACE = "steelblue"

# Two stacked layers sharing one baseline: the lower layer's top edge is the
# upper layer's bottom edge at the shared x.
STACK_X = 4.5
STACK_WIDTH = 0.8
STACK_LAYERS = ((1.5, 0.0, "orange"), (1.0, 1.5, "purple"))

# One horizontal bar anchored to an explicit left baseline.
BARH_Y = (-2.0,)
BARH_WIDTH = (2.5,)
BARH_HEIGHT = 0.8
BARH_BASELINE = 0.0
BARH_FACE = "red"

# Adapter-side histogram binning: declared edges plus fixed data pin the
# pre-computed bars the engine renders.  No engine binning is required.
HIST_DATA = (5.2, 5.4, 5.6, 6.1, 6.3, 6.8)
HIST_BINS = (5.0, 5.5, 6.0, 6.5, 7.0)
HIST_FACE = "green"

# A zero-area bar paints nothing in Agg (no coverage).  The strict adapter
# skips it at emission while keeping the declared baseline input verbatim.
ZERO_X = 3.5
ZERO_WIDTH = 0.8
ZERO_BASELINE = 0.0

BAR_EDGE = "black"
BAR_LINEWIDTH = 1.0

INPUT_CASES: dict[str, dict[str, Any]] = {
    "bar": {"artist": "matplotlib.patches.Rectangle", "face": BAR_FACE},
    "stack": {
        "artist": "matplotlib.patches.Rectangle",
        "faces": [layer[2] for layer in STACK_LAYERS],
        "layers": len(STACK_LAYERS),
    },
    "barh": {"artist": "matplotlib.patches.Rectangle", "face": BARH_FACE},
    "histogram": {
        "artist": "matplotlib.patches.Rectangle",
        "face": HIST_FACE,
        "bins": list(HIST_BINS),
    },
    "zero_area": {
        "artist": "matplotlib.patches.Rectangle",
        "face": BAR_FACE,
        "paints": False,
    },
}

# These values are intentionally explicit rather than inherited from a moving
# Matplotlib default.  They are also the relevant rcParams recorded in the
# manifest.  Every bar call below repeats the style values explicitly, so the
# patch.facecolor entry is inert documentation, not a styling source.
RC_PARAMS: dict[str, Any] = {
    "agg.path.chunksize": 0,
    "axes.facecolor": "none",
    "figure.dpi": EFFECTIVE_DPI,
    "figure.edgecolor": "white",
    "figure.facecolor": "white",
    "font.family": ["DejaVu Sans"],
    "font.size": 10.0,
    "patch.antialiased": True,
    "patch.edgecolor": BAR_EDGE,
    "patch.facecolor": "white",
    "patch.force_edgecolor": False,
    "patch.linewidth": BAR_LINEWIDTH,
    "path.simplify": False,
    "path.simplify_threshold": 0.0,
    "savefig.dpi": EFFECTIVE_DPI,
    "savefig.edgecolor": "white",
    "savefig.facecolor": "white",
    "savefig.format": "png",
    "savefig.transparent": False,
    "text.antialiased": True,
}

BAR_STYLE: dict[str, Any] = {
    "facecolor": "explicit per artist",
    "edgecolor": BAR_EDGE,
    "linewidth": BAR_LINEWIDTH,
    "alpha": 1.0,
    "antialiased": True,
}

PIXEL_CLASSES = [
    "background",
    "fully-covered",
    "antialias-fringe",
    "text-or-outline",
]
PIXEL_CLASS_CODES = {name: index for index, name in enumerate(PIXEL_CLASSES)}


def _bar_kwargs(face: str) -> dict[str, Any]:
    return {
        "facecolor": face,
        "edgecolor": BAR_EDGE,
        "linewidth": BAR_LINEWIDTH,
    }


def build_fixture_figure() -> tuple[Figure, Any, dict[str, Any]]:
    """Build the exact fixed Figure/bar input used by every test path."""

    figure = Figure(
        figsize=FIGSIZE_INCHES,
        dpi=EFFECTIVE_DPI,
        facecolor="white",
        edgecolor="white",
    )
    axes = figure.add_axes(AXES_RECT)
    axes.set_facecolor("none")
    axes.set_axis_off()
    bars = axes.bar(
        list(BAR_X),
        list(BAR_HEIGHT),
        width=BAR_WIDTH,
        bottom=BAR_BASELINE,
        **_bar_kwargs(BAR_FACE),
    )
    stacked = [
        axes.bar(
            [STACK_X],
            [height],
            width=STACK_WIDTH,
            bottom=bottom,
            **_bar_kwargs(face),
        )
        for height, bottom, face in STACK_LAYERS
    ]
    hbars = axes.barh(
        list(BARH_Y),
        list(BARH_WIDTH),
        height=BARH_HEIGHT,
        left=BARH_BASELINE,
        **_bar_kwargs(BARH_FACE),
    )
    _counts, _edges, hpatches = axes.hist(
        list(HIST_DATA),
        bins=list(HIST_BINS),
        **_bar_kwargs(HIST_FACE),
    )
    zero = axes.bar(
        [ZERO_X],
        [0.0],
        width=ZERO_WIDTH,
        bottom=ZERO_BASELINE,
        **_bar_kwargs(BAR_FACE),
    )
    axes.set_xlim(*XLIM)
    axes.set_ylim(*YLIM)
    artists = {
        "bar": list(bars),
        "stack": [list(layer) for layer in stacked],
        "barh": list(hbars),
        "hist": list(hpatches),
        "zero": list(zero),
    }
    return figure, axes, artists


def fixture_rc_context():
    """Return the pinned public Matplotlib rc-context used by the fixture."""

    return matplotlib.rc_context(RC_PARAMS)


def _rectangle_topology(patch: Any, *, baseline: Any) -> dict[str, Any]:
    return {
        "class": "matplotlib.patches.Rectangle",
        "api": "patch.get_xy()/get_width()/get_height()",
        "xy": [float(value) for value in patch.get_xy()],
        "width": float(patch.get_width()),
        "height": float(patch.get_height()),
        "baseline": baseline,
        "angle": float(patch.get_angle()),
        "zorder": float(patch.get_zorder()),
    }


def public_bar_topology(artists: dict[str, Any]) -> dict[str, Any]:
    """Return topology from documented public getters (data coordinates)."""

    return {
        "bar": {
            "construction": "axes.bar(x, height, width, bottom)",
            "x": list(BAR_X),
            "height": list(BAR_HEIGHT),
            "width": BAR_WIDTH,
            "bottom": BAR_BASELINE,
            "rectangles": [
                _rectangle_topology(patch, baseline=BAR_BASELINE)
                for patch in artists["bar"]
            ],
        },
        "stack": {
            "construction": "axes.bar(x, height, width, bottom) per layer",
            "x": STACK_X,
            "width": STACK_WIDTH,
            "layers": [
                {
                    "height": height,
                    "bottom": bottom,
                    "face": face,
                    "rectangles": [
                        _rectangle_topology(patch, baseline=bottom)
                        for patch in layer
                    ],
                }
                for layer, (height, bottom, face) in zip(
                    artists["stack"], STACK_LAYERS
                )
            ],
        },
        "barh": {
            "construction": "axes.barh(y, width, height, left)",
            "y": list(BARH_Y),
            "width": list(BARH_WIDTH),
            "height": BARH_HEIGHT,
            "left": BARH_BASELINE,
            "rectangles": [
                _rectangle_topology(patch, baseline=BARH_BASELINE)
                for patch in artists["barh"]
            ],
        },
        "histogram": {
            "construction": "axes.hist(data, bins)",
            "data": list(HIST_DATA),
            "bins": list(HIST_BINS),
            "rectangles": [
                _rectangle_topology(patch, baseline=0.0)
                for patch in artists["hist"]
            ],
        },
        "zero_area": {
            "construction": "axes.bar(x, 0.0, width, bottom)",
            "x": ZERO_X,
            "width": ZERO_WIDTH,
            "bottom": ZERO_BASELINE,
            "rectangles": [
                _rectangle_topology(patch, baseline=ZERO_BASELINE)
                for patch in artists["zero"]
            ],
        },
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


def _resolved_face_colors(artists: dict[str, Any]) -> list[np.ndarray]:
    """Resolve every fixture face/edge color through public getters only."""

    faces = [
        _rgba8(artists["bar"][0].get_facecolor()),
        _rgba8(artists["stack"][0][0].get_facecolor()),
        _rgba8(artists["stack"][1][0].get_facecolor()),
        _rgba8(artists["barh"][0].get_facecolor()),
        _rgba8(artists["hist"][0].get_facecolor()),
        _rgba8(BAR_EDGE),
    ]
    return faces


def _reference_mask(
    rgba: np.ndarray, figure: Figure, artists: dict[str, Any]
) -> np.ndarray:
    """Classify reference pixels from the fixed background and bar colors."""

    background = _rgba8(figure.get_facecolor())
    background_pixels = np.all(rgba == background, axis=2)
    fully_covered_pixels = np.zeros(rgba.shape[:2], dtype=bool)
    for face in _resolved_face_colors(artists):
        fully_covered_pixels |= np.all(rgba == face, axis=2)
    fringe_pixels = ~(background_pixels | fully_covered_pixels)
    labels = np.full(
        rgba.shape[:2],
        PIXEL_CLASS_CODES["antialias-fringe"],
        dtype=np.uint8,
    )
    labels[background_pixels] = PIXEL_CLASS_CODES["background"]
    labels[fully_covered_pixels] = PIXEL_CLASS_CODES["fully-covered"]

    # This fixture has no text or outline artists.  Opaque bar interiors are
    # byte-equal to a resolved face color; stroked edges and clipped bar
    # corners are fringe.  The candidate/native image is deliberately not an
    # input.
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
        figure, _axes, artists = build_fixture_figure()
        canvas = FigureCanvasAgg(figure)
        buffer = io.BytesIO()
        # Direct FigureCanvasAgg.print_png is the pinned oracle operation.
        canvas.print_png(buffer, metadata={})
        reference_png = buffer.getvalue()
        decoded = decode_png_rgba8(reference_png)
        topology = public_bar_topology(artists)
        mask = _reference_mask(decoded.rgba, figure, artists)
        dimensions = tuple(int(value) for value in canvas.get_width_height())
    return reference_png, mask, topology, dimensions


def _hist_counts() -> list[float]:
    counts, _edges = np.histogram(
        np.asarray(HIST_DATA, dtype=float), bins=np.asarray(HIST_BINS, dtype=float)
    )
    return [float(value) for value in counts]


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
        "fixture_id": "bar-barh-stack-histogram-stroked",
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
        "artist_class": "matplotlib.patches.Rectangle",
        "primitive": {
            "family": ["matplotlib.patches.Rectangle"],
            "constructions": [
                "axes.bar(x, height, width, bottom)",
                "axes.barh(y, width, height, left)",
                "axes.hist(data, bins)",
            ],
            "style": BAR_STYLE,
            "input_data": {
                "bar": {
                    "x": list(BAR_X),
                    "height": list(BAR_HEIGHT),
                    "width": BAR_WIDTH,
                    "bottom": BAR_BASELINE,
                    "face": BAR_FACE,
                },
                "stack": {
                    "x": STACK_X,
                    "width": STACK_WIDTH,
                    "layers": [
                        {"height": height, "bottom": bottom, "face": face}
                        for height, bottom, face in STACK_LAYERS
                    ],
                },
                "barh": {
                    "y": list(BARH_Y),
                    "width": list(BARH_WIDTH),
                    "height": BARH_HEIGHT,
                    "left": BARH_BASELINE,
                    "face": BARH_FACE,
                },
                "histogram": {
                    "data": list(HIST_DATA),
                    "bins": list(HIST_BINS),
                    "counts": _hist_counts(),
                    "face": HIST_FACE,
                },
                "zero_area": {
                    "x": ZERO_X,
                    "height": 0.0,
                    "width": ZERO_WIDTH,
                    "bottom": ZERO_BASELINE,
                    "face": BAR_FACE,
                    "paints": False,
                },
                "edge": {"color": BAR_EDGE, "linewidth": BAR_LINEWIDTH},
                "cases": INPUT_CASES,
            },
        },
        "input_data": {
            "bar": {
                "x": list(BAR_X),
                "height": list(BAR_HEIGHT),
                "width": BAR_WIDTH,
                "bottom": BAR_BASELINE,
                "face": BAR_FACE,
            },
            "stack": {
                "x": STACK_X,
                "width": STACK_WIDTH,
                "layers": [
                    {"height": height, "bottom": bottom, "face": face}
                    for height, bottom, face in STACK_LAYERS
                ],
            },
            "barh": {
                "y": list(BARH_Y),
                "width": list(BARH_WIDTH),
                "height": BARH_HEIGHT,
                "left": BARH_BASELINE,
                "face": BARH_FACE,
            },
            "histogram": {
                "data": list(HIST_DATA),
                "bins": list(HIST_BINS),
                "counts": _hist_counts(),
                "face": HIST_FACE,
            },
            "zero_area": {
                "x": ZERO_X,
                "height": 0.0,
                "width": ZERO_WIDTH,
                "bottom": ZERO_BASELINE,
                "face": BAR_FACE,
                "paints": False,
            },
            "cases": INPUT_CASES,
        },
        "topology": topology,
        "mask_generation": (
            "reference-only: figure facecolor and resolved bar face/edge "
            "colors; candidate/native pixels are not observed"
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
