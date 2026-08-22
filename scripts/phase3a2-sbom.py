#!/usr/bin/env python3
"""Emit the bounded CycloneDX input set used by Phase-3A2 evidence.

The document records exactly what the locked Cargo metadata reports.  A
registry-sourced package without a checksum, or any package without a
license expression, is a failure: the script never silently drops
integrity or licensing fields from the recorded inventory.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    packages = metadata.get("packages")
    if not isinstance(packages, list) or not packages:
        raise SystemExit("cargo metadata contains no package inventory")
    components = []
    for package in sorted(packages, key=lambda item: (item["name"], item["version"])):
        checksum = package.get("checksum")
        sourced = package.get("source") is not None
        if sourced and not isinstance(checksum, str):
            raise SystemExit(
                f"cargo metadata has no checksum for registry package {package['name']}"
            )
        license_id = package.get("license") or package.get("license_file")
        if not isinstance(license_id, str) or not license_id:
            raise SystemExit(f"cargo metadata has no license for package {package['name']}")
        component = {
            "bom-ref": f"pkg:cargo/{package['name']}@{package['version']}",
            "name": package["name"],
            "purl": f"pkg:cargo/{package['name']}@{package['version']}",
            "type": "library",
            "version": package["version"],
        }
        if isinstance(checksum, str):
            component["hashes"] = [{"alg": "SHA-256", "content": checksum}]
        # A single SPDX identifier is itself a valid SPDX expression, so every
        # entry uses the deterministic `expression` form.
        component["licenses"] = [{"license": {"expression": license_id}}]
        components.append(component)
    document = {
        "bomFormat": "CycloneDX",
        "components": components,
        "metadata": {"component": {"name": "lumenplot-mpl", "version": "0.1.0"}},
        "specVersion": "1.5",
        "version": 1,
    }
    print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
