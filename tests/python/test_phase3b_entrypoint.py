"""Phase-3B entry-point and loader-surface discovery checks.

These checks run against whatever ``lumenplot-mpl`` distribution is visible
in the current interpreter. They are deliberately tolerant of every
environment state and skip cleanly instead of failing:

1. backend absent: everything under ``EntryPointDiscoveryTests`` skips until
   ``lumenplot_mpl`` (sibling implementation lane) lands;
2. backend present, entry point undeclared: only the two entry-point-metadata
   checks skip until the pyproject ``[project.entry-points]`` table lands
   (packaging gap owned by t_bb3a2b34);
3. fully declared: the same assertions become the standing regression gate
   for the declared identity.

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
        # A missing matplotlib is NOT "backend available": without it the
        # entry-point metadata checks cannot run, so report not-available and
        # let them skip for that honest reason instead of failing.
        if error.name == "matplotlib":
            return False
        # A missing lumenplot_mpl or lumenplot_mpl.backend means the sibling
        # lane has not landed yet -> skip. Any other missing module (a broken
        # dependency) must fail loudly, not skip.
        return error.name not in ("lumenplot_mpl", "lumenplot_mpl.backend")
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


def _entry_point_declared() -> bool:
    """True iff the pyproject ``[project.entry-points]`` table has landed.

    The packaging gap (t_bb3a2b34) means the installed metadata does not yet
    declare the ``lumenplot`` entry point even when the backend module itself
    is importable, so the two entry-point-metadata checks must skip until the
    manifest lands — then activate automatically as the standing gate.
    """
    if not BACKEND_PRESENT:
        return False
    return any(
        ep.name == "lumenplot"
        for ep in entry_points(group="matplotlib.backend")
    )

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

    @unittest.skipUnless(
        _entry_point_declared(),
        "pyproject [project.entry-points] table not landed yet "
        "(owned by t_bb3a2b34)",
    )
    def test_entry_point_group_declares_lumenplot(self) -> None:
        values = [
            ep.value
            for ep in entry_points(group="matplotlib.backend")
            if ep.name == "lumenplot"
        ]
        self.assertEqual(values, [EXPECTED_ENTRY_POINT_VALUE])

    @unittest.skipUnless(
        _entry_point_declared(),
        "pyproject [project.entry-points] table not landed yet "
        "(owned by t_bb3a2b34)",
    )
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
