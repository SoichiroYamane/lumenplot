#!/usr/bin/env python3
"""Mutation tests for the Phase-3A2 SBOM evidence emitter."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SBOM = ROOT / "scripts" / "phase3a2-sbom.py"

LOCK_CHECKSUM = "aa" * 32
OTHER_CHECKSUM = "bb" * 32


def load_sbom_module():
    spec = importlib.util.spec_from_file_location("test_phase3a2_sbom_module", SBOM)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registry_package(name: str = "serde", version: str = "1.0.219", **overrides) -> dict:
    package = {
        "name": name,
        "version": version,
        "source": "registry+https://github.com/rust-lang/crates.io-index",
        "checksum": LOCK_CHECKSUM,
        "license": "MIT OR Apache-2.0",
    }
    package.update(overrides)
    if package.get("checksum") is None:
        del package["checksum"]
    return package


def lock_entry(name: str, version: str, checksum: str | None = LOCK_CHECKSUM) -> str:
    lines = [
        "[[package]]",
        f'name = "{name}"',
        f'version = "{version}"',
        'source = "registry+https://github.com/rust-lang/crates.io-index"',
    ]
    if checksum is not None:
        lines.append(f'checksum = "{checksum}"')
    return "\n".join(lines) + "\n"


class SbomTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_sbom_module()
        temporary = tempfile.TemporaryDirectory(prefix="lumenplot-sbom-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write_lock(self, body: str) -> Path:
        path = self.root / "Cargo.lock"
        path.write_text(body, encoding="utf-8")
        return path

    def write_metadata(self, packages: list[dict]) -> Path:
        path = self.root / "cargo-metadata.json"
        path.write_text(json.dumps({"packages": packages}), encoding="utf-8")
        return path

    def write_pyproject(self, body: str | None = None) -> Path:
        path = self.root / "pyproject.toml"
        path.write_text(
            body
            or (
                "[build-system]\n"
                'requires = ["maturin==1.14.1"]\n'
                "\n"
                "[project]\n"
                'name = "lumenplot-mpl"\n'
                'version = "0.1.0"\n'
            ),
            encoding="utf-8",
        )
        return path

    def run_main(
        self,
        metadata_path: Path | None,
        lock_path: Path | None,
        pyproject_path: Path | None | object = ...,
    ) -> tuple[int, str]:
        """Run main() with explicit arguments; returns (exit-code, output).

        A nonzero code carries the failure message instead of emitted JSON.
        """

        argv = ["phase3a2-sbom.py"]
        if metadata_path is not None:
            argv += ["--metadata", str(metadata_path)]
        if lock_path is not None:
            argv += ["--lockfile", str(lock_path)]
        if pyproject_path is not ...:
            if pyproject_path is not None:
                argv += ["--pyproject", str(pyproject_path)]
        else:
            argv += ["--pyproject", str(self.write_pyproject())]
        stdout = io.StringIO()
        with (
            unittest.mock.patch.object(sys, "argv", argv),
            contextlib.redirect_stdout(stdout),
        ):
            try:
                code = self.module.main()
            except SystemExit as error:
                if isinstance(error.code, int):
                    return error.code, stdout.getvalue()
                return 1, str(error.code)
        return code, stdout.getvalue()


import contextlib  # noqa: E402


class SbomHappyPathTests(SbomTestCase):
    def test_emits_verified_checksums_and_ignores_extra_lock_entries(self) -> None:
        metadata = self.write_metadata(
            [registry_package(), registry_package(name="lumenplot", source=None)]
        )
        lock = self.write_lock(
            "version = 4\n\n"
            + lock_entry("other", "9.9.9", OTHER_CHECKSUM)
            + "\n"
            + lock_entry("serde", "1.0.219")
        )
        code, output = self.run_main(metadata, lock)
        self.assertEqual(0, code)
        document = json.loads(output)
        components = {component["name"]: component for component in document["components"]}
        self.assertEqual(
            [{"alg": "SHA-256", "content": LOCK_CHECKSUM}],
            components["serde"]["hashes"],
        )
        self.assertNotIn("hashes", components["lumenplot"])
        self.assertEqual({"lumenplot", "serde"}, set(components))
        self.assertEqual(
            {"bom-ref": "pkg:cargo/serde@1.0.219"},
            {"bom-ref": components["serde"]["bom-ref"]},
        )

    def test_workspace_member_is_exempt_from_checksum_requirements(self) -> None:
        metadata = self.write_metadata([registry_package(name="lumenplot", source=None)])
        lock = self.write_lock("version = 4\n")
        code, output = self.run_main(metadata, lock)
        self.assertEqual(0, code)
        self.assertEqual(
            ["lumenplot"],
            [component["name"] for component in json.loads(output)["components"]],
        )

    def test_lock_without_source_line_still_verifies_registry_package(self) -> None:
        # A lock entry lacking `source` records no checksum; a registry
        # package therefore cannot be verified against it and must fail.
        metadata = self.write_metadata([registry_package()])
        lock = self.write_lock('version = 4\n\n[[package]]\nname = "serde"\nversion = "1.0.219"\n')
        code, message = self.run_main(metadata, lock)
        self.assertNotEqual(0, code)
        self.assertIn("no checksum entry", message)


class SbomFailClosedTests(SbomTestCase):
    LOCK = "version = 4\n\n" + lock_entry("serde", "1.0.219")

    def test_missing_lock_entry_for_registry_package_fails(self) -> None:
        metadata = self.write_metadata([registry_package()])
        lock = self.write_lock("version = 4\n")
        code, message = self.run_main(metadata, lock)
        self.assertNotEqual(0, code)
        self.assertIn("serde", message)

    def test_non_hex_checksum_fails(self) -> None:
        metadata = self.write_metadata([registry_package()])
        lock = self.write_lock(
            lock_entry("serde", "1.0.219", "A" + "b" * 63)
        )
        code, message = self.run_main(metadata, lock)
        self.assertNotEqual(0, code)
        self.assertIn("hexadecimal", message)

    def test_short_checksum_fails(self) -> None:
        metadata = self.write_metadata([registry_package()])
        lock = self.write_lock(lock_entry("serde", "1.0.219", "ab" * 31))
        code, message = self.run_main(metadata, lock)
        self.assertNotEqual(0, code)

    def test_uppercase_checksum_fails(self) -> None:
        metadata = self.write_metadata([registry_package()])
        lock = self.write_lock(lock_entry("serde", "1.0.219", "AB" * 32))
        code, message = self.run_main(metadata, lock)
        self.assertNotEqual(0, code)

    def test_metadata_checksum_disagreement_fails(self) -> None:
        metadata = self.write_metadata([registry_package(checksum="cc" * 32)])
        lock = self.write_lock(self.LOCK)
        code, message = self.run_main(metadata, lock)
        self.assertNotEqual(0, code)
        self.assertIn("does not match Cargo.lock", message)

    def test_missing_license_still_fails_closed(self) -> None:
        metadata = self.write_metadata([registry_package(license=None)])
        lock = self.write_lock(self.LOCK)
        code, message = self.run_main(metadata, lock)
        self.assertNotEqual(0, code)
        self.assertIn("no license for package serde", message)

    def test_unparsable_lockfile_fails(self) -> None:
        metadata = self.write_metadata([registry_package(name="lumenplot", source=None)])
        lock = self.write_lock("not [ valid toml {{{{")
        code, message = self.run_main(metadata, lock)
        self.assertNotEqual(0, code)
        self.assertIn("cannot parse Cargo.lock", message)

    def test_missing_required_arguments_fail(self) -> None:
        # argparse exits before main() logic runs, so bypass run_main's
        # SystemExit capture and require the exit to propagate.
        metadata = self.write_metadata([])
        lock = self.write_lock("")
        pyproject = self.write_pyproject()
        for argv in (
            ["phase3a2-sbom.py", "--lockfile", str(lock), "--pyproject", str(pyproject)],
            ["phase3a2-sbom.py", "--metadata", str(metadata), "--pyproject", str(pyproject)],
            ["phase3a2-sbom.py", "--metadata", str(metadata), "--lockfile", str(lock)],
        ):
            with (
                unittest.mock.patch.object(sys, "argv", argv),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                self.module.main()

    def test_empty_package_inventory_fails(self) -> None:
        metadata = self.write_metadata([])
        lock = self.write_lock(self.LOCK)
        code, message = self.run_main(metadata, lock)
        self.assertNotEqual(0, code)
        self.assertIn("no package inventory", message)


class PyprojectIdentityTests(SbomTestCase):
    def test_root_component_reflects_pyproject_identity(self) -> None:
        metadata = self.write_metadata([registry_package(name="lumenplot", source=None)])
        lock = self.write_lock("version = 4\n")
        pyproject = self.write_pyproject()
        code, output = self.run_main(metadata, lock, pyproject)
        self.assertEqual(0, code)
        component = json.loads(output)["metadata"]["component"]
        self.assertEqual({"name": "lumenplot-mpl", "version": "0.1.0"}, component)

    def test_dynamic_version_marker_is_rejected(self) -> None:
        metadata = self.write_metadata([registry_package(name="lumenplot", source=None)])
        lock = self.write_lock("version = 4\n")
        pyproject = self.write_pyproject(
            "[build-system]\n"
            'requires = ["maturin==1.14.1"]\n'
            "\n"
            "[project]\n"
            'name = "lumenplot-mpl"\n'
            "dynamic = [\"version\"]\n"
        )
        code, message = self.run_main(metadata, lock, pyproject)
        self.assertNotEqual(0, code)
        self.assertIn("no static version", message)

    def test_missing_project_table_fails(self) -> None:
        metadata = self.write_metadata([registry_package(name="lumenplot", source=None)])
        lock = self.write_lock("version = 4\n")
        pyproject = self.write_pyproject('[build-system]\nrequires = ["maturin==1.14.1"]\n')
        code, message = self.run_main(metadata, lock, pyproject)
        self.assertNotEqual(0, code)
        self.assertIn("no [project] table", message)

    def test_missing_name_or_version_fail(self) -> None:
        metadata = self.write_metadata([registry_package(name="lumenplot", source=None)])
        lock = self.write_lock("version = 4\n")
        for body in (
            "[project]\nversion = \"0.1.0\"\n",
            "[project]\nname = \"lumenplot-mpl\"\n",
        ):
            pyproject = self.write_pyproject(body)
            code, message = self.run_main(metadata, lock, pyproject)
            self.assertNotEqual(0, code)

    def test_unparsable_pyproject_fails(self) -> None:
        metadata = self.write_metadata([registry_package(name="lumenplot", source=None)])
        lock = self.write_lock("version = 4\n")
        pyproject = self.write_pyproject("not [ valid toml {{{{")
        code, message = self.run_main(metadata, lock, pyproject)
        self.assertNotEqual(0, code)
        self.assertIn("cannot parse pyproject", message)


if __name__ == "__main__":
    unittest.main()
