#!/usr/bin/env python3
"""Focused tests for the canonical requirements/traceability checker."""

from __future__ import annotations

from contextlib import contextmanager
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_requirements_traceability.py"
REQUIREMENTS_SOURCE = ROOT / "docs" / "requirements" / "lumenplot-v1.0.md"
TRACEABILITY_SOURCE = ROOT / "docs" / "requirements" / "traceability-v1.0.md"


class RequirementsTraceabilityCheckerTests(unittest.TestCase):
    @contextmanager
    def _controlled_documents(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            requirements = directory / "requirements.md"
            traceability = directory / "traceability.md"
            shutil.copyfile(REQUIREMENTS_SOURCE, requirements)
            shutil.copyfile(TRACEABILITY_SOURCE, traceability)
            yield requirements, traceability

    def _run_checker(self, requirements: Path, traceability: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), str(requirements), str(traceability)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    @staticmethod
    def _replace_in_section(
        text: str, heading: str, end_heading: str, old: str, new: str
    ) -> str:
        start = text.index(heading)
        end = text.index(end_heading, start + len(heading))
        section = text[start:end]
        updated, count = section.replace(old, new, 1), section.count(old)
        if count != 1:
            raise AssertionError(f"expected one mutation target in {heading!r}, found {count}")
        return text[:start] + updated + text[end:]

    @staticmethod
    def _remove_first_row(text: str, heading: str, end_heading: str) -> str:
        start = text.index(heading)
        end = text.find("\n## ", start + len(heading))
        if end == -1:
            end = len(text)
        section = text[start:end]
        lines = section.splitlines(keepends=True)
        row_index = next(
            index for index, line in enumerate(lines) if line.startswith("| `LP-")
        )
        del lines[row_index]
        return text[:start] + "".join(lines) + text[end:]

    def test_canonical_controlled_copies_pass(self) -> None:
        with self._controlled_documents() as (requirements, traceability):
            result = self._run_checker(requirements, traceability)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS: requirements/traceability consistent", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_missing_and_orphan_registry_id_are_reported(self) -> None:
        with self._controlled_documents() as (requirements, traceability):
            text = traceability.read_text(encoding="utf-8")
            text = self._replace_in_section(
                text,
                "## Complete requirement registry",
                "## Normative closure: every MUST and MUST NOT",
                "| `LP-PROD-001` |",
                "| `LP-TEST-999` |",
            )
            traceability.write_text(text, encoding="utf-8")
            result = self._run_checker(requirements, traceability)
        diagnostics = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requirement/registry ID mismatch", diagnostics)
        self.assertIn("missing from registry: LP-PROD-001", diagnostics)
        self.assertIn("orphan in registry: LP-TEST-999", diagnostics)

    def test_duplicate_registry_id_is_reported(self) -> None:
        with self._controlled_documents() as (requirements, traceability):
            text = traceability.read_text(encoding="utf-8")
            heading = "## Complete requirement registry"
            closure_heading = "## Normative closure: every MUST and MUST NOT"
            start = text.index(heading)
            end = text.index(closure_heading, start + len(heading))
            row = next(
                line for line in text[start:end].splitlines() if line.startswith("| `LP-")
            )
            text = text[:end] + row + "\n" + text[end:]
            traceability.write_text(text, encoding="utf-8")
            result = self._run_checker(requirements, traceability)
        diagnostics = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate registry ID(s): LP-PROD-001", diagnostics)

    def test_normative_closure_omission_is_reported(self) -> None:
        with self._controlled_documents() as (requirements, traceability):
            text = traceability.read_text(encoding="utf-8")
            text = self._remove_first_row(
                text,
                "## Normative closure: every MUST and MUST NOT",
                "## Evidence plans by requirement family",
            )
            traceability.write_text(text, encoding="utf-8")
            result = self._run_checker(requirements, traceability)
        diagnostics = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("normative closure missing ID(s): LP-PROD-002", diagnostics)

    def test_status_partition_mismatch_is_reported(self) -> None:
        with self._controlled_documents() as (requirements, traceability):
            text = traceability.read_text(encoding="utf-8")
            heading = "## Complete requirement registry"
            closure_heading = "## Normative closure: every MUST and MUST NOT"
            start = text.index(heading)
            end = text.index(closure_heading, start + len(heading))
            section = text[start:end]
            lines = section.splitlines(keepends=True)
            for index, line in enumerate(lines):
                if line.startswith("| `LP-PROD-003` "):
                    self.assertTrue(line.rstrip().endswith("| Not implemented |"))
                    lines[index] = line.replace(
                        "| Not implemented |",
                        "| Implemented (bounded; test mutation) |",
                        1,
                    )
                    break
            else:
                self.fail("status mutation target not found")
            traceability.write_text(
                text[:start] + "".join(lines) + text[end:], encoding="utf-8"
            )
            result = self._run_checker(requirements, traceability)
        diagnostics = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("status partition mismatch", diagnostics)
        self.assertIn("Implemented (bounded)=18", diagnostics)
        self.assertIn("Not implemented=145", diagnostics)

    def test_evidence_gate_count_mismatch_is_reported(self) -> None:
        with self._controlled_documents() as (requirements, traceability):
            text = traceability.read_text(encoding="utf-8")
            heading = "## Complete requirement registry"
            closure_heading = "## Normative closure: every MUST and MUST NOT"
            start = text.index(heading)
            end = text.index(closure_heading, start + len(heading))
            section = text[start:end]
            lines = section.splitlines(keepends=True)
            for index, line in enumerate(lines):
                if line.startswith("| `LP-FUNC-001` "):
                    self.assertIn("`AT-FUNC-LINE2D`", line)
                    lines[index] = line.replace("`AT-FUNC-LINE2D`", "", 1)
                    break
            else:
                self.fail("evidence-gate mutation target not found")
            traceability.write_text(
                text[:start] + "".join(lines) + text[end:], encoding="utf-8"
            )
            result = self._run_checker(requirements, traceability)
        diagnostics = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("evidence gates: expected 106, found 105", diagnostics)


if __name__ == "__main__":
    unittest.main()
