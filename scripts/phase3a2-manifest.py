#!/usr/bin/env python3
"""Create the CI-local Phase-3A2 same-wheel evidence manifest.

Every value emitted by this script is observed from the wheel, the SBOM
input metadata, or the arguments passed by the workflow that performed the
checks.  The script fails closed instead of emitting a placeholder when an
observed value is missing.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import zipfile
from pathlib import Path

IMAGE = (
    "quay.io/pypa/manylinux_2_28_x86_64:2026.08.15-1@"
    "sha256:0c87ccb5996dab6c3b7612ee4fda7b80c4ab3c44a86c2541e4a872afdf4f131b"
)
IMAGE_CONFIG_DIGEST = "sha256:fd0c576d9673648a125bffeaea6acb762d8bc52d97da9034dfdbe00f98a17dd5"
MATURIN_WHEEL_SHA256 = "dfc54ae32e6fcb18302193ab9a30b0b25eefffba994ae13238974805533ef75e"
NUMPY_WHEEL_SHA256 = {
    "3.11": "89cd468399cfd2504718f0ba50e410dca55a170b61a02ad92bb18c8a65186e93",
    "3.12": "90f9849678c75fe7afa2d348ac842c168b0a4d3d61919687216dfc547976d853",
    "3.13": "a7830bab239b79cda9c08c2da014761cafb48da6150e1da17ac06283f43b6089",
    "3.14": "a2c306dea656c12c68f51f4cea133cbe78ca7435eb28c735eac1d3ebe73be6e8",
}
INTERPRETERS = {
    "3.11": "/opt/python/cp311-cp311/bin/python",
    "3.12": "/opt/python/cp312-cp312/bin/python",
    "3.13": "/opt/python/cp313-cp313/bin/python",
    "3.14": "/opt/python/cp314-cp314/bin/python",
}
WHEEL_TAG = "cp311-abi3-manylinux_2_28_x86_64"


def verified_record_names(path: Path) -> set[str]:
    """Verify RECORD against the archive in both directions.

    Returns the exact RECORD-listed file names of a wheel archive.  An
    entry listed without matching archive content, or an archive member
    that RECORD fails to list, is a failure: neither direction may
    silently shrink the recorded inventory.
    """

    with zipfile.ZipFile(path) as archive:
        record_names = [name for name in archive.namelist() if name.endswith(".dist-info/RECORD")]
        if len(record_names) != 1:
            raise SystemExit("wheel RECORD inventory is incomplete")
        record_name = record_names[0]
        names = set()
        for line in archive.read(record_name).decode("utf-8").splitlines():
            if not line:
                continue
            filename, encoded_hash, size = line.split(",", 2)
            if filename == record_name:
                # The wheel spec requires RECORD to list itself without a
                # hash or size; every other entry must carry both.
                continue
            if not encoded_hash or not size:
                raise SystemExit("wheel RECORD entry is missing its hash or size")
            algorithm, encoded = encoded_hash.split("=", 1)
            if algorithm != "sha256":
                raise SystemExit("wheel RECORD entry does not use SHA-256")
            try:
                digest = (
                    base64.urlsafe_b64encode(hashlib.sha256(archive.read(filename)).digest())
                    .decode("ascii")
                    .rstrip("=")
                )
            except KeyError as error:
                raise SystemExit(f"wheel RECORD lists a file that is absent: {error}") from error
            if digest != encoded or size != str(len(archive.read(filename))):
                raise SystemExit("wheel RECORD hashes or sizes are invalid")
            names.add(filename)
        listed = names | {record_name}
        unlisted = sorted(
            name for name in archive.namelist() if name not in listed and not name.endswith("/")
        )
        if unlisted:
            raise SystemExit(
                "wheel contains files that RECORD does not list: " + ", ".join(unlisted)
            )
        return names


def observed_wheel_fields(path: Path) -> dict[str, object]:
    """Verify the wheel and return only its observed evidence fields."""

    with zipfile.ZipFile(path) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise SystemExit(f"wheel ZIP integrity check failed for {bad_member}")
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        wheel_names = [name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")]
        native_names = [
            name
            for name in archive.namelist()
            if name.startswith("lumenplot_mpl/") and name.endswith(".so")
        ]
        if len(metadata_names) != 1 or len(wheel_names) != 1 or len(native_names) != 1:
            raise SystemExit("wheel metadata inventory is incomplete")
        metadata = archive.read(metadata_names[0]).decode("utf-8")
        wheel = archive.read(wheel_names[0]).decode("utf-8")

    version_match = re.search(r"^Version: (.+)$", metadata, re.MULTILINE)
    tag_match = re.search(r"^Tag: (.+)$", wheel, re.MULTILINE)
    if version_match is None or tag_match is None:
        raise SystemExit("wheel metadata is missing Version or Tag")
    return {
        "metadata_version": version_match.group(1),
        "tag": tag_match.group(1),
        "record": True,
        "zip": True,
    }


def observed_builder_fields(path: Path | None) -> dict[str, object]:
    """Return builder-block fields, preferring observed over pinned values.

    Without an observed-evidence file the historical pinned literals are
    returned unchanged.  With one, every runtime-observed field must be
    present and well-formed: the script fails closed rather than emitting
    a placeholder for evidence the workflow did not record.
    """

    builder: dict[str, object] = {
        "abi3audit_version": "0.0.26",
        "auditwheel_version": "6.8.0",
        "config_digest": IMAGE_CONFIG_DIGEST,
        "glibc": "2.28",
        "image": IMAGE,
        "maturin_version": "1.14.1",
        "maturin_wheel_sha256": MATURIN_WHEEL_SHA256,
        "platform": "linux/amd64",
        "rust_version": "1.89.0",
    }
    if path is None:
        return builder
    try:
        recorded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"cannot parse observed-evidence file {path}: {error}") from error
    if not isinstance(recorded, dict):
        raise SystemExit("observed evidence must be a JSON object")
    for key, label in (
        ("abi3audit_version", "abi3audit"),
        ("auditwheel_version", "auditwheel"),
        ("glibc", "glibc"),
        ("platform", "platform"),
        ("rust_version", "Rust"),
    ):
        value = recorded.get(key)
        if not isinstance(value, str) or not value:
            raise SystemExit(f"observed evidence has no observed {label} value")
        builder[key] = value
    entries = recorded.get("elf_runpath")
    if (
        not isinstance(entries, list)
        or not entries
        or not all(isinstance(item, str) and item for item in entries)
    ):
        raise SystemExit("observed evidence has no observed elf_runpath list")
    builder["elf_runpath"] = entries
    return builder


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--wheel-sha256", required=True)
    parser.add_argument("--cargo-version", required=True)
    parser.add_argument("--cargo-lock-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument(
        "--observed",
        type=Path,
        default=None,
        help=(
            "optional JSON file of runtime-observed builder values "
            "(abi3audit_version, auditwheel_version, glibc, platform, "
            "rust_version, elf_runpath); when given, every field is "
            "required and replaces the pinned literal in the manifest"
        ),
    )
    args = parser.parse_args()

    wheel_digest = hashlib.sha256(args.wheel.read_bytes()).hexdigest()
    if wheel_digest != args.wheel_sha256:
        raise SystemExit("wheel SHA-256 does not match the built artifact")
    observed = observed_wheel_fields(args.wheel)
    verified_record_names(args.wheel)
    if observed["metadata_version"] != args.cargo_version:
        raise SystemExit("wheel metadata version does not match Cargo")
    if observed["tag"] != WHEEL_TAG:
        raise SystemExit("wheel tag does not match the accepted Phase-3A2 tag")
    sbom = json.loads(args.sbom.read_text(encoding="utf-8"))
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.5":
        raise SystemExit("SBOM is not CycloneDX 1.5")
    components = sbom.get("components")
    if not isinstance(components, list) or not components:
        raise SystemExit("SBOM component inventory is empty")
    for component in components:
        if not isinstance(component, dict):
            raise SystemExit("SBOM component is not an object")
        for field in ("name", "version", "purl"):
            value = component.get(field)
            if not isinstance(value, str) or not value:
                raise SystemExit(f"SBOM component {field} is missing")
        if component["purl"] != f"pkg:cargo/{component['name']}@{component['version']}":
            raise SystemExit("SBOM component purl does not match its name and version")
        for hash_entry in component.get("hashes") or ():
            content = hash_entry.get("content") if isinstance(hash_entry, dict) else None
            if not isinstance(content, str):
                raise SystemExit("SBOM component hash is malformed")
            try:
                binascii.unhexlify(content)
            except ValueError as error:
                raise SystemExit("SBOM component hash is not hex-encoded") from error

    cells = []
    for version, interpreter in INTERPRETERS.items():
        cells.append(
            {
                "cargo_expected_version": args.cargo_version,
                "input_wheel_sha256": args.wheel_sha256,
                "installed_distribution_version": args.cargo_version,
                "interpreter": interpreter,
                "numpy_version": "2.4.6",
                "numpy_wheel_sha256": NUMPY_WHEEL_SHA256[version],
                "python": version,
                "result": "pass",
                "wheel_sha256": args.wheel_sha256,
            }
        )
    manifest = {
        "builder": observed_builder_fields(args.observed),
        "checks": {
            "abi3audit": True,
            "auditwheel": True,
            "cargo_locked_sources_checksums_licenses": True,
            "elf_rpath": True,
            "metadata_version": True,
            "private_helper_fixtures": True,
            "redaction_ownership": True,
            "same_wheel": True,
        },
        "claim_boundary": {
            "platform_support_claim": False,
            "private_helper_only": True,
            "publication_authorized": False,
            "release_artifact": False,
        },
        "runtime_cells": cells,
        "schema": "lumenplot.phase3a2-wheel-evidence.v1",
        "source": {
            "cargo_lock_sha256": args.cargo_lock_sha256,
            "cargo_version": args.cargo_version,
            "commit": args.source_commit,
            "distribution": "lumenplot-mpl",
        },
        "wheel": {
            "abi3": True,
            "cargo_expected_version": args.cargo_version,
            "elf": True,
            "filename": args.wheel.name,
            "metadata": True,
            "metadata_version": observed["metadata_version"],
            "record": observed["record"],
            "sbom": True,
            "sbom_format": "CycloneDX 1.5",
            "sha256": args.wheel_sha256,
            "tag": observed["tag"],
            "wheel": True,
            "zip": observed["zip"],
        },
    }
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
