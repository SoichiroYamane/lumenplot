#!/usr/bin/env python3
"""Mutation tests for the Phase-2B dependency evidence checker."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_phase2b_dependencies.py"


class Phase2BDependencyMutationTests(unittest.TestCase):
    def fixture(self) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory(prefix="lumenplot-phase2b-dependencies-")
        fixture_root = Path(temporary.name)
        shutil.copy2(ROOT / "Cargo.toml", fixture_root / "Cargo.toml")
        shutil.copy2(ROOT / "Cargo.lock", fixture_root / "Cargo.lock")
        shutil.copytree(ROOT / "crates", fixture_root / "crates")
        scripts_dir = fixture_root / "scripts"
        scripts_dir.mkdir()
        shutil.copy2(CHECKER, scripts_dir / CHECKER.name)
        return temporary

    def run_checker(self, fixture_root: Path) -> tuple[int, str]:
        result = subprocess.run(
            [sys.executable, str(fixture_root / "scripts" / CHECKER.name), "--root", str(fixture_root)],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout + result.stderr

    def assert_rejected(self, mutate, expected: str) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            mutate(fixture_root)
            returncode, output = self.run_checker(fixture_root)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn(expected, output)
            self.assertNotIn(str(fixture_root), output)

    def test_unmodified_graph_passes(self) -> None:
        with self.fixture() as temporary:
            returncode, output = self.run_checker(Path(temporary))
            self.assertEqual(returncode, 0, output)
            self.assertIn("phase2b dependency graph: OK", output)
            self.assertIn("dependency build-script evidence: crc32fast", output)

    def test_checksum_drift_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "Cargo.lock"
            source = path.read_text(encoding="utf-8")
            path.write_text(
                source.replace(
                    "checksum = \"47ffee5eaaf5527f630fb0e356b90ebdec84d5d18d937c5e440350f88c5a91ea\"",
                    "checksum = \"0000000000000000000000000000000000000000000000000000000000000000\"",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_rejected(mutate, "Cargo.lock checksum drift for tiny-skia")

    def test_transitive_package_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "Cargo.lock"
            source = path.read_text(encoding="utf-8")
            path.write_text(
                source.replace(
                    'name = "tiny-skia-path"',
                    'name = "unexpected-package"',
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_rejected(mutate, "Cargo.lock missing packages: tiny-skia-path@0.12.0")


if __name__ == "__main__":
    unittest.main()
