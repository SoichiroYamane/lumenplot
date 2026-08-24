"""LP-MPL-012 text-matrix evidence: text boundaries under the Phase-3B slice.

Requirement under test (verbatim, ``docs/requirements/lumenplot-v1.0.md``)::

    LP-MPL-012 | SHOULD: "Keep ordinary strict-profile text capture at public
    Matplotlib text and metrics boundaries; private implementation names are not
    part of the compatibility contract." Target: versioned text matrix.
    Release: v1 quality. Phase: 2. Evidence: ``AT-MPL-TEXT``.

Current-slice reality pinned honestly (ADR 0015 section 4, mandatory collector
trace): text callbacks are EXCLUDED from the eligible trace, therefore

- strict mode rejects any text-bearing figure as unsupported before any write,
  and
- hybrid mode publishes a whole-frame Agg fallback whose text is rendered by
  Matplotlib's own public draw path, never by lumenplot capture.

No test in this file asserts anything about font or metrics internals: until a
text-capture slice exists, text layout, shaping, and metrics behavior are
Matplotlib-Agg-owned, and this suite deliberately measures none of them.

Versioned text matrix (evidence target: Matplotlib 3.11.1, backend API 1.1).
The executed row is filled only from observed runs of this suite; every other
row says ``not run`` and must stay that way until someone reruns the suite on
that version.

| mpl-version | strict-text | hybrid-text-path | source-of-truth |
| --- | --- | --- | --- |
| 3.11.1 | rejected (``unsupported-capability``) | whole-frame Agg fallback, text pixels seen | this suite (observed, CPython 3.14.7) |
| 3.8 - 3.10 | not run | not run | - |
| 3.11.0 | not run | not run | - |
| 3.11.2+ | not run | not run | - |
| 3.12 - latest | not run | not run | - |

Private-name rule (structural): no test here references a private Matplotlib
name. The only occurrence of forbidden-token spellings is the module-level
tuple consumed by the scan and by its negative control.
"""

from __future__ import annotations

import struct
import types
import unittest
import unittest.mock
import zlib

try:
    import matplotlib
except ModuleNotFoundError:  # offline cells: matplotlib evidence is a later slice
    matplotlib = None
else:
    matplotlib.use("module://matplotlib.backends.backend_agg")  # baseline only

    from matplotlib.lines import Line2D  # noqa: E402

MATPLOTLIB_PRESENT = matplotlib is not None

#: Stable API-0002 token for strict rejection (machine contract; wording is not).
UNSUPPORTED_CODE = "unsupported-capability"

#: Forbidden private-name spellings (ADR 0015 section 2). ``Axes.axison`` is a
#: documented-enough fixture knob already covered by the sibling suite and is
#: intentionally not scanned here. These literals must appear nowhere else in
#: this file.
FORBIDDEN_PRIVATE_TOKENS = (
    "_Backend",
    "_api",
    "_pylab_helpers",
    "_renderer",
    "Gcf",
    "matplotlib._",
)


# ---------------------------------------------------------------------------
# Local duplicates of the sibling-suite fixtures (do NOT modify the originals)
# ---------------------------------------------------------------------------


def _load_backend():
    """Import the backend lazily; requires matplotlib (absent in offline cells)."""
    import importlib

    return importlib.import_module("lumenplot_mpl.backend")


def _stub_native_png(width: int, height: int) -> bytes:
    """A minimal deterministic PNG with correct IHDR (no raster content)."""
    header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(
        ">IIBBBBB", width, height, 8, 6, 0, 0, 0
    )
    return header + b"\x00\x00\x00\x00IEND\xaeB`\x82"


class _StubNativeModule(types.SimpleNamespace):
    """Stand-in for the private native seam recording the last spec."""

    last_spec: dict | None = None

    @staticmethod
    def render_frame_png(spec):  # noqa: N802 - mirrors native name
        _StubNativeModule.last_spec = spec
        return _stub_native_png(spec["width_px"], spec["height_px"])


def _install_stub_native():
    """Patch the backend's private-seam accessor with the recording stub."""
    real = __import__("lumenplot_mpl.backend", fromlist=["_native"])
    return unittest.mock.patch.object(real, "_native", lambda: _StubNativeModule)


FIGSIZE = (2.0, 1.0)
DPI = 100
AXES_RECT = (0.1, 0.1, 0.8, 0.8)  # axison off; fixed-style line only
TEXT_DATA_AT = (1.0, 4.5)  # axes data coords; glyph span stays clear of the line


def _line_kwargs():
    """Fixed style surface required by ADR 0015 section 5."""
    return {
        "color": "red",
        "linewidth": 2.0,
        "solid_capstyle": "butt",
        "solid_joinstyle": "miter",
    }


