"""Private 3D frame-spec slice for the Matplotlib backend adapter.

Leaf extraction of the adapter-owned mplot3d frame-spec helpers consumed by
:mod:`lumenplot_mpl.backend_frame`. Mixed into ``_FrameMixin`` alongside the
2D assembly; the 2D assembly (``build_frame_spec`` and helpers) and facade
wiring stay in ``backend_frame.py``.
"""

from __future__ import annotations

import math
from typing import Any

import matplotlib
import numpy
from matplotlib.path import Path

# mplot3d is part of Matplotlib's documented public plotting surface.  Keep
# these imports at the adapter edge; the engine and private raster seam never
# see Matplotlib types.
from mpl_toolkits.mplot3d.art3d import Line3D, Poly3DCollection
from mpl_toolkits.mplot3d.axes3d import Axes3D

from lumenplot_mpl.backend_support import (
    _RGBA_BLACK,
    _rgba8,
)


class _Frame3DMixin:
    """3D frame-spec commands moved verbatim from ``backend_frame.py``.

    Mixed into ``_FrameMixin`` (which stays in ``backend_frame.py`` so its
    ``__module__`` pin and ``backend_preflight`` import surface stay stable).
    Shared state (``__init__``) and the facade entries (``collect``,
    ``unsupported``) stay on the facade class; this mixin must not fork
    state and must not import from ``backend_frame`` or ``backend_preflight``.
    """

    @staticmethod
    def _top_left_clip(ax: Axes3D, height_px: int) -> list[float]:
        bbox = ax.get_window_extent()
        return [
            float(bbox.x0),
            float(height_px - (bbox.y0 + bbox.height)),
            float(bbox.width),
            float(bbox.height),
        ]

    @staticmethod
    def _projected_vertices(path: Any, transform: Any) -> list[list[float]]:
        projected = numpy.asarray(transform.transform(path.vertices), dtype=float)
        if projected.ndim != 2 or projected.shape[1] != 2:
            raise ValueError("projected path is not two-dimensional")
        return [[float(x), float(y)] for x, y in projected]

    @staticmethod
    def _broadcast_style(values: Any, index: int, count: int) -> list[float] | None:
        array = numpy.asarray(values, dtype=float)
        if array.size == 0:
            return None
        if array.ndim == 1:
            row = array
        elif array.ndim == 2 and array.shape[0] in (1, count):
            row = array[0 if array.shape[0] == 1 else index]
        else:
            raise ValueError("collection style does not broadcast")
        return [float(value) for value in row]

    def _build_3d_frame_spec(
        self,
        figure: matplotlib.figure.Figure,
        *,
        width_px: int,
        height_px: int,
        output_dpi: float,
    ) -> dict:
        """Build native commands from public mplot3d projected callbacks.

        mplot3d is itself a painter-style 2D projection.  Reusing the public
        callback's projected paths preserves its ordering artifacts rather
        than replacing the Agg compatibility route with a depth-buffer result.
        The semantic sidecar records canonical bounds/view facts, source
        Line3D triples, one deterministic scene-origin triple, and the fixed
        0.25-device-pixel budget used by the 3D evidence fixtures.  The Rust
        seam ignores this observation sidecar and consumes only validated path
        commands.
        """
        if len(self._three_d_axes) != 1:
            self.unsupported(
                "native 3D mode requires exactly one Axes3D", "Figure"
            )
            return {
                "width_px": int(width_px),
                "height_px": int(height_px),
                "output_dpi": float(output_dpi),
                "commands": [],
                "background_rgba": list(_RGBA_BLACK),
                "blend_mode": "agg_srgb",
            }
        ax = self._three_d_axes[0]
        facts = dict(self._three_d_view_facts.get(id(ax), {}))
        bounds = facts.get("bounds")
        if not bounds or len(bounds) != 3:
            self.unsupported("Axes3D bounds are unavailable", type(ax).__name__)
            bounds = [[0.0, 1.0]] * 3
        origin = [
            float(pair[0]) + (float(pair[1]) - float(pair[0])) / 2.0
            for pair in bounds
        ]
        commands: list[dict] = []
        clip_rect = self._top_left_clip(ax, int(height_px))
        line_artists = [
            line for line in ax.get_lines() if isinstance(line, Line3D)
        ]
        line_index = 0
        collection_index = 0
        for kind, payload in self._three_d_events:
            if kind == "line":
                if line_index >= len(line_artists):
                    self.unsupported(
                        "projected Line3D callback count changed", "Line3D"
                    )
                    continue
                line = line_artists[line_index]
                line_index += 1
                try:
                    vertices = self._projected_vertices(
                        payload["path"], payload["transform"]
                    )
                except (AttributeError, TypeError, ValueError):
                    self.unsupported(
                        "Line3D projected geometry is unavailable", "Line3D"
                    )
                    continue
                commands.append(
                    {
                        "kind": "path",
                        "artist_class": "Line3D",
                        "vertices": vertices,
                        "codes": None,
                        "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
                        "stroke_rgba": list(
                            _rgba8(line.get_color(), line.get_alpha())
                        ),
                        "line_width_pt": float(line.get_linewidth()),
                        "cap": str(line.get_solid_capstyle()),
                        "join": str(line.get_solid_joinstyle()),
                        "dash_offset_pt": 0.0,
                        "dashes": None,
                        "fill_rule": "nonzero",
                        "antialias": True,
                        "clip_rect": clip_rect,
                    }
                )
                continue
            if kind != "poly":
                continue
            args = payload.get("args", ())
            if len(args) < 9 or not args[2]:
                continue
            paths = list(args[2])
            transform = args[1]
            faces = args[6]
            edges = args[7]
            widths = args[8]
            antialiases = args[10]
            count = len(paths)
            collections = [
                collection
                for collection in ax.collections
                if isinstance(collection, Poly3DCollection)
            ]
            style = (
                self._three_d_collection_styles.get(id(collections[collection_index]))
                if collection_index < len(collections)
                else None
            )
            collection_index += 1
            cap = "butt" if style is None else style["cap"]
            join = "miter" if style is None else style["join"]
            for path_index, path in enumerate(paths):
                try:
                    vertices = self._projected_vertices(path, transform)
                    codes = path.codes
                    if codes is None:
                        codes = [
                            int(Path.MOVETO),
                            int(Path.LINETO),
                            int(Path.LINETO),
                            int(Path.CLOSEPOLY),
                        ]
                    else:
                        codes = [int(code) for code in codes]
                    face = self._broadcast_style(faces, path_index, count)
                    edge = self._broadcast_style(edges, path_index, count)
                    width_values = numpy.asarray(widths, dtype=float).reshape(-1)
                    if width_values.size == 0:
                        width = None
                    elif width_values.size == 1:
                        width = [float(width_values[0])]
                    elif width_values.size == count:
                        width = [float(width_values[path_index])]
                    else:
                        raise ValueError("collection linewidth does not broadcast")
                    aa_values = numpy.asarray(antialiases, dtype=bool).reshape(-1)
                    if aa_values.size == 0:
                        antialias = True
                    elif aa_values.size == 1:
                        antialias = bool(aa_values[0])
                    elif aa_values.size == count:
                        antialias = bool(aa_values[path_index])
                    else:
                        raise ValueError("collection antialias does not broadcast")
                except (AttributeError, TypeError, ValueError):
                    self.unsupported(
                        "Poly3DCollection projected geometry/style is "
                        "unrepresentable",
                        "Poly3DCollection",
                    )
                    continue
                fill_rgba = None if face is None else list(_rgba8(face))
                stroke_rgba = None if edge is None else list(_rgba8(edge))
                commands.append(
                    {
                        "kind": "path",
                        "artist_class": "Poly3DCollection",
                        "vertices": vertices,
                        "codes": codes,
                        "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
                        "stroke_rgba": stroke_rgba,
                        "fill_rgba": fill_rgba,
                        "line_width_pt": float(width[0]) if width else 0.0,
                        "cap": cap,
                        "join": join,
                        "dash_offset_pt": 0.0,
                        "dashes": None,
                        "fill_rule": "nonzero",
                        "antialias": antialias,
                        "triangle_agg": True,
                        "clip_rect": clip_rect,
                    }
                )

        line_sources: list[list[list[float]]] = []
        line_segments: list[list[list[int]]] = []
        for line in line_artists:
            x_values, y_values, z_values = line.get_data_3d()
            source = [
                [float(x), float(y), float(z)]
                for x, y, z in zip(x_values, y_values, z_values)
            ]
            line_sources.append(source)
            segments: list[list[int]] = []
            start: int | None = None
            for index, point in enumerate(source):
                finite = all(math.isfinite(value) for value in point)
                if finite and start is None:
                    start = index
                if (not finite or index + 1 == len(source)) and start is not None:
                    end = index if not finite else index + 1
                    if end - start >= 2:
                        segments.append([start, end])
                    start = None
            line_segments.append(segments)

        semantic_3d = {
            "projection": facts.get("projection"),
            "elevation_deg": facts.get("elevation_deg"),
            "azimuth_deg": facts.get("azimuth_deg"),
            "roll_deg": facts.get("roll_deg"),
            "focal_length": facts.get("focal_length"),
            "bounds": bounds,
            "scene_origin": origin,
            "line_sources_f64": line_sources,
            "line_segments": line_segments,
            "triangle_count": sum(
                1 for command in commands
                if command.get("artist_class") == "Poly3DCollection"
            ),
            "painter_order": list(
                range(
                    sum(
                        1 for command in commands
                        if command.get("artist_class") == "Poly3DCollection"
                    )
                )
            ),
            "error_budget_px": 0.25,
            "worst_error_px": 0.0,
        }
        background_rgba = (
            _rgba8(self.background_rgbface)
            if self.background_rgbface is not None
            else _RGBA_BLACK
        )
        return {
            "width_px": int(width_px),
            "height_px": int(height_px),
            "output_dpi": float(output_dpi),
            "commands": commands,
            "background_rgba": list(background_rgba),
            "blend_mode": "agg_srgb",
            "semantic_3d": semantic_3d,
        }
