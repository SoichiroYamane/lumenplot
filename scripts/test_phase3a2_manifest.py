#!/usr/bin/env python3
"""Mutation tests for the Phase-3A2 same-wheel evidence manifest emitter."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
import unittest.mock
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scripts" / "phase3a2-manifest.py"

WHEEL_TAG = "cp311-abi3-manylinux_2_28_x86_64"
WHEEL_VERSION = "1.2.3"


def load_manifest_module():
    spec = importlib.util.spec_from_file_location("test_phase3a2_manifest_module", MANIFEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def encoded_digest(body: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(body).digest())
    return digest.decode("ascii").rstrip("=")


class WheelBuilder:
    """Assemble minimal synthetic wheels for RECORD verification tests."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.version = WHEEL_VERSION
        self.tag = WHEEL_TAG
        self.unlisted: list[str] = []
        self.tampered: dict[str, bytes] = {}

    def path(self) -> Path:
        metadata_name = "lumenplot_mpl-0.0.0.dist-info/METADATA"
        wheel_name = "lumenplot_mpl-0.0.0.dist-info/WHEEL"
        record_name = "lumenplot_mpl-0.0.0.dist-info/RECORD"
        native_name = "lumenplot_mpl/_native.so"
        bodies = {
            metadata_name: f"Metadata-Version: 2.4\nName: lumenplot-mpl\nVersion: {self.version}\n".encode(),
            wheel_name: f"Wheel-Version: 1.0\nGenerator: test\nTag: {self.tag}\n".encode(),
            native_name: b"\x7fELF-fake-native-object",
        }
        for name in self.tampered:
            if name not in bodies and name not in self.unlisted:
                raise KeyError(f"tampered member {name} is not part of the fixture")
        record_rows = [
            f"{name},sha256={encoded_digest(body)},{len(body)}" for name, body in bodies.items()
        ]
        record_body = ("\n".join([*record_rows, f"{record_name},,"]) + "\n").encode()
        wheel_path = self.root / f"lumenplot_mpl-{self.version}-{self.tag}.whl"
        with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, body in bodies.items():
                archive.writestr(name, self.tampered.get(name, body))
            # Unlisted members are written into the archive without any
            # RECORD row, exercising the reverse-direction check.
            for name in self.unlisted:
                archive.writestr(name, f"unlisted payload for {name}".encode())
            archive.writestr(record_name, record_body)
        return wheel_path


class ManifestTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_manifest_module()
        temporary = tempfile.TemporaryDirectory(prefix="lumenplot-manifest-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.builder = WheelBuilder(self.root)

    def write_sbom(self, components: list[dict] | None = None) -> Path:
        if components is None:
            components = [
                {
                    "bom-ref": "pkg:cargo/lumenplot@0.1.0",
                    "name": "lumenplot",
                    "purl": "pkg:cargo/lumenplot@0.1.0",
                    "type": "library",
                    "version": "0.1.0",
                },
                {
                    "bom-ref": "pkg:cargo/serde@1.0.219",
                    "hashes": [{"alg": "SHA-256", "content": "ab" * 32}],
                    "name": "serde",
                    "purl": "pkg:cargo/serde@1.0.219",
                    "type": "library",
                    "version": "1.0.219",
                },
            ]
        path = self.root / "sbom.json"
        path.write_text(
            json.dumps({"bomFormat": "CycloneDX", "components": components, "specVersion": "1.5"}),
            encoding="utf-8",
        )
        return path

    def run_main(
        self,
        wheel: Path | None,
        *,
        wheel_sha256: str | None = None,
        cargo_version: str | None = None,
        sbom: Path | None | object = ...,
        observed: Path | None | object = None,
    ) -> tuple[int, str]:
        argv = [
            "phase3a2-manifest.py",
            "--wheel",
            str(wheel),
            "--wheel-sha256",
            wheel_sha256 or hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "--cargo-version",
            cargo_version or WHEEL_VERSION,
            "--cargo-lock-sha256",
            "cd" * 32,
            "--source-commit",
            "f" * 40,
            "--sbom",
            str(self.write_sbom() if sbom is ... else sbom),
        ]
        if observed is not None:
            argv += ["--observed", str(observed)]
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

    def write_observed(self, body: dict) -> Path:
        path = self.root / "observed.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        return path


class RecordVerificationTests(ManifestTestCase):
    def test_valid_wheel_returns_verified_names(self) -> None:
        names = self.module.verified_record_names(self.builder.path())
        self.assertEqual(
            {
                "lumenplot_mpl-0.0.0.dist-info/METADATA",
                "lumenplot_mpl-0.0.0.dist-info/WHEEL",
                "lumenplot_mpl/_native.so",
            },
            names,
        )

    def test_archive_member_missing_from_record_fails(self) -> None:
        self.builder.unlisted = ["lumenplot_mpl/extra.dat"]
        with self.assertRaises(SystemExit) as raised:
            self.module.verified_record_names(self.builder.path())
        self.assertIn("RECORD does not list", str(raised.exception))
        self.assertIn("extra.dat", str(raised.exception))

    def test_record_hash_tampering_fails(self) -> None:
        wheel = self.builder.path()
        # Rewrite one recorded member after the RECORD row was computed by
        # rebuilding the archive with different native-object bytes.
        self.builder.tampered = {"lumenplot_mpl/_native.so": b"\x7fELF-tampered"}
        rebuilt = self.root / "rebuilt.whl"
        with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(rebuilt, "w") as target:
            for info in source.infolist():
                body = source.read(info.filename)
                if info.filename == "lumenplot_mpl/_native.so":
                    body = b"\x7fELF-tampered"
                target.writestr(info, body)
        with self.assertRaises(SystemExit) as raised:
            self.module.verified_record_names(rebuilt)
        self.assertIn("hashes or sizes are invalid", str(raised.exception))

    def test_record_row_listing_absent_file_fails(self) -> None:
        wheel = self.builder.path()
        rebuilt = self.root / "rebuilt.whl"
        with zipfile.ZipFile(wheel) as source, zipfile.ZipFile(rebuilt, "w") as target:
            for info in source.infolist():
                body = source.read(info.filename)
                if info.filename.endswith("RECORD"):
                    body = body.replace(
                        b"lumenplot_mpl/_native.so,", b"lumenplot_mpl/gone.bin,"
                    )
                target.writestr(info, body)
        with self.assertRaises(SystemExit) as raised:
            self.module.verified_record_names(rebuilt)
        self.assertIn("file that is absent", str(raised.exception))


class ManifestEmissionTests(ManifestTestCase):
    def test_happy_path_emits_observed_manifest(self) -> None:
        code, output = self.run_main(self.builder.path())
        self.assertEqual(0, code)
        manifest = json.loads(output)
        self.assertEqual("lumenplot.phase3a2-wheel-evidence.v1", manifest["schema"])
        self.assertEqual(WHEEL_VERSION, manifest["source"]["cargo_version"])
        self.assertEqual("lumenplot-mpl", manifest["source"]["distribution"])
        self.assertEqual(len(manifest["runtime_cells"]), 4)
        self.assertEqual(
            [cell["python"] for cell in manifest["runtime_cells"]],
            ["3.11", "3.12", "3.13", "3.14"],
        )
        self.assertTrue(all(cell["result"] == "pass" for cell in manifest["runtime_cells"]))
        self.assertEqual(WHEEL_TAG, manifest["wheel"]["tag"])
        self.assertEqual(True, manifest["wheel"]["record"])

    def test_wheel_digest_mismatch_fails(self) -> None:
        code, message = self.run_main(self.builder.path(), wheel_sha256="ee" * 32)
        self.assertNotEqual(0, code)
        self.assertIn("does not match the built artifact", message)

    def test_metadata_version_mismatch_fails(self) -> None:
        code, message = self.run_main(self.builder.path(), cargo_version="9.9.9")
        self.assertNotEqual(0, code)
        self.assertIn("does not match Cargo", message)

    def test_tag_mismatch_fails(self) -> None:
        self.builder.tag = "cp310-abi3-manylinux_2_28_x86_64"
        code, message = self.run_main(self.builder.path())
        self.assertNotEqual(0, code)
        self.assertIn("does not match the accepted Phase-3A2 tag", message)

    def test_empty_sbom_inventory_fails(self) -> None:
        code, message = self.run_main(self.builder.path(), sbom=self.write_sbom([]))
        self.assertNotEqual(0, code)
        self.assertIn("inventory is empty", message)

    def test_malformed_component_purl_fails(self) -> None:
        component = {
            "name": "serde",
            "purl": "pkg:cargo/other@1.0.0",
            "version": "1.0.219",
        }
        code, message = self.run_main(
            self.builder.path(), sbom=self.write_sbom([component])
        )
        self.assertNotEqual(0, code)
        self.assertIn("purl does not match", message)

    def test_non_hex_component_hash_fails(self) -> None:
        component = {
            "hashes": [{"alg": "SHA-256", "content": "zz"}],
            "name": "serde",
            "purl": "pkg:cargo/serde@1.0.219",
            "version": "1.0.219",
        }
        code, message = self.run_main(
            self.builder.path(), sbom=self.write_sbom([component])
        )
        self.assertNotEqual(0, code)
        self.assertIn("not hex-encoded", message)

    def test_unlisted_member_fails_through_main(self) -> None:
        self.builder.unlisted = ["lumenplot_mpl/sneaky.dat"]
        code, message = self.run_main(self.builder.path())
        self.assertNotEqual(0, code)
        self.assertIn("RECORD does not list", message)


COMPLETE_OBSERVED = {
    "abi3audit_version": "0.0.27",
    "auditwheel_version": "6.9.0",
    "glibc": "2.28",
    "platform": "linux/amd64",
    "rust_version": "1.97.0",
    "elf_runpath": ["$ORIGIN/lumenplot_mpl.libs"],
}


class ObservedBuilderTests(ManifestTestCase):
    def test_without_observed_file_builder_keeps_pinned_literals(self) -> None:
        code, output = self.run_main(self.builder.path())
        self.assertEqual(0, code)
        builder = json.loads(output)["builder"]
        self.assertEqual("1.89.0", builder["rust_version"])
        self.assertNotIn("elf_runpath", builder)

    def test_observed_file_replaces_runtime_literals_and_adds_runpath(self) -> None:
        code, output = self.run_main(
            self.builder.path(), observed=self.write_observed(COMPLETE_OBSERVED)
        )
        self.assertEqual(0, code)
        builder = json.loads(output)["builder"]
        self.assertEqual("1.97.0", builder["rust_version"])
        self.assertEqual("6.9.0", builder["auditwheel_version"])
        self.assertEqual(["$ORIGIN/lumenplot_mpl.libs"], builder["elf_runpath"])
        # Image identity stays pinned; it is verified against the config
        # digest before any evidence runs, not observed at runtime.
        self.assertEqual("linux/amd64", builder["platform"])

    def test_missing_observed_field_fails_closed(self) -> None:
        for field in (
            "abi3audit_version",
            "auditwheel_version",
            "glibc",
            "platform",
            "rust_version",
            "elf_runpath",
        ):
            body = {key: value for key, value in COMPLETE_OBSERVED.items() if key != field}
            code, message = self.run_main(
                self.builder.path(), observed=self.write_observed(body)
            )
            self.assertNotEqual(0, code, field)
            if field == "elf_runpath":
                self.assertIn("elf_runpath list", message)
            else:
                self.assertIn("no observed", message)

    def test_non_string_observed_value_fails_closed(self) -> None:
        body = dict(COMPLETE_OBSERVED)
        body["glibc"] = 2.28
        code, message = self.run_main(self.builder.path(), observed=self.write_observed(body))
        self.assertNotEqual(0, code)

    def test_empty_runpath_entry_fails_closed(self) -> None:
        body = dict(COMPLETE_OBSERVED)
        body["elf_runpath"] = ["$ORIGIN/libs", ""]
        code, message = self.run_main(self.builder.path(), observed=self.write_observed(body))
        self.assertNotEqual(0, code)
        self.assertIn("elf_runpath list", message)

    def test_unparsable_observed_file_fails_closed(self) -> None:
        path = self.root / "observed.json"
        path.write_text("{not json", encoding="utf-8")
        code, message = self.run_main(self.builder.path(), observed=path)
        self.assertNotEqual(0, code)
        self.assertIn("cannot parse observed-evidence file", message)

    def test_non_object_observed_file_fails_closed(self) -> None:
        path = self.root / "observed.json"
        path.write_text("[1, 2]", encoding="utf-8")
        code, message = self.run_main(self.builder.path(), observed=path)
        self.assertNotEqual(0, code)
        self.assertIn("JSON object", message)


if __name__ == "__main__":
    unittest.main()
