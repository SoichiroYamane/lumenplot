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

    def test_supported_strided_views_render_like_dense_copies(self) -> None:
        # API-0003 accepts safe positive, negative, and zero logical strides
        # and traverses them in logical order, so reversed, broadcast, and
        # strided-in-bounds views must render exactly like their dense
        # contiguous copies.
        dense_x = np.arange(4.0, dtype=np.float64)
        y = np.array([0.0, 2.0, 1.0, 3.0], dtype=np.float64)
        view_cases = (
            dense_x[::-1],
            np.broadcast_to(np.array([1.0], dtype=np.float64), (4,)),
            np.arange(8.0, dtype=np.float64)[::2],
        )
        for x in view_cases:
            with self.subTest(strides=x.strides):
                rendered = self.render(x, y)
                self.assertEqual(rendered[:8], b"\x89PNG\r\n\x1a\n")
                self.assertGreater(len(rendered), 8)
                dense = self.render(np.ascontiguousarray(x), y)
                self.assertEqual(rendered, dense)

    def test_out_of_root_bounds_spans_are_rejected_with_sanitized_errors(
        self,
    ) -> None:
        # Reads are bounded by the root allocation: a far-stride view whose
        # element addresses escape the backing buffer is rejected, and a
        # malformed zero-length buffer view produces either a sanitized
        # invalid-input diagnostic or a harmless accept — never a Rust panic
        # or memory fault.
        far_stride = np.lib.stride_tricks.as_strided(
            np.array([1.0], dtype=np.float64),
            shape=(2,),
            strides=(10**9,),
        )
        with self.assertRaises(LumenPlotError) as context:
            self.render(far_stride, np.zeros(2, dtype=np.float64))
        self.assertEqual(context.exception.code, "invalid-input")
        self.assertEqual(context.exception.category, "input")

        zero_length = np.frombuffer(
            bytearray(16), dtype=np.float64, count=0, offset=1
        )
        try:
            rendered = self.render(zero_length, zero_length.copy())
        except LumenPlotError as error:
            self.assertEqual(error.code, "invalid-input")
        else:
            self.assertIsInstance(rendered, bytes)

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
