"""LP-MPL-022 public unit-conversion consumption tests.

The adapter must consume Matplotlib's public processed-data getters rather than
reimplementing unit conversion. These fixtures use a small public Matplotlib
unit converter to pin calibrated numeric geometry, preserve Figure authority,
and reject a conversion result that cannot enter the native f64 seam.

Offline cells without Matplotlib or NumPy skip the runtime fixtures.
"""

from __future__ import annotations

import struct
import unittest
import unittest.mock
from typing import Any

try:
    import matplotlib
except ModuleNotFoundError:  # offline cells
    matplotlib = None
else:
    matplotlib.use("module://matplotlib.backends.backend_agg")

    from matplotlib import figure, units
    from matplotlib.lines import Line2D

try:
    import numpy
except ModuleNotFoundError:  # pragma: no cover - offline cells
    numpy = None


MATPLOTLIB_PRESENT = matplotlib is not None
NUMPY_PRESENT = numpy is not None
_Line2DBase = Line2D if MATPLOTLIB_PRESENT else object


class _CalibratedValue:
    """Raw value requiring a public Matplotlib unit conversion."""

    __slots__ = ("value",)

    def __init__(self, value: float) -> None:
        self.value = float(value)


class _CalibratedConverter(units.ConversionInterface if MATPLOTLIB_PRESENT else object):
    """Convert calibrated samples to the numeric values used by Agg."""

    @staticmethod
    def convert(value: Any, unit: Any, axis: Any) -> Any:
        del unit, axis
        if isinstance(value, _CalibratedValue):
            return value.value
        return numpy.asarray([item.value for item in value], dtype=float)

    @staticmethod
    def default_units(value: Any, axis: Any) -> str | None:
        del axis
        if isinstance(value, _CalibratedValue):
            return "calibrated"
        try:
            values = list(value)
        except TypeError:
            values = [value]
        if any(isinstance(item, _CalibratedValue) for item in values):
            return "calibrated"
        return None

    @staticmethod
    def axisinfo(unit: Any, axis: Any) -> None:
        del unit, axis
        return None


class _UnrepresentableValue:
    """Marker returned by the negative converter fixture."""


class _UnrepresentableProcessedLine(_Line2DBase):
    """Line whose public processed getter exposes an invalid native value."""

    def get_xdata(self, orig: bool = True) -> Any:
        if not orig:
            return numpy.asarray(
                [0.0, _UnrepresentableValue(), 10.0], dtype=object
            )
        return super().get_xdata(orig=orig)


class _StubNative:
    last_spec: dict | None = None

    @staticmethod
    def render_frame_png(spec: dict) -> bytes:
        _StubNative.last_spec = spec
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            + struct.pack(">IIBBBBB", spec["width_px"], spec["height_px"], 8, 6, 0, 0, 0)
            + b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )


def _backend_module():
    import importlib

    return importlib.import_module("lumenplot_mpl.backend")


def _calibrated_canvas():
    fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
    canvas = _backend_module().FigureCanvasLumenPlot(fig)
    ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
    ax.axison = False
    line, = ax.plot(
        [
            _CalibratedValue(0.0),
            _CalibratedValue(5.0),
            _CalibratedValue(10.0),
        ],
        [1.0, 3.0, 2.0],
        color="red",
        linewidth=2.0,
        solid_capstyle="butt",
        solid_joinstyle="miter",
    )
    ax.set_xlim(_CalibratedValue(0.0), _CalibratedValue(10.0))
    ax.set_ylim(0.0, 4.0)
    return fig, canvas, ax, line


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and NUMPY_PRESENT,
    "matplotlib/numpy not in this offline cell",
)
class TestCalibratedUnitGeometry(unittest.TestCase):
    def setUp(self) -> None:
        _StubNative.last_spec = None
        self.backend = _backend_module()
        self.previous = units.registry.get(_CalibratedValue)
        units.registry[_CalibratedValue] = _CalibratedConverter()
        self.addCleanup(self._restore_registry)
        self.patcher = unittest.mock.patch.object(
            self.backend, "_native", lambda: _StubNative
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def _restore_registry(self) -> None:
        if self.previous is None:
            units.registry.pop(_CalibratedValue, None)
        else:
            units.registry[_CalibratedValue] = self.previous

    def test_processed_calibrated_data_matches_public_axes_transform(self) -> None:
        """Converted numeric values drive native geometry, not raw objects."""
        fig, canvas, ax, line = _calibrated_canvas()
        raw_before = list(line.get_xdata(orig=True))
        limits_before = (ax.get_xlim(), ax.get_ylim())
        processed = numpy.asarray(line.get_xdata(orig=False), dtype=float)
        self.assertTrue(numpy.isfinite(processed).all())
        self.assertTrue(all(isinstance(item, _CalibratedValue) for item in raw_before))

        result = canvas.render_png()

        self.assertEqual(result.diagnostics, ())
        self.assertEqual((ax.get_xlim(), ax.get_ylim()), limits_before)
        self.assertEqual(list(line.get_xdata(orig=True)), raw_before)
        self.assertIsNotNone(_StubNative.last_spec)
        line_command = next(
            command
            for command in _StubNative.last_spec["commands"]
            if command.get("stroke_rgba") == [255, 0, 0, 255]
        )
        expected = ax.transData.transform(
            numpy.column_stack((processed, [1.0, 3.0, 2.0]))
        )
        numpy.testing.assert_allclose(line_command["vertices"], expected, rtol=0.0, atol=1e-12)


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and NUMPY_PRESENT,
    "matplotlib/numpy not in this offline cell",
)
class TestUnrepresentableUnitData(unittest.TestCase):
    def setUp(self) -> None:
        _StubNative.last_spec = None
        self.backend = _backend_module()
        self.patcher = unittest.mock.patch.object(
            self.backend, "_native", lambda: _StubNative
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_unrepresentable_conversion_is_explicitly_refused(self) -> None:
        fig = figure.Figure(figsize=(2.0, 1.0), dpi=100)
        canvas = self.backend.FigureCanvasLumenPlot(fig)
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        ax.axison = False
        line = _UnrepresentableProcessedLine(
            [0.0, 5.0, 10.0],
            [1.0, 3.0, 2.0],
            color="red",
            linewidth=2.0,
            solid_capstyle="butt",
            solid_joinstyle="miter",
        )
        ax.add_line(line)
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(0.0, 4.0)

        with self.assertRaises(self.backend.LumenPlotUnsupportedError) as context:
            canvas.render_png()

        self.assertEqual(context.exception.code, "unsupported-capability")
        self.assertIn("not representable as native f64", str(context.exception))
        self.assertIsNone(_StubNative.last_spec)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
