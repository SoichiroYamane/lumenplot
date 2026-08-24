"""Phase-3B native-authority seam tests (batch-1 lane C, LP-MPL-005).

Canon (docs/requirements/lumenplot-v1.0.md §15): LP-MPL-005 — MUST "Treat
PlotScene as authoritative in native mode" (evidence AT-SEM-STATE-REVISION;
ADR 0002 profile table: the ``accelerated-native`` profile operates on
LumenPlot-aware input after a sealed snapshot).

Boundary of this lane (orchestrator-scoped decision): PlotScene and its
SceneRevision live Rust-side (``crates/lumenplot/src/scene.rs``) and cannot be
reached from a Python test lane. This module therefore pins the
PYTHON-OBSERVABLE consequences of "PlotScene authoritative + revisioned
sealed snapshot" at the private seam ``lumenplot_mpl._native``
(``render_line_png``, ``render_frame_png(spec) -> bytes``; Python surface in
``python/lumenplot_mpl/_native.pyi``, Rust side
``crates/lumenplot-python/src/lib.rs`` § "Phase-3B frame seam"):

- caller-input immutability (extraction copies into owned IR exactly once;
  the caller's mapping is never retained or mutated),
- byte determinism for an identical spec (sealed-snapshot stability),
- snapshot consistency between requested frame geometry and emitted PNG,
- explicit validation failures (never silent),
- no cross-call state leakage between frames.

Full Rust-side PlotScene-authority proof remains Rust-unit/bench evidence
under its own environment gate (AT-SEM-STATE-REVISION) and is out of scope
for this Python lane.

Exception families are pinned EMPIRICALLY per the task card: the binding
contract comment (lib.rs § Phase-3B frame seam, ~line 530) states that
validation failures raise ValueError and internal/raster failures raise the
RuntimeError family, but the suite audits observed behavior whenever the
compiled extension is importable instead of trusting prose alone. The
internal-failure family is intentionally not exercised: every reachable
public input either validates or succeeds, and injecting OOM/panic faults
would require modifying the seam, which this test-only lane forbids.

Offline cells without the compiled extension skip the real-seam block
cleanly and exercise only the pure-Python harness contract (the recording
stub pattern shared with ``test_phase3b_backend.py``).
"""

from __future__ import annotations

import copy
import struct
import unittest

try:
    from lumenplot_mpl import _native as _native_seam
except (ImportError, AttributeError):  # extension not built in this cell
    _native_seam = None

HAS_REAL_NATIVE_SEAM = _native_seam is not None and callable(
    getattr(_native_seam, "render_frame_png", None)
)


# ---------------------------------------------------------------------------
# Spec builders (key map read from lib.rs § Phase-3B frame seam extraction
# helpers; not guessed: required keys are width_px, height_px, output_dpi,
# commands; a path command requires kind, vertices, transform, cap, join,
# fill_rule and at least one of stroke_rgba/fill_rgba).
# ---------------------------------------------------------------------------


def _path_command(**overrides):
    command = {
        "kind": "path",
        "vertices": [[0.0, 0.0], [63.0, 47.0]],
        "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
        "stroke_rgba": [200, 30, 30, 255],
        "line_width_pt": 2.0,
        "cap": "butt",
        "join": "miter",
        "fill_rule": "nonzero",
    }
    command.update(overrides)
    return command


def _frame_spec(width_px: int = 64, height_px: int = 48) -> dict:
    return {
        "width_px": width_px,
        "height_px": height_px,
        "output_dpi": 100.0,
        "commands": [_path_command()],
    }


def _frame_spec_missing_key() -> dict:
    spec = _frame_spec()
    del spec["commands"]
    return spec


def _frame_spec_bad_vertex() -> dict:
    return _frame_spec(
        commands=[_path_command(vertices=[[16.0, 12.0, 7.0], [32.0, 24.0]])]
    )


def _frame_spec_out_of_range_rgba() -> dict:
    return _frame_spec(
        commands=[_path_command(stroke_rgba=[256, 30, 30, 255])]
    )


def _png_dimensions(png_bytes: bytes) -> tuple[int, int]:
    """Parse IHDR width/height from PNG bytes (structural, stdlib only)."""
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "PNG magic missing"
    chunk = png_bytes[12:16]
    assert chunk == b"IHDR", f"first chunk is {chunk!r}, not IHDR"
    width, height = struct.unpack(">II", png_bytes[16:24])
    return int(width), int(height)


def _stub_png_bytes(width: int, height: int) -> bytes:
    """Header-only deterministic PNG with correct IHDR (harness artifact)."""
    header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(
        ">IIBBBBB", width, height, 8, 6, 0, 0, 0
    )
    return header + b"\x00\x00\x00\x00IEND\xaeB`\x82"


class _RecordingNativeStub:
    """Stand-in for ``lumenplot_mpl._native`` recording the last spec.

    Mirrors the real seam's observable harness contract: output depends only
    on the spec (stateless per-call bytes), and the caller's mapping is read
    but never mutated.
    """

    def __init__(self):
        self.last_spec = None
        self.calls = 0

    def render_frame_png(self, spec):  # noqa: N802 - mirrors native name
        self.calls += 1
        self.last_spec = spec
        return _stub_png_bytes(int(spec["width_px"]), int(spec["height_px"]))


# ---------------------------------------------------------------------------
# Empirical exception-family observation (card mandate: probe before pinning)
# ---------------------------------------------------------------------------

# (name, fresh-spec builder, family the suite pins), cited from the binding
# contract comment in crates/lumenplot-python/src/lib.rs § Phase-3B frame
# seam (~line 530): validation failures raise ValueError.
_PINNED_VALIDATION_PROBES = (
    ("missing_required_key", _frame_spec_missing_key, ValueError),
    ("malformed_vertex", _frame_spec_bad_vertex, ValueError),
    ("out_of_range_rgba", _frame_spec_out_of_range_rgba, ValueError),
)

