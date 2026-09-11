"""Generate and validate the fixed Matplotlib Agg tick-label/spine fixture.

The reference is deliberately produced only with documented Matplotlib APIs:
``Figure``, ``Polygon``, ``FigureCanvasAgg.print_png``, public
tick/spine/font-manager lookups, and ``Axis.get_ticklocs``. The committed
mask is derived from the reference image and the fixture's resolved
background/fill/spine colors; it never observes a candidate/native render.

The frame carries exactly the T-lane surface: visible major tick labels on
both axes (pinned explicit texts), the four visible spine edges of the
axes box, major tick strokes, and one axis-aligned filled polygon as the
eligible content artist (LP-FUNC-032 axis-aligned exact surface, so the
only strokes in the frame are the rectilinear decoration edges).

Run from the repository root with::

    PYTHONPATH=python:tests/python python tests/python/generate_agg_oracle_ticklabels.py

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
from matplotlib.patches import Polygon  # noqa: E402

try:
    from ._agg_oracle import decode_png_rgba8, load_reference_fixture
except ImportError:  # ``python tests/python/generate_...py`` / unittest discovery
    from _agg_oracle import decode_png_rgba8, load_reference_fixture


FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
MANIFEST_PATH = FIXTURE_DIR / "ticklabels_manifest.json"
REFERENCE_PNG_PATH = FIXTURE_DIR / "ticklabels_reference.png"
MASK_PATH = FIXTURE_DIR / "ticklabels_mask.json"

ORACLE_MATPLOTLIB_VERSION = "3.11.1"
ORACLE_API_VERSION = "1.1"
PYTHON_VERSION_RANGE = ">=3.11,<3.15"
FIGSIZE_INCHES = (2.0, 1.0)
EFFECTIVE_DPI = 100.0
AXES_RECT = (0.1, 0.1, 0.8, 0.8)
XLIM = (0.0, 10.0)
YLIM = (0.0, 5.0)
XTICKS = (0.0, 5.0, 10.0)
XTICKLABELS = ("0", "5", "10")
YTICKS = (0.0, 5.0)
YTICKLABELS = ("0", "5")
POLYGON_VERTICES = ((2.0, 1.0), (8.0, 1.0), (8.0, 4.0), (2.0, 4.0))

# These values are intentionally explicit rather than inherited from a moving
# Matplotlib default.  They are also the relevant rcParams recorded in the
# manifest.  The Figure/Axes/Polygon constructors repeat the values whose
# public artist getters are part of the adapter eligibility contract.
RC_PARAMS: dict[str, Any] = {
    "agg.path.chunksize": 0,
    "axes.edgecolor": "black",
    "axes.facecolor": "none",
    "axes.linewidth": 0.8,
    "figure.dpi": EFFECTIVE_DPI,
    "figure.edgecolor": "white",
    "figure.facecolor": "white",
    "font.family": ["DejaVu Sans"],
    "font.size": 10.0,
    "lines.antialiased": True,
    "lines.solid_capstyle": "butt",
    "lines.solid_joinstyle": "miter",
    "patch.antialiased": True,
    "patch.facecolor": "red",
    "patch.edgecolor": "red",
    "patch.linewidth": 0.0,
    "path.simplify": False,
    "savefig.dpi": EFFECTIVE_DPI,
    "savefig.edgecolor": "white",
    "savefig.facecolor": "white",
    "savefig.format": "png",
    "savefig.transparent": False,
    "text.antialiased": True,
    "xtick.labelsize": 10.0,
    "xtick.major.pad": 3.5,
    "xtick.major.size": 3.5,
    "xtick.major.width": 0.8,
    "ytick.labelsize": 10.0,
    "ytick.major.pad": 3.5,
    "ytick.major.size": 3.5,
    "ytick.major.width": 0.8,
}

POLYGON_STYLE: dict[str, Any] = {
    "facecolor": "red",
    "edgecolor": "red",
    "linewidth": 0.0,
    "antialiased": True,
}

SPINE_STYLE: dict[str, Any] = {
    "edgecolor": "black",
    "linewidth": 0.8,
    "visible": {"bottom": True, "top": True, "left": True, "right": True},
}

PIXEL_CLASSES = [
    "background",
    "fully-covered",
    "antialias-fringe",
    "text-or-outline",
]
PIXEL_CLASS_CODES = {name: index for index, name in enumerate(PIXEL_CLASSES)}


def build_fixture_figure() -> tuple[Figure, Any]:
    """Build the exact fixed Figure/input used by every test path."""

    figure = Figure(
        figsize=FIGSIZE_INCHES,
        dpi=EFFECTIVE_DPI,
        facecolor="white",
        edgecolor="white",
    )
    axes = figure.add_axes(AXES_RECT)
    axes.set_facecolor("none")
    axes.add_patch(
        Polygon(
            list(POLYGON_VERTICES),
            facecolor=POLYGON_STYLE["facecolor"],
            edgecolor=POLYGON_STYLE["edgecolor"],
            linewidth=POLYGON_STYLE["linewidth"],
            antialiased=POLYGON_STYLE["antialiased"],
        )
    )
    axes.set_xlim(*XLIM)
    axes.set_ylim(*YLIM)
    axes.set_xticks(list(XTICKS))
    axes.set_xticklabels(list(XTICKLABELS))
    axes.set_yticks(list(YTICKS))
    axes.set_yticklabels(list(YTICKLABELS))
    return figure, axes


def fixture_rc_context():
    """Return the pinned public Matplotlib rc-context used by the fixture."""

    return matplotlib.rc_context(RC_PARAMS)


def public_tick_topology(axes: Any) -> dict[str, Any]:
    """Return tick/spine/fill facts from documented public getters only."""

    x_locs = [float(value) for value in axes.xaxis.get_ticklocs()]
    y_locs = [float(value) for value in axes.yaxis.get_ticklocs()]
    x_labels = [
        label.get_text()
        for label in axes.xaxis.get_majorticklabels()
        if label.get_visible() and label.get_text() != ""
    ]
    y_labels = [
        label.get_text()
        for label in axes.yaxis.get_majorticklabels()
        if label.get_visible() and label.get_text() != ""
    ]
    spines = {
        side: {
            "visible": bool(axes.spines[side].get_visible()),
            "linewidth": float(axes.spines[side].get_linewidth()),
            "edgecolor": list(
                float(value)
                for value in to_rgba(axes.spines[side].get_edgecolor())
            ),
        }
        for side in ("bottom", "top", "left", "right")
    }
    polygons = [
        {
            "vertices": [
                [float(value) for value in vertex]
                for vertex in np.asarray(patch.get_xy(), dtype=float).tolist()
            ],
            "facecolor": list(
                float(value) for value in to_rgba(patch.get_facecolor())
            ),
        }
        for patch in axes.patches
        if isinstance(patch, Polygon)
    ]
    return {
        "api": (
            "Axis.get_ticklocs/get_majorticklabels, "
            "Spine.get_visible/get_linewidth/get_edgecolor, "
            "Polygon.get_xy/get_facecolor"
        ),
        "xlim": list(XLIM),
        "ylim": list(YLIM),
        "xticklocs": x_locs,
        "xticklabels": x_labels,
        "yticklocs": y_locs,
        "yticklabels": y_labels,
        "spines": spines,
        "polygons": polygons,
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


def _reference_mask(rgba: np.ndarray, figure: Figure) -> np.ndarray:
    """Classify reference pixels from the fixed resolved colors.

    Background and fully covered pixels (figure face, polygon fill, spine
    and glyph ink) must compare byte-exact; every other reference pixel is
    antialiased fringe under the fixed S15.1 gate.
    """

    background = _rgba8(figure.get_facecolor())
    fill = _rgba8(POLYGON_STYLE["facecolor"])
    ink = _rgba8(SPINE_STYLE["edgecolor"])
    background_pixels = np.all(rgba == background, axis=2)
    fully_covered_pixels = np.all(rgba == fill, axis=2) | np.all(
        rgba == ink, axis=2
    )
    fringe_pixels = ~(background_pixels | fully_covered_pixels)
    labels = np.full(
        rgba.shape[:2],
        PIXEL_CLASS_CODES["antialias-fringe"],
        dtype=np.uint8,
    )
    labels[background_pixels] = PIXEL_CLASS_CODES["background"]
    labels[fully_covered_pixels] = PIXEL_CLASS_CODES["fully-covered"]

    # This fixture has no other ink sources: every non-background reference
    # pixel is either resolved fill/spine/glyph ink or fringe.  The
    # candidate/native image is deliberately not an input to this operation.
    if not bool(np.all(background_pixels | fully_covered_pixels | fringe_pixels)):
        raise AssertionError("reference mask classification left unknown pixels")
    return labels


def render_reference() -> tuple[bytes, np.ndarray, dict[str, Any], tuple[int, int]]:
    """Render the fixed input with public FigureCanvasAgg APIs."""

    with fixture_rc_context():
        figure, axes = build_fixture_figure()
        canvas = FigureCanvasAgg(figure)
        buffer = io.BytesIO()
        # Direct FigureCanvasAgg.print_png is the pinned oracle operation.
        canvas.print_png(buffer, metadata={})
        reference_png = buffer.getvalue()
        decoded = decode_png_rgba8(reference_png)
        topology = public_tick_topology(axes)
        mask = _reference_mask(decoded.rgba, figure)
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
        "fixture_id": "tick-labels-major-xticks-yticks-axes-box-spines",
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
                "xlim": list(XLIM),
                "ylim": list(YLIM),
                "xticks": list(XTICKS),
                "xticklabels": list(XTICKLABELS),
                "yticks": list(YTICKS),
                "yticklabels": list(YTICKLABELS),
                "polygon_vertices": [list(vertex) for vertex in POLYGON_VERTICES],
                "polygon_style": dict(POLYGON_STYLE),
                "spine_style": {
                    "edgecolor": SPINE_STYLE["edgecolor"],
                    "linewidth": SPINE_STYLE["linewidth"],
                    "visible": dict(SPINE_STYLE["visible"]),
                },
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
        "artist_class": "matplotlib.text.Text",
        "secondary_classes": [
            "matplotlib.spines.Spine",
            "matplotlib.patches.Polygon",
        ],
        "primitive": {
            "class": "matplotlib.text.Text",
            "ticklabels": {
                "xticks": list(XTICKS),
                "xticklabels": list(XTICKLABELS),
                "yticks": list(YTICKS),
                "yticklabels": list(YTICKLABELS),
            },
            "spines": dict(SPINE_STYLE),
            "polygon_style": dict(POLYGON_STYLE),
        },
        "input_data": {
            "xticklocs": list(XTICKS),
            "xticklabels": list(XTICKLABELS),
            "yticklocs": list(YTICKS),
            "yticklabels": list(YTICKLABELS),
        },
        "topology": topology,
        "mask_generation": (
            "reference-only: figure facecolor plus resolved polygon fill and "
            "spine/glyph ink; candidate/native pixels are not observed"
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
