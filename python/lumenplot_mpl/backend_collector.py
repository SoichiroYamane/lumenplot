"""Private collector-grammar checks for the backend."""

from __future__ import annotations

from typing import Any

import matplotlib
import matplotlib.axes  # noqa: F401 - public submodule for type checks
import matplotlib.figure  # noqa: F401 - public figure type for annotations
import matplotlib.legend  # noqa: F401 - public submodule for the whitelist
import numpy
from matplotlib.path import Path

from lumenplot_mpl.backend_support import _finite


class _CollectorGrammarMixin:
    """Stage-two collector-grammar validation (ADR 0015 section 4).

    Mixed into ``_EligibilityPreflight`` (which stays in
    ``backend_preflight.py`` so its ``__module__`` pin stays stable).
    Shared state (``__init__``) and the facade entry (``collect``) stay on
    the facade class; this mixin must not fork state and must not import
    from ``backend_preflight``.
    """

    def _make_grammar_collector(
        self,
        collected: list[tuple],
        expected_labels: list[dict],
        canvas_width_px: float,
        canvas_height_px: float,
        output_dpi: float,
    ) -> Any:
        """Return a public ``RendererBase`` collector class.

        The collector records the full callback event stream of ADR 0015
        §4 — group open/close pairs, per-artist ``new_gc`` calls and
        ``draw_path`` strokes. Text callbacks are recorded as raw public
        observations and reconciled with the Figure after the traversal;
        this avoids inferring the undocumented Axes decoration-mode state
        before the one required collector pass. Any other renderer callback
        raises instead of silently succeeding through the base-class no-op.

        ``Text.draw`` consults three renderer services while laying out
        each label: the canvas size, the display flip, and text metrics.
        The flip and canvas size reproduce the top-left display space the
        adapter renders in, so Matplotlib itself hands over the true
        baseline-start anchors. Metrics delegate to a real public
        ``RendererAgg`` so alignment arithmetic sees Agg's exact numbers;
        nothing is approximated here.
        """
        from matplotlib.backend_bases import GraphicsContextBase
        from matplotlib.backend_bases import RendererBase

        class _GrammarCollector(RendererBase):
            def __init__(self) -> None:
                super().__init__()
                self._metrics_renderer: Any = None
                self._groups: list[str] = []

            def _record(self, kind: str, *rest: Any) -> None:
                collected.append((kind, *rest))

            # -- eligible events ----------------------------------------
            def open_group(self, s, gid=None):  # noqa: N802
                self._groups.append(str(s))
                self._record("open", s)

            def close_group(self, s):  # noqa: N802
                if self._groups:
                    self._groups.pop()
                self._record("close", s)

            def new_gc(self):  # noqa: N802
                self._record("new_gc")
                return GraphicsContextBase()

            def draw_path(self, gc, path, transform, rgbFace=None):  # noqa: N802
                self._record(
                    "draw_path",
                    {
                        "gc": gc,
                        "path": path,
                        "transform": transform,
                        "rgbFace": rgbFace,
                        "affine": bool(transform.is_affine),
                    },
                )

            def draw_path_collection(self, *args, **kwargs):  # noqa: N802
                # RendererBase's public collection callback carries the
                # already-projected mplot3d paths and the resolved per-element
                # colors/widths.  Keep it as an owned observation only for
                # Poly3DCollection; delegate every other collection to the
                # public base implementation so the existing fill-between
                # callback expands into the established draw_path trace.
                if "Poly3DCollection" not in self._groups:
                    return RendererBase.draw_path_collection(self, *args, **kwargs)
                self._record(
                    "draw_path_collection",
                    {
                        "args": args,
                        "kwargs": kwargs,
                    },
                )

            def draw_text(  # noqa: N802
                self,
                gc,
                x,
                y,
                s,
                prop,
                angle,
                ismath=False,
                mtext=None,
            ):
                del gc, mtext
                self._record(
                    "draw_text_raw",
                    {
                        "text": str(s),
                        "x": float(x),
                        "y": float(y),
                        "angle": float(angle),
                        "prop": prop,
                        "ismath": bool(ismath),
                    },
                )

            # -- layout services consumed by ``Text.draw`` ---------------
            def get_canvas_width_height(self):  # noqa: N802
                return (float(canvas_width_px), float(canvas_height_px))

            def flipy(self):  # noqa: N802
                return True

            def points_to_pixels(self, points):  # noqa: N802
                # Match RendererAgg (points * dpi / 72): legend layout
                # consumes fontsize-point metrics, so the collection draw
                # must lay out at output_dpi, not the base identity scale.
                return points * float(output_dpi) / 72.0

            def get_text_width_height_descent(  # noqa: N802
                self, s, prop, ismath
            ):
                if self._metrics_renderer is None:
                    from matplotlib.backends.backend_agg import RendererAgg

                    self._metrics_renderer = RendererAgg(
                        max(1, int(canvas_width_px)),
                        max(1, int(canvas_height_px)),
                        float(output_dpi),
                    )
                return self._metrics_renderer.get_text_width_height_descent(
                    s, prop, ismath
                )

            # -- everything else is outside the trace --------------------
            def __getattr__(self, name):
                if name.startswith("draw_"):
                    raise NotImplementedError(name)
                raise AttributeError(name)

        return _GrammarCollector

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
        a direct text child of the axes group (Matplotlib-provided
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
                # B-2a (R3): the center title draws after its axes' tick
                # and axis labels (a direct text child of the axes group,
                # carrying Matplotlib's own anchor/position). Only a
                # visible non-empty title enters the queue: an empty or
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

    def _decoration_flags(
        self, events: list[tuple], axes_count: int
    ) -> list[bool]:
        """Return which Axes emitted a public decoration group.

        The callback stream is the only public observation of the decoration
        mode.  Keep the result aligned with ``Figure.get_axes()`` so the
        geometry assembler can make the same decision without reading an
        undocumented Axes attribute.
        """
        flags = [False] * axes_count
        axes_index = -1
        in_axes = False
        for event in events:
            kind = event[0]
            tag = event[1] if len(event) > 1 else None
            if kind == "open" and tag == "axes":
                axes_index += 1
                in_axes = axes_index < axes_count
            elif kind == "close" and tag == "axes":
                in_axes = False
            elif (
                in_axes
                and axes_index < axes_count
                and kind == "open"
                and tag in ("matplotlib.axis", "axis3d", "pane3d", "grid3d")
            ):
                flags[axes_index] = True
        return flags

    def _reconcile_text_events(
        self,
        figure: matplotlib.figure.Figure,
        events: list[tuple],
    ) -> bool:
        """Match raw public text callbacks to observed Figure labels.

        Text callbacks are deliberately reconciled after drawing.  This
        preserves one collector pass while allowing an undecorated Axes to
        omit labels without consulting a private mode flag.
        """
        self._decorated_axes = self._decoration_flags(
            events, len(figure.get_axes())
        )
        expected = self._enumerate_expected_labels(figure)
        actual = [
            (index, event[1])
            for index, event in enumerate(events)
            if event[0] == "draw_text_raw"
        ]
        if len(actual) < len(expected):
            self.unsupported(
                "a statically accepted text label was not drawn",
                "Text",
            )
            return False
        if len(actual) > len(expected):
            self.unsupported(
                "an unexpected draw_text callback was emitted for a public "
                "label observation",
                "Text",
            )
            return False
        for (index, payload), entry in zip(actual, expected):
            try:
                size_ok = (
                    abs(float(payload["prop"].get_size()) - entry["size"])
                    <= 1.0e-9
                )
                angle_ok = (
                    abs(float(payload["angle"]) - entry["angle"]) <= 1.0e-9
                )
                # T-lane style contract: the draw-time face must be the
                # statically enumerated one (same FontProperties weight /
                # style / family); a substituted face would outline
                # different glyphs than the enumerated label.
                draw_prop = payload["prop"]
                font_ok = (
                    draw_prop.get_weight() == entry["weight"]
                    and draw_prop.get_style() == entry["style"]
                    and tuple(draw_prop.get_family()) == entry["family"]
                )
            except (AttributeError, TypeError, ValueError):
                size_ok = angle_ok = font_ok = False
            if payload.get("ismath") or "$" in entry["text"]:
                self.unsupported("math/TeX text is unsupported", "Text")
                return False
            if (
                payload.get("text") != entry["text"]
                or not size_ok
                or not angle_ok
                or not font_ok
            ):
                self.unsupported(
                    "the draw_text callback for a public label changed "
                    f"at draw time: expected {entry['text']!r}, got "
                    f"{payload.get('text')!r}",
                    "Text",
                )
                return False
            events[index] = (
                "draw_text",
                {
                    "kind": entry.get("kind", "tick_label"),
                    "artist": entry["artist"],
                    "x": float(payload["x"]),
                    "y": float(payload["y"]),
                    "angle": float(payload["angle"]),
                },
            )
        return True

    def _check_poly3d_callback(self, payload: dict) -> None:
        """Validate one public projected Poly3DCollection callback.

        Matplotlib may issue an empty collection callback before the real
        projected paths; that observation is harmless and is ignored. Every
        non-empty callback must contain only triangle loops and styles that
        broadcast one-to-one with the projected paths.
        """
        try:
            args = payload["args"]
            master_transform = args[1]
            paths = list(args[2])
            facecolors = numpy.asarray(args[6], dtype=float)
            edgecolors = numpy.asarray(args[7], dtype=float)
            linewidths = numpy.asarray(args[8], dtype=float).reshape(-1)
        except (KeyError, IndexError, TypeError, ValueError):
            self.unsupported(
                "Poly3DCollection callback payload is malformed",
                "Poly3DCollection",
            )
            return
        if not paths:
            return
        if not bool(getattr(master_transform, "is_affine", False)):
            self.unsupported(
                "Poly3DCollection projected transform is non-affine",
                "Poly3DCollection",
            )
            return
        try:
            matrix = numpy.asarray(master_transform.get_matrix(), dtype=float)
        except (AttributeError, TypeError, ValueError):
            self.unsupported(
                "Poly3DCollection projected transform is unavailable",
                "Poly3DCollection",
            )
            return
        if matrix.shape != (3, 3) or not numpy.isfinite(matrix).all():
            self.unsupported(
                "Poly3DCollection projected transform is invalid",
                "Poly3DCollection",
            )
        path_count = len(paths)
        for path in paths:
            vertices = numpy.asarray(path.vertices, dtype=float)
            codes = path.codes
            real_points = (
                len(vertices)
                if codes is None
                else sum(int(code) != int(Path.CLOSEPOLY) for code in codes)
            )
            if real_points != 3 or not numpy.isfinite(vertices).all():
                self.unsupported(
                    "Poly3DCollection native mode requires finite triangles",
                    "Poly3DCollection",
                )
                break
            if codes is not None and list(map(int, codes)) not in (
                [int(Path.MOVETO), int(Path.LINETO), int(Path.LINETO), int(Path.CLOSEPOLY)],
                [int(Path.MOVETO), int(Path.LINETO), int(Path.LINETO)],
            ):
                self.unsupported(
                    "Poly3DCollection triangle path codes are unsupported",
                    "Poly3DCollection",
                )
                break

        def _broadcastable(values: numpy.ndarray, channels: int) -> bool:
            return values.size == 0 or (
                values.ndim == 1 and values.size == channels
            ) or (
                values.ndim == 2
                and values.shape[1] == channels
                and values.shape[0] in (1, path_count)
            )

        if not _broadcastable(facecolors, 4) or not _broadcastable(edgecolors, 4):
            self.unsupported(
                "Poly3DCollection per-element colors do not broadcast",
                "Poly3DCollection",
            )
        if linewidths.size not in (0, 1, path_count) or not numpy.isfinite(linewidths).all():
            self.unsupported(
                "Poly3DCollection per-element linewidths do not broadcast",
                "Poly3DCollection",
            )

    def _consume_trace(self, events: list[tuple]) -> bool:
        """Validate the exact grouped callback grammar for this slice.

        Every leaf artist group has one ``new_gc`` immediately followed by
        its callback. ``FillBetweenPolyCollection`` is the one exception:
        one graphics context may service several polygon paths. Axis groups
        contain only ``xtick``/``ytick`` groups plus, since B-2a (R2), at
        most one direct ``text`` group per axis carrying that axis'
        ``xlabel``/``ylabel`` draw_text; tick-label texts stay nested
        inside their ``xtick``/``ytick`` groups. An axes group carries,
        since B-2a (R3), at most one direct ``text`` child carrying that
        axes' center title draw_text. A legend contains an
        optional frame patch followed by line/text entry pairs. The axes
        body remains order-free under LP-FUNC-035 D2, but unknown groups,
        bare callbacks, missing graphics contexts, and unbalanced nesting
        are refused instead of being silently accepted.
        """
        index = 0
        total = len(events)

        def fail(reason: str) -> bool:
            self.unsupported(reason, "Figure")
            return False

        def is_open(tag: str) -> bool:
            return (
                index < total
                and events[index][0] == "open"
                and events[index][1] == tag
            )

        def consume_leaf(
            tag: str, callback: str, alternatives: tuple[str, ...] = ()
        ) -> dict | None:
            """Consume ``open(tag), new_gc, callback, close(tag)``."""
            nonlocal index
            if not is_open(tag):
                fail(f"expected open({tag!r}) group")
                return None
            index += 1
            if index >= total or events[index][0] != "new_gc":
                fail(
                    f"{tag} group is missing its graphics context before "
                    f"{callback}"
                )
                return None
            index += 1
            accepted_callbacks = (callback, *alternatives)
            if index >= total or events[index][0] not in accepted_callbacks:
                actual = events[index][0] if index < total else "end-of-trace"
                fail(
                    f"{tag} group expected one of {accepted_callbacks}, "
                    f"observed {actual}"
                )
                return None
            payload = events[index][1]
            index += 1
            if index >= total or events[index] != ("close", tag):
                fail(f"{tag} group is not balanced after {callback}")
                return None
            index += 1
            return payload

        def consume_fill() -> bool:
            """Consume a collection group with shared graphics contexts."""
            nonlocal index
            tag = "FillBetweenPolyCollection"
            if not is_open(tag):
                fail(f"expected open({tag!r}) group")
                return False
            index += 1
            gc_count = 0
            while index < total and events[index][0] == "new_gc":
                gc_count += 1
                index += 1
            if gc_count == 0:
                fail(f"{tag} group is missing its graphics context")
                return False
            paths = 0
            while index < total and events[index][0] == "draw_path":
                paths += 1
                index += 1
            if paths == 0:
                fail(f"{tag} group carries no draw_path callback")
                return False
            if index >= total or events[index] != ("close", tag):
                fail(f"{tag} group is not balanced after its paths")
                return False
            index += 1
            return True

        def consume_poly3d() -> bool:
            """Consume one projected Poly3DCollection callback group."""
            nonlocal index
            tag = "Poly3DCollection"
            if not is_open(tag):
                fail(f"expected open({tag!r}) group")
                return False
            index += 1
            if index >= total or events[index][0] != "new_gc":
                fail(f"{tag} group is missing its graphics context")
                return False
            index += 1
            callbacks = 0
            while index < total and events[index][0] == "draw_path_collection":
                callbacks += 1
                index += 1
            if callbacks == 0:
                fail(f"{tag} group carries no projected collection callback")
                return False
            if index >= total or events[index] != ("close", tag):
                fail(f"{tag} group is not balanced after its callbacks")
                return False
            index += 1
            return True

        def consume_axis_tick(tag: str) -> bool:
            nonlocal index
            if not is_open(tag):
                fail(f"expected open({tag!r}) group")
                return False
            index += 1
            while index < total and events[index][0] == "open":
                child = events[index][1]
                if child == "line2d":
                    if consume_leaf(child, "draw_path") is None:
                        return False
                elif child == "text":
                    if consume_leaf(
                        "text", "draw_text", ("draw_text_unexpected",)
                    ) is None:
                        return False
                else:
                    fail(
                        f"unexpected {child!r} group inside {tag!r}"
                    )
                    return False
            if index >= total or events[index] != ("close", tag):
                fail(f"{tag} group is not balanced")
                return False
            index += 1
            return True

        def consume_axis() -> bool:
            nonlocal index
            tag = "matplotlib.axis"
            if not is_open(tag):
                fail(f"expected open({tag!r}) group")
                return False
            index += 1
            while index < total and events[index][0] == "open":
                child = events[index][1]
                if child in ("xtick", "ytick"):
                    if not consume_axis_tick(child):
                        return False
                elif child == "text":
                    # B-2a (R2): the direct text child of an axis group
                    # is that axis' xlabel/ylabel draw_text (tick-label
                    # texts nest inside xtick/ytick). The draw-order
                    # cross-check already proved the text matches the
                    # enumerated axis label; the grammar only proves the
                    # group shape.
                    if consume_leaf(
                        "text", "draw_text", ("draw_text_unexpected",)
                    ) is None:
                        return False
                else:
                    fail(
                        f"unexpected {child!r} group inside {tag!r}"
                    )
                    return False
            if index >= total or events[index] != ("close", tag):
                fail(f"{tag} group is not balanced")
                return False
            index += 1
            return True

        expected_shapes = list(self._expected_legend_shapes)
        expected_legend_count = len(expected_shapes)

        def consume_legend() -> bool:
            nonlocal index
            tag = "legend"
            if not is_open(tag):
                fail(f"expected open({tag!r}) group")
                return False
            index += 1
            frame_count = 0
            if is_open("patch"):
                if consume_leaf("patch", "draw_path") is None:
                    return False
                frame_count = 1
            if is_open("patch"):
                fail(
                    "legend emitted an extra frame patch; shadows and "
                    "repeated frames are unsupported"
                )
                return False
            entries = 0
            while is_open("line2d"):
                if consume_leaf("line2d", "draw_path") is None:
                    return False
                if not is_open("text"):
                    fail(
                        "legend handle is not followed by a text label; "
                        "label was not drawn"
                    )
                    return False
                if consume_leaf(
                    "text", "draw_text", ("draw_text_unexpected",)
                ) is None:
                    return False
                entries += 1
            if entries == 0:
                fail("legend group carries no line/text entries")
                return False
            shape = (frame_count == 1, entries)
            if expected_legend_count == 0:
                fail("collector emitted an unexpected legend group")
                return False
            if shape not in expected_shapes:
                fail(
                    "legend group frame/entry shape does not match the "
                    "statically enumerated legend"
                )
                return False
            expected_shapes.remove(shape)
            if index >= total or events[index] != ("close", tag):
                fail("legend group is not balanced")
                return False
            index += 1
            return True

        def consume_axes() -> bool:
            nonlocal index
            tag = "axes"
            if not is_open(tag):
                fail(f"expected open({tag!r}) group")
                return False
            index += 1
            while index < total and events[index][0] == "open":
                child = events[index][1]
                if child in ("line2d", "patch"):
                    if consume_leaf(child, "draw_path") is None:
                        return False
                elif child == "FillBetweenPolyCollection":
                    if not consume_fill():
                        return False
                elif child == "Poly3DCollection":
                    if not consume_poly3d():
                        return False
                elif child == "text":
                    # B-2a (R3): the direct text child of an axes group
                    # is that axes' center title draw_text (tick and
                    # axis-label texts nest inside matplotlib.axis).
                    # The draw-order cross-check already proved the text
                    # matches the enumerated center title; the grammar
                    # only proves the group shape.
                    if consume_leaf(
                        "text", "draw_text", ("draw_text_unexpected",)
                    ) is None:
                        return False
                elif child == "matplotlib.axis":
                    if not consume_axis():
                        return False
                elif child == "legend":
                    if not consume_legend():
                        return False
                else:
                    fail(f"unexpected {child!r} group inside axes")
                    return False
            if index >= total or events[index] != ("close", tag):
                fail("axes group is not balanced")
                return False
            index += 1
            return True

        if not is_open("figure"):
            return fail("collector trace does not start with open('figure')")
        index += 1
        background = consume_leaf("patch", "draw_path")
        if background is None:
            return False
        if background.get("rgbFace") is None:
            return fail("figure background stroke is missing its facecolor")
        # Axes3D emits its transparent/disabled patch at figure scope before
        # the content group.  It carries no independent native meaning in an
        # axis-off fixture and is accepted only in the dedicated 3D grammar.
        if self._three_d_axes and is_open("patch"):
            if consume_leaf("patch", "draw_path") is None:
                return False
        while is_open("axes"):
            if not consume_axes():
                return False
        if index >= total or events[index] != ("close", "figure"):
            return fail("figure group is not balanced")
        index += 1
        if index != total:
            kind = events[index][0]
            return fail(
                f"unexpected {kind!r} event outside the eligible trace"
            )
        if expected_shapes:
            return fail(
                "one or more statically enumerated legends were absent "
                "from the collector trace"
            )
        return True

    def _check_background_style(self, call: dict) -> None:
        gc = call["gc"]
        if bool(gc.get_antialiased()):
            self.unsupported("antialiased figure background is unsupported")
        if gc.get_linewidth() != 0.0:
            self.unsupported("stroked figure background is unsupported")

    def _check_line_call(self, call: dict, axes_position: int) -> None:
        path = call["path"]
        codes = path.codes
        if codes is not None and len(codes):
            code_values = {int(code) for code in codes}
            allowed = {
                int(Path.MOVETO),
                int(Path.LINETO),
                int(Path.CLOSEPOLY),
                0,
            }
            if not code_values <= allowed:
                self.unsupported("curved path segments are unsupported")
        vertices = path.vertices
        if len(vertices) < 2:
            self.unsupported("degenerate single-vertex stroke")
        self._check_stroke_common(call["gc"], axes_position)

    def _check_fill_call(self, call: dict, axes_position: int) -> None:
        """Collector-side checks for one fill draw_path (LP-FUNC-032).

        Fills must stay polygonal (MOVETO/LINETO/CLOSEPOLY only), carry
        a facecolor, and reconcile the rectangular axes clip against
        their own axes' rectangle (per-axes reconciliation, keyed by the
        enclosing axes' draw-order position). The shared
        ``_check_stroke_common`` runs
        the dash/sketch/snap/clip surface; the clip bookkeeping also
        seeds the fill command's ``clip_rect``.

        FILL-AA decision (b): a fill artist is strict-eligible IFF every
        polygon edge is axis-aligned in device/display space after
        transform (|dx| <= 1e-6 device px OR |dy| <= 1e-6 device px).
        Any slanted edge makes the artist strict-ineligible (fail before
        writing in strict; whole-frame Agg fallback in hybrid). Curves
        are already refused above; integer-pixel alignment is NOT part
        of eligibility (sub-pixel axis-aligned positions stay eligible;
        the pixel gate arbitrates them). Bars keep their existing
        angle==0 refusal; this message mirrors its reason style.
        """
        path = call["path"]
        codes = path.codes
        if codes is not None and len(codes):
            code_values = {int(code) for code in codes}
            allowed = {
                int(Path.MOVETO),
                int(Path.LINETO),
                int(Path.CLOSEPOLY),
                0,
            }
            if not code_values <= allowed:
                self.unsupported("curved path segments are unsupported")
        vertices = path.vertices
        # A closed loop needs at least three real positions (CLOSEPOLY's
        # vertex is a positional dummy); fewer cannot enclose area.
        real_points = (
            len(vertices)
            if codes is None
            else sum(1 for code in codes if int(code) != int(Path.CLOSEPOLY))
        )
        if real_points < 3:
            self.unsupported("degenerate fill path")
        self._check_fill_axis_alignment(call)
        gc = call["gc"]
        if gc.get_hatch() is not None:
            self.unsupported("hatching is unsupported in strict mode")
        self._check_stroke_common(gc, axes_position)

    def _check_fill_axis_alignment(self, call: dict) -> None:
        """Refuse one fill draw_path whose device-space edges slant.

        Every polygon edge is resolved in device/display pixels through
        the collected public transform (the same transform Agg used),
        then required to be axis-aligned: |dx| <= 1e-6 OR |dy| <= 1e-6.
        Subpaths are delimited by MOVETO/CLOSEPOLY so the CLOSEPOLY
        dummy vertex never forms an edge; an unclosed trailing loop is
        checked with its implicit closing edge, matching the seam's
        implicit-close behavior. Non-finite endpoints are skipped (gap
        handling owns them); an unresolvable transform fails closed
        with the same reason.
        """
        path = call["path"]
        codes = path.codes
        transform = call.get("transform")
        if transform is None:
            self.unsupported(
                "slanted fill edges are unsupported in strict mode; "
                "fills must be axis-aligned"
            )
            return
        try:
            import numpy as _np

            verts = _np.asarray(path.vertices, dtype=float)
            if verts.size == 0:
                return
            if verts.ndim != 2 or verts.shape[1] != 2:
                self.unsupported(
                    "slanted fill edges are unsupported in strict mode; "
                    "fills must be axis-aligned"
                )
                return
            device = transform.transform(verts)
        except (AttributeError, TypeError, ValueError, RuntimeError):
            self.unsupported(
                "slanted fill edges are unsupported in strict mode; "
                "fills must be axis-aligned"
            )
            return
        try:
            import math as _math

            def _edge_slanted(p0: Any, p1: Any) -> bool:
                try:
                    x0 = float(p0[0])
                    y0 = float(p0[1])
                    x1 = float(p1[0])
                    y1 = float(p1[1])
                except (IndexError, TypeError, ValueError):
                    return True
                if not (
                    _math.isfinite(x0)
                    and _math.isfinite(y0)
                    and _math.isfinite(x1)
                    and _math.isfinite(y1)
                ):
                    return False
                return (
                    abs(x1 - x0) > 1.0e-6 and abs(y1 - y0) > 1.0e-6
                )

            if codes is None:
                points = [tuple(row) for row in device.tolist()]
                if len(points) >= 3:
                    for index in range(len(points)):
                        if _edge_slanted(
                            points[index],
                            points[(index + 1) % len(points)],
                        ):
                            self.unsupported(
                                "slanted fill edges are unsupported in "
                                "strict mode; fills must be axis-aligned"
                            )
                            return
                return
            code_list = [int(code) for code in codes]
            current: list[tuple[float, float]] = []
            for index, code in enumerate(code_list):
                if code == int(Path.MOVETO):
                    if len(current) >= 3:
                        if _edge_slanted(current[-1], current[0]):
                            self.unsupported(
                                "slanted fill edges are unsupported in "
                                "strict mode; fills must be axis-aligned"
                            )
                            return
                    current = [tuple(device[index].tolist())]
                elif code == int(Path.LINETO):
                    point = tuple(device[index].tolist())
                    if current:
                        if _edge_slanted(current[-1], point):
                            self.unsupported(
                                "slanted fill edges are unsupported in "
                                "strict mode; fills must be axis-aligned"
                            )
                            return
                        current.append(point)
                    else:
                        current = [point]
                elif code == int(Path.CLOSEPOLY):
                    if len(current) >= 2:
                        if _edge_slanted(current[-1], current[0]):
                            self.unsupported(
                                "slanted fill edges are unsupported in "
                                "strict mode; fills must be axis-aligned"
                            )
                            return
                    current = []
                elif code == 0:
                    continue
                else:
                    # Curve codes are already refused above; they never
                    # satisfy the axis-aligned edge contract either.
                    continue
            if len(current) >= 3:
                if _edge_slanted(current[-1], current[0]):
                    self.unsupported(
                        "slanted fill edges are unsupported in strict mode; "
                        "fills must be axis-aligned"
                    )
                    return
        except (AttributeError, IndexError, TypeError, ValueError):
            self.unsupported(
                "slanted fill edges are unsupported in strict mode; "
                "fills must be axis-aligned"
            )
            return

    def _check_stroke_common(self, gc: Any, axes_position: int) -> None:
        """Shared dash/sketch/snap/clip checks for one eligible stroke.

        The rectangular-clip branch reconciles ``_axes_clip_points``
        against the enclosing axes' own rectangle, keyed by draw-order
        position: a second, different rectangle for the same axes
        refuses the frame instead of silently clipping with the wrong
        one. ``_clip_points`` keeps its first-rectangle seed as a
        fallback for geometry paths without an axes key.
        """
        if gc.get_dashes()[1] is not None:
            self.unsupported("dashed strokes are unsupported in strict mode")
        if gc.get_sketch_params() is not None:
            self.unsupported("sketch parameters are unsupported")
        if gc.get_snap() is not None:
            self.unsupported("explicit snap is unsupported")
        clip_rect = gc.get_clip_rectangle()
        if clip_rect is None:
            self.unsupported("absent rectangular clip where required")
        else:
            points = clip_rect.get_points()
            if not (
                _finite(points[0][0])
                and _finite(points[0][1])
                and _finite(points[1][0])
                and _finite(points[1][1])
            ):
                self.unsupported("non-finite clip rectangle")
        if gc.get_clip_path() != (None, None):
            self.unsupported("non-rectangular custom clip is unsupported")
        elif clip_rect is not None:
            # Remember the validated rectangular clip so the request can
            # carry an explicit clip_rect. Content strokes of one axes
            # reconcile against that axes' own rectangle, keyed by
            # draw-order position; a second, different rectangle for the
            # same position refuses the frame instead of silently
            # clipping with the wrong one.
            known = self._axes_clip_points.get(axes_position)
            if known is not None and (
                tuple(float(v) for row in known for v in row)
                != tuple(float(v) for row in points for v in row)
            ):
                self.unsupported(
                    "content strokes of one axes disagree on their "
                    "rectangular clip"
                )
            elif known is None:
                self._axes_clip_points[axes_position] = points
            if self._clip_points is None:
                self._clip_points = points
