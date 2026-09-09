"""Focused tests for the fixed, private Agg-oracle comparator contract."""

from __future__ import annotations

import copy
import hashlib
import json
import struct
import unittest
import zlib
from pathlib import Path

import numpy as np

try:
    from ._agg_oracle import (
        AggOracleContractError,
        FRINGE_MISMATCH_RATE_MAX,
        PIXEL_CLASS_CODES,
        PIXEL_CLASS_NAMES,
        TOP_TO_BOTTOM,
        compare_pngs,
        compare_rgba8,
        decode_png_rgba8,
        load_pixel_class_mask,
        load_reference_fixture,
        validate_manifest,
    )
except ImportError:  # unittest discover -s tests/python
    from _agg_oracle import (
        AggOracleContractError,
        FRINGE_MISMATCH_RATE_MAX,
        PIXEL_CLASS_CODES,
        PIXEL_CLASS_NAMES,
        TOP_TO_BOTTOM,
        compare_pngs,
        compare_rgba8,
        decode_png_rgba8,
        load_pixel_class_mask,
        load_reference_fixture,
        validate_manifest,
    )


FIXTURE_DIR = Path(__file__).with_name("fixtures") / "agg_oracle"
MANIFEST_PATH = FIXTURE_DIR / "contract_manifest.json"


def _encode_rgba8(rgba: np.ndarray) -> bytes:
    """Encode a small RGBA8 array without adding a test dependency."""

    array = np.asarray(rgba)
    if array.dtype != np.uint8 or array.ndim != 3 or array.shape[-1] != 4:
        raise AssertionError("test encoder requires uint8[height, width, 4]")
    height, width, _ = array.shape
    raw = b"".join(
        b"\x00" + bytes(array[row_index].reshape(-1))
        for row_index in range(height)
    )
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _case_arrays(height: int, width: int, mask_code: int = 0):
    reference = np.zeros((height, width, 4), dtype=np.uint8)
    candidate = reference.copy()
    mask = np.full((height, width), mask_code, dtype=np.uint8)
    return reference, candidate, mask


class TestCommittedFixture(unittest.TestCase):
    def setUp(self):
        self.fixture = load_reference_fixture(MANIFEST_PATH)

    def test_committed_mask_and_manifest_fields(self):
        manifest = self.fixture.manifest
        validate_manifest(manifest, (2, 4))
        self.assertEqual(manifest["orientation"], TOP_TO_BOTTOM)
        self.assertEqual(manifest["channels"], "RGBA8")
        self.assertEqual(tuple(manifest["pixel_classes"]), PIXEL_CLASS_NAMES)
        self.assertEqual(manifest["contract"]["fringe_max_channel_delta"], 1)
        self.assertEqual(
            manifest["contract"]["fringe_mismatch_rate_denominator"],
            "total-pixels",
        )
        self.assertEqual(
            manifest["contract"]["fringe_mismatch_rate_max"],
            FRINGE_MISMATCH_RATE_MAX,
        )
        self.assertEqual(self.fixture.mask.labels.shape, (2, 4))
        self.assertEqual(
            set(np.unique(self.fixture.mask.labels)),
            set(PIXEL_CLASS_CODES.values()),
        )
        self.assertEqual(manifest["dimensions"], {"width": 4, "height": 2})
        self.assertTrue(manifest["reference_png_sha256"])
        self.assertTrue(manifest["mask_sha256"])
        self.assertTrue(manifest["figure"]["construction"])
        self.assertIsInstance(manifest["figure"]["options"], dict)
        self.assertIsInstance(manifest["rcparams"], dict)
        self.assertTrue(manifest["artist_class"])
        self.assertTrue(manifest["font_bytes_sha256"])

    def test_reference_rows_are_top_to_bottom_and_exact_match_passes(self):
        decoded = decode_png_rgba8(self.fixture.reference_png)
        self.assertEqual(decoded.orientation, TOP_TO_BOTTOM)
        self.assertEqual((decoded.width, decoded.height), (4, 2))
        self.assertEqual(tuple(decoded.rgba[0, 0]), (255, 255, 255, 255))
        self.assertEqual(tuple(decoded.rgba[1, 0]), (0, 0, 0, 255))
        report = compare_pngs(
            self.fixture.reference_png,
            self.fixture.reference_png,
            self.fixture.mask,
            manifest=self.fixture.manifest,
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.max_channel_delta, 0)
        self.assertEqual(report.mean_channel_delta, 0.0)
        self.assertEqual(report.mismatch_count, 0)
        self.assertEqual(report.per_class_counts["background"], 3)
        self.assertEqual(report.per_class_counts["fully-covered"], 2)
        self.assertEqual(report.per_class_counts["antialias-fringe"], 2)
        self.assertEqual(report.per_class_counts["text-or-outline"], 1)
        self.assertEqual(report.per_class_mismatch_counts, {
            name: 0 for name in PIXEL_CLASS_NAMES
        })
        self.assertEqual(report.as_dict()["orientation"], TOP_TO_BOTTOM)

    def test_loader_uses_manifest_digests(self):
        mask_bytes = (FIXTURE_DIR / "contract_mask.json").read_bytes()
        self.assertEqual(
            hashlib.sha256(mask_bytes).hexdigest(),
            self.fixture.manifest["mask_sha256"],
        )
        self.assertEqual(
            load_pixel_class_mask(FIXTURE_DIR / "contract_mask.json").labels.tolist(),
            self.fixture.mask.labels.tolist(),
        )


