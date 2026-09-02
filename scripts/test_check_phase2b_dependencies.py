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
            self.assertIn("crc32fast", output)

    def test_wgpu_package_checksum_drift_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "Cargo.lock"
            source = path.read_text(encoding="utf-8")
            marker = (
                'name = "wgpu"\n'
                'version = "29.0.4"\n'
                'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
                'checksum = "76e8840e1ba2881d4cbb18d2147627a56af426ff064c0401eb0c8410c6325d07"'
            )
            self.assertIn(marker, source)
            path.write_text(
                source.replace(
                    'checksum = "76e8840e1ba2881d4cbb18d2147627a56af426ff064c0401eb0c8410c6325d07"',
                    'checksum = "0000000000000000000000000000000000000000000000000000000000000000"',
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_rejected(mutate, "Cargo.lock checksum drift for wgpu")

    def test_wgpu_lock_inventory_digest_is_fail_closed(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "Cargo.lock"
            path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

        self.assert_rejected(mutate, "Cargo.lock wgpu inventory hash drift")

    def test_bench_workspace_edge_drift_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            # Remove the render-api edge from the bench manifest AND its
            # lockfile entry: the exact workspace-edge expectation must fire.
            path = root / "crates/lumenplot-bench/Cargo.toml"
            text = path.read_text(encoding="utf-8")
            marker = 'lumenplot-render-api = { path = "../lumenplot-render-api"'
            self.assertIn(marker, text)
            lines = [line for line in text.splitlines(keepends=True) if marker not in line]
            path.write_text("".join(lines), encoding="utf-8")

            lock = root / "Cargo.lock"
            source = lock.read_text(encoding="utf-8")
            start = source.index('name = "lumenplot-bench"')
            end = source.index("[[package]]", start)
            block = source[start:end]
            dependency = ' "lumenplot-render-api",\n'
            self.assertIn(dependency, block)
            lock.write_text(
                source[:start] + block.replace(dependency, "") + source[end:],
                encoding="utf-8",
            )

        self.assert_rejected(
            mutate,
            "dependency graph drift for workspace package lumenplot-bench",
        )

    def test_bench_unexpected_extra_edge_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            # Add an undeclared extra internal edge to the bench manifest and
            # mirror it into the lockfile so metadata stays resolvable; the
            # exact inventory must reject it closed.
            path = root / "crates/lumenplot-bench/Cargo.toml"
            text = path.read_text(encoding="utf-8")
            text = text.replace(
                "[dependencies]\n",
                '[dependencies]\nlumenplot-viewer = { path = "../lumenplot-viewer", version = "0.1.0" }\n',
                1,
            )
            path.write_text(text, encoding="utf-8")

            lock = root / "Cargo.lock"
            source = lock.read_text(encoding="utf-8")
            start = source.index('name = "lumenplot-bench"')
            end = source.index("[[package]]", start)
            block = source[start:end]
            block = block.replace(
                'dependencies = [\n',
                'dependencies = [\n "lumenplot-viewer",\n',
                1,
            )
            lock.write_text(source[:start] + block + source[end:], encoding="utf-8")

        self.assert_rejected(
            mutate,
            "dependency graph drift for workspace package lumenplot-bench",
        )

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

    # ------------------------------------------------------------------
    # B2-P Metal prototype lane (workstream-manager decision on task
    # t_50138c06): transitive closure of the macOS-target-gated objc2 edges.
    # ------------------------------------------------------------------

    def test_metal_objc2_checksum_drift_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "Cargo.lock"
            source = path.read_text(encoding="utf-8")
            marker = 'checksum = "561f357ba7f3a2a61563a186a163d0a3a5247e1089524a3981d49adb775078bc"'
            self.assertIn(marker, source)
            path.write_text(
                source.replace(
                    marker,
                    'checksum = "0000000000000000000000000000000000000000000000000000000000000000"',
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_rejected(mutate, "Cargo.lock checksum drift for objc2")

    def test_metal_transitive_package_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "Cargo.lock"
            source = path.read_text(encoding="utf-8")
            path.write_text(
                source.replace('name = "objc2-encode"', 'name = "unexpected-package"', 1),
                encoding="utf-8",
            )

        self.assert_rejected(mutate, "Cargo.lock missing packages: objc2-encode@4.1.0")

    def test_metal_workspace_edges_are_enforced_in_lockfile(self) -> None:
        def mutate(root: Path) -> None:
            # Strip the pinned gate from the manifest *and* its lock entry.
            # The now-orphaned objc packages keep the lock stale for
            # `--locked`, so the exact workspace-edge expectation surfaces
            # through the lockfile check.
            path = root / "crates/lumenplot-render-metal/Cargo.toml"
            text = path.read_text(encoding="utf-8")
            marker = '[target.\'cfg(target_os = "macos")\'.dependencies]'
            self.assertIn(marker, text)
            path.write_text(text[: text.index(marker)].rstrip() + "\n", encoding="utf-8")

            lock = root / "Cargo.lock"
            source = lock.read_text(encoding="utf-8")
            start = source.index('name = "lumenplot-render-metal"')
            end = source.index("[[package]]", start)
            block = source[start:end]
            for dependency in (' "objc2",\n', ' "objc2-foundation",\n', ' "objc2-metal",\n'):
                self.assertIn(dependency, block)
                block = block.replace(dependency, "")
            lock.write_text(source[:start] + block + source[end:], encoding="utf-8")

        self.assert_rejected(
            mutate,
            "Cargo.lock dependency graph drift for workspace package lumenplot-render-metal",
        )

    def test_metal_workspace_edge_is_enforced_in_metadata(self) -> None:
        def mutate(root: Path) -> None:
            # Strip the pinned gate everywhere so `cargo metadata --locked`
            # stays resolvable; the missing objc edges must then be caught by
            # the exact metadata resolution expectation.
            path = root / "crates/lumenplot-render-metal/Cargo.toml"
            text = path.read_text(encoding="utf-8")
            marker = '[target.\'cfg(target_os = "macos")\'.dependencies]'
            self.assertIn(marker, text)
            path.write_text(text[: text.index(marker)].rstrip() + "\n", encoding="utf-8")

            lock = root / "Cargo.lock"
            source = lock.read_text(encoding="utf-8")
            start = source.index('name = "lumenplot-render-metal"')
            end = source.index("[[package]]", start)
            block = source[start:end]
            for dependency in (' "objc2",\n', ' "objc2-foundation",\n', ' "objc2-metal",\n'):
                self.assertIn(dependency, block)
                block = block.replace(dependency, "")
            source = source[:start] + block + source[end:]
            lock.write_text(source, encoding="utf-8")

        self.assert_rejected(
            mutate,
            "metadata dependency graph drift for workspace package lumenplot-render-metal",
        )


if __name__ == "__main__":
    unittest.main()
