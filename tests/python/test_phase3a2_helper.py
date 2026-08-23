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

        # Views whose base chain reaches an owner with no resolvable
        # allocation (as_strided over a bare ndarray) have no trustworthy
        # root extent and must fail closed as invalid input.
        unknown_root_cases = (
            np.lib.stride_tricks.as_strided(np.array([1.0]), (2,), (8,)),
            np.lib.stride_tricks.as_strided(np.arange(4.0), (8,), (8,)),
            np.lib.stride_tricks.as_strided(np.arange(4.0)[1:], (4,), (8,)),
        )
        for x in unknown_root_cases:
            with self.subTest(shape=x.shape, strides=x.strides):
                with self.assertRaises(LumenPlotError) as context:
                    self.render(x, np.zeros(x.shape[0], dtype=np.float64))
                self.assertEqual(context.exception.code, "invalid-input")
                self.assertEqual(context.exception.category, "input")

    def test_multidimensional_root_extent_accepts_views(self) -> None:
        # The root allocation of a view chain ending in an exact N-D ndarray
        # spans the product of ALL its shape dimensions, not just shape[0]:
        # column, ravel, and fast-axis row views read elements past
        # `shape[0]` but inside the full allocation and must render exactly
        # like their dense contiguous copies instead of being rejected.
        c_plane = np.arange(8.0, dtype=np.float64).reshape(2, 4).copy()
        f_plane = np.asfortranarray(c_plane)
        cases = (
            ("C-order column view", c_plane[:, 0]),
            ("C-order ravel view", c_plane.ravel()),
            ("F-order fast-axis row view", f_plane[0]),
        )
        for name, x in cases:
            with self.subTest(case=name, shape=x.shape, strides=x.strides):
                y = np.linspace(0.0, 3.0, x.size, dtype=np.float64)
                rendered = self.render(x, y)
                self.assertEqual(rendered[:8], b"\x89PNG\r\n\x1a\n")
                self.assertGreater(len(rendered), 8)
                self.assertEqual(rendered, self.render(np.ascontiguousarray(x), y))

    def test_zero_dimensional_root_chain_never_leaks_raw_type_errors(self) -> None:
        # A 0-d root array has an empty shape: its element count is the
        # empty-product 1, so resolving the root extent must never surface a
        # raw TypeError from the Rust helper. A fully in-bounds 0-d chain
        # view may render safely, while an out-of-bounds one fails closed
        # with a sanitized invalid-input diagnostic.
        zero_d_base = np.asarray(np.float64(1.0))
        self.assertEqual(zero_d_base.shape, ())
        in_bounds = zero_d_base.reshape(1)[:]
        try:
            rendered = self.render(in_bounds, np.zeros(1, dtype=np.float64))
        except LumenPlotError as error:
            self.assertEqual(error.code, "invalid-input")
            self.assertEqual(error.category, "input")
        else:
            self.assertIsInstance(rendered, bytes)

        out_of_bounds = np.lib.stride_tricks.as_strided(
            np.asarray(np.float64(1.0)),
            shape=(2,),
            strides=(8,),
        )
        with self.assertRaises(LumenPlotError) as context:
            self.render(out_of_bounds, np.zeros(2, dtype=np.float64))
        self.assertEqual(context.exception.code, "invalid-input")
        self.assertEqual(context.exception.category, "input")

    def test_bytes_backed_views_render_like_dense_copies(self) -> None:
        # The root allocation of a bytes-backed array lives behind a
        # memoryview base, so its data pointer must come from the buffer
        # protocol rather than the owner object's address; both fixture
        # families must render identically to their dense copies.
        frombuffer_x = np.frombuffer(
            bytearray(64), dtype=np.float64, count=8  # type: ignore[call-overload]
        )
        dense_frombuffer_x = np.array(frombuffer_x, dtype=np.float64)
        y = np.linspace(0.0, 3.0, 8)

        cast_x = np.frombuffer(
            memoryview(bytearray(64)).cast("d"), dtype=np.float64  # type: ignore[arg-type]
        )

        for x, dense in (
            (frombuffer_x, dense_frombuffer_x),
            (cast_x, dense_frombuffer_x),
        ):
            with self.subTest(source=type(x.base).__name__):
                self.assertIs(type(x.base), memoryview)
                rendered = self.render(x, y)
                self.assertEqual(rendered[:8], b"\x89PNG\r\n\x1a\n")
                self.assertGreater(len(rendered), 8)
                self.assertEqual(rendered, self.render(dense, y))

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