class TestFixedPixelClasses(unittest.TestCase):
    def test_allowed_fringe_delta_uses_total_pixel_denominator(self):
        reference, candidate, mask = _case_arrays(1, 1001)
        mask[0, 0] = PIXEL_CLASS_CODES["antialias-fringe"]
        candidate[0, 0, 1] = 1
        report = compare_rgba8(reference, candidate, mask)
        self.assertTrue(report.passed)
        self.assertEqual(report.max_channel_delta, 1)
        self.assertAlmostEqual(report.mean_channel_delta, 1 / (1001 * 4))
        self.assertEqual(report.fringe_mismatch_count, 1)
        self.assertEqual(report.fringe_oversized_count, 0)
        self.assertAlmostEqual(report.fringe_mismatch_rate, 1 / 1001)
        self.assertEqual(report.per_class_mismatch_counts["antialias-fringe"], 1)

    def test_covered_and_background_mismatches_are_not_allowed(self):
        reference, candidate, mask = _case_arrays(1, 2)
        mask[0, 0] = PIXEL_CLASS_CODES["fully-covered"]
        candidate[0, 0, 0] = 1
        candidate[0, 1, 3] = 1
        report = compare_rgba8(reference, candidate, mask)
        self.assertFalse(report.passed)
        self.assertEqual(report.exact_mismatch_count, 2)
        self.assertEqual(report.fringe_mismatch_count, 0)
        self.assertEqual(report.per_class_mismatch_counts["fully-covered"], 1)
        self.assertEqual(report.per_class_mismatch_counts["background"], 1)

    def test_oversized_fringe_channel_delta_fails(self):
        reference, candidate, mask = _case_arrays(1, 1001)
        mask[0, 0] = PIXEL_CLASS_CODES["antialias-fringe"]
        candidate[0, 0, 0] = 2
        report = compare_rgba8(reference, candidate, mask)
        self.assertFalse(report.passed)
        self.assertEqual(report.max_channel_delta, 2)
        self.assertEqual(report.fringe_oversized_count, 1)
        self.assertEqual(report.fringe_mismatch_count, 1)
        self.assertLessEqual(report.fringe_mismatch_rate, FRINGE_MISMATCH_RATE_MAX)

    def test_oversized_fringe_mismatch_rate_fails(self):
        reference, candidate, mask = _case_arrays(
            1, 1001, PIXEL_CLASS_CODES["antialias-fringe"]
        )
        candidate[0, 0, 0] = 1
        candidate[0, 1, 0] = 1
        report = compare_rgba8(reference, candidate, mask)
        self.assertFalse(report.passed)
        self.assertEqual(report.max_channel_delta, 1)
        self.assertEqual(report.fringe_oversized_count, 0)
        self.assertEqual(report.fringe_mismatch_count, 2)
        self.assertGreater(report.fringe_mismatch_rate, FRINGE_MISMATCH_RATE_MAX)

    def test_report_contains_max_mean_and_per_class_counts(self):
        reference, candidate, mask = _case_arrays(1, 4)
        mask[0, 0] = PIXEL_CLASS_CODES["fully-covered"]
        mask[0, 1] = PIXEL_CLASS_CODES["antialias-fringe"]
        candidate[0, 0, :] = 3
        candidate[0, 1, :] = 1
        report = compare_rgba8(reference, candidate, mask)
        self.assertEqual(report.max_delta, 3)
        self.assertGreater(report.mean_delta, 0.0)
        self.assertEqual(
            set(report.per_class_counts), set(PIXEL_CLASS_NAMES)
        )
        self.assertEqual(report.per_class_counts["fully-covered"], 1)
        self.assertEqual(report.per_class_counts["antialias-fringe"], 1)
        self.assertEqual(report.per_class_mismatch_counts["fully-covered"], 1)
        self.assertEqual(report.per_class_mismatch_counts["antialias-fringe"], 1)
        self.assertIn("max_delta=3", report.summary())
        self.assertIn("mean_delta=", report.summary())


class TestMalformedOracleInputs(unittest.TestCase):
    def test_malformed_image_dimensions_are_rejected(self):
        reference, candidate, mask = _case_arrays(2, 2)
        del candidate
        with self.assertRaises(AggOracleContractError):
            compare_rgba8(reference, np.zeros((2, 3, 4), dtype=np.uint8), mask)
        with self.assertRaises(AggOracleContractError):
            compare_pngs(
                _encode_rgba8(reference),
                _encode_rgba8(np.zeros((2, 3, 4), dtype=np.uint8)),
                mask,
            )

    def test_malformed_orientation_is_rejected_without_flipping(self):
        reference, candidate, mask = _case_arrays(1, 2)
        with self.assertRaises(AggOracleContractError):
            compare_rgba8(
                reference,
                candidate,
                mask,
                orientation="bottom-to-top",
            )
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest["orientation"] = "bottom-to-top"
        with self.assertRaises(AggOracleContractError):
            validate_manifest(manifest)

    def test_malformed_mask_shape_and_class_are_rejected(self):
        reference, candidate, _mask = _case_arrays(2, 2)
        with self.assertRaises(AggOracleContractError):
            compare_rgba8(reference, candidate, np.zeros((1, 2), dtype=np.uint8))
        bad_class = np.zeros((2, 2), dtype=np.uint8)
        bad_class[0, 0] = 99
        with self.assertRaises(AggOracleContractError):
            compare_rgba8(reference, candidate, bad_class)

    def test_manifest_missing_fixed_fields_is_rejected(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        del manifest["mask_sha256"]
        with self.assertRaises(AggOracleContractError):
            validate_manifest(manifest)

    def test_manifest_dimensions_and_contract_are_fixed(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest["dimensions"]["width"] = 5
        with self.assertRaises(AggOracleContractError):
            validate_manifest(manifest, (2, 4))
        manifest = copy.deepcopy(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))
        manifest["contract"]["fringe_mismatch_rate_max"] = 0.01
        with self.assertRaises(AggOracleContractError):
            validate_manifest(manifest)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
