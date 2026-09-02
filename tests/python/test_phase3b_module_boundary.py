"""Private-module and documented-Matplotlib boundary checks for Phase-3B."""

from __future__ import annotations

import re
from pathlib import Path
import unittest


class TestBackendPrivateModuleBoundary(unittest.TestCase):
    """The backend facade keeps its accepted names after private factoring."""

    def test_public_exports_and_record_identity_are_unchanged(self) -> None:
        import lumenplot_mpl.backend as backend
        from matplotlib.backend_bases import FigureCanvasBase, FigureManagerBase

        self.assertEqual(
            set(backend.__all__),
            {
                "FigureCanvas",
                "FigureCanvasLumenPlot",
                "FigureManager",
                "LumenPlotFallbackDiagnostic",
                "LumenPlotPngResult",
                "filetypes",
                "required_interactive_framework",
            },
        )
        self.assertIs(backend.FigureCanvas, backend.FigureCanvasLumenPlot)
        self.assertTrue(issubclass(backend.FigureCanvasLumenPlot, FigureCanvasBase))
        self.assertIs(backend.FigureManager, FigureManagerBase)
        self.assertEqual(backend.filetypes, {"png": "Portable Network Graphics"})
        self.assertIsNone(backend.required_interactive_framework)
        self.assertEqual(
            {
                backend.LumenPlotFallbackDiagnostic.__module__,
                backend.LumenPlotPngResult.__module__,
                backend.LumenPlotUnsupportedError.__module__,
            },
            {backend.__name__},
        )

    def test_preflight_is_private_and_backend_seam_stays_patchable(self) -> None:
        import lumenplot_mpl.backend as backend

        self.assertEqual(
            backend._EligibilityPreflight.__module__,
            "lumenplot_mpl.backend_preflight",
        )
        self.assertTrue(callable(backend._native))

    def test_adapter_sources_do_not_reference_forbidden_private_apis(self) -> None:
        import lumenplot_mpl.backend as backend

        package_dir = Path(backend.__file__).resolve().parent
        sources = tuple(
            package_dir / name
            for name in (
                "backend.py",
                "backend_preflight.py",
                "backend_support.py",
                "backend_types.py",
            )
        )
        forbidden = (
            re.compile(r"matplotlib\._"),
            re.compile(r"(?<!\w)_Backend(?!\w)"),
            re.compile(r"(?<!\w)_renderer(?!\w)"),
            re.compile(r"(?<!\w)_api(?!\w)"),
            re.compile(r"_pylab_helpers"),
            re.compile(r"\baxison\b"),
            re.compile(r"_original_dpi"),
        )
        for path in sources:
            source = path.read_text(encoding="utf-8")
            for pattern in forbidden:
                self.assertIsNone(
                    pattern.search(source),
                    f"{pattern.pattern} found in {path.name}",
                )


if __name__ == "__main__":
    unittest.main()
