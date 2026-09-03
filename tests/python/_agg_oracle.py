"""Private, fixed Matplotlib Agg-oracle comparator for test fixtures.

This module is test-only.  It deliberately does not derive tolerances from a
candidate render: a fixture supplies the reference PNG, a committed pixel
class mask, and a manifest that records the oracle contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
TOP_TO_BOTTOM = "top-to-bottom"
RGBA8 = "RGBA8"
MASK_SCHEMA_VERSION = "agg-oracle-mask-v1"
MANIFEST_SCHEMA_VERSION = "agg-oracle-manifest-v1"
PIXEL_CLASS_NAMES = (
    "background",
    "fully-covered",
    "antialias-fringe",
    "text-or-outline",
)
PIXEL_CLASS_CODES = {
    name: code for code, name in enumerate(PIXEL_CLASS_NAMES)
}
FRINGE_MAX_CHANNEL_DELTA = 1
FRINGE_MISMATCH_RATE_MAX = 0.001


class AggOracleContractError(ValueError):
    """The reference fixture or decoded image violates the fixed contract."""


@dataclass(frozen=True)
class DecodedPng:
    """An RGBA8 image in the contract's deterministic row orientation."""

    width: int
    height: int
    rgba: np.ndarray
    orientation: str = TOP_TO_BOTTOM


@dataclass(frozen=True)
class PixelClassMask:
    """A validated reference mask whose rows are top-to-bottom."""

    labels: np.ndarray
    orientation: str = TOP_TO_BOTTOM
    class_names: tuple[str, ...] = PIXEL_CLASS_NAMES


@dataclass(frozen=True)
class ReferenceFixture:
    """Committed Agg reference bytes, mask, and validated manifest."""

    reference_png: bytes
    mask: PixelClassMask
    manifest: Mapping[str, Any]


