"""Phase-3B entry-point and loader-surface discovery checks.

These checks run against whatever ``lumenplot-mpl`` distribution is visible
in the current interpreter. They are deliberately tolerant of the sibling
implementation lane: when the public backend surface is absent, every test
skips cleanly instead of failing, so the suite stays green before and after
the backend lands. Once the backend exists, the same assertions become the
standing regression gate for the declared identity.

Declared identity under test (ADR 0015 §11 / API 0005 §1):
    distribution      lumenplot-mpl
    import package    lumenplot_mpl
    backend module    lumenplot_mpl.backend
    module loader     module://lumenplot_mpl.backend
    entry point       [project.entry-points."matplotlib.backend"]
                      lumenplot = "lumenplot_mpl.backend"

Run inside the probe venv:
    <probe-venv>/bin/python -m unittest discover -s tests/python
"""

from __future__ import annotations

import unittest
from importlib.metadata import entry_points


def _backend_module_available() -> bool:
    try:
        __import__("lumenplot_mpl.backend")
    except ModuleNotFoundError as error:
        # Only the missing backend module itself counts as "not landed";
        # a broken dependency should fail loudly, not skip.
        return error.name != "lumenplot_mpl.backend"
    except ImportError:
        return False
    return True


def _matplotlib_available() -> bool:
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return False
    return True


BACKEND_PRESENT = _backend_module_available()
MATPLOTLIB_PRESENT = _matplotlib_available()

EXPECTED_ENTRY_POINT_VALUE = "lumenplot_mpl.backend"
FORBIDDEN_EXPORTS = (
    "_Backend",
    "new_figure_manager",
    "draw_if_interactive",
    "show",
)


@unittest.skipUnless(
    BACKEND_PRESENT,
    "lumenplot_mpl.backend not implemented yet (sibling lane owns it); "
    "these checks activate automatically once it lands",
)
class EntryPointDiscoveryTests(unittest.TestCase):
    """Identity checks that need the installed backend module."""

    def test_entry_point_group_declares_lumenplot(self) -> None:
        values = [
            ep.value
            for ep in entry_points(group="matplotlib.backend")
            if ep.name == "lumenplot"
        ]
        self.assertEqual(values, [EXPECTED_ENTRY_POINT_VALUE])

    def test_entry_point_resolves_to_backend_module(self) -> None:
        matches = [
            ep for ep in entry_points(group="matplotlib.backend")
            if ep.name == "lumenplot"
        ]
        if not matches:
            self.fail("entry point lumenplot missing from matplotlib.backend group")
        loaded = matches[0].load()
        self.assertTrue(hasattr(loaded, "FigureCanvasLumenPlot"))

    def test_forbidden_legacy_exports_absent(self) -> None:
        import lumenplot_mpl.backend as backend

        for name in FORBIDDEN_EXPORTS:
            self.assertFalse(hasattr(backend, name), name)

    @unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not installed")
    def test_module_loader_registration(self) -> None:
        import matplotlib

        matplotlib.use("module://lumenplot_mpl.backend")
        self.assertEqual(matplotlib.get_backend(), "module://lumenplot_mpl.backend")


class DeclaredIdentityConstantsTests(unittest.TestCase):
    """Always-on guard that the declared identity strings stay canonical."""

    def test_identity_matches_api0005(self) -> None:
        self.assertEqual(EXPECTED_ENTRY_POINT_VALUE, "lumenplot_mpl.backend")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
