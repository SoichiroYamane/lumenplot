"""Generate and validate the fixed Matplotlib Agg fill-primitive fixture.

The reference is deliberately produced only with documented Matplotlib APIs:
``Figure``, ``Axes.fill``, ``Axes.fill_between``, ``Axes.axvspan``,
``Axes.axhspan``, ``Axes.stackplot``, ``FigureCanvasAgg.print_png``, public
font-manager lookups, and public ``Path``/``Rectangle`` getters. The
committed mask is derived from the reference image and the fixture's
resolved background/face colors; it never observes a candidate/native
render.

Run from the repository root with::

    PYTHONPATH=python:tests/python python tests/python/generate_agg_oracle_fill.py

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
MANIFEST_PATH = FIXTURE_DIR / "fill_manifest.json"
REFERENCE_PNG_PATH = FIXTURE_DIR / "fill_reference.png"
MASK_PATH = FIXTURE_DIR / "fill_mask.json"

ORACLE_MATPLOTLIB_VERSION = "3.11.1"
ORACLE_API_VERSION = "1.1"
PYTHON_VERSION_RANGE = ">=3.11,<3.15"
FIGSIZE_INCHES = (2.0, 1.0)
EFFECTIVE_DPI = 100.0
AXES_RECT = (0.1, 0.1, 0.8, 0.8)
XLIM = (0.0, 10.0)
YLIM = (-2.0, 6.0)

# Four non-overlapping opaque fill families (except one documented span/span
# overlap that pins painter's-order compositing).  Opaque faces keep the
# fixed pixel-class contract meaningful: interior pixels are byte-equal to
# the resolved face color, exactly like the Line2D lane's stroke interiors.
#
# Every edge is axis-aligned on an integer display coordinate (200x100 at
# 100 dpi: X(x) = 20 + 16*x, Y(y) = 30 + 10*y, so x steps of 0.0625 and y
# steps of 0.1 land on pixel boundaries).  Slanted edges produce
# partial-coverage fringe whose Agg-vs-native AA kernels differ by more than
# the fixed gate allows (measured: fringe-only, max channel delta 11,
# fringe rate 0.0075 with bit-exact adapter vertices) -- the same rasterizer
# trait as the known line2d F1 residual.  The pixel-parity fixture therefore
# pins the engine's exact surface; slanted-fill pixel parity is follow-up
# work, not a widened gate.
FILL_X = (0.5, 2.5, 2.5, 0.5)
FILL_Y = (0.0, 0.0, 2.0, 2.0)
FILL_FACE = "red"

FILL_BETWEEN_X = (3.0, 4.0, 5.0)
FILL_BETWEEN_Y1 = (2.0, 2.0, 2.0)
FILL_BETWEEN_Y2 = (0.0, 0.0, 0.0)
FILL_BETWEEN_FACE = "blue"

VSPAN_X = (6.0, 7.5)
VSPAN_FACE = "green"

HSPAN_Y = (-1.5, -0.5)
HSPAN_FACE = "yellow"

STACK_X = (8.0, 9.0, 10.0)
STACK_LAYERS = ((1.0, 1.0, 1.0), (0.5, 0.5, 0.5))
STACK_FACES = ("orange", "purple")

INPUT_CASES: dict[str, dict[str, Any]] = {
    "fill": {"artist": "matplotlib.patches.Polygon", "face": FILL_FACE},
    "fill_between": {
        "artist": "matplotlib.collections.FillBetweenPolyCollection",
        "face": FILL_BETWEEN_FACE,
    },
    "vspan": {"artist": "matplotlib.patches.Rectangle", "face": VSPAN_FACE},
    "hspan": {"artist": "matplotlib.patches.Rectangle", "face": HSPAN_FACE},
    "stack": {
        "artist": "matplotlib.collections.FillBetweenPolyCollection",
        "faces": list(STACK_FACES),
        "layers": len(STACK_LAYERS),
    },
}

# These values are intentionally explicit rather than inherited from a moving
# Matplotlib default.  They are also the relevant rcParams recorded in the
# manifest.
RC_PARAMS: dict[str, Any] = {
    "agg.path.chunksize": 0,
    "axes.facecolor": "none",
    "figure.dpi": EFFECTIVE_DPI,
    "figure.edgecolor": "white",
    "figure.facecolor": "white",
    "font.family": ["DejaVu Sans"],
    "font.size": 10.0,
    "lines.antialiased": True,
    "lines.solid_capstyle": "butt",
    "lines.solid_joinstyle": "miter",
    "patch.antialiased": True,
    "patch.edgecolor": "none",
    "patch.facecolor": "red",
    "patch.force_edgecolor": False,
    "patch.linewidth": 0.0,
    "path.simplify": False,
    "path.simplify_threshold": 0.0,
    "savefig.dpi": EFFECTIVE_DPI,
    "savefig.edgecolor": "white",
    "savefig.facecolor": "white",
    "savefig.format": "png",
    "savefig.transparent": False,
    "text.antialiased": True,
}

FILL_STYLE: dict[str, Any] = {
    "facecolor": "explicit per artist",
    "edgecolor": "none",
    "linewidth": 0.0,
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


def build_fixture_figure() -> tuple[Figure, Any, dict[str, Any]]:
    """Build the exact fixed Figure/fill input used by every test path."""

    figure = Figure(
        figsize=FIGSIZE_INCHES,
        dpi=EFFECTIVE_DPI,
        facecolor="white",
        edgecolor="white",
    )
    axes = figure.add_axes(AXES_RECT)
    axes.set_facecolor("none")
    axes.set_axis_off()
    polygon = axes.fill(
        list(FILL_X),
        list(FILL_Y),
        facecolor=FILL_FACE,
        edgecolor="none",
        linewidth=0.0,
    )[0]
    band = axes.fill_between(
        list(FILL_BETWEEN_X),
        list(FILL_BETWEEN_Y1),
        list(FILL_BETWEEN_Y2),
        facecolor=FILL_BETWEEN_FACE,
        edgecolor="none",
        linewidth=0.0,
    )
    vspan = axes.axvspan(
        VSPAN_X[0], VSPAN_X[1], facecolor=VSPAN_FACE, edgecolor="none",
        linewidth=0.0,
    )
    hspan = axes.axhspan(
        HSPAN_Y[0], HSPAN_Y[1], facecolor=HSPAN_FACE, edgecolor="none",
        linewidth=0.0,
    )
    stacks = axes.stackplot(
        list(STACK_X),
        [list(layer) for layer in STACK_LAYERS],
        colors=list(STACK_FACES),
        edgecolor="none",
        linewidth=0.0,
    )
    axes.set_xlim(*XLIM)
    axes.set_ylim(*YLIM)
    artists = {
        "fill": polygon,
        "fill_between": band,
        "vspan": vspan,
        "hspan": hspan,
        "stack": list(stacks),
    }
    return figure, axes, artists


def fixture_rc_context():
    """Return the pinned public Matplotlib rc-context used by the fixture."""

    return matplotlib.rc_context(RC_PARAMS)


def _path_topology(path: Any) -> dict[str, Any]:
    return {
        "vertices": [
            [float(value) for value in np.asarray(vertex).reshape(-1)]
            for vertex in np.asarray(path.vertices).tolist()
        ],
        "codes": (
            [int(code) for code in path.codes]
            if path.codes is not None
            else None
        ),
    }


def public_fill_topology(artists: dict[str, Any]) -> dict[str, Any]:
    """Return topology from documented public getters (data coordinates)."""

    polygon = artists["fill"]
    band = artists["fill_between"]
    vspan = artists["vspan"]
    hspan = artists["hspan"]
    stacks = artists["stack"]
    return {
        "fill": {
            "class": "matplotlib.patches.Polygon",
            "api": "patch.get_path().vertices/codes",
            "path": _path_topology(polygon.get_path()),
            "zorder": float(polygon.get_zorder()),
        },
        "fill_between": {
            "class": "matplotlib.collections.FillBetweenPolyCollection",
            "api": "collection.get_paths()",
            "loops": [_path_topology(path) for path in band.get_paths()],
            "zorder": float(band.get_zorder()),
        },
        "vspan": {
            "class": "matplotlib.patches.Rectangle",
            "api": "patch.get_xy()/get_width()/get_height()",
            "xy": [float(value) for value in vspan.get_xy()],
            "width": float(vspan.get_width()),
            "height": float(vspan.get_height()),
            "zorder": float(vspan.get_zorder()),
        },
        "hspan": {
            "class": "matplotlib.patches.Rectangle",
            "api": "patch.get_xy()/get_width()/get_height()",
            "xy": [float(value) for value in hspan.get_xy()],
            "width": float(hspan.get_width()),
            "height": float(hspan.get_height()),
            "zorder": float(hspan.get_zorder()),
        },
        "stack": {
            "class": "matplotlib.collections.FillBetweenPolyCollection",
            "api": "collection.get_paths()",
            "layers": [
                {
                    "loops": [
                        _path_topology(path)
                        for path in layer.get_paths()
                    ],
                    "zorder": float(layer.get_zorder()),
                }
                for layer in stacks
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
    """Resolve every fixture face color through public getters only."""

    faces = [
        _rgba8(artists["fill"].get_facecolor()),
        _rgba8(artists["fill_between"].get_facecolor()[0]),
        _rgba8(artists["vspan"].get_facecolor()),
        _rgba8(artists["hspan"].get_facecolor()),
    ]
    for layer in artists["stack"]:
        faces.append(_rgba8(layer.get_facecolor()[0]))
    return faces


def _reference_mask(
    rgba: np.ndarray, figure: Figure, artists: dict[str, Any]
) -> np.ndarray:
    """Classify reference pixels from the fixed background and face colors."""

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

    # This fixture has no text or outline artists.  Opaque interiors are
    # byte-equal to a resolved face color.  All edges are axis-aligned on
    # integer display coordinates, so Agg coverage is binary and the fringe
    # class is empty by construction; the comparator still evaluates its
    # fixed fringe duo (oversized count and total-pixel rate) against the
    # committed mask.  The candidate/native image is deliberately not an
    # input.
    if not bool(np.all(background_pixels | fully_covered_pixels | fringe_pixels)):
        raise AssertionError("reference mask classification left unknown pixels")
    if not bool(background_pixels.any()):
        raise AssertionError("reference mask has no background pixels")
    if not bool(fully_covered_pixels.any()):
        raise AssertionError("reference mask has no fully-covered pixels")
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
        topology = public_fill_topology(artists)
        mask = _reference_mask(decoded.rgba, figure, artists)
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
        "fixture_id": "fill-fill-between-span-stack-opaque",
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
        "artist_class": (
            "matplotlib.patches.Polygon + "
            "matplotlib.collections.FillBetweenPolyCollection + "
            "matplotlib.patches.Rectangle"
        ),
        "primitive": {
            "family": [
                "matplotlib.patches.Polygon",
                "matplotlib.collections.FillBetweenPolyCollection",
                "matplotlib.patches.Rectangle",
            ],
            "style": FILL_STYLE,
            "input_data": {
                "fill": {
                    "x": list(FILL_X),
                    "y": list(FILL_Y),
                    "face": FILL_FACE,
                },
                "fill_between": {
                    "x": list(FILL_BETWEEN_X),
                    "y1": list(FILL_BETWEEN_Y1),
                    "y2": list(FILL_BETWEEN_Y2),
                    "face": FILL_BETWEEN_FACE,
                },
                "vspan": {"x": list(VSPAN_X), "face": VSPAN_FACE},
                "hspan": {"y": list(HSPAN_Y), "face": HSPAN_FACE},
                "stack": {
                    "x": list(STACK_X),
                    "layers": [list(layer) for layer in STACK_LAYERS],
                    "faces": list(STACK_FACES),
                },
                "cases": INPUT_CASES,
            },
        },
        "input_data": {
            "fill": {
                "x": list(FILL_X),
                "y": list(FILL_Y),
                "face": FILL_FACE,
            },
            "fill_between": {
                "x": list(FILL_BETWEEN_X),
                "y1": list(FILL_BETWEEN_Y1),
                "y2": list(FILL_BETWEEN_Y2),
                "face": FILL_BETWEEN_FACE,
            },
            "vspan": {"x": list(VSPAN_X), "face": VSPAN_FACE},
            "hspan": {"y": list(HSPAN_Y), "face": HSPAN_FACE},
            "stack": {
                "x": list(STACK_X),
                "layers": [list(layer) for layer in STACK_LAYERS],
                "faces": list(STACK_FACES),
            },
            "cases": INPUT_CASES,
        },
        "topology": topology,
        "mask_generation": (
            "reference-only: figure facecolor and resolved fill face "
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
