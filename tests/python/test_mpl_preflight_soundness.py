"""LP-MPL-021 strict-preflight soundness and fallback fixtures.

AT-MPL-PREFLIGHT-SOUNDNESS requires every Figure outside the selected native
surface to fail explicitly in strict mode before any native seam or target
write.  The same Figures may succeed in hybrid mode only through one
whole-frame Agg render with exactly one structured diagnostic.
"""

from __future__ import annotations

import io
import unittest
import unittest.mock

import matplotlib

matplotlib.use("Agg")

from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

import lumenplot_mpl.backend as backend_mod  # noqa: E402


_UNSUPPORTED_SCALE_CASES = ("unsupported-x-scale", "unsupported-y-scale")
_INVERTED_LIMIT_CASES = ("inverted-x-limits", "inverted-y-limits")
_GEOMETRY_REFUSAL_CASE = "zero-projected-content"


class _NativeTrap:
    """Fail loudly if an unrepresentable frame reaches the native seam."""

    def __init__(self) -> None:
        self.calls = 0

    def render_frame_png(self, spec: dict) -> bytes:
        self.calls += 1
        raise AssertionError(f"unrepresentable frame reached native seam: {spec!r}")


class _RecordingTarget:
    """Record every external write attempted by the adapter."""

    def __init__(self) -> None:
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> int:
        payload = bytes(data)
        self.writes.append(payload)
        return len(payload)


def _build_figure(case: str) -> Figure:
    """Build one public-API Figure for a required soundness refusal."""

    figure = Figure(figsize=(2.0, 1.0), dpi=100)
    axes = figure.add_axes([0.1, 0.1, 0.8, 0.8])
    axes.set_axis_off()

    if case == _GEOMETRY_REFUSAL_CASE:
        xdata = [float("nan"), float("nan")]
        ydata = [1.0, 2.0]
    else:
        xdata = [1.0, 10.0]
        ydata = [1.0, 5.0]

    axes.add_line(
        Line2D(
            xdata,
            ydata,
            color="red",
            linewidth=2.0,
            solid_capstyle="butt",
            solid_joinstyle="miter",
        )
    )
    axes.set_xlim(1.0, 10.0)
    axes.set_ylim(1.0, 5.0)

    if case == "unsupported-x-scale":
        axes.set_xscale("symlog")
    elif case == "unsupported-y-scale":
        axes.set_yscale("symlog")
    elif case == "inverted-x-limits":
        axes.invert_xaxis()
    elif case == "inverted-y-limits":
        axes.invert_yaxis()
    elif case != _GEOMETRY_REFUSAL_CASE:
        raise AssertionError(f"unknown soundness fixture: {case}")

    return figure


def _direct_agg_png(case: str) -> bytes:
    """Render an independently constructed copy through public Agg APIs."""

    figure = _build_figure(case)
    FigureCanvasAgg(figure)
    target = io.BytesIO()
    figure.savefig(target, format="png", dpi=100)
    return target.getvalue()


class TestStrictPreflightSoundness(unittest.TestCase):
    """Strict refusals are explicit and occur before all output surfaces."""

    def _assert_refused_before_output(
        self,
        case: str,
        *,
        message: str,
        type_context: str,
    ) -> None:
        figure = _build_figure(case)
        canvas = backend_mod.FigureCanvasLumenPlot(figure, mode="strict")
        target = _RecordingTarget()
        native = _NativeTrap()

        with unittest.mock.patch.object(
            backend_mod, "_native", return_value=native
        ) as native_loader:
            with self.assertRaises(
                backend_mod.LumenPlotUnsupportedError
            ) as caught:
                canvas.render_png(target)

        self.assertEqual(caught.exception.code, "unsupported-capability")
        self.assertEqual(caught.exception.type_context, type_context)
        self.assertIn(message, str(caught.exception))
        self.assertEqual(target.writes, [], "strict refusal wrote PNG bytes")
        native_loader.assert_not_called()
        self.assertEqual(native.calls, 0)
        self.assertEqual(canvas.last_diagnostics, ())
        self.assertIs(figure.canvas, canvas)

    def test_unsupported_scale_classes_refuse_without_png(self) -> None:
        for case in _UNSUPPORTED_SCALE_CASES:
            with self.subTest(case=case):
                self._assert_refused_before_output(
                    case,
                    message="scale",
                    type_context="Axes",
                )

    def test_inverted_limit_pairs_refuse_without_png(self) -> None:
        for case in _INVERTED_LIMIT_CASES:
            with self.subTest(case=case):
                self._assert_refused_before_output(
                    case,
                    message="increasing x/y limits",
                    type_context="Axes",
                )

    def test_geometry_refusal_with_zero_content_refuses_without_png(self) -> None:
        self._assert_refused_before_output(
            _GEOMETRY_REFUSAL_CASE,
            message="fewer than two finite points",
            type_context="Line2D",
        )


class TestHybridPreflightSoundness(unittest.TestCase):
    """Hybrid success is one whole-frame Agg result, never partial native."""

    def _assert_whole_frame_agg_fallback(
        self,
        case: str,
        *,
        type_context: str,
    ) -> None:
        expected_png = _direct_agg_png(case)
        figure = _build_figure(case)
        canvas = backend_mod.FigureCanvasLumenPlot(figure, mode="hybrid")
        native = _NativeTrap()
        agg_calls: list[Figure] = []
        real_savefig = Figure.savefig

        def spy_savefig(subject: Figure, *args, **kwargs):
            agg_calls.append(subject)
            return real_savefig(subject, *args, **kwargs)

        with (
            unittest.mock.patch.object(
                backend_mod, "_native", return_value=native
            ) as native_loader,
            unittest.mock.patch.object(Figure, "savefig", spy_savefig),
        ):
            result = canvas.render_png()

        self.assertEqual(agg_calls, [figure])
        native_loader.assert_not_called()
        self.assertEqual(native.calls, 0)
        self.assertEqual(result.png_bytes, expected_png)
        self.assertTrue(result.png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(len(result.diagnostics), 1)
        diagnostic = result.diagnostics[0]
        self.assertIsInstance(
            diagnostic, backend_mod.LumenPlotFallbackDiagnostic
        )
        self.assertEqual(diagnostic.kind, "unsupported-capability")
        self.assertEqual(diagnostic.type, type_context)
        self.assertEqual(diagnostic.output_format, "png")
        self.assertEqual(diagnostic.scope, "whole-frame")
        self.assertEqual(diagnostic.representation, "raster")
        self.assertEqual(diagnostic.fallback_type, "matplotlib-agg")
        self.assertEqual(diagnostic.generation, 1)
        self.assertEqual(canvas.last_diagnostics, result.diagnostics)
        self.assertIs(figure.canvas, canvas)

    def test_unsupported_scale_classes_use_one_whole_frame_fallback(self) -> None:
        for case in _UNSUPPORTED_SCALE_CASES:
            with self.subTest(case=case):
                self._assert_whole_frame_agg_fallback(
                    case,
                    type_context="Axes",
                )

    def test_inverted_limit_pairs_use_one_whole_frame_fallback(self) -> None:
        for case in _INVERTED_LIMIT_CASES:
            with self.subTest(case=case):
                self._assert_whole_frame_agg_fallback(
                    case,
                    type_context="Axes",
                )

    def test_zero_content_refusal_uses_one_whole_frame_fallback(self) -> None:
        self._assert_whole_frame_agg_fallback(
            _GEOMETRY_REFUSAL_CASE,
            type_context="Line2D",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
