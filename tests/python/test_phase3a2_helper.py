import unittest

import numpy as np

from lumenplot_mpl import LumenPlotError
from lumenplot_mpl import _native


class NativeLinePngTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kwargs = {
            "viewport": (0.0, 4.0, 0.0, 4.0),
            "canvas": (64.0, 64.0),
            "plot_rect": (4.0, 4.0, 60.0, 60.0),
            "logical_units_per_inch": 72.0,
            "output_dpi": 72.0,
            "line_rgba": (10, 20, 30, 255),
            "line_width": 1.0,
            "background_rgba": (255, 255, 255, 255),
        }

    def render(self, x: np.ndarray, y: np.ndarray, **overrides: object) -> bytes:
        options = self.kwargs | overrides
        return _native.render_line_png(x, y, **options)

    def test_success_returns_png_and_accepts_supported_views(self) -> None:
        x = np.array([0.0, 1.0, 2.0], dtype=np.float64)
        y = np.array([0.0, 2.0, 1.0], dtype=np.float64)
        x_before = x.copy()
        y_before = y.copy()
        self.assertTrue(self.render(x, y).startswith(b"\x89PNG\r\n\x1a\n"))
        np.testing.assert_array_equal(x, x_before)
        np.testing.assert_array_equal(y, y_before)

    def test_non_dense_views_are_rejected_with_explicit_diagnostic(self) -> None:
        # The helper reads one dense forward byte span per array. Strided,
        # reversed, and broadcast views are rejected instead of being read
        # through their logical iteration order.
        cases = (
            np.arange(4.0, dtype=np.float64)[::-1],
            np.broadcast_to(np.array([1.0], dtype=np.float64), (4,)),
            np.arange(8.0, dtype=np.float64)[::2],
        )
        for x in cases:
            with self.subTest(strides=x.strides):
                with self.assertRaises(LumenPlotError) as context:
                    self.render(x, np.zeros(x.shape[0], dtype=np.float64))
                self.assertEqual(context.exception.code, "invalid-input")
                self.assertEqual(context.exception.category, "input")
                self.assertIn("dense", context.exception.message)

    def test_nan_values_form_gaps_but_infinity_is_rejected(self) -> None:
        result = self.render(
            np.array([0.0, np.nan, 2.0]),
            np.array([0.0, 1.0, 2.0]),
        )
        self.assertEqual(result[:8], b"\x89PNG\r\n\x1a\n")
        with self.assertRaises(LumenPlotError) as context:
            self.render(np.array([0.0, np.inf]), np.array([0.0, 1.0]))
        self.assertEqual(context.exception.code, "invalid-input")

    def test_input_contract_rejects_coercion_and_unsupported_arrays(self) -> None:
        cases = (
            ([0.0, 1.0], np.array([0.0, 1.0])),
            (np.array([0, 1], dtype=np.int64), np.array([0.0, 1.0])),
            (np.array([[0.0, 1.0]]), np.array([0.0, 1.0])),
            (np.ma.array([0.0, 1.0], mask=[False, True]), np.array([0.0, 1.0])),
        )
        for x, y in cases:
            with self.subTest(type=type(x).__name__):
                with self.assertRaises(LumenPlotError) as context:
                    self.render(x, y)  # type: ignore[arg-type]
                self.assertEqual(context.exception.code, "invalid-input")

        class ArraySubclass(np.ndarray):
            pass

        with self.assertRaises(LumenPlotError):
            self.render(
                np.array([0.0, 1.0]).view(ArraySubclass),
                np.array([0.0, 1.0]),
            )

    def test_native_endian_and_alignment_are_checked(self) -> None:
        non_native = np.array([0.0, 1.0], dtype=">f8")
        if non_native.dtype.byteorder != "=":
            with self.assertRaises(LumenPlotError):
                self.render(non_native, np.array([0.0, 1.0]))

        unaligned = np.frombuffer(bytearray(24), dtype=np.float64, count=1, offset=1)
        with self.assertRaises(LumenPlotError):
            self.render(unaligned, np.array([0.0]))

    def test_error_properties_are_read_only_and_geometry_is_structured(self) -> None:
        with self.assertRaises(LumenPlotError) as context:
            self.render(np.array([0.0]), np.array([0.0]), plot_rect=(0.0, 0.0, 65.0, 64.0))
        error = context.exception
        self.assertEqual(error.code, "invalid-input")
        self.assertEqual(error.category, "input")
        self.assertEqual(str(error), error.message)
        with self.assertRaises(AttributeError):
            error.code = "changed"  # type: ignore[misc]

    def test_call_binding_errors_remain_type_error(self) -> None:
        with self.assertRaises(TypeError):
            _native.render_line_png(
                np.array([0.0]),
                np.array([0.0]),
                self.kwargs["viewport"],  # type: ignore[arg-type]
            )
        with self.assertRaises(TypeError):
            self.render(np.array([0.0]), np.array([0.0]), line_rgba=(1.0, 2.0, 3.0, 4.0))


if __name__ == "__main__":
    unittest.main()
