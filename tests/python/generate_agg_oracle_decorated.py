"""Generate and validate the fixed Matplotlib Agg decorated-frame fixture.

The reference is deliberately produced only with documented Matplotlib APIs:
``Figure``, ``Line2D``, ``Axes.set_xticks``/``set_yticks``,
``Axes.tick_params``, ``Axes.grid``, ``Spine`` setters,
``FigureCanvasAgg.print_png``, public font-manager lookups, and public
artist getters. The committed mask is derived from the reference image
and the fixture's resolved background/stroke colors; it never observes a
candidate/native render.

The figure keeps exactly one standard axes with decorations on
(LP-FUNC-003 MUST): visible major tick labels, four box/spine edges, and
solid major gridlines, plus one strict-eligible diagonal content line.
Titles, axis labels, offset text, minor ticks, and minor gridlines are
all absent so the pinned input stays inside the strict decorated slice.

Run from the repository root with::

    PYTHONPATH=python:tests/python python tests/python/generate_agg_oracle_decorated.py

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
MANIFEST_PATH = FIXTURE_DIR / "decorated_frame_manifest.json"
REFERENCE_PNG_PATH = FIXTURE_DIR / "decorated_frame_reference.png"
MASK_PATH = FIXTURE_DIR / "decorated_frame_mask.json"

ORACLE_MATPLOTLIB_VERSION = "3.11.1"
ORACLE_API_VERSION = "1.1"
PYTHON_VERSION_RANGE = ">=3.11,<3.15"
FIGSIZE_INCHES = (2.0, 1.0)
EFFECTIVE_DPI = 100.0
AXES_RECT = (0.1, 0.1, 0.8, 0.8)
XLIM = (0.0, 10.0)
YLIM = (0.0, 5.0)

# Deterministic content: one diagonal across the full data limits, using the
# strict-eligible stroke surface (butt caps, miter joins) shared with the
# live decorated-axes tests.
LINE_X = (0.0, 10.0)
LINE_Y = (0.0, 5.0)
LINE_COLOR = "red"
LINE_WIDTH = 2.0

# Explicit major tick locations pin the label strings ("0", "5", "10" on x;
# "0", "2.5", "5" on y): no whitespace, no newlines, no math markers, so the
# strict tick-label whitelist accepts every visible label verbatim.
XTICKS = (0.0, 5.0, 10.0)
YTICKS = (0.0, 2.5, 5.0)

GRID_COLOR = "#808080"
GRID_LINEWIDTH = 0.8
GRID_LINESTYLE = "-"
GRID_ALPHA = 1.0

SPINE_COLOR = "black"
SPINE_LINEWIDTH = 1.0
SPINE_SIDES = ("left", "right", "top", "bottom")

TICK_COLOR = "black"
TICK_LENGTH = 3.5
TICK_WIDTH = 0.8
TICK_LABELSIZE = 10.0

INPUT_CASES: dict[str, dict[str, Any]] = {
    "content_line": {"artist": "matplotlib.lines.Line2D", "color": LINE_COLOR},
    "tick_labels": {"artist": "matplotlib.text.Text", "count": 6},
    "grid": {"artist": "matplotlib.lines.Line2D", "which": "major"},
    "spines": {"artist": "matplotlib.spines.Spine", "sides": list(SPINE_SIDES)},
}

# These values are intentionally explicit rather than inherited from a moving
# Matplotlib default.  They are also the relevant rcParams recorded in the
# manifest.  Every axes call below repeats the style values explicitly, so
# the rc entries pin the cell rather than styling by inheritance.
RC_PARAMS: dict[str, Any] = {
    "agg.path.chunksize": 0,
    "axes.axisbelow": "line",
    "axes.edgecolor": SPINE_COLOR,
    "axes.facecolor": "none",
    "axes.grid": False,
    "axes.linewidth": SPINE_LINEWIDTH,
    "figure.dpi": EFFECTIVE_DPI,
    "figure.edgecolor": "white",
    "figure.facecolor": "white",
    "font.family": ["DejaVu Sans"],
    "font.size": 10.0,
    "grid.alpha": GRID_ALPHA,
    "grid.color": GRID_COLOR,
    "grid.linestyle": GRID_LINESTYLE,
    "grid.linewidth": GRID_LINEWIDTH,
    "lines.antialiased": True,
    "lines.color": LINE_COLOR,
    "lines.dash_capstyle": "butt",
    "lines.dash_joinstyle": "miter",
    "lines.linestyle": "-",
    # NOTE: the adapter's tick-stroke command reads the tick Line2D's
    # ``get_linewidth()``, which inherits ``lines.linewidth`` at tick
    # creation, while Agg draws tick marks at the tick ``width``
    # (markeredgewidth). Pinning rc ``lines.linewidth`` to the tick width
    # keeps the emitted tick stroke identical to the Agg stroke; the
    # content line overrides its width explicitly per artist.
    "lines.linewidth": TICK_WIDTH,
    "lines.marker": "None",
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
    "xtick.color": TICK_COLOR,
    "xtick.direction": "out",
    "xtick.labelsize": TICK_LABELSIZE,
    "xtick.major.size": TICK_LENGTH,
    "xtick.major.width": TICK_WIDTH,
    "ytick.color": TICK_COLOR,
    "ytick.direction": "out",
    "ytick.labelsize": TICK_LABELSIZE,
    "ytick.major.size": TICK_LENGTH,
    "ytick.major.width": TICK_WIDTH,
}

LINE_STYLE: dict[str, Any] = {
    "color": LINE_COLOR,
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


def build_fixture_figure() -> tuple[Figure, Any, dict[str, Any]]:
    """Build the exact fixed Figure/decorated-axes input used by every path."""

    figure = Figure(
        figsize=FIGSIZE_INCHES,
        dpi=EFFECTIVE_DPI,
        facecolor="white",
        edgecolor="white",
    )
    axes = figure.add_axes(AXES_RECT)
    axes.set_facecolor("none")
    line = Line2D(
        list(LINE_X),
        list(LINE_Y),
        **LINE_STYLE,
    )
    axes.add_line(line)
    axes.set_xticks(list(XTICKS))
    axes.set_yticks(list(YTICKS))
    axes.tick_params(
        which="major",
        direction="out",
        length=TICK_LENGTH,
        width=TICK_WIDTH,
        colors=TICK_COLOR,
        labelsize=TICK_LABELSIZE,
        labelcolor=TICK_COLOR,
        bottom=True,
        top=False,
        left=True,
        right=False,
        labelbottom=True,
        labelleft=True,
    )
    axes.grid(
        True,
        which="major",
        axis="both",
        color=GRID_COLOR,
        linewidth=GRID_LINEWIDTH,
        linestyle=GRID_LINESTYLE,
        alpha=GRID_ALPHA,
    )
    for side in SPINE_SIDES:
        axes.spines[side].set_edgecolor(SPINE_COLOR)
        axes.spines[side].set_linewidth(SPINE_LINEWIDTH)
    axes.set_xlim(*XLIM)
    axes.set_ylim(*YLIM)
    return figure, axes, {"line": line}


def fixture_rc_context():
    """Return the pinned public Matplotlib rc-context used by the fixture."""

    return matplotlib.rc_context(RC_PARAMS)


def public_line_topology(line: Line2D) -> dict[str, Any]:
    """Return content-line topology from the documented public Path API."""

    segments = list(line.get_path().iter_segments(remove_nans=True))
    codes = [int(code) for _vertices, code in segments]
    vertices = [
        [float(value) for value in np.asarray(segment_vertices).reshape(-1)]
        for segment_vertices, _code in segments
    ]
    return {
        "api": "line.get_path().iter_segments(remove_nans=True)",
        "class": "matplotlib.lines.Line2D",
        "xdata": [float(value) for value in np.asarray(line.get_xdata()).tolist()],
        "ydata": [float(value) for value in np.asarray(line.get_ydata()).tolist()],
        "color": str(line.get_color()),
        "linewidth": float(line.get_linewidth()),
        "linestyle": str(line.get_linestyle()),
        "marker": str(line.get_marker()),
        "drawstyle": str(line.get_drawstyle()),
        "solid_capstyle": str(line.get_solid_capstyle()),
        "solid_joinstyle": str(line.get_solid_joinstyle()),
        "segment_codes": codes,
        "vertices": vertices,
        "moveto_count": sum(code == int(MatplotlibPath.MOVETO) for code in codes),
        "lineto_count": sum(code == int(MatplotlibPath.LINETO) for code in codes),
    }


def public_ticks_topology(axes: Any) -> dict[str, Any]:
    """Return tick locations and label strings via documented getters."""

    x_locs = [float(value) for value in axes.xaxis.get_ticklocs()]
    y_locs = [float(value) for value in axes.yaxis.get_ticklocs()]
    x_labels = [label.get_text() for label in axes.xaxis.get_majorticklabels()]
    y_labels = [label.get_text() for label in axes.yaxis.get_majorticklabels()]
    x_visible = [
        bool(label.get_visible()) for label in axes.xaxis.get_majorticklabels()
    ]
    y_visible = [
        bool(label.get_visible()) for label in axes.yaxis.get_majorticklabels()
    ]
    return {
        "construction": "axes.set_xticks/set_yticks plus tick_params",
        "x_ticklocs": x_locs,
        "y_ticklocs": y_locs,
        "x_labels": x_labels,
        "y_labels": y_labels,
        "x_label_visible": x_visible,
        "y_label_visible": y_visible,
        "tick_params": {
            "direction": "out",
            "length": TICK_LENGTH,
            "width": TICK_WIDTH,
            "color": TICK_COLOR,
            "labelsize": TICK_LABELSIZE,
        },
    }


def public_grid_topology(axes: Any) -> dict[str, Any]:
    """Return visible major gridline style via documented getters."""

    entries = []
    for axis_name, axis in (("x", axes.xaxis), ("y", axes.yaxis)):
        for gridline in axis.get_gridlines():
            entries.append(
                {
                    "axis": axis_name,
                    "visible": bool(gridline.get_visible()),
                    "color": str(gridline.get_color()),
                    "linewidth": float(gridline.get_linewidth()),
                    "linestyle": str(gridline.get_linestyle()),
                }
            )
    return {
        "construction": "axes.grid(True, which='major', axis='both', ...)",
        "which": "major",
        "entries": entries,
    }


def public_spine_topology(axes: Any) -> dict[str, Any]:
    """Return box/spine edges via documented Spine getters."""

    sides = {}
    for side in SPINE_SIDES:
        spine = axes.spines[side]
        sides[side] = {
            "class": type(spine).__name__,
            "visible": bool(spine.get_visible()),
            "edgecolor": str(spine.get_edgecolor()),
            "linewidth": float(spine.get_linewidth()),
        }
    return {
        "construction": "axes.spines[side].set_edgecolor/set_linewidth",
        "sides": sides,
    }


def public_decorated_topology(axes: Any, artists: dict[str, Any]) -> dict[str, Any]:
    """Return the full decorated-frame topology from public getters only."""

    return {
        "axes": {
            "construction": "figure.add_axes((0.1, 0.1, 0.8, 0.8))",
            "rect": list(AXES_RECT),
            "xlim": list(axes.get_xlim()),
            "ylim": list(axes.get_ylim()),
            "facecolor": str(axes.get_facecolor()),
            "axis_on": True,
        },
        "line": public_line_topology(artists["line"]),
        "ticks": public_ticks_topology(axes),
        "grid": public_grid_topology(axes),
        "spines": public_spine_topology(axes),
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
    rgba: np.ndarray, figure: Figure, artists: dict[str, Any], axes: Any
) -> np.ndarray:
    """Classify reference pixels from the fixed background and stroke colors."""

    background = _rgba8(figure.get_facecolor())
    content = _rgba8(artists["line"].get_color())
    grid = _rgba8(GRID_COLOR)
    ink = _rgba8(SPINE_COLOR)
    background_pixels = np.all(rgba == background, axis=2)
    fully_covered_pixels = (
        np.all(rgba == content, axis=2)
        | np.all(rgba == grid, axis=2)
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

    # Tick-label glyphs share the resolved black ink: exact-black glyph
    # interiors are fully covered and antialiased glyph edges are fringe.
    # The candidate/native image is deliberately not an input.
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
        figure, axes, artists = build_fixture_figure()
        canvas = FigureCanvasAgg(figure)
        buffer = io.BytesIO()
        # Direct FigureCanvasAgg.print_png is the pinned oracle operation.
        canvas.print_png(buffer, metadata={})
        reference_png = buffer.getvalue()
        decoded = decode_png_rgba8(reference_png)
        topology = public_decorated_topology(axes, artists)
        mask = _reference_mask(decoded.rgba, figure, artists, axes)
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
        "fixture_id": "decorated-frame-ticklabels-grid-spines",
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
                "xticks": list(XTICKS),
                "yticks": list(YTICKS),
                "grid": {
                    "visible": True,
                    "which": "major",
                    "axis": "both",
                    "color": GRID_COLOR,
                    "linewidth": GRID_LINEWIDTH,
                    "linestyle": GRID_LINESTYLE,
                    "alpha": GRID_ALPHA,
                },
                "spines": {
                    "sides": list(SPINE_SIDES),
                    "edgecolor": SPINE_COLOR,
                    "linewidth": SPINE_LINEWIDTH,
                },
                "tick_params": {
                    "direction": "out",
                    "length": TICK_LENGTH,
                    "width": TICK_WIDTH,
                    "color": TICK_COLOR,
                    "labelsize": TICK_LABELSIZE,
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
        "artist_class": "matplotlib.axes.Axes",
        "primitive": {
            "family": [
                "matplotlib.axes.Axes",
                "matplotlib.lines.Line2D",
                "matplotlib.text.Text",
                "matplotlib.spines.Spine",
            ],
            "constructions": [
                "figure.add_axes((0.1, 0.1, 0.8, 0.8))",
                "axes.add_line(Line2D(x, y, ...))",
                "axes.set_xticks/set_yticks",
                "axes.grid(True, which='major', axis='both', ...)",
            ],
            "style": {
                "line": LINE_STYLE,
                "grid": {
                    "color": GRID_COLOR,
                    "linewidth": GRID_LINEWIDTH,
                    "linestyle": GRID_LINESTYLE,
                    "alpha": GRID_ALPHA,
                },
                "spine": {"edgecolor": SPINE_COLOR, "linewidth": SPINE_LINEWIDTH},
                "tick": {
                    "color": TICK_COLOR,
                    "length": TICK_LENGTH,
                    "width": TICK_WIDTH,
                    "labelsize": TICK_LABELSIZE,
                },
            },
            "input_data": {
                "line": {
                    "x": list(LINE_X),
                    "y": list(LINE_Y),
                    "color": LINE_COLOR,
                    "linewidth": LINE_WIDTH,
                },
                "xticks": list(XTICKS),
                "yticks": list(YTICKS),
                "grid": {
                    "color": GRID_COLOR,
                    "linewidth": GRID_LINEWIDTH,
                    "linestyle": GRID_LINESTYLE,
                    "which": "major",
                },
                "spines": {
                    "sides": list(SPINE_SIDES),
                    "edgecolor": SPINE_COLOR,
                    "linewidth": SPINE_LINEWIDTH,
                },
                "cases": INPUT_CASES,
            },
        },
        "input_data": {
            "line": {
                "x": list(LINE_X),
                "y": list(LINE_Y),
                "color": LINE_COLOR,
                "linewidth": LINE_WIDTH,
            },
            "xticks": list(XTICKS),
            "yticks": list(YTICKS),
            "grid": {
                "color": GRID_COLOR,
                "linewidth": GRID_LINEWIDTH,
                "linestyle": GRID_LINESTYLE,
                "which": "major",
            },
            "spines": {
                "sides": list(SPINE_SIDES),
                "edgecolor": SPINE_COLOR,
                "linewidth": SPINE_LINEWIDTH,
            },
            "cases": INPUT_CASES,
        },
        "topology": topology,
        "mask_generation": (
            "reference-only: figure facecolor and resolved content/grid/ink "
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
