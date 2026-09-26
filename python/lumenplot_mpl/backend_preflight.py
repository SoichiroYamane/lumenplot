"""Private eligibility orchestration for the backend."""

from __future__ import annotations

from typing import Any

import matplotlib
import matplotlib.axes  # noqa: F401 - public submodule for type checks
import matplotlib.legend  # noqa: F401 - public submodule for the whitelist

# mplot3d is part of Matplotlib's documented public plotting surface.  Keep
# these imports at the adapter edge; the engine and private raster seam never
# see Matplotlib types.
from mpl_toolkits.mplot3d.axes3d import Axes3D

from lumenplot_mpl.backend_collector import _CollectorGrammarMixin
from lumenplot_mpl.backend_eligibility import _StaticEligibilityMixin
from lumenplot_mpl.backend_frame import _FrameMixin
from lumenplot_mpl.backend_legend import _LegendMixin


class _EligibilityPreflight(_StaticEligibilityMixin, _LegendMixin, _CollectorGrammarMixin, _FrameMixin):
    """Two-stage eligibility preflight (ADR 0015 §3-4, API 0005 §4).

    Stage one checks the static documented-public object whitelist; stage
    two runs exactly one public ``RendererBase`` collector traversal and
    asserts the exact eligible trace of one figure-background ``draw_path``
    plus per-line single-stroke ``draw_path`` calls. The collector is an
    observation: it never mutates the Figure. Any other renderer callback,
    unknown artist type, non-affine transform, non-rectangular clip, or
    style outside the fixed supported set records an explicit unsupported
    reason.
    """

    def __init__(self) -> None:
        self.reasons: list[tuple[str | None, str]] = []
        self.background_seen = False
        self.background_rgbface: Any = None
        self.line_paths = 0
        self.fill_paths = 0
        self._clip_points: Any = None
        # Rectangular clip of each axes' content strokes, keyed by the
        # axes' draw-order position in ``Figure.get_axes``. Strokes of one
        # axes reconcile against that axes' own rectangle only; a second,
        # different rectangle for the same axes is refused instead of
        # silently clipping with the wrong rectangle. ``_clip_points``
        # keeps its first-rectangle seed as a fallback.
        self._axes_clip_points: dict[int, Any] = {}
        self._height_px = 0
        self._canvas_width_px = 0
        self._effective_dpi = 100.0
        # ``draw_text`` payloads captured by the stage-two collector.
        self._observed_text_payloads: list[dict] = []
        # Legend strokes captured by the stage-two collector (PRAC-A-L):
        # the rounded frame outline and the per-entry handle polylines,
        # already laid out by Matplotlib's own ``Legend.draw``.
        self._legend_frame_calls: list[dict] = []
        self._legend_handle_calls: list[dict] = []
        #: ``id(Legend) ->`` seam-ready path commands, built at collect
        #: time and consumed by :meth:`build_frame_spec`.
        self._legend_payloads: dict[int, list[dict]] = {}
        #: Frame-on flag and public line-entry count captured before the
        #: renderer traversal; the trace grammar matches each observed
        #: legend group against this static expectation.
        self._expected_legend_shapes: list[tuple[bool, int]] = []
        #: Whether each Axes emitted its public decoration group during the
        #: collector traversal.  The public Axes API has no axis-off getter,
        #: so the observed callback stream is the source of truth.
        self._decorated_axes: list[bool] = []
        #: Public mplot3d facts collected from one eligible Axes3D.
        self._three_d_axes: list[Axes3D] = []
        self._three_d_view_facts: dict[int, dict[str, Any]] = {}
        self._three_d_collection_styles: dict[int, dict[str, Any]] = {}
        self._three_d_events: list[tuple[str, dict]] = []

    def unsupported(self, reason: str, type_context: str | None = None) -> None:
        self.reasons.append((type_context, reason))


    # -- stage two: public RendererBase collector ------------------------

    def collect(
        self,
        figure: matplotlib.figure.Figure,
        *,
        width_px: int | None = None,
        height_px: int | None = None,
        dpi: float | None = None,
    ) -> None:
        """Run one collector traversal through a public RendererBase.

        Asserts the exact eligible trace of ADR 0015 §4: one
        figure-background ``draw_path`` plus one single-stroke
        ``draw_path`` per whitelisted Line2D, with the figure/patch/axes/
        line2d group structure and per-artist ``new_gc`` calls. Since the
        PRAC-A-W wire-up the trace also admits one ``draw_text`` callback
        per statically enumerated major tick label, cross-checked against
        that label's public string/font size/rotation. Since B-2a (R2)
        it additionally admits one ``draw_text`` per visible non-empty
        ``xlabel``/``ylabel``, in per-axis draw order (xlabel after its
        x-ticks, ylabel after its y-ticks). Since B-2a (R3) it
        additionally admits one ``draw_text`` for the visible non-empty
        center title, after its axes' tick and axis labels. Since PRAC-A-L it
        additionally admits, per whitelisted legend, the rounded frame
        patch stroke and one handle stroke per entry (validated and
        converted into seam-ready commands keyed by legend identity).
        Only the strokes emitted inside a ``line2d`` group are content
        lines; any other renderer callback or unexpected path shape
        records an unsupported reason; nothing is silently ignored.
        """
        from matplotlib.backend_bases import RendererBase

        # Record the effective geometry before any traversal: legend
        # strokes are converted into seam-ready commands during this
        # method, and their full-canvas clip needs the real pixel size
        # (``build_frame_spec`` re-states the same values afterwards).
        if height_px is not None:
            self._height_px = int(height_px)
        if width_px is not None:
            self._canvas_width_px = int(width_px)
        if dpi is not None:
            self._effective_dpi = float(dpi)

        collected: list[tuple] = []
        self._three_d_events = []
        self._three_d_view_facts = dict(self._three_d_view_facts)
        self._expected_legend_shapes = [
            (
                bool(legend.get_frame_on()),
                len(legend.get_lines()),
            )
            for ax in figure.get_axes()
            if type(ax) is matplotlib.axes.Axes
            for legend in (ax.get_legend(),)
            if type(legend) is matplotlib.legend.Legend
        ]

        collector_cls = self._make_grammar_collector(
            collected,
            [],
            float(
                self._canvas_width_px if width_px is None else width_px
            ),
            float(self._height_px if height_px is None else height_px),
            float(self._effective_dpi if dpi is None else dpi),
        )
        for name in ("open_group", "close_group", "new_gc",
                     self._ELIGIBLE_CALLBACKS[0]):
            if not hasattr(RendererBase, name):  # pragma: no cover - defensive
                self.unsupported(f"renderer callback {name} unavailable")
                return
        try:
            collector_instance = collector_cls()
            figure.draw(collector_instance)
        except NotImplementedError as error:
            message = str(error) or "unknown"
            self.unsupported(
                f"renderer callback {message} is outside the eligible trace"
            )
            return

        if not collected:
            self.unsupported("no drawable content observed", "Figure")
            return
        if not self._reconcile_text_events(figure, collected):
            return
        if not self._consume_trace(collected):
            return

        for ax_index, ax in enumerate(figure.get_axes()):
            decorated = (
                ax_index < len(self._decorated_axes)
                and self._decorated_axes[ax_index]
            )
            self._check_axes_decorations(ax, decorated=decorated)
        if self.reasons:
            return

        line_calls: list[dict] = []
        fill_calls: list[dict] = []
        text_calls: list[dict] = []
        background_call: dict | None = None
        idx = 0
        total = len(collected)
        events = collected
        stack: list[str] = []
        # Draw-order position of the innermost open axes group. The
        # validated trace opens axes groups only at figure>patch depth and
        # never nests them, so this ordinal is the axes' position in
        # ``Figure.get_axes``; it keys the per-axes clip reconciliation.
        current_axes = -1

        while idx < total:
            kind = events[idx][0]
            if kind == "open":
                tag = events[idx][1]
                # Top-level axes groups open straight under the figure
                # group (the figure patch has already closed by then);
                # nothing else may claim the ordinal.
                if tag == "axes" and stack == ["figure"]:
                    current_axes += 1
                stack.append(tag)
                idx += 1
                continue
            if kind == "close":
                tag = events[idx][1]
                idx += 1
                if not stack or stack.pop() != tag:
                    self.unsupported(
                        f"unbalanced close({tag!r}) in the collector trace"
                    )
                    return
                continue
            if kind == "new_gc":
                idx += 1
                continue
            if kind == "draw_path":
                call = events[idx][1]
                idx += 1
                # The figure background stroke sits in figure > patch;
                # content and tick-mark line2d groups sit deeper in the
                # tree. Only these shapes are eligible.
                if (
                    len(stack) == 2
                    and stack[0] == "figure"
                    and stack[1] == "patch"
                ):
                    if background_call is not None:
                        if self._three_d_axes:
                            # Axes3D's figure-scope patch is a structural
                            # duplicate of the canvas background in axis-off
                            # mode; the grammar consumes it separately.
                            continue
                        self.unsupported(
                            "multiple figure-background strokes are "
                            "outside the eligible trace"
                        )
                        return
                    background_call = call
                    continue
                if (
                    len(stack) >= 4
                    and stack[-1] == "patch"
                    and stack[-2] == "legend"
                ):
                    # The legend frame outline (PRAC-A-L): a rounded
                    # FancyBboxPatch path already transformed into
                    # display space by ``Legend.draw``. Dispatched before
                    # the generic patch branch, whose polygon-only fill
                    # contract does not apply to this sanctioned shape.
                    self._legend_frame_calls.append(call)
                    continue
                if len(stack) >= 3 and stack[-1] in (
                    "patch",
                    "FillBetweenPolyCollection",
                ):
                    # Patch-shaped groups carry three kinds of strokes:
                    # LP-FUNC-032 fill content, the transparent axes
                    # background, and the spine-edge decoration strokes.
                    # All three are validated here; the geometry assembly
                    # re-derives decorations from public getters.
                    if any(part == "axes" for part in stack[:-1]):
                        if stack[-1] == "FillBetweenPolyCollection":
                            # A fill-between collection group: every
                            # draw_path inside is fill content; the
                            # enclosing axes group keys the per-axes clip
                            # reconciliation.
                            call["axes_position"] = current_axes
                            fill_calls.append(call)
                            continue
                        gc = call["gc"]
                        is_axes_background = (
                            stack[-2] == "axes"
                            and gc.get_linewidth() == 0.0
                            and call["rgbFace"] is None
                            and len(call["path"].vertices) == 5
                        )
                        if is_axes_background:
                            # The transparent axes-background fill: no clip
                            # is required for a zero-width full-frame fill.
                            continue
                        has_clip = gc.get_clip_rectangle() is not None
                        is_spine = (
                            stack[-2] == "axes"
                            and call["rgbFace"] is None
                            and len(call["path"].vertices) == 2
                            and not has_clip
                        )
                        if is_spine:
                            # Spine decoration stroke: validated by the
                            # targeted static decoration walk.
                            continue
                        # Everything else under axes > patch with a real
                        # facecolor is user fill content (LP-FUNC-032); the
                        # enclosing axes group keys the per-axes clip
                        # reconciliation.
                        call["axes_position"] = current_axes
                        fill_calls.append(call)
                        continue
                    self.unsupported(
                        "a patch stroke outside an axes is outside "
                        "the eligible trace"
                    )
                    return
                if len(stack) >= 3 and stack[-1] == "line2d":
                    if any(part == "axes" for part in stack[:-1]):
                        if stack[-2] == "axes":
                            # A direct content line of this axes; the
                            # enclosing axes group keys the per-axes clip
                            # reconciliation.
                            call["axes_position"] = current_axes
                            line_calls.append(call)
                            if self._three_d_axes:
                                self._three_d_events.append(("line", call))
                        elif stack[-2] == "legend":
                            # A legend handle stroke (PRAC-A-L): the
                            # proxy Line2D's path in handlebox-local
                            # coordinates with its layout affine.
                            self._legend_handle_calls.append(call)
                        else:
                            # Tick-mark strokes are validated by the
                            # targeted decoration walk, not here.
                            pass
                        continue
                    self.unsupported(
                        f"a line2d stroke under {stack[-2]!r} (no axes "
                        "ancestor) is outside the eligible trace"
                    )
                    return
                self.unsupported(
                    "a draw_path outside the figure patch and line2d "
                    "groups is outside the eligible trace"
                )
                return
            if kind == "draw_path_collection":
                payload = events[idx][1]
                idx += 1
                if stack and stack[-1] == "Poly3DCollection":
                    self._three_d_events.append(("poly", payload))
                    continue
                self.unsupported(
                    "a path collection outside Poly3DCollection is "
                    "outside the eligible trace",
                    stack[-1] if stack else "Figure",
                )
                return
            if kind == "draw_text":
                payload = events[idx][1]
                idx += 1
                text_calls.append(payload)
                continue
            if kind == "draw_text_unexpected":
                payload = events[idx][1]
                idx += 1
                expected = payload.get("expected")
                if expected is None:
                    self.unsupported(
                        "an unexpected draw_text callback (no statically "
                        f"accepted label remains): {payload.get('text')!r}",
                        "Text",
                    )
                else:
                    self.unsupported(
                        "the draw_text callback for an accepted text "
                        f"label changed at draw time: expected {expected!r}, got "
                        f"{payload.get('text')!r}",
                        "Text",
                    )
                return
            self.unsupported(f"unexpected {kind!r} event in the trace")
            return

        if stack:
            self.unsupported("a collector group is left open")
            return

        self._observed_text_payloads = text_calls

        # -- legend strokes (PRAC-A-L) ------------------------------------
        # The static stage already proved each legend's frame patch,
        # handles, and labels satisfy the style contracts. Here the
        # collected geometry is validated (affine-only, expected shapes)
        # and converted into seam-ready path commands keyed by legend
        # identity, so ``build_frame_spec`` can emit each legend bundle at
        # the Legend artist's real public zorder inside the axes' stable
        # D1 sort, preserving D2 interleaving with decorations/content.
        for call in self._legend_frame_calls:
            self._check_legend_frame_call(call)
        if not self.reasons:
            for call in self._legend_handle_calls:
                self._check_legend_handle_call(call)
        if not self.reasons:
            self._build_legend_payloads(figure)

        if background_call is None:
            self.unsupported("no drawable content observed", "Figure")
            return
        first = background_call
        background = first["rgbFace"]
        if background is None:
            self.unsupported("first draw_path is not a filled background")
        elif len(first["path"].vertices) != 5:
            self.unsupported("figure background is not a closed rectangle")
        else:
            self.background_seen = True
            self.background_rgbface = background
            self._check_background_style(first)

        for call in line_calls:
            self.line_paths += 1
            self._check_line_call(call, call["axes_position"])
        for call in fill_calls:
            self.fill_paths += 1
            self._check_fill_call(call, call["axes_position"])
        if self._three_d_axes:
            for kind, payload in self._three_d_events:
                if kind == "poly":
                    self._check_poly3d_callback(payload)
        if not line_calls and not fill_calls and not self._three_d_events:
            self.unsupported("no drawable content observed", "Figure")
