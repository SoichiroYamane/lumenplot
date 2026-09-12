"""Generate and validate the fixed Matplotlib Agg line-handle legend fixture.

The reference is deliberately produced only with documented Matplotlib APIs:
``Figure``, ``Line2D``, ``Axes.legend``, ``FigureCanvasAgg.print_png``,
public font-manager lookups, ``Axes.get_xlim``/``Axes.get_ylim``, the public
axes transform, and public Legend/Line2D/Text/FancyBboxPatch getters.  The
committed mask is derived from the reference image and the fixture's resolved
background/stroke/ink colors; it never observes a candidate/native render.

The frame carries exactly the legend lane surface: a deterministic axes-on
figure (spines visible, tick strokes removed via explicit empty tick lists)
with two eligible solid line handles, one framed single-column legend, its
rounded frame, two handle polylines, and two label glyphs.  No tick labels,
gridlines, titles, or axis labels are present; the legend labels are the only
text surface.

Run from the repository root with::

    PYTHONPATH=python:tests/python python tests/python/generate_agg_oracle_legend.py

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
MANIFEST_PATH = FIXTURE_DIR / "legend_manifest.json"
REFERENCE_PNG_PATH = FIXTURE_DIR / "legend_reference.png"
MASK_PATH = FIXTURE_DIR / "legend_mask.json"

ORACLE_MATPLOTLIB_VERSION = "3.11.1"
ORACLE_API_VERSION = "1.1"
PYTHON_VERSION_RANGE = ">=3.11,<3.15"
FIGSIZE_INCHES = (2.0, 1.0)
EFFECTIVE_DPI = 100.0
AXES_RECT = (0.1, 0.1, 0.8, 0.8)
XLIM = (0.0, 10.0)
YLIM = (0.0, 5.0)
LEGEND_LOC = "upper right"

# Two eligible content lines: solid, butt/miter, default drawstyle, no marker.
# Both use linewidth 2.0 so the handle strokes mirror a single thick surface.
LINE_ALPHA = {"x": (0.0, 10.0), "y": (0.0, 5.0), "color": "red", "label": "alpha"}
LINE_BETA = {"x": (0.0, 10.0), "y": (5.0, 0.0), "color": "blue", "label": "beta"}
LINE_WIDTH = 2.0

INPUT_CASES: dict[str, dict[str, Any]] = {
    "alpha": {
        "artist": "matplotlib.lines.Line2D",
        "color": "red",
        "label": "alpha",
    },
    "beta": {
        "artist": "matplotlib.lines.Line2D",
        "color": "blue",
        "label": "beta",
    },
}

# These values are intentionally explicit rather than inherited from a moving
# Matplotlib default.  They are also the relevant rcParams recorded in the
# manifest.  The Figure/Line2D/legend constructors repeat the style values
# whose public artist getters are part of the adapter eligibility contract.
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
    "legend.edgecolor": "black",
    "legend.facecolor": "white",
    "legend.framealpha": 1.0,
    "legend.fontsize": 10.0,
    "lines.antialiased": True,
    "lines.dash_capstyle": "butt",
    "lines.dash_joinstyle": "miter",
    "lines.linestyle": "-",
    "lines.linewidth": LINE_WIDTH,
    "lines.solid_capstyle": "butt",
    "lines.solid_joinstyle": "miter",
    "patch.antialiased": True,
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
    "linewidth": LINE_WIDTH,
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


def build_fixture_figure() -> tuple[Figure, Any, Any, list[Line2D]]:
    """Build the exact fixed Figure/axes/legend input used by every test path."""

    figure = Figure(
        figsize=FIGSIZE_INCHES,
        dpi=EFFECTIVE_DPI,
        facecolor="white",
        edgecolor="white",
    )
    axes = figure.add_axes(AXES_RECT)
    axes.set_facecolor("none")
    axes.tick_params(labelbottom=False, labelleft=False)
    line_alpha = Line2D(
        np.asarray(LINE_ALPHA["x"], dtype=float),
        np.asarray(LINE_ALPHA["y"], dtype=float),
        color=str(LINE_ALPHA["color"]),
        label=str(LINE_ALPHA["label"]),
        **LINE_STYLE,
    )
    line_beta = Line2D(
        np.asarray(LINE_BETA["x"], dtype=float),
        np.asarray(LINE_BETA["y"], dtype=float),
        color=str(LINE_BETA["color"]),
        label=str(LINE_BETA["label"]),
        **LINE_STYLE,
    )
    axes.add_line(line_alpha)
    axes.add_line(line_beta)
    # Axes-on with a minimal deterministic decoration: spines stay visible
    # while tick strokes are removed via explicit empty tick lists.  The
    # legend labels remain the only text surface in the frame.
    axes.set_xticks([])
    axes.set_yticks([])
    legend = axes.legend(loc=LEGEND_LOC, frameon=True)
    axes.set_xlim(*XLIM)
    axes.set_ylim(*YLIM)
    return figure, axes, legend, [line_alpha, line_beta]


def fixture_rc_context():
    """Return the pinned public Matplotlib rc-context used by the fixture."""

    return matplotlib.rc_context(RC_PARAMS)


def public_legend_topology(
    axes: Any, legend: Any, lines: list[Line2D]
) -> dict[str, Any]:
    """Return content + legend facts from documented public getters only."""

    moveto = int(MatplotlibPath.MOVETO)
    lineto = int(MatplotlibPath.LINETO)
    content = []
    for line in lines:
        segments = list(line.get_path().iter_segments(remove_nans=True))
        codes = [int(code) for _vertices, code in segments]
        vertices = [
            [float(value) for value in np.asarray(v).reshape(-1)]
            for v, _code in segments
        ]
        data = np.column_stack(
            [np.asarray(line.get_xdata(), dtype=float),
             np.asarray(line.get_ydata(), dtype=float)]
        )
        display = axes.transData.transform(data)
        content.append(
            {
                "label": str(line.get_label()),
                "color": str(line.get_color()),
                "linewidth": float(line.get_linewidth()),
                "linestyle": str(line.get_linestyle()),
                "drawstyle": str(line.get_drawstyle()),
                "marker": str(line.get_marker()),
                "segment_count": len(segments),
                "moveto_count": sum(code == moveto for code in codes),
                "lineto_count": sum(code == lineto for code in codes),
                "segment_codes": codes,
                "vertices": vertices,
                "display_vertices": [
                    [float(value) for value in row]
                    for row in np.asarray(display).tolist()
                ],
            }
        )
    frame = legend.get_frame()
    boxstyle = frame.get_boxstyle()
    handles = list(legend.get_lines())
    labels = list(legend.get_texts())
    legend_topology: dict[str, Any] = {
        "class": f"{type(legend).__module__}.{type(legend).__name__}",
        "loc": LEGEND_LOC,
        "frameon": bool(legend.get_frame_on()),
        "entry_count": len(labels),
        "handle_count": len(handles),
        "frame": {
            "class": f"{type(frame).__module__}.{type(frame).__name__}",
            "boxstyle": f"{type(boxstyle).__module__}.{type(boxstyle).__name__}",
            "facecolor": [float(v) for v in to_rgba(frame.get_facecolor())],
            "edgecolor": [float(v) for v in to_rgba(frame.get_edgecolor())],
            "linewidth": float(frame.get_linewidth()),
            "fill": bool(frame.get_fill()),
        },
        "entries": [
            {
                "label": str(label.get_text()),
                "label_fontsize": float(label.get_fontsize()),
                "handle_color": str(handle.get_color()),
                "handle_linewidth": float(handle.get_linewidth()),
                "handle_linestyle": str(handle.get_linestyle()),
                "handle_drawstyle": str(handle.get_drawstyle()),
            }
            for handle, label in zip(handles, labels)
        ],
        "label_texts": [str(label.get_text()) for label in labels],
    }
    spines = {
        side: {
            "visible": bool(axes.spines[side].get_visible()),
            "linewidth": float(axes.spines[side].get_linewidth()),
            "edgecolor": [
                float(value)
                for value in to_rgba(axes.spines[side].get_edgecolor())
            ],
        }
        for side in ("bottom", "top", "left", "right")
    }
    return {
        "api": (
            "line.get_path().iter_segments(remove_nans=True), "
            "axes.transData.transform(data), "
            "legend.get_texts/get_lines/get_frame, "
            "Spine.get_visible/get_linewidth/get_edgecolor"
        ),
        "scales": {"x": "linear", "y": "linear"},
        "limits": {"xlim": list(XLIM), "ylim": list(YLIM)},
        "axis_on": True,
        "xticks": [],
        "yticks": [],
        "content_lines": content,
        "legend": legend_topology,
        "spines": spines,
        "display_api": "axes.transData.transform(data)",
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

    Background (figure face, equal to the legend frame fill) and
    fully-covered pixels (content red/blue plus black spine/frame-edge/glyph
    ink) must compare byte-exact; every other reference pixel is
    antialiased fringe under the fixed S15.1 gate.
    """

    background = _rgba8(figure.get_facecolor())
    red = _rgba8("red")
    blue = _rgba8("blue")
    ink = _rgba8("black")
    background_pixels = np.all(rgba == background, axis=2)
    fully_covered_pixels = (
        np.all(rgba == red, axis=2)
        | np.all(rgba == blue, axis=2)
        | np.all(rgba == ink, axis=2)
    )
    fringe_pixels = ~(background_pixels | fully_covered_pixels)
    labels = np.full(
        rgba.shape[:2],
        PIXEL_CLASS_CODES["antialias-fringe"],
        dtype=np.uint8,
    )
    labels[background_pixels] = PIXEL_CLASS_CODES["background"]
    labels[fully_covered_pixels] = PIXEL_CLASS_CODES["fully-covered"]

    # This fixture's only ink sources are the two content strokes, the four
    # spine edges, the legend frame edge, the two handle strokes, and the two
    # label glyph cores.  The candidate/native image is deliberately not an
    # input to this operation.
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
        figure, axes, legend, lines = build_fixture_figure()
        canvas = FigureCanvasAgg(figure)
        buffer = io.BytesIO()
        # Direct FigureCanvasAgg.print_png is the pinned oracle operation.
        canvas.print_png(buffer, metadata={})
        reference_png = buffer.getvalue()
        decoded = decode_png_rgba8(reference_png)
        topology = public_legend_topology(axes, legend, lines)
        mask = _reference_mask(decoded.rgba, figure)
        width_px, height_px = canvas.get_width_height()
        dimensions = (int(width_px), int(height_px))
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
        "fixture_id": "legend-line-handles-framed-single-column",
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
                "axis_on": True,
                "xlim": list(XLIM),
                "ylim": list(YLIM),
                "xticks": [],
                "yticks": [],
                "legend_loc": LEGEND_LOC,
                "legend_frameon": True,
                "content_lines": [
                    {
                        "label": str(LINE_ALPHA["label"]),
                        "color": str(LINE_ALPHA["color"]),
                        "linewidth": LINE_WIDTH,
                    },
                    {
                        "label": str(LINE_BETA["label"]),
                        "color": str(LINE_BETA["color"]),
                        "linewidth": LINE_WIDTH,
                    },
                ],
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
        "artist_class": "matplotlib.legend.Legend",
        "secondary_classes": [
            "matplotlib.lines.Line2D",
            "matplotlib.patches.FancyBboxPatch",
            "matplotlib.text.Text",
            "matplotlib.spines.Spine",
        ],
        "primitive": {
            "class": "matplotlib.legend.Legend",
            "legend": {
                "loc": LEGEND_LOC,
                "frameon": True,
                "labels": [str(LINE_ALPHA["label"]), str(LINE_BETA["label"])],
            },
            "handles": [
                {
                    "class": "matplotlib.lines.Line2D",
                    "color": str(LINE_ALPHA["color"]),
                    "linewidth": LINE_WIDTH,
                },
                {
                    "class": "matplotlib.lines.Line2D",
                    "color": str(LINE_BETA["color"]),
                    "linewidth": LINE_WIDTH,
                },
            ],
        },
        "input_data": {
            "alpha": {
                "x": list(LINE_ALPHA["x"]),
                "y": list(LINE_ALPHA["y"]),
                "color": str(LINE_ALPHA["color"]),
                "label": str(LINE_ALPHA["label"]),
            },
            "beta": {
                "x": list(LINE_BETA["x"]),
                "y": list(LINE_BETA["y"]),
                "color": str(LINE_BETA["color"]),
                "label": str(LINE_BETA["label"]),
            },
            "xlim": list(XLIM),
            "ylim": list(YLIM),
            "cases": INPUT_CASES,
        },
        "topology": topology,
        "mask_generation": (
            "reference-only: figure facecolor plus resolved red/blue/black "
            "ink; candidate/native pixels are not observed"
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