def _canvas_with_text(mode="strict"):
    """Eligible one-line figure plus exactly one Axes Text artist."""
    from matplotlib import figure

    fig = figure.Figure(figsize=FIGSIZE, dpi=DPI)
    canvas = _load_backend().FigureCanvasLumenPlot(fig, mode=mode)
    ax = fig.add_axes(list(AXES_RECT))
    ax.axison = False
    ax.add_line(Line2D([0.0, 10.0], [0.0, 5.0], **_line_kwargs()))
    ax.text(*TEXT_DATA_AT, "hello")
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(0.0, 5.0)
    return fig, canvas


def _canvas_without_text(mode="strict", dashed=False):
    """Control figure: identical geometry, no Text artist."""
    from matplotlib import figure

    fig = figure.Figure(figsize=FIGSIZE, dpi=DPI)
    canvas = _load_backend().FigureCanvasLumenPlot(fig, mode=mode)
    ax = fig.add_axes(list(AXES_RECT))
    ax.axison = False
    kwargs = _line_kwargs()
    if dashed:
        kwargs["linestyle"] = "--"
    ax.add_line(Line2D([0.0, 10.0], [0.0, 5.0], **kwargs))
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(0.0, 5.0)
    return fig, canvas


class _RecordingTarget:
    """Binary file-like target recording every public write/close call."""

    def __init__(self):
        self.chunks: list[bytes] = []
        self.write_calls = 0
        self.close_calls = 0

    def write(self, data):
        self.write_calls += 1
        self.chunks.append(data)

    def close(self):
        self.close_calls += 1


# ---------------------------------------------------------------------------
# Minimal stdlib PNG inspection of bytes this suite itself received
# ---------------------------------------------------------------------------


def _ihdr_dimensions(png_bytes: bytes) -> tuple[int, int]:
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "PNG magic missing"
    chunk = png_bytes[12:16]
    assert chunk == b"IHDR"
    width, height = struct.unpack(">II", png_bytes[16:24])
    return width, height


def _decode_png_rows(png_bytes: bytes) -> list[bytes]:
    """Decode a non-interlaced RGBA8 PNG into unfiltered top-down rows."""
    pos = 8
    idat = bytearray()
    width = height = None
    while pos < len(png_bytes):
        (length,) = struct.unpack(">I", png_bytes[pos : pos + 4])
        ctype = png_bytes[pos + 4 : pos + 8]
        data = png_bytes[pos + 8 : pos + 8 + length]
        if ctype == b"IHDR":
            width, height, _depth, color, *_rest = struct.unpack(">IIBBBBB", data[:13])
            assert (_depth, color) == (8, 6), "expected 8-bit RGBA"
        elif ctype == b"IDAT":
            idat += data
        pos += 12 + length
    raw = zlib.decompress(bytes(idat))
    stride = width * 4
    bpp = 4
    rows: list[bytes] = []
    previous = bytearray(stride)
    cursor = 0
    for _y in range(height):
        filt = raw[cursor]
        cursor += 1
        line = bytearray(raw[cursor : cursor + stride])
        cursor += stride
        if filt == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif filt == 2:
            for x in range(stride):
                line[x] = (line[x] + previous[x]) & 0xFF
        elif filt == 3:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + previous[x]) >> 1)) & 0xFF
        elif filt == 4:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                corner = previous[x - bpp] if x >= bpp else 0
                above = previous[x]
                predictor = left + above - corner
                pa, pb, pc = (
                    abs(predictor - left),
                    abs(predictor - above),
                    abs(predictor - corner),
                )
                if pa <= pb and pa <= pc:
                    chosen = left
                elif pb <= pc:
                    chosen = above
                else:
                    chosen = corner
                line[x] = (line[x] + chosen) & 0xFF
        else:
            assert filt == 0, f"unexpected PNG filter {filt}"
        previous = line
        rows.append(bytes(line))
    return rows


def _pixel_span() -> tuple[int, int, int, int]:
    """Public-geometry bounding box around the text, excluding the line.

    Derived from FIGSIZE/DPI/AXES_RECT/TEXT_DATA_AT only: the linear data-to-
    pixel mapping of the fixture places the glyphs near the computed anchor,
    and the diagonal line stays well below this span.
    """
    width_px = round(FIGSIZE[0] * DPI)
    height_px = round(FIGSIZE[1] * DPI)
    ax_x, ax_y, ax_w, ax_h = AXES_RECT
    anchor_x = ax_x * width_px + (TEXT_DATA_AT[0] / 10.0) * ax_w * width_px
    anchor_y = ax_y * height_px + (TEXT_DATA_AT[1] / 5.0) * ax_h * height_px
    baseline_row = height_px - anchor_y  # top-left row of the text baseline
    return (
        max(0, round(anchor_x) - 4),
        max(0, round(baseline_row) - 16),
        min(width_px, round(anchor_x) + 42),
        min(height_px, round(baseline_row) + 8),
    )