_OBSERVED_FAMILIES: dict[str, type[BaseException] | None] | None = None


def _observed_validation_families() -> dict[str, type[BaseException] | None]:
    """Run each probe once against the real seam and cache the outcome."""
    global _OBSERVED_FAMILIES
    if _OBSERVED_FAMILIES is None:
        observed: dict[str, type[BaseException] | None] = {}
        for name, build_spec, _pinned in _PINNED_VALIDATION_PROBES:
            try:
                _native_seam.render_frame_png(build_spec())
            except Exception as exc:  # noqa: BLE001 - observation, not handling
                observed[name] = type(exc)
            else:
                observed[name] = None
        _OBSERVED_FAMILIES = observed
    return _OBSERVED_FAMILIES


# ---------------------------------------------------------------------------
# Harness contract (runs everywhere; no compiled extension required)
# ---------------------------------------------------------------------------


class TestRecordingStubHarness(unittest.TestCase):
    """Pure-Python harness semantics shared with the backend test lane."""

    def setUp(self):
        self.stub = _RecordingNativeStub()

    def test_last_spec_equals_spec_of_just_made_call(self):
        spec_a = _frame_spec(64, 48)
        spec_b = _frame_spec(80, 40)
        self.stub.render_frame_png(spec_a)
        self.assertEqual(self.stub.last_spec, spec_a)
        snapshot_a = copy.deepcopy(spec_a)
        self.stub.render_frame_png(spec_b)
        self.assertEqual(self.stub.last_spec, spec_b)
        # Earlier specs are not retained beyond the latest call record and
        # neither spec was disturbed by the harness reads.
        self.assertEqual(spec_a, snapshot_a)

    def test_output_deterministic_per_spec_across_interleave(self):
        spec_a = _frame_spec(64, 48)
        spec_b = _frame_spec(80, 40)
        first_a = self.stub.render_frame_png(spec_a)
        first_b = self.stub.render_frame_png(spec_b)
        second_a = self.stub.render_frame_png(copy.deepcopy(spec_a))
        self.assertEqual(first_a, second_a, "A/B/A interleave changed spec A")
        self.assertNotEqual(first_a, first_b, "distinct geometries collided")

    def test_stub_ihdr_tracks_requested_geometry(self):
        png = self.stub.render_frame_png(_frame_spec(96, 60))
        self.assertEqual(_png_dimensions(png), (96, 60))


# ---------------------------------------------------------------------------
# Real-seam authority consequences (skipped unless the compiled extension is
# importable, mirroring test_phase3b_backend.py's guard pattern)
# ---------------------------------------------------------------------------


@unittest.skipUnless(
    HAS_REAL_NATIVE_SEAM, "compiled lumenplot_mpl._native seam not available"
)
class TestNativeAuthorityConsequences(unittest.TestCase):
    """PYTHON-OBSERVABLE half of LP-MPL-005 at the private native seam."""

    def test_same_spec_renders_identical_bytes(self):
        # Sealed-snapshot stability: an identical request must not drift.
        first = _native_seam.render_frame_png(_frame_spec())
        second = _native_seam.render_frame_png(_frame_spec())
        self.assertEqual(first, second)

    def test_caller_spec_is_never_mutated(self):
        # Extraction copies into owned IR exactly once (lib.rs binding
        # contract); the caller's mapping must survive byte-for-byte.
        spec = _frame_spec()
        snapshot = copy.deepcopy(spec)
        _native_seam.render_frame_png(spec)
        self.assertEqual(spec, snapshot)

    def test_ihdr_matches_requested_canvas_pixels(self):
        spec = _frame_spec(72, 56)
        png = _native_seam.render_frame_png(spec)
        self.assertEqual(_png_dimensions(png), (72, 56))

    def test_different_geometry_is_not_a_cached_first_frame(self):
        small = _native_seam.render_frame_png(_frame_spec(64, 48))
        large = _native_seam.render_frame_png(_frame_spec(96, 64))
        self.assertNotEqual(small, large)

    def test_alternating_specs_show_no_cross_call_state_leakage(self):
        spec_a = _frame_spec(64, 48)
        spec_b = _frame_spec(80, 40)
        first_a = _native_seam.render_frame_png(copy.deepcopy(spec_a))
        _native_seam.render_frame_png(spec_b)
        second_a = _native_seam.render_frame_png(copy.deepcopy(spec_a))
        self.assertEqual(first_a, second_a, "interleaved call changed spec A")

    # -- validation failures are explicit, never silent (contract: ValueError
    #    family per lib.rs binding-contract comment; audited empirically) --

    def test_missing_required_key_raises_valueerror(self):
        with self.assertRaises(ValueError):
            _native_seam.render_frame_png(_frame_spec_missing_key())

    def test_malformed_vertex_raises_valueerror(self):
        with self.assertRaises(ValueError):
            _native_seam.render_frame_png(_frame_spec_bad_vertex())

    def test_out_of_range_rgba_raises_valueerror(self):
        with self.assertRaises(ValueError):
            _native_seam.render_frame_png(_frame_spec_out_of_range_rgba())

    def test_observed_exception_families_match_pinned_expectations(self):
        observed = _observed_validation_families()
        for name, _build_spec, pinned in _PINNED_VALIDATION_PROBES:
            with self.subTest(probe=name):
                seen = observed[name]
                self.assertIsNotNone(
                    seen, "invalid input was accepted silently"
                )
                self.assertTrue(
                    issubclass(seen, pinned),
                    f"{name}: observed {seen.__name__}, suite pins "
                    f"{pinned.__name__} (lib.rs binding-contract comment)",
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
