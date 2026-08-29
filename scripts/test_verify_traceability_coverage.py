#!/usr/bin/env python3
"""Mutation tests for the traceability coverage-bookkeeping verifier."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "verify_traceability_coverage.py"
TRACE = ROOT / "docs" / "requirements" / "traceability-v1.0.md"
GAPR1 = ROOT / "docs" / "research" / "codex-gap-verification-candidate-rows-t_3f634d0b.md"


class TraceabilityCoverageMutationTests(unittest.TestCase):
    def fixture(self) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory(prefix="lumenplot-traceability-coverage-")
        fixture_root = Path(temporary.name)
        requirements_dir = fixture_root / "docs" / "requirements"
        research_dir = fixture_root / "docs" / "research"
        scripts_dir = fixture_root / "scripts"
        requirements_dir.mkdir(parents=True)
        research_dir.mkdir(parents=True)
        scripts_dir.mkdir()
        shutil.copy2(TRACE, requirements_dir / TRACE.name)
        shutil.copy2(GAPR1, research_dir / GAPR1.name)
        shutil.copy2(CHECKER, scripts_dir / CHECKER.name)
        return temporary

    def run_checker(self, fixture_root: Path) -> tuple[int, str]:
        result = subprocess.run(
            [sys.executable, str(fixture_root / "scripts" / CHECKER.name)],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout + result.stderr

    def replace_once(self, root: Path, old: str, new: str) -> None:
        path = root / "docs" / "requirements" / "traceability-v1.0.md"
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def assert_rejected(self, mutate, expected: str) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            mutate(fixture_root)
            returncode, output = self.run_checker(fixture_root)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn(expected, output)
            self.assertNotIn(str(fixture_root), output)

    def test_unmodified_document_passes(self) -> None:
        with self.fixture() as temporary:
            returncode, output = self.run_checker(Path(temporary))
            self.assertEqual(returncode, 0, output)
            self.assertIn("OK: traceability coverage bookkeeping verified", output)
            self.assertIn("237 entries, 156 normative, 106 gates", output)

    def test_published_entry_total_drift_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            self.replace_once(root,
                              "Requirement entries: **237**.",
                              "Requirement entries: **238**.")

        self.assert_rejected(mutate, "[FAIL] published entries == recomputed")

    def test_normative_split_regression_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            self.replace_once(root,
                              "three normative, two advisory",
                              "two normative, three advisory")

        self.assert_rejected(mutate, "[FAIL] adoption note says three normative, two advisory")

    def test_missing_closure_row_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "docs" / "requirements" / "traceability-v1.0.md"
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            kept = []
            removed = False
            in_closure = False
            for line in lines:
                if line.startswith("## Normative closure"):
                    in_closure = True
                if in_closure and not removed and line.startswith("| `LP-MPL-021`"):
                    removed = True
                    continue
                kept.append(line)
            self.assertTrue(removed)
            path.write_text("".join(kept), encoding="utf-8")

        self.assert_rejected(mutate, "missing=['LP-MPL-021']")

    def test_registry_class_drift_against_source_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            # Flip LP-FUNC-040's registry class; the source research doc still
            # levels it MUST, and the closure section keeps the old class.
            self.replace_once(root,
                              "| `LP-FUNC-040` | `MUST` |",
                              "| `LP-FUNC-040` | `SHOULD` |")

        self.assert_rejected(mutate, "[FAIL] GAP-R1 split is three normative / two advisory")

    def test_gate_name_typo_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            self.replace_once(root,
                              "`AT-MPL-UNIT-DATA` | Not implemented |",
                              "`AT-MPL-UNIT-DATAX` | Not implemented |")

        self.assert_rejected(mutate,
                             "[FAIL] GAP-R1 gate defined in registry: AT-MPL-UNIT-DATA")


if __name__ == "__main__":
    unittest.main()
