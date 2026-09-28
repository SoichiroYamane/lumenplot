"""Private frame-spec assembly for the backend."""

from __future__ import annotations

import math
from typing import Any

import matplotlib
import matplotlib.axes  # noqa: F401 - public submodule for type checks
import matplotlib.collections  # noqa: F401 - public submodule for the whitelist
import matplotlib.lines  # noqa: F401 - public submodule for the whitelist
import matplotlib.patches  # noqa: F401 - public submodule for the whitelist

# mplot3d is part of Matplotlib's documented public plotting surface.  Keep
# 3D imports at the adapter edge in backend_frame_3d.py; the engine and
# private raster seam never see Matplotlib types.

from lumenplot_mpl.backend_decoration import _DecorationMixin
from lumenplot_mpl.backend_fill import _FillMixin
from lumenplot_mpl.backend_frame_3d import _Frame3DMixin
from lumenplot_mpl.backend_lines import _LineMixin
from lumenplot_mpl.backend_support import (
    _RGBA_BLACK,
    _SpineStroke,
    _rgba8,
)
from lumenplot_mpl.backend_textlabels import _TextLabelsMixin
from lumenplot_mpl.backend_types import LumenPlotUnsupportedError


class _FrameMixin(
    _DecorationMixin, _TextLabelsMixin, _Frame3DMixin, _LineMixin, _FillMixin
):
    """Frame-spec geometry commands (ADR 0015 sections 5-6, API 0005 section 5).

    Mixed into ``_EligibilityPreflight`` (which stays in
    ``backend_preflight.py`` so its ``__module__`` pin stays stable).
    Shared state (``__init__``) and the facade entries (``collect``,
    ``unsupported``) stay on the facade class; this mixin must not fork
    state and must not import from ``backend_preflight``.
    """

    def build_frame_spec(
        self,
        figure: matplotlib.figure.Figure,
        *,
        width_px: int,
        height_px: int,
        output_dpi: float,
    ) -> dict:
        """Build the ``render_frame_png`` spec from public getters.

        Rendering sources geometry through the data route: public Line2D
        data plus public linear increasing Axes limits feed one temporary
        affine request; the collected path only reconciles affine and clip
        behavior. Background color comes from the collected figure patch.
        Since the PRAC-A-D amendment, each decorated axes emits its
        solid major gridlines, major tick strokes, and visible spine edges
        as explicit path commands ahead of its content lines.
        Since PRAC-A-L a whitelisted legend contributes its frame and
        handle strokes as one bundle that rides the Legend artist's real
        public zorder inside the same per-axes sort (see the D1 contract
        below).

        LP-FUNC-035 compositing contract (D1): each axes reproduces Agg's
        ``Axes.draw`` ordering -- one stable sort of every eligible child
        by public ``get_zorder()`` (Python ``sorted`` keeps add order on
        ties, which is Agg's own stable-sort semantics). Gridline, tick,
        and spine decorations ride their artists' real zorders inside that
        single sort instead of the former decorations-first special case:
        at the default surface this preserves the legacy relative order
        (gridlines z2 and tick strokes z2.01 below content lines z2 are
        impossible under a strict per-value read, so the ratified model is
        the Axis-unit placement Agg actually draws: grid/tick strokes with
        their axis unit below default content, spines z2.5 above it),
        while inverted or negative zorders interleave exactly as Agg
        paints them. Tick, axis label, and center title glyphs stay appended
        after content: the text wire-up owns their emission position and
        Agg itself always paints labels last within the axes' decoration
        surface.
        """
        if self._three_d_axes:
            return self._build_3d_frame_spec(
                figure,
                width_px=width_px,
                height_px=height_px,
                output_dpi=output_dpi,
            )
        commands: list[dict] = []
        background_rgba = _RGBA_BLACK
        self._height_px = int(height_px)
        self._canvas_width_px = int(width_px)
        self._effective_dpi = float(output_dpi)
        self._label_payloads = list(self._observed_text_payloads)
        legend_commands_by_id: dict[int, list[dict]] = {}
        if not self.reasons:
            legend_commands_by_id = dict(self._legend_payloads)
        for ax_index, ax in enumerate(figure.get_axes()):
            xlim = ax.get_xlim()
            ylim = ax.get_ylim()
            # LP-FUNC-004 (W3): each axis projects through its own scale.
            # "linear" keeps the historical affine; base-10 "log" applies
            # the fractional log placement Agg's transData produces. Any
            # other scale records the explicit unsupported reason instead
            # of silently skipping the axes (the former skip emitted an
            # empty command surface for scaled frames -- a silent
            # degradation LP-MPL-020 forbids). Base selection reads only
            # public getters: matplotlib's own limit clamp (axis.py
            # ``_set_lim``) guarantees positive increasing limits on an
            # installed log axis, so log10 of both ends is well-defined;
            # non-base-10 log scales refuse explicitly rather than touch
            # private transform state.
            x_scale = str(ax.get_xscale())
            y_scale = str(ax.get_yscale())
            if x_scale not in ("linear", "log") or y_scale not in (
                "linear",
                "log",
            ):
                self.unsupported(
                    f"only linear and base-10 log scales are supported; "
                    f"xscale={x_scale!r}, yscale={y_scale!r} is unsupported "
                    "in strict mode",
                    type(ax).__name__,
                )
                continue
            if not (xlim[0] < xlim[1] and ylim[0] < ylim[1]):
                self.unsupported(
                    f"only increasing x/y limits are supported; "
                    f"xlim={xlim!r}, ylim={ylim!r} is unsupported "
                    "in strict mode",
                    type(ax).__name__,
                )
                continue
            bbox = ax.get_window_extent()
            x0, y0 = bbox.x0, bbox.y0
            w, h = bbox.width, bbox.height

            def _fraction(value: float, lo: float, hi: float,
                          scale: str) -> float:
                if scale == "log":
                    return (math.log10(max(value, 1e-300))
                            - math.log10(lo)) / (math.log10(hi)
                                                 - math.log10(lo))
                return (value - lo) / (hi - lo)

            def to_px_x(x: Any, _x0=x0, _w=w, _lim=xlim,
                        _s=x_scale) -> Any:
                return _x0 + _fraction(float(x), float(_lim[0]),
                                       float(_lim[1]), _s) * _w

            def to_px_y(y: Any, _y0=y0, _h=h, _lim=ylim,
                        _s=y_scale) -> Any:
                return _y0 + _fraction(float(y), float(_lim[0]),
                                       float(_lim[1]), _s) * _h

            if self._clip_points is None:
                self._clip_points = ((x0, y0), (x0 + w, y0 + h))
            # Content strokes of one axes reconcile against that axes'
            # own rectangle, keyed by draw-order position.
            if ax_index not in self._axes_clip_points:
                self._axes_clip_points[ax_index] = (
                    (x0, y0),
                    (x0 + w, y0 + h),
                )

            decorated = (
                ax_index < len(self._decorated_axes)
                and self._decorated_axes[ax_index]
            )
            # LP-FUNC-035 (D1): one stable z-order sort per axes over
            # every eligible child, exactly reproducing the ``sorted``
            # semantics of ``Axes.draw``. Matplotlib draws from one
            # add-ordered child list (public ``Axes.get_children``), so
            # equal-zorder ties keep pure add order across primitive
            # classes; the public children enumeration supplies that
            # rank. Decoration bundles ride the enumerated rank of
            # their representative artist (the x-axis unit, the bottom
            # spine).
            artist_rank: dict[int, int] = {
                id(child): rank
                for rank, child in enumerate(ax.get_children())
            }
            next_rank = len(artist_rank)
            entries: list[tuple[float, int, list[dict]]] = []
            seq = 0

            def _emit(zorder: float, rank: int,
                      cmds: list[dict]) -> None:
                nonlocal seq
                if cmds:
                    entries.append((float(zorder), rank, cmds))
                    seq += 1

            def _rank_of(artist: Any) -> int:
                nonlocal next_rank
                rank = artist_rank.get(id(artist))
                if rank is None:
                    # A live artist absent from the enumeration (should
                    # not happen) keeps a deterministic tail rank.
                    rank = next_rank
                    next_rank += 1
                return rank

            if decorated:
                # Decoration artists ride their real public zorders:
                # gridlines (default 2) and tick strokes (default 2.01)
                # sort with their Axis unit below default content lines,
                # spines (default 2.5) above it. Tick locations project
                # through the axis' own scale (LP-FUNC-004).
                _emit(
                    ax.xaxis.get_zorder(),
                    _rank_of(ax.xaxis),
                    self._decoration_commands(
                        ax, x0, y0, w, h, kinds=("gridline", "tick"),
                        to_px_x=to_px_x, to_px_y=to_px_y,
                    ),
                )
                _emit(
                    ax.spines["bottom"].get_zorder(),
                    _rank_of(ax.spines["bottom"]),
                    self._decoration_commands(
                        ax, x0, y0, w, h, kinds=("spine",),
                        to_px_x=to_px_x, to_px_y=to_px_y,
                    ),
                )
            for collection in ax.collections:
                if not isinstance(
                    collection,
                    matplotlib.collections.FillBetweenPolyCollection,
                ):
                    continue
                fill = self._fill_command(collection, to_px_x, to_px_y,
                                          ax_index)
                _emit(collection.get_zorder(),
                      _rank_of(collection),
                      [fill] if fill is not None else [])
            for patch in ax.patches:
                if not (
                    isinstance(patch, matplotlib.patches.Polygon)
                    or isinstance(patch, matplotlib.patches.Rectangle)
                ):
                    continue
                fill = self._fill_command(patch, to_px_x, to_px_y, ax_index)
                _emit(patch.get_zorder(), _rank_of(patch),
                      [fill] if fill is not None else [])
            for line in ax.get_lines():
                spec_command = self._line_command(line, to_px_x, to_px_y,
                                                  ax_index)
                _emit(line.get_zorder(), _rank_of(line),
                      [spec_command] if spec_command is not None else [])
            legend = ax.get_legend()
            legend_commands = legend_commands_by_id.pop(id(legend), None)
            if legend_commands:
                # PRAC-A-L: the Legend artist is a real whitelisted child
                # of the axes, so its frame and handles ride the same
                # stable public-zorder sort as every other axes child.
                _emit(
                    legend.get_zorder(),
                    _rank_of(legend),
                    legend_commands,
                )
            entries.sort(key=lambda entry: entry[:2])
            for _, _, entry_commands in entries:
                commands.extend(entry_commands)

        # Tick label glyphs paint above lines and decorations in Matplotlib
        # (text artists draw after the axes' line content), so the wire-up
        # appends them last: same relative order, no z-order regression.
        commands.extend(self._tick_label_commands())

        # A legend payload built for an axes skipped by the assembly
        # (non-linear or non-increasing limits) would silently vanish;
        # refusing keeps the render explicit about what it drops.
        if legend_commands_by_id:
            self.unsupported(
                "a legend could not be placed on its axes' supported "
                "projection",
                "Legend",
            )

        if self.background_rgbface is not None:
            background_rgba = _rgba8(self.background_rgbface)
        return {
            "width_px": int(width_px),
            "height_px": int(height_px),
            "output_dpi": float(output_dpi),
            "commands": commands,
            "background_rgba": list(background_rgba),
            # Architecture ruling 2026-08-25 (ADR 0012 additive amendment):
            # the adapter's quality oracle is matplotlib Agg, whose blend
            # arithmetic runs in encoded sRGB. The parity path opts in
            # explicitly; export and every default-mode consumer keep the
            # frozen linear-light compositing.
            "blend_mode": "agg_srgb",
        }
