#!/usr/bin/env python3
"""Emit the bounded CycloneDX input set used by Phase-3A2 evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, required=True)
    args = parser.parse_args()
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    components = []
    for package in sorted(metadata["packages"], key=lambda item: (item["name"], item["version"])):
        component = {
            "bom-ref": f"pkg:cargo/{package['name']}@{package['version']}",
            "name": package["name"],
            "purl": f"pkg:cargo/{package['name']}@{package['version']}",
            "type": "library",
            "version": package["version"],
        }
        if package.get("checksum"):
            component["hashes"] = [{"alg": "SHA-256", "content": package["checksum"]}]
        if package.get("license"):
            component["licenses"] = [{"license": {"expression": package["license"]}}]
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
