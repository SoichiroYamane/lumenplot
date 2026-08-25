"""PRAC-A-T lane tests: text-to-path glyph outline extraction.

Covers ``python/lumenplot_mpl/textpath.py`` (task t_1c790b2b, decisions
1-5 of the Phase-3B planning card):

- frozen frozen-seam command shape (keys, values, identity transform);
- TextPath coordinate contract verified against the installed Matplotlib:
  points, baseline y = 0, y up -- so the module's negated vertices place
  ink above the origin in top-left pixel space;
- affine application order ``x' = ox + x*s + (-y)*k`` with a real shear
  case cross-checked against an independent computation;
- determinism for identical inputs and distinctness across scales;
- failure policy: ValueError carrying the stable
  ``unsupported-text-path`` token for empty/whitespace-only text,
  non-string input, non-finite arguments, non-finite coordinates, and a
  wrong-length origin; no other exception family escapes;
- the module never imports the private seam (import-level assertion).

The real-seam rasterization probe (glyph ink lands where the contract
says) runs only when the compiled extension is importable, mirroring the
skip pattern of test_phase3b_backend.py / test_phase3b_native_authority.py.
"""

from __future__ import annotations

import math
import os
import struct
import sys
import unittest


REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    import matplotlib  # noqa: F401

    MATPLOTLIB_PRESENT = True
except ModuleNotFoundError:  # pragma: no cover - offline cells
    MATPLOTLIB_PRESENT = False

try:
    from lumenplot_mpl import _native as _native_seam
except (ImportError, AttributeError):  # extension not built in this cell
    _native_seam = None

HAS_REAL_SEAM = _native_seam is not None and callable(
    getattr(_native_seam, "render_frame_png", None)
)


def _load_module():
    import importlib

    return importlib.import_module("lumenplot_mpl.textpath")


def _require_matplotlib(testcase: unittest.TestCase) -> None:
    if not MATPLOTLIB_PRESENT:
        testcase.skipTest("matplotlib not in this offline cell")


def _png_dimensions(png_bytes: bytes) -> tuple[int, int]:
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "PNG magic missing"
    chunk = png_bytes[12:16]
    assert chunk == b"IHDR", f"first chunk is {chunk!r}, not IHDR"
    width, height = struct.unpack(">II", png_bytes[16:24])
    return int(width), int(height)


