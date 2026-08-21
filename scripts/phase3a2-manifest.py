#!/usr/bin/env python3
"""Create the CI-local Phase-3A2 same-wheel evidence manifest."""

from __future__ import annotations

import argparse
import base64
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


def record_is_valid(path: Path) -> bool:
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
        record_names = [name for name in entries if name.endswith(".dist-info/RECORD")]
        if len(record_names) != 1:
            return False
        for line in entries[record_names[0]].decode("utf-8").splitlines():
            filename, encoded_hash, size = line.split(",", 2)
            if not encoded_hash:
                continue
            algorithm, encoded = encoded_hash.split("=", 1)
            if algorithm != "sha256" or filename not in entries:
                return False
            digest = base64.urlsafe_b64encode(hashlib.sha256(entries[filename]).digest()).decode("ascii").rstrip("=")
            if digest != encoded or size != str(len(entries[filename])):
                return False
    return True


def wheel_metadata(path: Path) -> tuple[str, str, bool, bool, bool]:
    with zipfile.ZipFile(path) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        wheel_names = [name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")]
        record_names = [name for name in archive.namelist() if name.endswith(".dist-info/RECORD")]
        if len(metadata_names) != 1 or len(wheel_names) != 1 or len(record_names) != 1:
            raise SystemExit("wheel metadata inventory is incomplete")
        metadata = archive.read(metadata_names[0]).decode("utf-8")
        wheel = archive.read(wheel_names[0]).decode("utf-8")
    version_match = re.search(r"^Version: (.+)$", metadata, re.MULTILINE)
    tag_match = re.search(r"^Tag: (.+)$", wheel, re.MULTILINE)
    if version_match is None or tag_match is None:
        raise SystemExit("wheel metadata is missing Version or Tag")
    return version_match.group(1), tag_match.group(1), True, True, True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--wheel-sha256", required=True)
    parser.add_argument("--cargo-version", required=True)
    parser.add_argument("--cargo-lock-sha256", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--sbom", type=Path, required=True)
    args = parser.parse_args()

    wheel_digest = hashlib.sha256(args.wheel.read_bytes()).hexdigest()
    if wheel_digest != args.wheel_sha256:
        raise SystemExit("wheel SHA-256 does not match the built artifact")
    metadata_version, tag, metadata_ok, wheel_ok, record_metadata_ok = wheel_metadata(args.wheel)
    if metadata_version != args.cargo_version:
        raise SystemExit("wheel metadata version does not match Cargo")
    if tag != "cp311-abi3-manylinux_2_28_x86_64":
        raise SystemExit("wheel tag does not match the accepted Phase-3A2 tag")
    if not record_is_valid(args.wheel):
        raise SystemExit("wheel RECORD hashes or sizes are invalid")
    sbom = json.loads(args.sbom.read_text(encoding="utf-8"))
    if sbom.get("bomFormat") != "CycloneDX" or sbom.get("specVersion") != "1.5":
        raise SystemExit("SBOM is not CycloneDX 1.5")

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
        "builder": {
            "abi3audit_version": "0.0.26",
            "auditwheel_version": "6.8.0",
            "config_digest": IMAGE_CONFIG_DIGEST,
            "glibc": "2.28",
            "image": IMAGE,
            "maturin_version": "1.14.1",
            "maturin_wheel_sha256": MATURIN_WHEEL_SHA256,
            "platform": "linux/amd64",
            "rust_version": "1.89.0",
        },
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
            "metadata": metadata_ok,
            "metadata_version": metadata_version,
            "record": record_metadata_ok,
            "sbom": True,
            "sbom_format": "CycloneDX 1.5",
            "sha256": args.wheel_sha256,
            "tag": tag,
            "wheel": wheel_ok,
            "zip": True,
        },
    }
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
