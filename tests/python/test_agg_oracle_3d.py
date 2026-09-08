"""AT-FUNC-3D fixtures and explicit adapter eligibility evidence."""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from ._agg_oracle import (
        compare_pngs,
        load_reference_fixture,
    )
    from .generate_agg_oracle_3d import (
        CASES,
        FIXTURE_DIR,
        build_fixture,
        check_fixture,
        render_reference,
    )
except ImportError:  # unittest discover -s tests/python
    from _agg_oracle import compare_pngs, load_reference_fixture
    from generate_agg_oracle_3d import (
        CASES,
        FIXTURE_DIR,
        build_fixture,
        check_fixture,
        render_reference,
    )


class TestCommitted3DOracleFixtures(unittest.TestCase):
    def test_committed_fixtures_regenerate_byte_for_byte(self):
        for case in CASES:
            with self.subTest(case=case):
                check_fixture(case)

    def test_projection_view_bounds_origin_and_fixed_budget_are_recorded(self):
        for case, config in CASES.items():
            with self.subTest(case=case):
                manifest = load_reference_fixture(
                    FIXTURE_DIR / config["manifest"]
                ).manifest
                facts = manifest["three_d"]
                self.assertEqual(
                    facts["projection"], config["projection"]
                )
                self.assertEqual(
                    facts["view"],
                    {
                        "elevation_deg": 30.0,
                        "azimuth_deg": -60.0,
                        "roll_deg": 0.0,
                        "focal_length": (
                            1.0 if config["projection"] == "perspective" else None
                        ),
                    },
                )
                self.assertEqual(
                    facts["bounds_f64"],
                    {"x": [0.0, 3.0], "y": [0.0, 2.0], "z": [0.0, 2.0]},
                )
                self.assertEqual(facts["scene_origin_f64"], [1.5, 1.0, 1.0])
                self.assertEqual(facts["error_budget_px"], 0.25)
                self.assertLessEqual(facts["worst_error_px"], 0.25)

    def test_line_fixture_preserves_nonfinite_run_boundaries(self):
        manifest = load_reference_fixture(
            FIXTURE_DIR / CASES["line3d_perspective"]["manifest"]
        ).manifest
        topology = manifest["topology"]
        self.assertEqual(topology["line_data_api"], "Line3D.get_data_3d()")
        self.assertEqual(topology["finite_segments"][-1], [[0, 2], [5, 7]])
        self.assertEqual(topology["nonfinite_tokens"], ["NaN", "+Inf", "-Inf"])

    def test_poly_fixture_records_triangle_order_and_element_styles(self):
        manifest = load_reference_fixture(
            FIXTURE_DIR / CASES["poly3d_perspective"]["manifest"]
        ).manifest
        primitive = manifest["primitive"]
        self.assertEqual(len(primitive["triangles"]), 2)
        self.assertEqual(len(primitive["facecolors"]), 2)
        self.assertEqual(len(primitive["edgecolors"]), 2)
        self.assertEqual(primitive["linewidths"], [1.0, 1.75])
        self.assertEqual(manifest["three_d"]["painter_order"], [0, 1])
        self.assertIn("per-element", manifest["three_d"]["triangle_style_semantics"])

    def test_reference_comparator_accepts_each_pinned_image(self):
        for case, config in CASES.items():
            with self.subTest(case=case):
                fixture = load_reference_fixture(
                    FIXTURE_DIR / config["manifest"]
                )
                report = compare_pngs(
                    fixture.reference_png,
                    fixture.reference_png,
                    fixture.mask,
                    manifest=fixture.manifest,
                )
                self.assertTrue(report.passed, report.summary())
                self.assertEqual(report.max_channel_delta, 0)
                self.assertEqual(report.mismatch_count, 0)
    def test_native_adapter_pixels_match_each_pinned_fixture(self):
        """Exercise the real Rust seam, not only the captured spec."""
        from lumenplot_mpl import backend

        for case, config in CASES.items():
            with self.subTest(case=case):
                figure, _axes, _lines, _collection = build_fixture(case)
                result = backend.FigureCanvasLumenPlot(
                    figure, mode="strict"
                ).render_png()
                fixture = load_reference_fixture(
                    FIXTURE_DIR / config["manifest"]
                )
                report = compare_pngs(
                    fixture.reference_png,
                    result.png_bytes,
                    fixture.mask,
                    manifest=fixture.manifest,
                )
                self.assertEqual(result.diagnostics, ())
                self.assertTrue(report.passed, report.summary())


