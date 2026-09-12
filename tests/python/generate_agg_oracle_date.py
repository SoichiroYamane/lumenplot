"""Generate and validate the fixed Matplotlib Agg date-axis fixture.

The reference is deliberately produced only with documented Matplotlib APIs:
``Figure``, ``Axes.plot`` (which registers the date unit converter on the
axis -- ``add_line`` does not), ``AutoDateLocator``,
``FigureCanvasAgg.print_png``, public font-manager lookups, the public
``orig=False`` unit-processed data getters, ``Axis.get_ticklocs`` /
``get_majorticklabels``, and the public axes transform.  The committed mask
is derived from the reference image and the fixture's resolved
background/stroke/ink colors; it never observes a candidate/native render.

The frame is one bounded date/unit-aware axes-on input: Figure-authoritative
converted numeric data, locator/formatter results, visible major ticks with
solid major gridlines on both axes, four visible spine edges, and plain
date label glyphs.  No mathtext/TeX, no alternate scales, no titles, no
axis labels, and no offset text enter the fixture.

Run from the repository root with::

    PYTHONPATH=python:tests/python python tests/python/generate_agg_oracle_date.py

Use ``--check`` in a test or verification job to prove the committed PNG and
mask are byte-stable for the pinned Matplotlib cell.
"""

from __future__ import annotations

import argparse
import datetime as dt
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
from matplotlib.dates import AutoDateLocator, date2num  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.font_manager import FontProperties, findfont  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.path import Path as MatplotlibPath  # noqa: E402

try:
    from ._agg_oracle import decode_png_rgba8, load_reference_fixture
except ImportError:  # ``python tests/python/generate_...py`` / unittest discovery
    from _agg_oracle import decode_png_rgba8, load_reference_fixture


FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
MANIFEST_PATH = FIXTURE_DIR / "date_axis_manifest.json"
REFERENCE_PNG_PATH = FIXTURE_DIR / "date_axis_reference.png"
MASK_PATH = FIXTURE_DIR / "date_axis_mask.json"

ORACLE_MATPLOTLIB_VERSION = "3.11.1"
ORACLE_API_VERSION = "1.1"
PYTHON_VERSION_RANGE = ">=3.11,<3.15"
FIGSIZE_INCHES = (2.0, 1.0)
EFFECTIVE_DPI = 100.0
AXES_RECT = (0.1, 0.1, 0.8, 0.8)
XLIM_DATES = (
    dt.datetime(2026, 1, 1),
    dt.datetime(2026, 1, 3),
)
YLIM = (0.0, 4.0)
XSCALE = "linear"
YSCALE = "linear"

# Three daily samples.  ``Axes.plot`` (not ``add_line``) registers the date
# unit converter on the axis, which is the realistic user route and the one
# the parity draft's F-10 note assumes ("unit conversion happens upstream
# of the public getters").
INPUT_DATES = (
    dt.datetime(2026, 1, 1),
    dt.datetime(2026, 1, 2),
    dt.datetime(2026, 1, 3),
)
Y_DATA = (1.0, 3.0, 2.0)

LOCATOR_MINTICKS = 2
LOCATOR_MAXTICKS = 5

GRID_STYLE: dict[str, Any] = {
    "which": "major",
    "axis": "both",
    "color": "#b0b0b0",
    "linestyle": "-",
    "linewidth": 0.8,
    "alpha": 1.0,
}

INPUT_CASES: dict[str, dict[str, Any]] = {
    "date-x-line": {
        "artist": "matplotlib.lines.Line2D",
        "construction": "axes.plot(datetimes, y)",
        "converter": "date",
        "locator": "matplotlib.dates.AutoDateLocator",
        "formatter": "matplotlib.dates.AutoDateFormatter",
    },
}

