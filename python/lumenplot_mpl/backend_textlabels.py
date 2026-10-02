"""Private shared text-coverage unit for the Matplotlib backend adapter.

Leaf extraction of the adapter-owned shared text-coverage helper consumed by
:mod:`lumenplot_mpl.backend_frame`. Mixed into ``_FrameMixin`` alongside the
2D assembly; the 2D assembly (``build_frame_spec`` and helpers) and facade
wiring stay in ``backend_frame.py``.
"""

from __future__ import annotations

import math

import matplotlib.axes  # noqa: F401 - public submodule for type checks
import matplotlib.figure  # noqa: F401 - public figure type for annotations
import matplotlib.legend  # noqa: F401 - public submodule for the whitelist

from lumenplot_mpl import textpath
from lumenplot_mpl.backend_support import _rgba8
from lumenplot_mpl.backend_types import LumenPlotUnsupportedError


class _TextLabelsMixin:
    """Shared text-coverage commands moved verbatim from ``backend_frame.py``.

    Mixed into ``_FrameMixin`` (which stays in ``backend_frame.py`` so its
    ``__module__`` pin and ``backend_preflight`` import surface stay stable).
    Shared state (``__init__``) and the facade entries (``collect``,
    ``unsupported``) stay on the facade class; this mixin must not fork
    state and must not import from ``backend_frame`` or ``backend_preflight``.
    """

    def _tick_label_commands(self) -> list[dict]:
        """Build one filled glyph path command per collected text label.

        Each stage-two ``draw_text`` payload carries the true baseline
        anchor in top-left display pixels, handed over by Matplotlib's own
        ``Text.draw`` layout under the collector's flip/canvas/metric
        services. The public ``lumenplot_mpl.textpath`` module extracts
        the glyph outlines in identity space (baseline at the origin,
        y up); this method composes them into display space with one
        explicit matrix per label::

            p_display = R(angle) @ S(output_dpi / 72) @ p_outline + anchor

        so the pt-space outlines land exactly where Agg would have inked
        them, honoring rotation without re-deriving any layout algebra.
        Color and alpha come from the label artist through the same
        public-getter route as every other command surface. Since the
        PRAC-A-L amendment the same route renders legend entry labels
        (payload kind ``legend_label``), tagged with a distinct
        ``decoration`` marker. Since B-2a (R2) it renders ``xlabel`` /
        ``ylabel`` axis labels (payload kind ``axis_label``) with the
        ``axis_label`` marker. Since B-2a (R3) it renders the center
        ``title`` (payload kind ``title``) with the ``title`` marker,
        and since the loc-title slice the left/right ``title`` pair
        rides the same payload kind and marker.
        Since the P3 PNG-only label-coverage amendment (ADR 0015 section
        4b) legend entry labels instead ride as one coverage-blit image
        command per label: the private textpath coverage helper rasterizes
        the label with FT2Font at the output DPI into an alpha mask,
        anchored by the same Matplotlib-provided anchor below, and the
        native side composites it with the agg_srgb blend. Under the
        P3-NEXT Q1 allowlist tick labels ride the same coverage-blit
        route (decoration ``tick_label`` kept, no new kind discriminator);
        since the title slice the center ``title`` rides the same
        coverage-blit route (decoration ``title`` kept); since the
        loc-title slice the left/right ``title`` pair rides that same
        route (decoration ``title`` kept, no new kind discriminator);
        since the
        axis-label slice the ``xlabel``/``ylabel`` pair rides the same
        coverage-blit route (decoration ``axis_label`` kept).
        """
        commands: list[dict] = []
        scale = self._effective_dpi / 72.0
        for payload in self._label_payloads:
            label = payload["artist"]
            anchor_x = float(payload["x"])
            anchor_y = float(payload["y"])
            angle_deg = float(payload["angle"])
            label_kind = str(payload.get("kind", "tick_label"))
            if label_kind == "legend_label":
                decoration = "legend_label"
            elif label_kind == "axis_label":
                decoration = "axis_label"
            elif label_kind == "title":
                decoration = "title"
            else:
                decoration = "tick_label"
            if label_kind in ("legend_label", "tick_label", "title", "axis_label"):
                try:
                    # The collector records the draw_text anchor in the same
                    # y-down display frame Agg consumes, so it feeds the
                    # coverage helper unchanged (no second flip).
                    left_col, top_row, mask_w, mask_h, mask = (
                        textpath._label_coverage_mask(
                            str(label.get_text()),
                            anchor_x,
                            anchor_y,
                            float(self._height_px),
                            angle_deg,
                            font_size_pt=float(label.get_fontsize()),
                            prop=label.get_fontproperties(),
                            dpi=self._effective_dpi,
                        )
                    )
                except ValueError as error:
                    raise LumenPlotUnsupportedError(
                        f"{decoration} glyphs are unsupported: {error}",
                    ) from error
                style_rgba = _rgba8(label.get_color(), label.get_alpha())
                rgba = bytearray(4 * mask_w * mask_h)
                for index, cover in enumerate(mask):
                    rgba[4 * index] = style_rgba[0]
                    rgba[4 * index + 1] = style_rgba[1]
                    rgba[4 * index + 2] = style_rgba[2]
                    rgba[4 * index + 3] = textpath._agg_multiply_byte(
                        style_rgba[3], int(cover)
                    )
                commands.append(
                    {
                        "kind": "image",
                        "decoration": decoration,
                        "x": float(left_col),
                        "y": float(self._height_px) - float(top_row + mask_h),
                        "width": int(mask_w),
                        "height": int(mask_h),
                        "rgba": bytes(rgba),
                        "clip_rect": [
                            0.0,
                            0.0,
                            float(self._canvas_width_px),
                            float(self._height_px),
                        ],
                    }
                )
                continue
            try:
                outline = textpath._writer_glyph_outline_commands(
                    str(label.get_text()),
                    (0.0, 0.0),
                    1.0,
                    0.0,
                    font_size_pt=float(label.get_fontsize()),
                    prop=label.get_fontproperties(),
                    dpi=self._effective_dpi,
                )[0]
            except ValueError as error:
                raise LumenPlotUnsupportedError(
                    f"{decoration} glyphs are unsupported: {error}",
                ) from error

            theta = math.radians(angle_deg)
            cos_t = math.cos(theta)
            sin_t = math.sin(theta)

            vertices: list[list[float]] = []
            for vx, vy in outline["vertices"]:
                # ``glyph_outline_commands`` already emits top-left pixel
                # orientation (its contract negates TextPath's y-up sign
                # once), so both axes scale uniformly without another
                # negation before the rotation.
                px = vx * scale
                py = vy * scale
                vertices.append(
                    [
                        anchor_x + px * cos_t + py * sin_t,
                        self._height_px - (anchor_y - px * sin_t
                                           + py * cos_t),
                    ]
                )
            commands.append(
                {
                    "kind": "path",
                    "decoration": decoration,
                    "vertices": vertices,
                    "codes": list(outline["codes"]),
                    "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
                    "stroke_rgba": None,
                    "fill_rgba": list(_rgba8(label.get_color(),
                                             label.get_alpha())),
                    "line_width_pt": 0.0,
                    "cap": "butt",
                    "join": "miter",
                    "dash_offset_pt": 0.0,
                    "dashes": None,
                    "fill_rule": "nonzero",
                    "antialias": True,
                    "clip_rect": [
                        0.0,
                        0.0,
                        float(self._canvas_width_px),
                        float(self._height_px),
                    ],
                }
            )
        return commands

    def _enumerate_expected_labels(
        self,
        figure: matplotlib.figure.Figure,
    ) -> list[dict]:
        """Enumerate accepted tick, axis, title, and legend labels in draw order.

        Matplotlib draws each decorated axes' major ticks through public
        ``Axis.get_major_ticks``/``get_ticklocs`` in the same order the
        collector observes their ``draw_text`` callbacks (x-axis first,
        then y-axis; ``label1`` before ``label2`` per tick). The B-2a
        (R2) axis labels interleave per axis: the x-axis ``xlabel``
        draws after its x-tick labels and before the y-axis ticks, and
        the y-axis ``ylabel`` draws after its y-tick labels. The B-2a
        (R3) center title draws after its axes' tick and axis labels as
        a direct text child of the axes group, and since the loc-title
        slice the left title draws after the center title and the right
        title draws after the left title (Matplotlib-provided
        anchors/positions only; no title layout math here). Only
        visible non-empty labels whose tick location lies inside
        ``Axis.get_view_interval()`` enter the queue: ``Tick.draw``
        skips out-of-view ticks entirely, so an unfiltered enumeration
        would accept labels the renderer never draws. A whitelisted
        legend then contributes its entry labels after its axes' tick,
        axis, and title labels.
        """
        entries: list[dict] = []
        decorated_axes = self._decorated_axes or None
        for ax_index, ax in enumerate(figure.get_axes()):
            if type(ax) is not matplotlib.axes.Axes:
                continue
            decorated = (
                decorated_axes is None
                or ax_index >= len(decorated_axes)
                or decorated_axes[ax_index]
            )
            if decorated:
                for axis in (ax.xaxis, ax.yaxis):
                    # Public formatter access materializes the labels that
                    # ``Tick.draw`` will subsequently emit.  This mirrors
                    # the former static pass without reading a private Axes
                    # decoration flag.
                    axis.get_majorticklabels()
                    view_lo, view_hi = (
                        float(axis.get_view_interval()[0]),
                        float(axis.get_view_interval()[1]),
                    )
                    locations = [float(loc) for loc in axis.get_ticklocs()]
                    for index, tick in enumerate(axis.get_major_ticks()):
                        if index >= len(locations):
                            break
                        location = locations[index]
                        if not (view_lo <= location <= view_hi):
                            continue
                        for label in (tick.label1, tick.label2):
                            text = label.get_text()
                            if not label.get_visible() or text == "":
                                continue
                            label_prop = label.get_fontproperties()
                            entries.append(
                                {
                                    "artist": label,
                                    "text": str(text),
                                    "size": float(label.get_fontsize()),
                                    "angle": float(label.get_rotation()),
                                    "weight": label_prop.get_weight(),
                                    "style": label_prop.get_style(),
                                    "family": tuple(label_prop.get_family()),
                                }
                            )
                    # B-2a (R2): the axis label draws immediately after
                    # its own axis' tick labels (xlabel after x-ticks,
                    # ylabel after y-ticks). Only visible non-empty
                    # labels enter the queue: an empty or invisible
                    # label draws nothing.
                    axis_label = axis.get_label()
                    axis_text = axis_label.get_text()
                    if axis_label.get_visible() and axis_text != "":
                        axis_prop = axis_label.get_fontproperties()
                        entries.append(
                            {
                                "kind": "axis_label",
                                "artist": axis_label,
                                "text": str(axis_text),
                                "size": float(axis_label.get_fontsize()),
                                "angle": float(axis_label.get_rotation()),
                                "weight": axis_prop.get_weight(),
                                "style": axis_prop.get_style(),
                                "family": tuple(axis_prop.get_family()),
                            }
                        )
                # B-2a (R3) plus the loc-title slice: the center, left, and
                # right titles draw after their axes' tick and axis labels
                # in that order (each a direct text child of the axes
                # group, carrying Matplotlib's own anchor/position). Only
                # a visible non-empty title enters the queue: an empty or
                # invisible title draws nothing.
                center_title = ax.title
                center_text = center_title.get_text()
                if center_title.get_visible() and center_text != "":
                    center_prop = center_title.get_fontproperties()
                    entries.append(
                        {
                            "kind": "title",
                            "artist": center_title,
                            "text": str(center_text),
                            "size": float(center_title.get_fontsize()),
                            "angle": float(center_title.get_rotation()),
                            "weight": center_prop.get_weight(),
                            "style": center_prop.get_style(),
                            "family": tuple(center_prop.get_family()),
                        }
                    )
                for loc_title in (ax._left_title, ax._right_title):
                    loc_text = loc_title.get_text()
                    if not loc_title.get_visible() or loc_text == "":
                        continue
                    loc_prop = loc_title.get_fontproperties()
                    entries.append(
                        {
                            "kind": "title",
                            "artist": loc_title,
                            "text": str(loc_text),
                            "size": float(loc_title.get_fontsize()),
                            "angle": float(loc_title.get_rotation()),
                            "weight": loc_prop.get_weight(),
                            "style": loc_prop.get_style(),
                            "family": tuple(loc_prop.get_family()),
                        }
                    )
            legend = ax.get_legend()
            if type(legend) is matplotlib.legend.Legend:
                for label in legend.get_texts():
                    text = label.get_text()
                    if not label.get_visible() or text == "":
                        continue
                    legend_prop = label.get_fontproperties()
                    entries.append(
                        {
                            "kind": "legend_label",
                            "artist": label,
                            "text": str(text),
                            "size": float(label.get_fontsize()),
                            "angle": float(label.get_rotation()),
                            "weight": legend_prop.get_weight(),
                            "style": legend_prop.get_style(),
                            "family": tuple(legend_prop.get_family()),
                        }
                    )
        return entries