def _count_ink_pixels(rows: list[bytes], span: tuple[int, int, int, int]) -> int:
    """Pixels darker than the white background inside *span*."""
    x0, y0, x1, y1 = span
    count = 0
    for row_index in range(y0, y1):
        row = rows[row_index]
        for column in range(x0, x1):
            offset = column * 4
            red, green, blue = row[offset], row[offset + 1], row[offset + 2]
            if min(red, green, blue) < 200:
                count += 1
    return count


def _count_different_pixels(rows_a: list[bytes], rows_b: list[bytes]) -> int:
    assert len(rows_a) == len(rows_b)
    count = 0
    for row_a, row_b in zip(rows_a, rows_b):
        assert len(row_a) == len(row_b)
        for offset in range(0, len(row_a), 4):
            if row_a[offset : offset + 4] != row_b[offset : offset + 4]:
                count += 1
    return count


# ---------------------------------------------------------------------------
# Case 1: strict mode rejects text before publishing anything
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestStrictRejectsText(unittest.TestCase):
    """Text artists are excluded from the eligible trace: strict rejects."""

    def setUp(self):
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_axes_text_rejected_before_any_write(self):
        _fig, canvas = _canvas_with_text(mode="strict")
        target = _RecordingTarget()
        with self.assertRaises(
            _load_backend().LumenPlotUnsupportedError
        ) as ctx:
            canvas.render_png(target)
        self.assertEqual(ctx.exception.code, UNSUPPORTED_CODE)
        self.assertEqual(target.write_calls, 0)
        self.assertEqual(target.chunks, [])
        self.assertEqual(target.close_calls, 0)

    def test_figure_text_is_rejected_like_axes_text(self):
        from matplotlib import figure

        fig = figure.Figure(figsize=FIGSIZE, dpi=DPI)
        canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="strict")
        ax = fig.add_axes(list(AXES_RECT))
        ax.axison = False
        ax.add_line(Line2D([0.0, 10.0], [0.0, 5.0], **_line_kwargs()))
        ax.set_xlim(0.0, 10.0)
        ax.set_ylim(0.0, 5.0)
        fig.text(0.5, 0.5, "figure text")
        target = _RecordingTarget()
        with self.assertRaises(
            _load_backend().LumenPlotUnsupportedError
        ) as ctx:
            canvas.render_png(target)
        self.assertEqual(ctx.exception.code, UNSUPPORTED_CODE)
        self.assertEqual(target.write_calls, 0)

    def test_savefig_path_rejects_text_before_any_write(self):
        _fig, canvas = _canvas_with_text(mode="strict")
        target = _RecordingTarget()
        with self.assertRaises(
            _load_backend().LumenPlotUnsupportedError
        ) as ctx:
            canvas.figure.savefig(target, format="png")
        self.assertEqual(ctx.exception.code, UNSUPPORTED_CODE)
        self.assertEqual(target.write_calls, 0)

    def test_failed_strict_attempt_publishes_no_diagnostics(self):
        _fig, canvas = _canvas_with_text(mode="strict")
        with self.assertRaises(_load_backend().LumenPlotUnsupportedError):
            canvas.render_png()
        self.assertEqual(canvas.last_diagnostics, ())


