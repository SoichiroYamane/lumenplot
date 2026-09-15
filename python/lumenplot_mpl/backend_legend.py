"""Private legend-lane checks and payload assembly for the backend."""

from __future__ import annotations

import math
from typing import Any

import matplotlib
import matplotlib.legend  # noqa: F401 - public submodule for the whitelist
from matplotlib.path import Path

from lumenplot_mpl.backend_support import (
    _finite,
    _rgba8,
)


class _LegendMixin:
    """Legend collector-side validation and payload assembly (PRAC-A-L).

    Mixed into ``_EligibilityPreflight`` (which stays in
    ``backend_preflight.py`` so its ``__module__`` pin stays stable).
    Shared state (``__init__``) and shared checks (``unsupported``,
    ``_check_stroke_common``) stay on the facade class; this mixin must
    not fork state and must not import from ``backend_preflight``.
    """

    def _check_legend_gc(self, gc: Any, *, frame: bool) -> None:
        """Re-check the legend stroke surface at callback time.

        Static artist properties can change after stage one, so the
        collected graphics context is checked independently before its
        values reach the native seam.
        """
        width = float(gc.get_linewidth())
        if not math.isfinite(width) or width <= 0.0:
            self.unsupported(
                "legend stroke width must be finite and positive", "Legend"
            )
        if gc.get_dashes()[1] is not None:
            self.unsupported(
                "dashed strokes are unsupported in strict mode", "Legend"
            )
        if gc.get_hatch() is not None:
            self.unsupported("hatching is unsupported in strict mode", "Legend")
        if gc.get_sketch_params() is not None:
            self.unsupported("sketch parameters are unsupported", "Legend")
        expected_snap = True if frame else None
        if gc.get_snap() is not expected_snap:
            self.unsupported(
                "legend stroke snap differs from the fixed style surface",
                "Legend",
            )
        if not bool(gc.get_antialiased()):
            self.unsupported("legend stroke antialiasing is required", "Legend")
        if str(gc.get_capstyle()) != "butt":
            self.unsupported("legend stroke cap style must be 'butt'", "Legend")
        if str(gc.get_joinstyle()) != "miter":
            self.unsupported(
                "legend stroke join style must be 'miter'", "Legend"
            )
        if gc.get_clip_rectangle() is not None:
            self.unsupported(
                "legend strokes cannot carry a clip rectangle", "Legend"
            )
        if gc.get_clip_path() != (None, None):
            self.unsupported("legend strokes cannot carry a custom clip", "Legend")
        try:
            rgba = tuple(float(value) for value in gc.get_rgb())
        except (TypeError, ValueError):
            rgba = ()
        if len(rgba) != 4 or any(
            not math.isfinite(value) or not 0.0 <= value <= 1.0
            for value in rgba
        ):
            self.unsupported("legend stroke color must be finite RGBA", "Legend")

    def _check_legend_frame_call(self, call: dict) -> None:
        """Validate one collected legend-frame stroke (PRAC-A-L).

        The rounded ``FancyBboxPatch`` frame arrives already transformed
        into display space by Matplotlib's own legend layout: an affine
        transform, a filled path with curve-capable codes, and no clip.
        The fill/stroke style surface was checked statically; only the
        geometric shape contract is enforced here so the assembly below
        never consumes an unexpected path shape.
        """
        transform = call["transform"]
        if not bool(call.get("affine", True)):
            self.unsupported(
                "the legend frame carries a non-affine transform",
                "Legend",
            )
            return
        identity = (
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
        )
        try:
            matrix = transform.get_matrix()
            is_identity = all(
                math.isfinite(float(matrix[row][column]))
                and abs(float(matrix[row][column]) - identity[row][column])
                <= 1.0e-12
                for row in range(3)
                for column in range(3)
            )
        except (AttributeError, IndexError, TypeError, ValueError):
            is_identity = False
        if not is_identity:
            self.unsupported(
                "the legend frame transform is not identity display space",
                "Legend",
            )
            return
        path = call["path"]
        codes = path.codes
        if codes is None or not len(codes):
            self.unsupported(
                "the legend frame outline is not a closed loop", "Legend"
            )
            return
        code_values = {int(code) for code in codes}
        allowed = {
            int(Path.MOVETO),
            int(Path.LINETO),
            int(Path.CURVE3),
            int(Path.CLOSEPOLY),
            0,
        }
        if not code_values <= allowed:
            self.unsupported(
                "the legend frame outline contains unsupported segments",
                "Legend",
            )
            return
        real_points = sum(
            1 for code in codes if int(code) != int(Path.CLOSEPOLY)
        )
        if real_points < 3:
            self.unsupported("degenerate legend frame path", "Legend")
            return
        gc = call["gc"]
        self._check_legend_gc(gc, frame=True)
        if int(codes[0]) != int(Path.MOVETO) or int(codes[-1]) != int(Path.CLOSEPOLY):
            self.unsupported(
                "the legend frame outline is not a closed rounded path",
                "Legend",
            )
        if any(
            not _finite(float(value))
            for vertex in path.vertices
            for value in vertex
        ):
            self.unsupported("non-finite legend frame geometry", "Legend")
        rgb_face = call.get("rgbFace")
        try:
            face_values = tuple(float(value) for value in rgb_face)
        except (TypeError, ValueError):
            face_values = ()
        if len(face_values) != 4 or any(
            not _finite(value) or not 0.0 <= value <= 1.0
            for value in face_values
        ):
            self.unsupported("legend frame facecolor must be finite RGBA", "Legend")

    def _check_legend_handle_call(self, call: dict) -> None:
        """Validate one collected legend handle stroke (PRAC-A-L)."""
        if not bool(call.get("affine", True)):
            self.unsupported(
                "a legend handle carries a non-affine transform",
                "Legend",
            )
            return
        self._check_legend_gc(call["gc"], frame=False)
        path = call["path"]
        vertices = path.vertices
        if len(vertices) < 2:
            self.unsupported("degenerate single-vertex stroke", "Legend")
        if any(
            not _finite(float(value))
            for vertex in vertices
            for value in vertex
        ):
            self.unsupported("non-finite legend handle geometry", "Legend")
        codes = path.codes
        if codes is not None and len(codes):
            allowed = {
                int(Path.MOVETO),
                int(Path.LINETO),
                int(Path.CLOSEPOLY),
                0,
            }
            if any(int(code) not in allowed for code in codes):
                self.unsupported(
                    "legend handle contains unsupported path segments",
                    "Legend",
                )
        transform = call["transform"]
        try:
            matrix = transform.get_matrix()
            if any(
                not _finite(float(matrix[row][column]))
                for row in range(3)
                for column in range(3)
            ):
                self.unsupported(
                    "legend handle transform contains non-finite values",
                    "Legend",
                )
        except (AttributeError, IndexError, TypeError, ValueError):
            self.unsupported(
                "legend handle transform is malformed", "Legend"
            )

    def _legend_clip(self, legend: Any) -> list[float]:
        """Return the frozen-seam clip rectangle for one legend.

        The frameless legend clips its strokes to the canvas exactly like
        the tick-label glyphs; a framed legend additionally paints inside
        its frame patch, which Agg realizes through patch clipping. The
        conservative full-canvas rectangle keeps every visible pixel of
        either case while staying inside the frozen seam's axis-aligned
        clip vocabulary (top-left origin, exclusive right/bottom edges).
        """
        del legend
        return [
            0.0,
            0.0,
            float(self._canvas_width_px),
            float(self._height_px),
        ]

    def _legend_frame_command(self, call: dict) -> dict | None:
        """Build one seam path command from the collected frame stroke."""
        path = call["path"]
        gc = call["gc"]
        rgb_face = call["rgbFace"]
        if rgb_face is None:
            # A framed legend always fills its patch; a missing facecolor
            # means the collector trace drifted from the static stage.
            self.unsupported(
                "the legend frame stroke lost its facecolor", "Legend"
            )
            return None
        edge_rgb = gc.get_rgb()
        width = float(gc.get_linewidth())
        try:
            edge_rgba8 = _rgba8(tuple(float(c) for c in edge_rgb))
        except (TypeError, ValueError):
            edge_rgba8 = None
        explicit_edge = (
            tuple(float(c) for c in edge_rgb)[3] != 0.0 and width > 0.0
        )
        face_color = tuple(float(c) for c in rgb_face)
        # Agg snaps the legend frame path at draw time: the legend patch
        # is created with snap=True, so every vertex (anchors and curve
        # controls alike) rounds to the odd/even linewidth offset in
        # device space before stroking. Reproduce that snap here so the
        # seam rasterizes the same geometry Agg does; when the artist
        # does not request snapping the vertices ride through verbatim.
        snap = gc.get_snap() if hasattr(gc, "get_snap") else None
        snap_offset: float | None = None
        if snap is True:
            width_dev = width * float(self._effective_dpi) / 72.0
            snap_offset = (
                0.5 if math.floor(width_dev + 0.5) % 2 == 1 else 0.0
            )
        height_px = float(self._height_px)
        if snap_offset is None:
            frame_vertices = [
                # Collected display space is bottom-left-origin display
                # pixels, matching the established adapter-to-seam
                # convention (the seam applies the display-to-device
                # y-flip itself); emit verbatim without an extra flip.
                [float(vx), float(vy)]
                for vx, vy in path.vertices
            ]
        else:
            # Snap every vertex by default; Agg evidence decides whether
            # curve controls ride along (see corner residuals).
            frame_vertices = []
            for vx, vy in path.vertices:
                device_x = float(vx)
                device_y = height_px - float(vy)
                snapped_x = math.floor(device_x + 0.5) + snap_offset
                snapped_y = math.floor(device_y + 0.5) + snap_offset
                frame_vertices.append([snapped_x, height_px - snapped_y])
        command: dict[str, Any] = {
            "kind": "path",
            "decoration": "legend_frame",
            "vertices": frame_vertices,
            "codes": [int(code) for code in path.codes],
            "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            "stroke_rgba": list(edge_rgba8) if explicit_edge else None,
            "line_width_pt": width,
            "cap": str(gc.get_capstyle()),
            "join": str(gc.get_joinstyle()),
            "dash_offset_pt": 0.0,
            "dashes": None,
            "fill_rule": "nonzero",
            "antialias": True,
            "clip_rect": self._legend_clip(None),
            "fill_rgba": list(_rgba8(face_color)),
        }
        if command["cap"] not in ("butt", "round", "projecting"):
            self.unsupported(
                f"legend frame cap style {command['cap']!r} is unsupported",
                "Legend",
            )
            return None
        if command["join"] not in ("miter", "round", "bevel"):
            self.unsupported(
                f"legend frame join style "
                f"{command['join']!r} is unsupported",
                "Legend",
            )
            return None
        return command

    def _legend_handle_command(self, call: dict) -> dict | None:
        """Build one seam stroke command from a collected handle."""
        path = call["path"]
        gc = call["gc"]
        transform = call["transform"]
        affine = transform.get_matrix()
        vertices = [
            [
                float(affine[0][0]) * float(x)
                + float(affine[0][1]) * float(y)
                + float(affine[0][2]),
                float(affine[1][0]) * float(x)
                + float(affine[1][1]) * float(y)
                + float(affine[1][2]),
            ]
            for x, y in path.vertices
        ]
        rgb = gc.get_rgb()
        color = tuple(float(c) for c in rgb)
        alpha = gc.get_alpha()
        if alpha is not None:
            color = color[:3] + (float(alpha),)
        # Handle strokes arrive in handlebox-local coordinates under the
        # legend layout affine (bottom-left-origin display space, matching
        # the content-line geometry); the seam folds the display-to-device
        # y-flip in itself, so emit the affine result verbatim.
        display_vertices = [
            [float(vx), float(vy)]
            for vx, vy in vertices
        ]
        return {
            "kind": "path",
            "decoration": "legend_handle",
            "vertices": display_vertices,
            "codes": None,
            "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            "stroke_rgba": list(_rgba8(color)),
            "line_width_pt": float(gc.get_linewidth()),
            "cap": str(gc.get_capstyle()),
            "join": str(gc.get_joinstyle()),
            "dash_offset_pt": 0.0,
            "dashes": None,
            "fill_rule": "nonzero",
            "antialias": True,
            "clip_rect": self._legend_clip(None),
        }

    def _build_legend_payloads(
        self, figure: matplotlib.figure.Figure
    ) -> None:
        """Group collected legend strokes per legend, in paint order."""
        legends = [
            ax.get_legend()
            for ax in figure.get_axes()
            if ax.get_legend() is not None
        ]
        legends.extend(figure.legends)
        frames = list(self._legend_frame_calls)
        handles = list(self._legend_handle_calls)
        expected_frames = sum(
            1 for legend in legends
            if type(legend) is matplotlib.legend.Legend
            and bool(legend.get_frame_on())
        )
        expected_handles = sum(
            len(legend.get_lines())
            for legend in legends
            if type(legend) is matplotlib.legend.Legend
        )
        if len(frames) != expected_frames:
            self.unsupported(
                "collector emitted unmatched legend frame strokes; "
                "shadowed or repeated frames are unsupported",
                "Legend",
            )
            return
        if len(handles) != expected_handles:
            self.unsupported(
                "collector emitted unmatched legend handle strokes",
                "Legend",
            )
            return
        for legend in legends:
            if type(legend) is not matplotlib.legend.Legend:
                continue
            commands: list[dict] = []
            frame_count = 1 if bool(legend.get_frame_on()) else 0
            for _ in range(frame_count):
                command = self._legend_frame_command(frames.pop(0))
                if command is not None:
                    commands.append(command)
            entry_count = len(legend.get_lines())
            for _ in range(entry_count):
                command = self._legend_handle_command(handles.pop(0))
                if command is not None:
                    commands.append(command)
            self._legend_payloads[id(legend)] = commands
