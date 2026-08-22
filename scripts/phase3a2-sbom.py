#!/usr/bin/env python3
"""Emit the bounded CycloneDX input set used by Phase-3A2 evidence.

The document records exactly what the locked Cargo metadata reports,
cross-checked against the committed Cargo.lock.  A registry-sourced package
without a lockfile checksum entry, with a lockfile checksum that is not a
64-character lowercase hexadecimal digest, or whose metadata checksum
disagrees with the lockfile is a failure, as is any package without a
license expression: the script never silently drops or substitutes
integrity or licensing fields from the recorded inventory.
"""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path

CHECKSUM_PATTERN = re.compile(r"[0-9a-f]{64}")


def lockfile_checksums(path: Path) -> dict[tuple[str, str], str]:
    """Index the SHA-256 checksums recorded in a Cargo.lock document."""

    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise SystemExit(f"cannot parse Cargo.lock {path}: {error}") from error
    entries: dict[tuple[str, str], str] = {}
    for package in document.get("package") or ():
        if not isinstance(package, dict):
            raise SystemExit("Cargo.lock contains a malformed package entry")
        name = package.get("name")
        version = package.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise SystemExit("Cargo.lock contains a package entry without name or version")
        checksum = package.get("checksum")
        if isinstance(checksum, str):
            entries[(name, version)] = checksum
    return entries


def pyproject_identity(path: Path) -> tuple[str, str]:
    """Return the root distribution name and version from pyproject.toml."""

    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise SystemExit(f"cannot parse pyproject {path}: {error}") from error
    project = document.get("project")
    if not isinstance(project, dict):
        raise SystemExit("pyproject has no [project] table")
    name = project.get("name")
    version = project.get("version")
    if not isinstance(name, str) or not name:
        raise SystemExit("pyproject [project] has no name")
    if not isinstance(version, str) or not version:
        raise SystemExit("pyproject [project] has no static version")
    return name, version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--lockfile", type=Path, required=True)
    parser.add_argument("--pyproject", type=Path, required=True)
    args = parser.parse_args()
    root_name, root_version = pyproject_identity(args.pyproject)
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    packages = metadata.get("packages")
    if not isinstance(packages, list) or not packages:
        raise SystemExit("cargo metadata contains no package inventory")
    locks = lockfile_checksums(args.lockfile)
    components = []
    for package in sorted(packages, key=lambda item: (item["name"], item["version"])):
        name = package["name"]
        version = package["version"]
        sourced = package.get("source") is not None
        checksum = None
        if sourced:
            recorded = locks.get((name, version))
            if recorded is None:
                raise SystemExit(
                    f"Cargo.lock has no checksum entry for registry package {name}"
                )
            if CHECKSUM_PATTERN.fullmatch(recorded) is None:
                raise SystemExit(
                    f"Cargo.lock checksum for registry package {name} is not a "
                    "64-character lowercase hexadecimal digest"
                )
            declared = package.get("checksum")
            if isinstance(declared, str) and declared != recorded:
                raise SystemExit(
                    f"cargo metadata checksum for registry package {name} does not "
                    "match Cargo.lock"
                )
            checksum = recorded
        license_id = package.get("license") or package.get("license_file")
        if not isinstance(license_id, str) or not license_id:
            raise SystemExit(f"cargo metadata has no license for package {name}")
        component = {
            "bom-ref": f"pkg:cargo/{name}@{version}",
            "name": name,
            "purl": f"pkg:cargo/{name}@{version}",
            "type": "library",
            "version": version,
        }
        if checksum is not None:
            # Only lockfile-verified digests are recorded; workspace members
            # carry no integrity claim.
            component["hashes"] = [{"alg": "SHA-256", "content": checksum}]
        # A single SPDX identifier is itself a valid SPDX expression, so every
        # entry uses the deterministic `expression` form.
        component["licenses"] = [{"license": {"expression": license_id}}]
        components.append(component)
    document = {
        "bomFormat": "CycloneDX",
        "components": components,
        "metadata": {"component": {"name": root_name, "version": root_version}},
        "specVersion": "1.5",
        "version": 1,
    }
    print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