# ---------------------------------------------------------------------------
# Case 2: hybrid publishes whole-frame Agg PNG carrying rendered text pixels
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestHybridTextPath(unittest.TestCase):
    """Whole-frame Agg fallback renders text via Matplotlib's public path."""

    def setUp(self):
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_text_figure_falls_back_with_exactly_one_diagnostic(self):
        backend = _load_backend()
        _fig, canvas = _canvas_with_text(mode="hybrid")
        result = canvas.render_png()
        self.assertIsInstance(result, backend.LumenPlotPngResult)
        self.assertEqual(result.png_bytes[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(_ihdr_dimensions(result.png_bytes), (200, 100))
        self.assertEqual(len(result.diagnostics), 1)
        diagnostic = result.diagnostics[0]
        self.assertIsInstance(diagnostic, backend.LumenPlotFallbackDiagnostic)
        self.assertEqual(diagnostic.kind, UNSUPPORTED_CODE)
        self.assertEqual(diagnostic.scope, "whole-frame")
        self.assertEqual(diagnostic.representation, "raster")
        self.assertEqual(diagnostic.output_format, "png")
        self.assertEqual(diagnostic.fallback_type, "matplotlib-agg")
        self.assertEqual(diagnostic.generation, 1)
        self.assertEqual(canvas.last_diagnostics, result.diagnostics)

        # Pixel evidence: the published frame carries rendered glyph pixels
        # that the otherwise-identical text-free control render lacks.
        control_a_png = self._render_hybrid_control()
        control_b_png = self._render_hybrid_control()
        self.assertEqual(control_a_png, control_b_png)  # same-host determinism
        text_rows = _decode_png_rows(result.png_bytes)
        control_rows = _decode_png_rows(control_a_png)
        span = _pixel_span()
        ink_in_text_render = _count_ink_pixels(text_rows, span)
        ink_in_control = _count_ink_pixels(control_rows, span)
        self.assertGreaterEqual(ink_in_text_render, 10)
        self.assertEqual(ink_in_control, 0)
        self.assertGreaterEqual(
            _count_different_pixels(text_rows, control_rows),
            ink_in_text_render,
        )

    def _render_hybrid_control(self) -> bytes:
        """Same fixture geometry, dashed line forces the same Agg fallback."""
        _fig, canvas = _canvas_without_text(mode="hybrid", dashed=True)
        result = canvas.render_png()
        self.assertEqual(len(result.diagnostics), 1)
        self.assertEqual(
            result.diagnostics[0].fallback_type, "matplotlib-agg"
        )
        return result.png_bytes


# ---------------------------------------------------------------------------
# Case 3: private-name rule pinned structurally on the adapter source
# ---------------------------------------------------------------------------


def _adapter_source() -> str:
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / "python" / "lumenplot_mpl" / "backend.py").read_text(
        encoding="utf-8"
    )


def _forbidden_token_hits(source: str) -> list[str]:
    return [token for token in FORBIDDEN_PRIVATE_TOKENS if token in source]


class TestPrivateBoundaryScan(unittest.TestCase):
    """The adapter stays on documented public Matplotlib APIs (ADR 0015 s2)."""

    def test_adapter_source_contains_no_private_matplotlib_names(self):
        self.assertEqual(_forbidden_token_hits(_adapter_source()), [])

    def test_negative_control_flips_the_scan_red(self):
        poisoned = _adapter_source() + "\nprobe = " + repr(
            FORBIDDEN_PRIVATE_TOKENS[0]
        ) + "\n"
        self.assertEqual(
            _forbidden_token_hits(poisoned), [FORBIDDEN_PRIVATE_TOKENS[0]]
        )


# ---------------------------------------------------------------------------
# Cases 4 and 5: docstring boundary statements and matrix self-consistency
# ---------------------------------------------------------------------------


class TestDocumentedBoundaries(unittest.TestCase):
    """The honesty statements are load-bearing artifacts of this suite."""

    def test_metrics_behavior_declared_matplotlib_agg_owned(self):
        self.assertIn("Matplotlib-Agg-owned", __doc__)

    def test_matrix_header_columns_present(self):
        for column in ("mpl-version", "strict-text", "hybrid-text-path",
                       "source-of-truth"):
            self.assertIn(column, __doc__)


def _normalized(text: str) -> str:
    """Collapse whitespace so RST table padding never hides a mismatch."""
    return " ".join(text.split())


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestMatrixSelfConsistency(unittest.TestCase):
    """The executed row must declare exactly the running Matplotlib version.

    A run on any other version fails here on purpose: the row may only be
    updated after someone reruns this suite on that version and observes the
    behavior again.
    """

    def _normalized_doc_rows(self) -> list[str]:
        return [_normalized(line) for line in (__doc__ or "").splitlines()]

    def test_executed_row_declares_observed_version(self):
        # Keep these two literals in sync with the executed docstring row.
        expected_prefix = _normalized(
            f"| {matplotlib.__version__} |"
            " rejected (``unsupported-capability``)"
            " | whole-frame Agg fallback, text pixels seen"
        )
        matching = [
            row
            for row in self._normalized_doc_rows()
            if row.startswith(expected_prefix)
        ]
        self.assertTrue(
            matching,
            "docstring text matrix lacks an observed row for the running"
            f" Matplotlib {matplotlib.__version__}",
        )
        self.assertIn("| this suite", matching[0])

    def test_every_other_row_stays_not_run(self):
        observed_prefix = f"| {matplotlib.__version__} |"
        for line in (__doc__ or "").splitlines():
            stripped = line.strip()
            if not stripped.startswith("| 3.") or "mpl-version" in stripped:
                continue
            if stripped.startswith(observed_prefix):
                continue
            self.assertIn(
                "not run",
                stripped,
                f"row for another version claims evidence: {stripped!r}",
            )