def _decode_rgba8(png_bytes: bytes) -> tuple[int, int, list[bytes]]:
    """Decode a filtered type-0 truecolor+alpha PNG into rows of RGBA."""
    width, height = _png_dimensions(png_bytes)
    offset = 8
    idat = bytearray()
    while offset < len(png_bytes):
        length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        kind = png_bytes[offset + 4 : offset + 8]
        data = png_bytes[offset + 8 : offset + 8 + length]
        if kind == b"IDAT":
            idat.extend(data)
        elif kind == b"IEND":
            break
        offset += 12 + length
    import zlib

    raw = zlib.decompress(bytes(idat))
    stride = width * 4
    rows: list[bytes] = []
    previous = bytearray(stride)
    cursor = 0
    for _ in range(height):
        filter_type = raw[cursor]
        scanline = bytearray(raw[cursor + 1 : cursor + 1 + stride])
        cursor += 1 + stride
        if filter_type == 0:
            pass
        elif filter_type == 1:  # Sub
            for i in range(4, stride):
                scanline[i] = (scanline[i] + scanline[i - 4]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                scanline[i] = (scanline[i] + previous[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = scanline[i - 4] if i >= 4 else 0
                scanline[i] = (scanline[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                a = scanline[i - 4] if i >= 4 else 0
                b = previous[i]
                c = previous[i - 4] if i >= 4 else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                predictor = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                scanline[i] = (scanline[i] + predictor) & 0xFF
        else:  # pragma: no cover - seam never emits other filters today
            raise AssertionError(f"unexpected PNG filter {filter_type}")
        rows.append(bytes(scanline))
        previous = scanline
    return width, height, rows


# ---------------------------------------------------------------------------
# Frozen command shape and coordinate contract
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestFrozenCommandShape(unittest.TestCase):
    def setUp(self):
        self.module = _load_module()

    def test_command_keys_and_fixed_values(self):
        commands = self.module.glyph_outline_commands("n", (10.0, 20.0), 1.0, 0.0)
        self.assertEqual(len(commands), 1)
        command = commands[0]
        self.assertEqual(command["kind"], "path")
        self.assertEqual(command["transform"], [1.0, 0.0, 0.0, 1.0, 0.0, 0.0])
        self.assertIsNone(command["stroke_rgba"])
        self.assertEqual(command["fill_rgba"], [0, 0, 0, 255])
        self.assertEqual(command["line_width_pt"], 0.0)
        self.assertEqual(command["cap"], "butt")
        self.assertEqual(command["join"], "miter")
        self.assertEqual(command["dashes"], None)
        self.assertEqual(command["dash_offset_pt"], 0.0)
        self.assertEqual(command["fill_rule"], "nonzero")
        self.assertTrue(command["antialias"])
        self.assertIsNone(command["clip_rect"])

    def test_codes_parallel_vertices_and_in_seam_vocabulary(self):
        commands = self.module.glyph_outline_commands("ag", (5.0, 25.0), 2.0, 0.0)
        command = commands[0]
        codes = command["codes"]
        vertices = command["vertices"]
        self.assertEqual(len(codes), len(vertices))
        self.assertGreater(len(codes), 0)
        allowed = {0, 1, 2, 3, 4, 79}
        self.assertTrue(set(codes).issubset(allowed))
        # A filled outline always starts with MOVETO.
        self.assertEqual(codes[0], 1)

    def test_baseline_anchor_and_y_up_ink(self):
        # 'n' has no descender: every glyph vertex sits at or below the
        # baseline in top-left pixel space (y <= origin_y).
        origin_y = 40.0
        command = self.module.glyph_outline_commands("n", (10.0, origin_y), 1.0, 0.0)[0]
        ys = [y for _, y in command["vertices"]]
        self.assertTrue(all(y <= origin_y + 1e-9 for y in ys))
        self.assertAlmostEqual(max(ys), origin_y, places=6)

    def test_descender_reaches_above_origin_row(self):
        # 'p' descends below the typographic baseline; in top-left pixel
        # space that means ink strictly ABOVE the origin row.
        origin_y = 40.0
        command = self.module.glyph_outline_commands("p", (10.0, origin_y), 1.0, 0.0)[0]
        ys = [y for _, y in command["vertices"]]
        self.assertTrue(min(ys) < origin_y - 1.0)

    def test_x_positions_start_at_origin(self):
        command = self.module.glyph_outline_commands("n", (30.0, 40.0), 1.0, 0.0)[0]
        xs = [x for x, _ in command["vertices"]]
        self.assertAlmostEqual(min(xs), 30.0, places=6)

    def test_scale_x_multiplies_widths_not_heights(self):
        base = self.module.glyph_outline_commands("m", (0.0, 50.0), 1.0, 0.0)[0]
        scaled = self.module.glyph_outline_commands("m", (0.0, 50.0), 2.0, 0.0)[0]
        base_width = max(x for x, _ in base["vertices"]) - min(
            x for x, _ in base["vertices"]
        )
        scaled_width = max(x for x, _ in scaled["vertices"]) - min(
            x for x, _ in scaled["vertices"]
        )
        self.assertAlmostEqual(scaled_width, base_width * 2.0, places=6)
        base_height = max(y for _, y in base["vertices"]) - min(
            y for _, y in base["vertices"]
        )
        scaled_height = max(y for _, y in scaled["vertices"]) - min(
            y for _, y in scaled["vertices"]
        )
        self.assertAlmostEqual(scaled_height, base_height, places=6)


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestAffineApplication(unittest.TestCase):
    def setUp(self):
        self.module = _load_module()

    def test_shear_matches_independent_computation(self):
        scale, shear = 1.5, -0.35
        ox, oy = 7.0, 33.0
        command = self.module.glyph_outline_commands("g", (ox, oy), scale, shear)[0]

        from matplotlib.textpath import TextPath

        reference = TextPath((0.0, 0.0), "g", size=10.0)
        self.assertEqual(len(command["vertices"]), len(reference.vertices))
        for emitted, (rx, ry) in zip(command["vertices"], reference.vertices):
            expected_x = ox + rx * scale + (-ry) * shear
            expected_y = oy + (-ry)
            self.assertAlmostEqual(emitted[0], expected_x, places=9)
            self.assertAlmostEqual(emitted[1], expected_y, places=9)

    def test_zero_scale_is_finite_degenerate_geometry_not_crash(self):
        command = self.module.glyph_outline_commands("n", (10.0, 20.0), 0.0, 0.0)[0]
        for x, y in command["vertices"]:
            self.assertTrue(math.isfinite(x) and math.isfinite(y))

    def test_determinism_identical_inputs(self):
        first = self.module.glyph_outline_commands("Wg", (3.0, 44.0), 1.25, 0.1)
        second = self.module.glyph_outline_commands("Wg", (3.0, 44.0), 1.25, 0.1)
        self.assertEqual(first, second)

    def test_distinct_scale_gives_distinct_geometry(self):
        first = self.module.glyph_outline_commands("Wg", (3.0, 44.0), 1.0, 0.0)
        second = self.module.glyph_outline_commands("Wg", (3.0, 44.0), 2.0, 0.0)
        self.assertNotEqual(first, second)


# ---------------------------------------------------------------------------
# Failure policy (decision 4)
# ---------------------------------------------------------------------------


class TestFailurePolicy(unittest.TestCase):
    TOKEN = "unsupported-text-path"

    def setUp(self):
        self.module = _load_module()

    def assert_unsupported(self, callable_, *args, **kwargs):
        with self.assertRaises(ValueError) as caught:
            callable_(*args, **kwargs)
        self.assertIn(self.TOKEN, str(caught.exception))

    @unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
    def test_empty_text_rejected(self):
        self.assert_unsupported(self.module.glyph_outline_commands, "", (0.0, 0.0), 1.0, 0.0)

    @unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
    def test_whitespace_only_text_rejected(self):
        self.assert_unsupported(
            self.module.glyph_outline_commands, " \t\n", (0.0, 0.0), 1.0, 0.0
        )

    def test_non_string_text_rejected_without_matplotlib_work(self):
        # Must fail before any Matplotlib call, so it holds offline too.
        self.assert_unsupported(
            self.module.glyph_outline_commands, 42, (0.0, 0.0), 1.0, 0.0
        )

    @unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
    def test_non_finite_arguments_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            self.assert_unsupported(
                self.module.glyph_outline_commands, "n", (bad, 10.0), 1.0, 0.0
            )
            self.assert_unsupported(
                self.module.glyph_outline_commands, "n", (10.0, bad), 1.0, 0.0
            )
            self.assert_unsupported(
                self.module.glyph_outline_commands, "n", (0.0, 0.0), bad, 0.0
            )
            self.assert_unsupported(
                self.module.glyph_outline_commands, "n", (0.0, 0.0), 1.0, bad
            )
            self.assert_unsupported(
                self.module.glyph_outline_commands,
                "n",
                (0.0, 0.0),
                1.0,
                0.0,
                font_size_pt=bad,
            )

    @unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
    def test_wrong_length_origin_rejected_as_unsupported(self):
        self.assert_unsupported(self.module.glyph_outline_commands, "n", (1.0,), 1.0, 0.0)
        self.assert_unsupported(self.module.glyph_outline_commands, "n", (), 1.0, 0.0)


# ---------------------------------------------------------------------------
# Module hygiene
# ---------------------------------------------------------------------------


class TestModuleHygiene(unittest.TestCase):
    def test_module_never_imports_private_seam(self):
        source_path = os.path.join(REPO_ROOT, "python/lumenplot_mpl/textpath.py")
        with open(source_path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("_native", source)

    @unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
    def test_public_surface_is_exactly_documented(self):
        module = _load_module()
        self.assertEqual(
            set(module.__all__), {"glyph_outline_commands", "UNSUPPORTED_TEXT_PATH"}
        )
        self.assertTrue(callable(module.glyph_outline_commands))


# ---------------------------------------------------------------------------
# Real-seam rasterization probe (skipped without the compiled extension)
# ---------------------------------------------------------------------------


@unittest.skipUnless(
    MATPLOTLIB_PRESENT and HAS_REAL_SEAM,
    "matplotlib or compiled lumenplot_mpl._native seam not available",
)
class TestRealSeamRasterization(unittest.TestCase):
    def test_glyph_ink_lands_above_baseline_inside_expected_columns(self):
        module = _load_module()
        width, height = 120, 80
        origin = (20.0, 60.0)
        commands = module.glyph_outline_commands("n", origin, 2.0, 0.0)
        spec = {
            "width_px": width,
            "height_px": height,
            "output_dpi": 72.0,
            "commands": commands,
        }
        png_bytes = _native_seam.render_frame_png(spec)
        self.assertEqual(_png_dimensions(png_bytes), (width, height))
        decoded_width, decoded_height, rows = _decode_rgba8(png_bytes)
        self.assertEqual(decoded_height, height)

        ink_rows = []
        ink_cols = []
        for y in range(height):
            row = rows[y]
            for x in range(width):
                alpha = row[x * 4 + 3]
                if alpha > 0:
                    ink_rows.append(y)
                    ink_cols.append(x)
        self.assertTrue(ink_rows, "expected visible glyph ink")
        # Top-left pixel space: ink extends UP from the baseline row. The
        # 'n' x-height at size 10pt scale 2 is ~14px, so the top ink row
        # must stay within the canvas but clearly above the baseline.
        self.assertLessEqual(min(ink_rows), origin[1])
        self.assertLessEqual(origin[1] - min(ink_rows), height)
        # And starts at the requested origin column.
        self.assertGreaterEqual(min(ink_cols), origin[0])
        self.assertLess(max(ink_cols), width)

    def test_spec_with_background_composites_over_it(self):
        module = _load_module()
        commands = module.glyph_outline_commands("i", (10.0, 40.0), 3.0, 0.0)
        background = {
            "kind": "path",
            "vertices": [
                [0.0, 0.0],
                [100.0, 0.0],
                [100.0, 60.0],
                [0.0, 60.0],
                [0.0, 0.0],
            ],
            "codes": None,
            "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            "stroke_rgba": None,
            "fill_rgba": [255, 255, 255, 255],
            "line_width_pt": 0.0,
            "cap": "butt",
            "join": "miter",
            "dash_offset_pt": 0.0,
            "dashes": None,
            "fill_rule": "nonzero",
            "antialias": True,
            "clip_rect": None,
        }
        spec = {
            "width_px": 100,
            "height_px": 60,
            "output_dpi": 72.0,
            "commands": [background] + commands,
        }
        png_bytes = _native_seam.render_frame_png(spec)
        _, _, rows = _decode_rgba8(png_bytes)
        center_pixel = rows[30][45:49]
        self.assertEqual(tuple(center_pixel), (255, 255, 255, 255))


if __name__ == "__main__":
    unittest.main()