class Test3DAdapterNativeSpec(unittest.TestCase):
    @staticmethod
    def _capture_spec(case: str):
        from lumenplot_mpl import backend

        figure, _axes, _lines, _collection = build_fixture(case)
        canvas = backend.FigureCanvasLumenPlot(figure, mode="strict")
        captured: list[dict] = []

        def capture(spec, _generation):
            captured.append(spec)
            return b"native-test-png"

        with patch.object(canvas, "_call_native", side_effect=capture):
            result = canvas.render_png()
        return result, captured[0]

    def test_line3d_spec_keeps_f64_source_and_gap_semantics(self):
        result, spec = self._capture_spec("line3d_perspective")
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(spec["semantic_3d"]["projection"], "perspective")
        self.assertEqual(spec["semantic_3d"]["bounds"], [[0.0, 3.0], [0.0, 2.0], [0.0, 2.0]])
        self.assertEqual(spec["semantic_3d"]["scene_origin"], [1.5, 1.0, 1.0])
        self.assertEqual(spec["semantic_3d"]["line_segments"][-1], [[0, 2], [5, 7]])
        self.assertEqual(
            sum(command["artist_class"] == "Line3D" for command in spec["commands"]),
            4,
        )

    def test_poly3d_spec_preserves_projected_painter_order_and_styles(self):
        result, spec = self._capture_spec("poly3d_perspective")
        self.assertEqual(result.diagnostics, ())
        poly_commands = [
            command
            for command in spec["commands"]
            if command["artist_class"] == "Poly3DCollection"
        ]
        self.assertEqual(len(poly_commands), 2)
        self.assertEqual(spec["semantic_3d"]["painter_order"], [0, 1])
        self.assertEqual(poly_commands[0]["line_width_pt"], 1.0)
        self.assertEqual(poly_commands[1]["line_width_pt"], 1.75)
        self.assertIsNotNone(poly_commands[0]["fill_rgba"])
        self.assertIsNotNone(poly_commands[1]["fill_rgba"])
        for command in poly_commands:
            self.assertEqual(
                command["codes"], [1, 2, 2, 79]
            )
            self.assertGreater(command["clip_rect"][2], 0.0)
            self.assertGreater(command["clip_rect"][3], 0.0)

    def test_orthographic_surface_is_explicit_not_inferred_default(self):
        result, spec = self._capture_spec("poly3d_orthographic")
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(spec["semantic_3d"]["projection"], "orthographic")
        self.assertIsNone(spec["semantic_3d"]["focal_length"])


class Test3DRefusalAndFallback(unittest.TestCase):
    def _build_axis_on_figure(self):
        figure, axes, _lines, _collection = build_fixture("line3d_perspective")
        axes.set_axis_on()
        return figure

    def test_strict_refuses_axis_decorations_before_native_call(self):
        from lumenplot_mpl import backend

        canvas = backend.FigureCanvasLumenPlot(
            self._build_axis_on_figure(), mode="strict"
        )
        target = io.BytesIO()
        with patch.object(canvas, "_call_native") as native:
            with self.assertRaises(backend.LumenPlotUnsupportedError) as caught:
                canvas.render_png(target)
        self.assertEqual(caught.exception.code, "unsupported-capability")
        self.assertEqual(target.getvalue(), b"")
        native.assert_not_called()
        self.assertEqual(canvas.last_diagnostics, ())

    def test_hybrid_uses_one_whole_frame_agg_fallback_for_axis_on(self):
        from lumenplot_mpl import backend

        figure = self._build_axis_on_figure()
        canvas = backend.FigureCanvasLumenPlot(figure, mode="hybrid")
        expected = io.BytesIO()
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        FigureCanvasAgg(figure).print_png(expected, metadata={})
        result = canvas.render_png()
        self.assertEqual(result.png_bytes, expected.getvalue())
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(result.diagnostics[0].scope, "whole-frame")
        self.assertEqual(result.diagnostics[0].fallback_type, "matplotlib-agg")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