@dataclass(frozen=True)
class ComparisonReport:
    """Measured result of one fixed-oracle comparison."""

    passed: bool
    width: int
    height: int
    orientation: str
    total_pixel_count: int
    max_channel_delta: int
    mean_channel_delta: float
    mean_pixel_delta: float
    mismatch_count: int
    exact_mismatch_count: int
    fringe_mismatch_count: int
    fringe_oversized_count: int
    fringe_mismatch_rate: float
    per_class_counts: Mapping[str, int]
    per_class_mismatch_counts: Mapping[str, int]
    per_class_oversized_counts: Mapping[str, int]

    @property
    def max_delta(self) -> int:
        """Short alias used by diagnostics and test assertions."""

        return self.max_channel_delta

    @property
    def mean_delta(self) -> float:
        """Short alias for the mean RGBA channel delta."""

        return self.mean_channel_delta

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly report without NumPy scalar values."""

        return {
            "passed": self.passed,
            "width": self.width,
            "height": self.height,
            "orientation": self.orientation,
            "total_pixel_count": self.total_pixel_count,
            "max_channel_delta": self.max_channel_delta,
            "mean_channel_delta": self.mean_channel_delta,
            "mean_pixel_delta": self.mean_pixel_delta,
            "mismatch_count": self.mismatch_count,
            "exact_mismatch_count": self.exact_mismatch_count,
            "fringe_mismatch_count": self.fringe_mismatch_count,
            "fringe_oversized_count": self.fringe_oversized_count,
            "fringe_mismatch_rate": self.fringe_mismatch_rate,
            "per_class_counts": dict(self.per_class_counts),
            "per_class_mismatch_counts": dict(self.per_class_mismatch_counts),
            "per_class_oversized_counts": dict(self.per_class_oversized_counts),
        }

    def summary(self) -> str:
        """Format the fixed measurements for a failure message."""

        return (
            f"{self.width}x{self.height} {self.orientation}; "
            f"max_delta={self.max_channel_delta}, "
            f"mean_delta={self.mean_channel_delta:.6f}, "
            f"mismatches={self.mismatch_count}, "
            f"exact_mismatches={self.exact_mismatch_count}, "
            f"fringe_mismatches={self.fringe_mismatch_count}, "
            f"fringe_oversized={self.fringe_oversized_count}, "
            f"fringe_rate={self.fringe_mismatch_rate:.6f}; "
            f"per_class={dict(self.per_class_mismatch_counts)}"
        )


class AggOracleMismatch(AssertionError):
    """A decoded candidate failed the fixed pixel-class comparison."""

    def __init__(self, report: ComparisonReport):
        self.report = report
        super().__init__(report.summary())


def _contract_error(message: str) -> AggOracleContractError:
    return AggOracleContractError(message)


def _ensure_bytes(value: bytes | bytearray | memoryview, name: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise _contract_error(f"{name} must be bytes-like")
    return bytes(value)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _parse_png(png_bytes: bytes) -> tuple[dict[str, Any], bytes, bytes | None, bytes | None]:
    if not png_bytes.startswith(PNG_SIGNATURE):
        raise _contract_error("PNG signature missing")

    offset = len(PNG_SIGNATURE)
    chunks: list[tuple[bytes, bytes]] = []
    seen_iend = False
    while offset < len(png_bytes):
        if len(png_bytes) - offset < 12:
            raise _contract_error("truncated PNG chunk header")
        length = struct.unpack(">I", png_bytes[offset : offset + 4])[0]
        end = offset + 12 + length
        if end > len(png_bytes):
            raise _contract_error("truncated PNG chunk payload")
        kind = png_bytes[offset + 4 : offset + 8]
        payload_start = offset + 8
        payload_end = payload_start + length
        payload = png_bytes[payload_start:payload_end]
        expected_crc = struct.unpack(">I", png_bytes[payload_end:end])[0]
        actual_crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise _contract_error(f"PNG CRC mismatch for {kind!r}")
        chunks.append((kind, payload))
        offset = end
        if kind == b"IEND":
            seen_iend = True
            break

    if not seen_iend or offset != len(png_bytes):
        raise _contract_error("PNG must end at a valid IEND chunk")
    if not chunks or chunks[0][0] != b"IHDR":
        raise _contract_error("PNG IHDR must be the first chunk")

    ihdr = chunks[0][1]
    if len(ihdr) != 13:
        raise _contract_error("PNG IHDR has the wrong length")
    width, height, bit_depth, color_type, compression, filter_method, interlace = (
        struct.unpack(">IIBBBBB", ihdr)
    )
    if width <= 0 or height <= 0:
        raise _contract_error("PNG dimensions must be positive")
    if bit_depth != 8:
        raise _contract_error("only 8-bit PNG samples are supported")
    if color_type not in (0, 2, 3, 4, 6):
        raise _contract_error(f"unsupported PNG color type {color_type}")
    if compression != 0 or filter_method != 0 or interlace != 0:
        raise _contract_error("PNG must use non-interlaced standard filtering")

    idat = b"".join(payload for kind, payload in chunks if kind == b"IDAT")
    if not idat:
        raise _contract_error("PNG contains no IDAT payload")
    palette = next((payload for kind, payload in chunks if kind == b"PLTE"), None)
    transparency = next(
        (payload for kind, payload in chunks if kind == b"tRNS"), None
    )
    if color_type == 3 and (palette is None or len(palette) == 0):
        raise _contract_error("paletted PNG is missing PLTE")
    if palette is not None and len(palette) % 3:
        raise _contract_error("PNG PLTE length is not a multiple of three")
    return (
        {
            "width": width,
            "height": height,
            "bit_depth": bit_depth,
            "color_type": color_type,
        },
        idat,
        palette,
        transparency,
    )


def decode_png_rgba8(png_bytes: bytes | bytearray | memoryview) -> DecodedPng:
    """Decode a PNG into top-to-bottom ``uint8[height, width, 4]`` RGBA.

    The decoder is deliberately stdlib/NumPy-only.  PNG scanlines are defined
    in top-to-bottom order; this function preserves that order and records it
    explicitly rather than guessing or silently flipping a candidate image.
    """

    data = _ensure_bytes(png_bytes, "png_bytes")
    header, compressed, palette, transparency = _parse_png(data)
    width = int(header["width"])
    height = int(header["height"])
    color_type = int(header["color_type"])
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    row_bytes = width * channels
    try:
        raw = zlib.decompress(compressed)
    except zlib.error as exc:
        raise _contract_error(f"invalid PNG DEFLATE stream: {exc}") from exc
    expected_size = height * (row_bytes + 1)
    if len(raw) != expected_size:
        raise _contract_error(
            f"PNG scanline size {len(raw)} does not match {expected_size}"
        )

    rows = bytearray(height * row_bytes)
    previous = bytearray(row_bytes)
    source_offset = 0
    for row_index in range(height):
        filter_kind = raw[source_offset]
        source_offset += 1
        filtered = raw[source_offset : source_offset + row_bytes]
        source_offset += row_bytes
        current = bytearray(row_bytes)
        for index, value in enumerate(filtered):
            left = current[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_kind == 0:
                predictor = 0
            elif filter_kind == 1:
                predictor = left
            elif filter_kind == 2:
                predictor = up
            elif filter_kind == 3:
                predictor = (left + up) // 2
            elif filter_kind == 4:
                predictor = _paeth(left, up, upper_left)
            else:
                raise _contract_error(f"unsupported PNG filter {filter_kind}")
            current[index] = (value + predictor) & 0xFF
        row_start = row_index * row_bytes
        rows[row_start : row_start + row_bytes] = current
        previous = current

    source = np.frombuffer(rows, dtype=np.uint8).reshape(height, width, channels)
    rgba = np.empty((height, width, 4), dtype=np.uint8)
    if color_type == 6:
        rgba[...] = source
    elif color_type == 2:
        rgba[..., :3] = source
        rgba[..., 3] = 255
        if transparency is not None:
            if len(transparency) != 6:
                raise _contract_error("RGB tRNS payload must contain three words")
            transparent = np.frombuffer(transparency, dtype=">u2")
            rgb8 = transparent.astype(np.uint8)
            rgba[..., 3] = np.where(
                np.all(source == rgb8.reshape(1, 1, 3), axis=2), 0, 255
            )
    elif color_type == 0:
        gray = source[..., 0]
        rgba[..., :3] = gray[..., None]
        rgba[..., 3] = 255
        if transparency is not None:
            if len(transparency) != 2:
                raise _contract_error("grayscale tRNS payload must contain one word")
            transparent = struct.unpack(">H", transparency)[0]
            rgba[..., 3] = np.where(gray == transparent, 0, 255)
    elif color_type == 4:
        gray = source[..., 0]
        rgba[..., :3] = gray[..., None]
        rgba[..., 3] = source[..., 1]
    else:  # color_type == 3
        assert palette is not None  # checked by _parse_png
        palette_rgb = np.frombuffer(palette, dtype=np.uint8).reshape(-1, 3)
        indexes = source[..., 0]
        if int(indexes.max(initial=0)) >= len(palette_rgb):
            raise _contract_error("PNG palette index is out of range")
        rgba[..., :3] = palette_rgb[indexes]
        rgba[..., 3] = 255
        if transparency is not None:
            alpha = np.full(len(palette_rgb), 255, dtype=np.uint8)
            alpha[: len(transparency)] = np.frombuffer(transparency, dtype=np.uint8)
            rgba[..., 3] = alpha[indexes]

    rgba.setflags(write=False)
    return DecodedPng(width, height, rgba, TOP_TO_BOTTOM)


# A short alias keeps call sites readable while retaining the explicit API.
decode_png = decode_png_rgba8


def _require_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise _contract_error(f"manifest field {field!r} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise _contract_error(f"manifest field {field!r} is not hexadecimal") from exc
    return value.lower()


def _require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _contract_error(f"manifest field {field!r} must be a non-empty string")
    return value


def _require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise _contract_error(f"manifest field {field!r} must be a positive integer")
    return value


def validate_manifest(
    manifest: Mapping[str, Any], expected_shape: tuple[int, int] | None = None
) -> Mapping[str, Any]:
    """Validate the required immutable fields of an Agg-oracle manifest."""

    required = (
        "schema_version",
        "oracle",
        "python_version",
        "figure",
        "effective_dpi",
        "dimensions",
        "orientation",
        "channels",
        "rcparams",
        "font_bytes_sha256",
        "artist_class",
        "reference_png_file",
        "reference_png_sha256",
        "mask_file",
        "mask_sha256",
        "pixel_classes",
        "contract",
    )
    missing = [field for field in required if field not in manifest]
    if missing:
        raise _contract_error(f"manifest missing required fields: {', '.join(missing)}")
    if manifest["schema_version"] != MANIFEST_SCHEMA_VERSION:
        raise _contract_error("manifest schema_version is not the fixed Agg schema")

    oracle = manifest["oracle"]
    if not isinstance(oracle, Mapping):
        raise _contract_error("manifest oracle must be an object")
    for field in ("backend", "matplotlib_version", "api_version"):
        _require_nonempty_string(oracle.get(field), f"oracle.{field}")
    if oracle["backend"] != "FigureCanvasAgg":
        raise _contract_error("manifest oracle.backend must be FigureCanvasAgg")

    _require_nonempty_string(manifest["python_version"], "python_version")
    figure = manifest["figure"]
    if not isinstance(figure, Mapping):
        raise _contract_error("manifest figure must be an object")
    _require_nonempty_string(figure.get("construction"), "figure.construction")
    if not isinstance(figure.get("options"), Mapping):
        raise _contract_error("manifest figure.options must be an object")

    dpi = manifest["effective_dpi"]
    if isinstance(dpi, bool) or not isinstance(dpi, (int, float)):
        raise _contract_error("manifest effective_dpi must be numeric")
    if not math.isfinite(float(dpi)) or float(dpi) <= 0:
        raise _contract_error("manifest effective_dpi must be finite and positive")

    dimensions = manifest["dimensions"]
    if not isinstance(dimensions, Mapping):
        raise _contract_error("manifest dimensions must be an object")
    width = _require_positive_int(dimensions.get("width"), "dimensions.width")
    height = _require_positive_int(dimensions.get("height"), "dimensions.height")
    shape = (height, width)
    if expected_shape is not None and shape != tuple(expected_shape):
        raise _contract_error(
            f"manifest dimensions {width}x{height} do not match image {expected_shape[1]}x{expected_shape[0]}"
        )

    if manifest["orientation"] != TOP_TO_BOTTOM:
        raise _contract_error(
            f"manifest orientation must be {TOP_TO_BOTTOM!r}, "
            f"got {manifest['orientation']!r}"
        )
    if manifest["channels"] != RGBA8:
        raise _contract_error("manifest channels must be RGBA8")
    if not isinstance(manifest["rcparams"], Mapping):
        raise _contract_error("manifest rcparams must be an object")
    _require_nonempty_string(manifest["font_bytes_sha256"], "font_bytes_sha256")
    _require_nonempty_string(manifest["artist_class"], "artist_class")
    _require_nonempty_string(manifest["reference_png_file"], "reference_png_file")
    _require_nonempty_string(manifest["mask_file"], "mask_file")
    _require_digest(manifest["reference_png_sha256"], "reference_png_sha256")
    _require_digest(manifest["mask_sha256"], "mask_sha256")

    classes = manifest["pixel_classes"]
    if tuple(classes) != PIXEL_CLASS_NAMES:
        raise _contract_error(
            "manifest pixel_classes must be exactly "
            f"{list(PIXEL_CLASS_NAMES)!r}"
        )

    contract = manifest["contract"]
    if not isinstance(contract, Mapping):
        raise _contract_error("manifest contract must be an object")
    expected_contract = {
        "orientation": TOP_TO_BOTTOM,
        "channels": RGBA8,
        "background": "byte-equal",
        "fully-covered": "byte-equal",
        "fringe_max_channel_delta": FRINGE_MAX_CHANNEL_DELTA,
        "fringe_mismatch_rate_denominator": "total-pixels",
        "fringe_mismatch_rate_max": FRINGE_MISMATCH_RATE_MAX,
    }
    for field, expected in expected_contract.items():
        if contract.get(field) != expected:
            raise _contract_error(
                f"manifest contract.{field} must be {expected!r}, "
                f"got {contract.get(field)!r}"
            )
    return manifest


def _validate_mask_array(
    labels: Any,
    expected_shape: tuple[int, int] | None = None,
    orientation: str = TOP_TO_BOTTOM,
) -> PixelClassMask:
    if orientation != TOP_TO_BOTTOM:
        raise _contract_error(
            f"mask orientation must be {TOP_TO_BOTTOM!r}, got {orientation!r}"
        )
    array = np.asarray(labels)
    if array.ndim != 2:
        raise _contract_error("pixel-class mask must be a two-dimensional array")
    if expected_shape is not None and tuple(array.shape) != tuple(expected_shape):
        raise _contract_error(
            f"pixel-class mask shape {tuple(array.shape)} does not match "
            f"image shape {tuple(expected_shape)}"
        )
    if not np.issubdtype(array.dtype, np.integer):
        raise _contract_error("pixel-class mask values must be integers")
    if array.size == 0:
        raise _contract_error("pixel-class mask must not be empty")
    if int(array.min()) < 0 or int(array.max()) >= len(PIXEL_CLASS_NAMES):
        raise _contract_error("pixel-class mask contains an unknown class code")
    normalized = np.asarray(array, dtype=np.uint8).copy()
    normalized.setflags(write=False)
    return PixelClassMask(normalized, orientation, PIXEL_CLASS_NAMES)


def load_pixel_class_mask(mask_path: str | Path) -> PixelClassMask:
    """Load and validate a committed JSON pixel-class mask."""

    path = Path(mask_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _contract_error(f"cannot load pixel-class mask {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise _contract_error("pixel-class mask document must be an object")
    required = ("schema_version", "orientation", "shape", "classes", "data")
    missing = [field for field in required if field not in payload]
    if missing:
        raise _contract_error(f"mask missing required fields: {', '.join(missing)}")
    if payload["schema_version"] != MASK_SCHEMA_VERSION:
        raise _contract_error("mask schema_version is not the fixed Agg schema")
    if payload["orientation"] != TOP_TO_BOTTOM:
        raise _contract_error("mask orientation is not top-to-bottom")
    shape = payload["shape"]
    if (
        not isinstance(shape, Sequence)
        or isinstance(shape, (str, bytes))
        or len(shape) != 2
    ):
        raise _contract_error("mask shape must be [height, width]")
    height = _require_positive_int(shape[0], "mask.shape[0]")
    width = _require_positive_int(shape[1], "mask.shape[1]")
    if tuple(payload["classes"]) != PIXEL_CLASS_NAMES:
        raise _contract_error("mask classes do not match the fixed class set")
    try:
        labels = np.asarray(payload["data"], dtype=np.int64)
    except (TypeError, ValueError) as exc:
        raise _contract_error(f"mask data is not an integer grid: {exc}") from exc
    return _validate_mask_array(labels, (height, width), payload["orientation"])


def load_reference_fixture(manifest_path: str | Path) -> ReferenceFixture:
    """Load a committed reference PNG, mask, and manifest as one fixture."""

    path = Path(manifest_path)
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _contract_error(f"cannot load Agg manifest {path}: {exc}") from exc
    if not isinstance(manifest, Mapping):
        raise _contract_error("Agg manifest document must be an object")
    validate_manifest(manifest)

    reference_path = path.parent / manifest["reference_png_file"]
    mask_path = path.parent / manifest["mask_file"]
    try:
        reference_png = reference_path.read_bytes()
        mask_bytes = mask_path.read_bytes()
    except OSError as exc:
        raise _contract_error(f"cannot read Agg fixture file: {exc}") from exc
    reference_digest = hashlib.sha256(reference_png).hexdigest()
    if reference_digest != manifest["reference_png_sha256"].lower():
        raise _contract_error("reference PNG digest does not match manifest")
    mask_digest = hashlib.sha256(mask_bytes).hexdigest()
    if mask_digest != manifest["mask_sha256"].lower():
        raise _contract_error("pixel-class mask digest does not match manifest")
    decoded = decode_png_rgba8(reference_png)
    validate_manifest(manifest, (decoded.height, decoded.width))
    mask = load_pixel_class_mask(mask_path)
    if tuple(mask.labels.shape) != (decoded.height, decoded.width):
        raise _contract_error("reference mask dimensions do not match reference PNG")
    return ReferenceFixture(reference_png, mask, manifest)


def _coerce_rgba(image: Any, name: str) -> np.ndarray:
    array = np.asarray(image)
    if array.dtype != np.uint8:
        raise _contract_error(f"{name} must have dtype uint8")
    if array.ndim != 3 or array.shape[-1] != 4:
        raise _contract_error(f"{name} must have shape [height, width, 4]")
    if array.shape[0] <= 0 or array.shape[1] <= 0:
        raise _contract_error(f"{name} dimensions must be positive")
    return array


def compare_rgba8(
    reference_rgba: Any,
    candidate_rgba: Any,
    mask: PixelClassMask | Any,
    *,
    orientation: str = TOP_TO_BOTTOM,
    manifest: Mapping[str, Any] | None = None,
) -> ComparisonReport:
    """Compare decoded RGBA8 arrays under the fixed pixel-class contract.

    All classes except ``antialias-fringe`` are byte-exact.  Fringe allowance
    is channel-wise ``<= 1`` and its nonzero mismatch count uses the fixed
    total-frame denominator, never the number of fringe pixels.
    """

    reference = _coerce_rgba(reference_rgba, "reference_rgba")
    candidate = _coerce_rgba(candidate_rgba, "candidate_rgba")
    if orientation != TOP_TO_BOTTOM:
        raise _contract_error(
            f"image orientation must be {TOP_TO_BOTTOM!r}, got {orientation!r}"
        )
    if reference.shape != candidate.shape:
        raise _contract_error(
            f"image dimensions differ: reference={reference.shape[1]}x{reference.shape[0]}, "
            f"candidate={candidate.shape[1]}x{candidate.shape[0]}"
        )
    expected_shape = (int(reference.shape[0]), int(reference.shape[1]))
    if isinstance(mask, PixelClassMask):
        pixel_mask = _validate_mask_array(
            mask.labels, expected_shape, mask.orientation
        )
    else:
        pixel_mask = _validate_mask_array(mask, expected_shape)
    if manifest is not None:
        validate_manifest(manifest, expected_shape)
        if manifest["orientation"] != orientation:
            raise _contract_error("manifest/image orientation mismatch")

    delta = np.abs(
        candidate.astype(np.int16) - reference.astype(np.int16)
    ).astype(np.uint16)
    pixel_delta = delta.max(axis=2)
    nonzero = pixel_delta != 0
    fringe = pixel_mask.labels == PIXEL_CLASS_CODES["antialias-fringe"]
    exact = ~fringe
    exact_mismatch = nonzero & exact
    fringe_nonzero = nonzero & fringe
    fringe_oversized = fringe & (pixel_delta > FRINGE_MAX_CHANNEL_DELTA)
    total_pixels = int(pixel_delta.size)
    fringe_mismatch_count = int(fringe_nonzero.sum())
    fringe_rate = fringe_mismatch_count / total_pixels

    per_class_counts: dict[str, int] = {}
    per_class_mismatches: dict[str, int] = {}
    per_class_oversized: dict[str, int] = {}
    for name, code in PIXEL_CLASS_CODES.items():
        selected = pixel_mask.labels == code
        per_class_counts[name] = int(selected.sum())
        per_class_mismatches[name] = int((selected & nonzero).sum())
        per_class_oversized[name] = int((selected & (pixel_delta > 1)).sum())

    report = ComparisonReport(
        passed=(
            not bool(exact_mismatch.any())
            and not bool(fringe_oversized.any())
            and fringe_rate <= FRINGE_MISMATCH_RATE_MAX
        ),
        width=int(reference.shape[1]),
        height=int(reference.shape[0]),
        orientation=orientation,
        total_pixel_count=total_pixels,
        max_channel_delta=int(delta.max()),
        mean_channel_delta=float(delta.mean()),
        mean_pixel_delta=float(pixel_delta.mean()),
        mismatch_count=int(nonzero.sum()),
        exact_mismatch_count=int(exact_mismatch.sum()),
        fringe_mismatch_count=fringe_mismatch_count,
        fringe_oversized_count=int(fringe_oversized.sum()),
        fringe_mismatch_rate=fringe_rate,
        per_class_counts=per_class_counts,
        per_class_mismatch_counts=per_class_mismatches,
        per_class_oversized_counts=per_class_oversized,
    )
    return report


def compare_pngs(
    reference_png: bytes | bytearray | memoryview,
    candidate_png: bytes | bytearray | memoryview,
    mask: PixelClassMask | Any,
    *,
    manifest: Mapping[str, Any] | None = None,
) -> ComparisonReport:
    """Decode two PNGs top-to-bottom and apply :func:`compare_rgba8`."""

    reference_bytes = _ensure_bytes(reference_png, "reference_png")
    candidate_bytes = _ensure_bytes(candidate_png, "candidate_png")
    reference = decode_png_rgba8(reference_bytes)
    candidate = decode_png_rgba8(candidate_bytes)
    if manifest is not None:
        expected_digest = _require_digest(
            manifest.get("reference_png_sha256"), "reference_png_sha256"
        )
        actual_digest = hashlib.sha256(reference_bytes).hexdigest()
        if actual_digest != expected_digest:
            raise _contract_error("reference PNG digest does not match manifest")
    return compare_rgba8(
        reference.rgba,
        candidate.rgba,
        mask,
        orientation=reference.orientation,
        manifest=manifest,
    )


def assert_png_parity(
    reference_png: bytes | bytearray | memoryview,
    candidate_png: bytes | bytearray | memoryview,
    mask: PixelClassMask | Any,
    *,
    manifest: Mapping[str, Any] | None = None,
) -> ComparisonReport:
    """Return a passing report or raise with the complete measured report."""

    report = compare_pngs(reference_png, candidate_png, mask, manifest=manifest)
    if not report.passed:
        raise AggOracleMismatch(report)
    return report


# Compatibility spelling for test-only call sites.
compare_png = compare_pngs
