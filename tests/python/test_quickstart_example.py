"""Smoke tests for ``examples/quickstart.py`` (card U1).

Runs the quickstart script as a subprocess and checks that it exits 0 and
that the produced file is a real PNG (magic bytes plus IHDR dimensions).
This is deliberately end-to-end: the example is the user-facing "first five
minutes" entry point, so the test exercises the installed distribution the
same way a user would (the CI gate pip-installs the distribution before
running this suite).

Environment policy mirrors the existing Phase-3B suites:

- matplotlib present  -> full run of the script subprocess;
- matplotlib absent   -> structural checks only (the suite skips the
  subprocess run via ``skipUnless``, never fails).

The compiled native seam is not stubbed here on purpose: the smoke test
must prove the real render path works, exactly as the card's local
verification step (``pip install . && python examples/quickstart.py``)
does.
"""

from __future__ import annotations

import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
QUICKSTART = REPO_ROOT / "examples" / "quickstart.py"

try:
    import matplotlib  # noqa: F401

    MATPLOTLIB_PRESENT = True
except ModuleNotFoundError:  # offline cells: matplotlib evidence is a later slice
    MATPLOTLIB_PRESENT = False


def _png_ihdr_dimensions(png_bytes: bytes) -> tuple[int, int]:
    """Validate PNG magic + IHDR header and return ``(width, height)``."""
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "PNG magic missing"
    length = struct.unpack(">I", png_bytes[8:12])[0]
    chunk_type = png_bytes[12:16]
    assert chunk_type == b"IHDR"
    width, height = struct.unpack(">II", png_bytes[16:24])
    assert length == 13
    return width, height


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class QuickstartRunTests(unittest.TestCase):
    """Execute the quickstart script like a user and inspect its output."""

    def test_quickstart_exits_zero_and_writes_png(self) -> None:
        with tempfile.TemporaryDirectory() as workdir:
            completed = subprocess.run(
                [sys.executable, str(QUICKSTART)],
                cwd=workdir,
                env={**os.environ},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            self.assertEqual(
                completed.returncode,
                0,
                msg=f"stdout={completed.stdout!r} stderr={completed.stderr!r}",
            )

            output = Path(workdir) / "quickstart.png"
            self.assertTrue(output.is_file(), "quickstart.png was not created")
            png_bytes = output.read_bytes()
            self.assertTrue(len(png_bytes) > 8, "PNG output is truncated")

            width, height = _png_ihdr_dimensions(png_bytes)
            # figsize=(4, 3) inches at dpi=144 -> 576 x 432 pixels.
            self.assertEqual((width, height), (576, 432))


class QuickstartStructureTests(unittest.TestCase):
    """Always-on guards that do not need matplotlib or the native seam."""

    def test_example_file_exists(self) -> None:
        self.assertTrue(QUICKSTART.is_file(), f"missing {QUICKSTART}")

    def test_backend_selected_before_figure_work(self) -> None:
        source = QUICKSTART.read_text(encoding="utf-8")
        use_call = 'matplotlib.use("module://lumenplot_mpl.backend")'
        self.assertIn(use_call, source)
        # The backend selection must precede any figure/canvas construction
        # in the module text so a fresh interpreter never binds Agg first.
        # (The word "pyplot" appears only in the example's prose comment, so
        # guard against an actual pyplot import instead of a substring hit.)
        self.assertLess(
            source.index(use_call),
            source.index("figure.Figure("),
            "backend selection must come before figure creation",
        )
        self.assertNotIn("from matplotlib import pyplot", source)
        code_lines = [
            line for line in source.splitlines()
            if not line.lstrip().startswith("#")
        ]
        self.assertFalse(
            any("pyplot" in line for line in code_lines),
            "the example must not use pyplot",
        )

    def test_hybrid_mode_documented(self) -> None:
        source = QUICKSTART.read_text(encoding="utf-8")
        self.assertIn('mode="hybrid"', source)

    def test_strict_eligibility_style_surface(self) -> None:
        # The example must keep the fixed strict-mode style surface: axes
        # off, butt caps, miter joins, and none of the elements strict mode
        # rejects (titles/text/markers/dashes).
        source = QUICKSTART.read_text(encoding="utf-8")
        self.assertIn("set_axis_off()", source)
        self.assertIn('solid_capstyle="butt"', source)
        self.assertIn('solid_joinstyle="miter"', source)
        for forbidden in ("set_title", ".text(", "marker=", "linestyle"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