# These values are intentionally explicit rather than inherited from a moving
# Matplotlib default.  They are also the relevant rcParams recorded in the
# manifest.  The Figure/Line2D/grid constructors repeat the style values
# whose public artist getters are part of the adapter eligibility contract.
RC_PARAMS: dict[str, Any] = {
    "agg.path.chunksize": 0,
    "axes.axisbelow": "line",
    "axes.edgecolor": "black",
    "axes.facecolor": "none",
    "axes.grid": True,
    "axes.grid.which": "major",
    "axes.linewidth": 0.8,
    "figure.dpi": EFFECTIVE_DPI,
    "figure.edgecolor": "white",
    "figure.facecolor": "white",
    "font.family": ["DejaVu Sans"],
    "font.size": 10.0,
    "grid.alpha": GRID_STYLE["alpha"],
    "grid.color": GRID_STYLE["color"],
    "grid.linestyle": GRID_STYLE["linestyle"],
    "grid.linewidth": GRID_STYLE["linewidth"],
    "lines.antialiased": True,
    "lines.color": "red",
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
    "xtick.labelsize": 10.0,
    "xtick.major.pad": 3.5,
    "xtick.major.size": 3.5,
    "xtick.major.width": 0.8,
    "ytick.labelsize": 10.0,
    "ytick.major.pad": 3.5,
    "ytick.major.size": 3.5,
    "ytick.major.width": 0.8,
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


def build_fixture_figure() -> tuple[Figure, Any, Line2D]:
    """Build the exact fixed Figure/date-line input used by every test path."""

    figure = Figure(
        figsize=FIGSIZE_INCHES,
        dpi=EFFECTIVE_DPI,
        facecolor="white",
        edgecolor="white",
    )
    axes = figure.add_axes(AXES_RECT)
    axes.set_facecolor("none")
    # ``Axes.plot`` registers the date unit converter on the x axis; the
    # pinned locator then resolves ticks from the converted day floats.
    (line,) = axes.plot(
        list(INPUT_DATES),
        list(Y_DATA),
        color=LINE_STYLE["color"],
        linewidth=LINE_STYLE["linewidth"],
        solid_capstyle=LINE_STYLE["solid_capstyle"],
        solid_joinstyle=LINE_STYLE["solid_joinstyle"],
    )
    axes.set_xlim(*XLIM_DATES)
    axes.set_ylim(*YLIM)
    axes.xaxis.set_major_locator(
        AutoDateLocator(minticks=LOCATOR_MINTICKS, maxticks=LOCATOR_MAXTICKS)
    )
    axes.grid(
        True,
        which=GRID_STYLE["which"],
        axis=GRID_STYLE["axis"],
        color=GRID_STYLE["color"],
        linestyle=GRID_STYLE["linestyle"],
        linewidth=GRID_STYLE["linewidth"],
        alpha=GRID_STYLE["alpha"],
    )
    return figure, axes, line


def fixture_rc_context():
    """Return the pinned public Matplotlib rc-context used by the fixture."""

    return matplotlib.rc_context(RC_PARAMS)


def _visible_label_texts(axis: Any) -> list[str]:
    """Return visible non-empty major label strings in draw order, x first."""

    texts = []
    for tick in axis.get_major_ticks():
        for label in (tick.label1, tick.label2):
            if label.get_visible() and label.get_text() != "":
                texts.append(str(label.get_text()))
    return texts


def public_date_topology(line: Line2D, axes: Any) -> dict[str, Any]:
    """Return conversion/locator/formatter/geometry facts from public getters.

    The figure must have been drawn (the reference render draws it) so the
    locator/formatter results are the Figure-authoritative outputs Agg used.
    """

    # LP-MPL-022: the ``orig=False`` view is the publicly converted numeric
    # data both Agg and the adapter consume; the raw route hands back
    # datetime objects that the finite filter must refuse.
    converted_x = [float(value) for value in line.get_xdata(orig=False)]
    converted_y = [float(value) for value in line.get_ydata(orig=False)]
    segments = list(line.get_path().iter_segments(remove_nans=True))
    codes = [int(code) for _vertices, code in segments]
    vertices = [
        [float(value) for value in np.asarray(segment_vertices).reshape(-1)]
        for segment_vertices, _code in segments
    ]
    moveto = int(MatplotlibPath.MOVETO)
    lineto = int(MatplotlibPath.LINETO)
    data = np.column_stack(
        [
            np.asarray(converted_x, dtype=float),
            np.asarray(converted_y, dtype=float),
        ]
    )
    display = axes.transData.transform(data)
    display_vertices = [
        [float(value) for value in row] for row in np.asarray(display)
    ]
    locator = axes.xaxis.get_major_locator()
    x_formatter = axes.xaxis.get_major_formatter()
    y_formatter = axes.yaxis.get_major_formatter()
    x_locs = [float(value) for value in axes.xaxis.get_ticklocs()]
    y_locs = [float(value) for value in axes.yaxis.get_ticklocs()]
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
    grid = {
        side: [
            {
                "visible": bool(gridline.get_visible()),
                "linestyle": str(gridline.get_linestyle()),
                "linewidth": float(gridline.get_linewidth()),
                "color": list(
                    float(value)
                    for value in to_rgba(gridline.get_color())
                ),
            }
            for gridline in axis.get_gridlines()
            if gridline.get_visible()
        ]
        for side, axis in (("x", axes.xaxis), ("y", axes.yaxis))
    }
    return {
        "line_api": "line.get_xdata(orig=False)/line.get_ydata(orig=False)",
        "input_dates_iso": [value.isoformat() for value in INPUT_DATES],
        "converted_x": converted_x,
        "converted_y": converted_y,
        "conversion_cross_check": {
            "api": "matplotlib.dates.date2num(input_dates)",
            "date2num": [
                float(value) for value in date2num(list(INPUT_DATES))
            ],
        },
        "converter": type(axes.xaxis.get_converter()).__name__,
        "segment_count": len(segments),
        "subpath_count": sum(code == moveto for code in codes),
        "moveto_count": sum(code == moveto for code in codes),
        "lineto_count": sum(code == lineto for code in codes),
        "segment_codes": codes,
        "vertices": vertices,
        "scales": {"x": XSCALE, "y": YSCALE},
        "limits": {
            "xlim_iso": [value.isoformat() for value in XLIM_DATES],
            "xlim_converted": [float(value) for value in date2num(list(XLIM_DATES))],
            "ylim": list(YLIM),
        },
        "locator": {
            "class": type(locator).__name__,
            "api": "axis.get_major_locator",
            "minticks": int(locator.minticks),
            "maxticks": {
                str(key): int(value)
                for key, value in dict(locator.maxticks).items()
            },
        },
        "formatters": {
            "x": type(x_formatter).__name__,
            "y": type(y_formatter).__name__,
            "api": "axis.get_major_formatter",
        },
        "xticklocs": x_locs,
        "xticklabels": _visible_label_texts(axes.xaxis),
        "yticklocs": y_locs,
        "yticklabels": _visible_label_texts(axes.yaxis),
        "grid": grid,
        "spines": spines,
        "display_api": "axes.transData.transform(converted_data)",
        "display_vertices": display_vertices,
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

    Background and fully covered pixels (figure face, the red content
    stroke, black spine/tick/glyph ink, and the resolved gray grid stroke)
    must compare byte-exact; every other reference pixel is antialiased
    fringe under the fixed S15.1 gate.
    """

    background = _rgba8(figure.get_facecolor())
    stroke = _rgba8(LINE_STYLE["color"])
    ink = _rgba8(SPINE_STYLE["edgecolor"])
    grid = _rgba8(GRID_STYLE["color"])
    background_pixels = np.all(rgba == background, axis=2)
    fully_covered_pixels = (
        np.all(rgba == stroke, axis=2)
        | np.all(rgba == ink, axis=2)
        | np.all(rgba == grid, axis=2)
    )
    fringe_pixels = ~(background_pixels | fully_covered_pixels)
    labels = np.full(
        rgba.shape[:2],
        PIXEL_CLASS_CODES["antialias-fringe"],
        dtype=np.uint8,
    )
    labels[background_pixels] = PIXEL_CLASS_CODES["background"]
    labels[fully_covered_pixels] = PIXEL_CLASS_CODES["fully-covered"]

    # The candidate/native image is deliberately not an input to this
    # operation.
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
        figure, axes, line = build_fixture_figure()
        canvas = FigureCanvasAgg(figure)
        buffer = io.BytesIO()
        # Direct FigureCanvasAgg.print_png is the pinned oracle operation.
        canvas.print_png(buffer, metadata={})
        reference_png = buffer.getvalue()
        decoded = decode_png_rgba8(reference_png)
        topology = public_date_topology(line, axes)
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
        "fixture_id": "date-axis-converted-line-decorated",
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
                "xscale": XSCALE,
                "yscale": YSCALE,
                "xlim_iso": [value.isoformat() for value in XLIM_DATES],
                "ylim": list(YLIM),
                "line_construction": (
                    "axes.plot([datetime(2026, 1, 1), datetime(2026, 1, 2), "
                    "datetime(2026, 1, 3)], [1.0, 3.0, 2.0], color='red', "
                    "linewidth=2.0, solid_capstyle='butt', "
                    "solid_joinstyle='miter')"
                ),
                "locator_construction": (
                    "axes.xaxis.set_major_locator("
                    "matplotlib.dates.AutoDateLocator(minticks=2, maxticks=5))"
                ),
                "grid_construction": (
                    "axes.grid(True, which='major', axis='both', "
                    "color='#b0b0b0', linestyle='-', linewidth=0.8, alpha=1.0)"
                ),
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
        "artist_class": "matplotlib.lines.Line2D",
        "secondary_classes": [
            "matplotlib.text.Text",
            "matplotlib.spines.Spine",
        ],
        "primitive": {
            "class": "matplotlib.lines.Line2D",
            "style": LINE_STYLE,
            "scales": {"x": XSCALE, "y": YSCALE},
            "locator": {
                "class": "matplotlib.dates.AutoDateLocator",
                "minticks": LOCATOR_MINTICKS,
                "maxticks": LOCATOR_MAXTICKS,
            },
            "formatters": {
                "x": "matplotlib.dates.AutoDateFormatter",
                "y": "matplotlib.ticker.ScalarFormatter",
            },
            "grid": dict(GRID_STYLE),
            "input_data": {
                "dates_iso": [value.isoformat() for value in INPUT_DATES],
                "y": [float(value) for value in Y_DATA],
                "cases": INPUT_CASES,
            },
        },
        "input_data": {
            "dates_iso": [value.isoformat() for value in INPUT_DATES],
            "y": [float(value) for value in Y_DATA],
            "xlim_iso": [value.isoformat() for value in XLIM_DATES],
            "ylim": list(YLIM),
            "cases": INPUT_CASES,
        },
        "topology": topology,
        "mask_generation": (
            "reference-only: figure facecolor plus resolved red stroke, "
            "black spine/tick/glyph ink, and gray grid stroke; "
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
