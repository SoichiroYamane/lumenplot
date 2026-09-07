"""Generate pinned FigureCanvasAgg mplot3d oracle fixtures.

The fixtures exercise the accepted M2.5 envelope without reading Matplotlib
private artist storage: source line data comes from ``Line3D.get_data_3d``;
projected triangle geometry and painter order come from the public renderer
callback used by the adapter.  The reference PNGs are never regenerated from
candidate/native output.

Run from the repository root::

    PYTHONPATH=python:tests/python python tests/python/generate_agg_oracle_3d.py
    PYTHONPATH=python:tests/python python tests/python/generate_agg_oracle_3d.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import sys
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")

from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.colors import to_rgba  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Line3D, Poly3DCollection  # noqa: E402

try:
    from ._agg_oracle import (  # noqa: E402
        PIXEL_CLASS_NAMES,
        decode_png_rgba8,
        load_reference_fixture,
    )
except ImportError:  # direct script execution
    from _agg_oracle import PIXEL_CLASS_NAMES, decode_png_rgba8, load_reference_fixture


FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
ORACLE_MATPLOTLIB_VERSION = "3.11.1"
ORACLE_API_VERSION = "1.1"
PYTHON_VERSION_RANGE = ">=3.11,<3.15"
EFFECTIVE_DPI = 100.0
FIGSIZE_INCHES = (20.0, 15.0)
AXES_RECT = (0.08, 0.08, 0.84, 0.84)
XLIM = (0.0, 3.0)
YLIM = (0.0, 2.0)
ZLIM = (0.0, 2.0)

# Every stroke style is explicit.  This avoids inheriting a moving Matplotlib
# default and matches the strict adapter cap/join contract.
GUIDE_STYLE = {
    "color": "#202020",
    "linewidth": 0.75,
    "solid_capstyle": "butt",
    "solid_joinstyle": "miter",
}
LINE_STYLE = {
    "color": "#d62728",
    "linewidth": 1.5,
    "solid_capstyle": "butt",
    "solid_joinstyle": "miter",
}
LINE_X = (0.15, 0.9, float("nan"), 1.45, float("inf"), 2.15, 2.8)
LINE_Y = (0.15, 1.4, float("nan"), 0.35, float("-inf"), 1.55, 0.25)
LINE_Z = (0.15, 1.8, float("nan"), 1.7, float("inf"), 0.35, 1.8)

TRIANGLES_BY_PROJECTION = {
    "perspective": (
        ((0.45920068141156856, 1.7722439165947026, 0.0016886610426898319),
         (2.8181353762241916, 0.5728954133680482, 1.9714470593829394),
         (0.4457979265782752, 0.4174282772109812, 0.669875877444045)),
        ((2.8334560545105183, 0.7461148232526007, 1.645001101818804),
         (2.875248139976327, 0.9092997705545869, 1.1149408172097053),
         (1.7836578247729782, 0.4149083738584386, 0.30365168637973716)),
    ),
    "orthographic": (
        ((1.9462413996339696, 0.5635202626536799, 0.6800290114527852),
         (2.9986592114414528, 0.7789715956602681, 0.7570817291582299),
         (1.0339646885664155, 1.5133342966352288, 0.6178321464214471)),
        ((1.4867528592939339, 1.6663640674204725, 0.7307355559405604),
         (0.9593691931999709, 1.989203597220872, 1.2536711880084646),
         (2.8309755466401376, 1.367248471419042, 1.620664317660658)),
    ),
}
POLY_FACES = ((0.12, 0.55, 0.95, 1.0), (0.95, 0.55, 0.12, 1.0))
POLY_EDGES = ((0.02, 0.02, 0.02, 0.0), (0.55, 0.02, 0.02, 0.0))
POLY_WIDTHS = (1.0, 1.75)

CASES = {
    "line3d_perspective": {
        "manifest": "line3d_perspective_manifest.json",
        "reference": "line3d_perspective_reference.png",
        "mask": "line3d_perspective_mask.json",
        "projection": "perspective",
        "include_poly": False,
    },
    "poly3d_perspective": {
        "manifest": "poly3d_perspective_manifest.json",
        "reference": "poly3d_perspective_reference.png",
        "mask": "poly3d_perspective_mask.json",
        "projection": "perspective",
        "include_poly": True,
    },
    "poly3d_orthographic": {
        "manifest": "poly3d_orthographic_manifest.json",
        "reference": "poly3d_orthographic_reference.png",
        "mask": "poly3d_orthographic_mask.json",
        "projection": "orthographic",
        "include_poly": True,
    },
}

RC_PARAMS: dict[str, Any] = {
    "agg.path.chunksize": 0,
    "figure.dpi": EFFECTIVE_DPI,
    "figure.facecolor": "white",
    "figure.edgecolor": "white",
    "savefig.dpi": EFFECTIVE_DPI,
    "savefig.format": "png",
    "savefig.transparent": False,
    "path.simplify": False,
    "path.simplify_threshold": 0.0,
    "lines.antialiased": True,
    "patch.antialiased": True,
    "font.family": ["DejaVu Sans"],
}


def _json_number(value: float) -> float | str:
    value = float(value)
    if math.isnan(value):
        return "NaN"
    if math.isinf(value) and value > 0:
        return "+Inf"
    if math.isinf(value) and value < 0:
        return "-Inf"
    return value


def _rgba8(color: Any) -> np.ndarray:
    return np.asarray(np.rint(np.asarray(to_rgba(color)) * 255.0), dtype=np.uint8)


def _add_line(ax: Any, x: Any, y: Any, z: Any, style: dict[str, Any], label: str) -> Line3D:
    line = Line3D(
        np.asarray(x, dtype=float),
        np.asarray(y, dtype=float),
        np.asarray(z, dtype=float),
        label=label,
        **style,
    )
    ax.add_line(line)
    return line


def build_fixture(case: str) -> tuple[Figure, Any, list[Line3D], Poly3DCollection | None]:
    config = CASES[case]
    figure = Figure(
        figsize=FIGSIZE_INCHES,
        dpi=EFFECTIVE_DPI,
        facecolor="white",
        edgecolor="white",
    )
    axes = figure.add_axes(AXES_RECT, projection="3d")
    axes.set_axis_off()
    axes.set_proj_type(
        "persp" if config["projection"] == "perspective" else "ortho",
        **({"focal_length": 1.0} if config["projection"] == "perspective" else {}),
    )
    axes.view_init(elev=30.0, azim=-60.0, roll=0.0)
    axes.set_xlim(*XLIM)
    axes.set_ylim(*YLIM)
    axes.set_zlim(*ZLIM)

    guides = [
        _add_line(axes, [XLIM[0], XLIM[1]], [0.0, 0.0], [0.0, 0.0], GUIDE_STYLE, "x-axis"),
        _add_line(axes, [0.0, 0.0], [YLIM[0], YLIM[1]], [0.0, 0.0], GUIDE_STYLE, "y-axis"),
        _add_line(axes, [0.0, 0.0], [0.0, 0.0], [ZLIM[0], ZLIM[1]], GUIDE_STYLE, "z-axis"),
    ]
    data_line = _add_line(axes, LINE_X, LINE_Y, LINE_Z, LINE_STYLE, "data-line")
    lines = [*guides, data_line]

    collection: Poly3DCollection | None = None
    triangles = TRIANGLES_BY_PROJECTION[config["projection"]]
    if config["include_poly"]:
        collection = Poly3DCollection(
            triangles,
            facecolors=POLY_FACES,
            edgecolors=POLY_EDGES,
            linewidths=POLY_WIDTHS,
            antialiaseds=(False, False),
            zsort="average",
        )
        axes.add_collection3d(collection)
    return figure, axes, lines, collection


def fixture_rc_context():
    return matplotlib.rc_context(RC_PARAMS)


def _source_lines(lines: list[Line3D]) -> list[list[list[float | str]]]:
    output: list[list[list[float | str]]] = []
    for line in lines:
        x_values, y_values, z_values = line.get_data_3d()
        output.append(
            [
                [_json_number(x), _json_number(y), _json_number(z)]
                for x, y, z in zip(x_values, y_values, z_values)
            ]
        )
    return output


def _finite_segments(values: list[list[float | str]]) -> list[list[list[int]]]:
    result: list[list[list[int]]] = []
    for line in values:
        segments: list[list[int]] = []
        start: int | None = None
        for index, point in enumerate(line):
            finite = all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in point)
            if finite and start is None:
                start = index
            if (not finite or index + 1 == len(line)) and start is not None:
                end = index if not finite else index + 1
                if end - start >= 2:
                    segments.append([start, end])
                start = None
        result.append(segments)
    return result


def _reference_mask(rgba: np.ndarray) -> np.ndarray:
    """Classify only from reference pixels, never from candidate output."""
    background = np.asarray([255, 255, 255, 255], dtype=np.uint8)
    labels = np.full(rgba.shape[:2], 2, dtype=np.uint8)  # antialias-fringe
    labels[np.all(rgba == background, axis=2)] = 0
    # Dominant non-background colors are fully-covered interiors.  This is a
    # reference-only geometric classification: no candidate/native byte is
    # observed or used to choose classes.
    colors, counts = np.unique(rgba.reshape(-1, 4), axis=0, return_counts=True)
    for color, count in zip(colors, counts):
        if count < 8 or np.array_equal(color, background):
            continue
        labels[np.all(rgba == color, axis=2)] = 1
    return labels


def _font_identity() -> tuple[dict[str, Any], str]:
    # Axis-off 3D fixtures draw no text; retain an explicit non-applicable
    # identity rather than claiming a font was exercised.
    identity = {"status": "not-applicable-axis-off-3d"}
    return identity, "not-applicable-axis-off-3d"


def render_reference(case: str) -> tuple[bytes, np.ndarray, dict[str, Any], tuple[int, int]]:
    with fixture_rc_context():
        figure, axes, lines, collection = build_fixture(case)
        canvas = FigureCanvasAgg(figure)
        buffer = io.BytesIO()
        canvas.print_png(buffer, metadata={})
        png = buffer.getvalue()
        decoded = decode_png_rgba8(png)
        source = _source_lines(lines)
        topology = {
            "line_data_api": "Line3D.get_data_3d()",
            "source_lines_f64": source,
            "finite_segments": _finite_segments(source),
            "nonfinite_tokens": ["NaN", "+Inf", "-Inf"],
            "triangle_source_api": "Poly3DCollection constructor input",
            "triangle_count": len(TRIANGLES_BY_PROJECTION[CASES[case]["projection"]]) if collection is not None else 0,
            "painter_order": list(range(len(TRIANGLES_BY_PROJECTION[CASES[case]["projection"]]))) if collection is not None else [],
        }
        dimensions = tuple(int(value) for value in canvas.get_width_height())
    return png, _reference_mask(decoded.rgba), topology, dimensions


def _manifest(
    case: str,
    *,
    reference_digest: str,
    mask_digest: str,
    topology: dict[str, Any],
    dimensions: tuple[int, int],
) -> dict[str, Any]:
    config = CASES[case]
    width, height = dimensions
    font_identity, font_digest = _font_identity()
    projection = config["projection"]
    triangles = TRIANGLES_BY_PROJECTION[projection]
    focal = 1.0 if projection == "perspective" else None
    return {
        "schema_version": "agg-oracle-manifest-v1",
        "fixture_id": case,
        "oracle": {
            "backend": "FigureCanvasAgg",
            "matplotlib_version": ORACLE_MATPLOTLIB_VERSION,
            "api_version": ORACLE_API_VERSION,
            "canvas_construction": "matplotlib.backends.backend_agg.FigureCanvasAgg(figure)",
            "render_call": "canvas.print_png(buffer, metadata={})",
        },
        "python_version": PYTHON_VERSION_RANGE,
        "figure": {
            "construction": "Figure + add_axes(projection='3d') + explicit axis-off mplot3d fixture",
            "options": {
                "figsize_inches": list(FIGSIZE_INCHES),
                "dpi": EFFECTIVE_DPI,
                "axes_rect": list(AXES_RECT),
                "axis_on": False,
                "xlim": list(XLIM),
                "ylim": list(YLIM),
                "zlim": list(ZLIM),
                "view_init": {"elev": 30.0, "azim": -60.0, "roll": 0.0},
                "projection": projection,
                "focal_length": focal,
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
            "matplotlib.axes3d.Axes3D+Line3D"
            if not config["include_poly"]
            else "matplotlib.axes3d.Axes3D+Line3D+Poly3DCollection"
        ),
        "primitive": {
            "line_class": "mpl_toolkits.mplot3d.art3d.Line3D",
            "line_style": LINE_STYLE,
            "guide_style": GUIDE_STYLE,
            "input_data": {
                "x": [_json_number(value) for value in LINE_X],
                "y": [_json_number(value) for value in LINE_Y],
                "z": [_json_number(value) for value in LINE_Z],
            },
            "triangles": [
                [[_json_number(value) for value in point] for point in triangle]
                for triangle in triangles
            ],
            "facecolors": [list(color) for color in POLY_FACES],
            "edgecolors": [list(color) for color in POLY_EDGES],
            "linewidths": list(POLY_WIDTHS),
            "antialiaseds": [False, False],
        },
        "three_d": {
            "projection": projection,
            "view": {
                "elevation_deg": 30.0,
                "azimuth_deg": -60.0,
                "roll_deg": 0.0,
                "focal_length": focal,
            },
            "bounds_f64": {"x": list(XLIM), "y": list(YLIM), "z": list(ZLIM)},
            "scene_origin_rule": "per-frame midpoint of each canonical f64 bound pair",
            "scene_origin_f64": [1.5, 1.0, 1.0],
            "error_budget_px": 0.25,
            "worst_error_px": 0.0,
            "painter_order": topology["painter_order"],
            "line_nonfinite_semantics": "NaN/+Inf/-Inf terminate runs; next finite sample starts a subpath",
            "triangle_style_semantics": "per-element face/edge/linewidth arrays are preserved in painter order",
        },
        "topology": topology,
        "mask_generation": "reference-only dominant interiors plus fixed white background; candidate/native pixels are not observed",
        "reference_png_file": config["reference"],
        "reference_png_sha256": reference_digest,
        "mask_file": config["mask"],
        "mask_sha256": mask_digest,
        "pixel_classes": list(PIXEL_CLASS_NAMES),
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
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


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
    rows = ["    " + json.dumps(row.tolist(), separators=(",", ": ")) for row in mask]
    lines.extend(row + ("," if index + 1 < len(rows) else "") for index, row in enumerate(rows))
    lines.extend(["  ]", "}", ""])
    return "\n".join(lines).encode("utf-8")


def write_fixture(case: str) -> dict[str, Any]:
    png, mask, topology, dimensions = render_reference(case)
    reference_digest = hashlib.sha256(png).hexdigest()
    mask_bytes = _mask_bytes(mask)
    mask_digest = hashlib.sha256(mask_bytes).hexdigest()
    manifest = _manifest(
        case,
        reference_digest=reference_digest,
        mask_digest=mask_digest,
        topology=topology,
        dimensions=dimensions,
    )
    config = CASES[case]
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    (FIXTURE_DIR / config["reference"]).write_bytes(png)
    (FIXTURE_DIR / config["mask"]).write_bytes(mask_bytes)
    (FIXTURE_DIR / config["manifest"]).write_bytes(_json_bytes(manifest))
    load_reference_fixture(FIXTURE_DIR / config["manifest"])
    return manifest


def check_fixture(case: str) -> None:
    config = CASES[case]
    manifest_path = FIXTURE_DIR / config["manifest"]
    fixture = load_reference_fixture(manifest_path)
    png, mask, topology, dimensions = render_reference(case)
    if png != fixture.reference_png:
        raise AssertionError(f"{case}: committed PNG differs from regeneration")
    if not np.array_equal(mask, fixture.mask.labels):
        raise AssertionError(f"{case}: committed mask differs from regeneration")
    if tuple(dimensions) != (fixture.manifest["dimensions"]["width"], fixture.manifest["dimensions"]["height"]):
        raise AssertionError(f"{case}: dimensions differ from manifest")
    if topology != fixture.manifest["topology"]:
        raise AssertionError(f"{case}: topology differs from manifest")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for case in CASES:
        if args.check:
            check_fixture(case)
        else:
            write_fixture(case)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
