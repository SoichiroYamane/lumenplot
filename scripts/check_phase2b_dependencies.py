#!/usr/bin/env python3
"""Check the exact Phase-2B resolved dependency graph and evidence boundary."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

REGISTRY_SOURCE = "registry+https://github.com/rust-lang/crates.io-index"

EXPECTED_REGISTRY: dict[str, dict[str, Any]] = {
    "adler2": {
        "version": "2.0.1",
        "checksum": "320119579fcad9c21884f5c4861d16174d0e06250625266f50fe6898340abefa",
        "license": "0BSD OR MIT OR Apache-2.0",
        "dependencies": set(),
    },
    "arrayref": {
        "version": "0.3.9",
        "checksum": "76a2e8124351fda1ef8aaaa3bbd7ebbcb486bbcd4225aca0aa0d84bb2db8fecb",
        "license": "BSD-2-Clause",
        "dependencies": set(),
    },
    "arrayvec": {
        "version": "0.7.8",
        "checksum": "d3fb67a6e08acf24fdeccbac2cb6ac4305825bd1f117462e0e6f2f193345ad56",
        "license": "MIT OR Apache-2.0",
        "dependencies": set(),
    },
    "bitflags": {
        "version": "2.13.1",
        "checksum": "b588b76d00fde79687d7646a9b5bdf3cc0f655e0bbd080335a95d7e96f3587da",
        "license": "MIT OR Apache-2.0",
        "dependencies": set(),
    },
    "bytemuck": {
        "version": "1.25.2",
        "checksum": "95832e849adfb21180ccb6826a99da14e5d266ae5c2e668e1602cf234f153797",
        "license": "Zlib OR Apache-2.0 OR MIT",
        "dependencies": set(),
    },
    "cfg-if": {
        "version": "1.0.4",
        "checksum": "9330f8b2ff13f34540b44e946ef35111825727b38d33286ef986142615121801",
        "license": "MIT OR Apache-2.0",
        "dependencies": set(),
    },
    "crc32fast": {
        "version": "1.5.0",
        "checksum": "9481c1c90cbf2ac953f07c8d4a58aa3945c425b7185c9154d67a65e4230da511",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"cfg-if"},
    },
    "fdeflate": {
        "version": "0.3.7",
        "checksum": "1e6853b52649d4ac5c0bd02320cddc5ba956bdb407c4b75a2c6b75bf51500f8c",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"simd-adler32"},
    },
    "flate2": {
        "version": "1.1.9",
        "checksum": "843fba2746e448b37e26a819579957415c8cef339bf08564fe8b7ddbd959573c",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"crc32fast", "miniz_oxide"},
    },
    "log": {
        "version": "0.4.33",
        "checksum": "0ceec5bc11778974d1bcb055b18002eba7f4b3518b6a0081b3af5f21666da9ad",
        "license": "MIT OR Apache-2.0",
        "dependencies": set(),
    },
    "miniz_oxide": {
        "version": "0.8.9",
        "checksum": "1fa76a2c86f704bdb222d66965fb3d63269ce38518b83cb0575fca855ebb6316",
        "license": "MIT OR Zlib OR Apache-2.0",
        "dependencies": {"adler2", "simd-adler32"},
    },
    "png": {
        "version": "0.18.1",
        "checksum": "60769b8b31b2a9f263dae2776c37b1b28ae246943cf719eb6946a1db05128a61",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"bitflags", "crc32fast", "fdeflate", "flate2", "miniz_oxide"},
    },
    "simd-adler32": {
        "version": "0.3.10",
        "checksum": "3a219298ac11a56ea9a6d2120044824d6f01aeb034955e7af7bc16858527deea",
        "license": "MIT",
        "dependencies": set(),
    },
    "strict-num": {
        "version": "0.1.1",
        "checksum": "6637bab7722d379c8b41ba849228d680cc12d0a45ba1fa2b48f2a30577a06731",
        "license": "MIT",
        "dependencies": set(),
    },
    "tiny-skia": {
        "version": "0.12.0",
        "checksum": "47ffee5eaaf5527f630fb0e356b90ebdec84d5d18d937c5e440350f88c5a91ea",
        "license": "BSD-3-Clause",
        "dependencies": {"arrayref", "arrayvec", "bytemuck", "cfg-if", "log", "tiny-skia-path"},
    },
    "tiny-skia-path": {
        "version": "0.12.0",
        "checksum": "edca365c3faccca67d06593c5980fa6c57687de727a03131735bb85f01fdeeb9",
        "license": "BSD-3-Clause",
        "dependencies": {"arrayref", "bytemuck", "strict-num"},
    },
}

EXPECTED_WORKSPACE_DEPENDENCIES = {
    "lumenplot": {"lumenplot-engine", "lumenplot-export"},
    "lumenplot-bench": {"lumenplot"},
    "lumenplot-engine": set(),
    "lumenplot-export": {"lumenplot-engine", "png", "tiny-skia"},
    "lumenplot-python": {"lumenplot"},
    "lumenplot-render-api": {"lumenplot-engine"},
    "lumenplot-render-wgpu": {"lumenplot-render-api"},
    "lumenplot-runtime": {"lumenplot-render-wgpu"},
    "lumenplot-viewer": {"lumenplot", "lumenplot-runtime"},
}


def check_lock(root: Path, errors: list[str]) -> None:
    lock_path = root / "Cargo.lock"
    try:
        with lock_path.open("rb") as source:
            lock = tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError):
        errors.append("Cargo.lock is missing or invalid")
        return
    if lock.get("version") != 4:
        errors.append("Cargo.lock format must be version 4")
    packages = lock.get("package")
    if not isinstance(packages, list):
        errors.append("Cargo.lock package table is missing")
        return

    actual: dict[str, dict[str, Any]] = {}
    for package in packages:
        if not isinstance(package, dict) or not isinstance(package.get("name"), str):
            errors.append("Cargo.lock contains an invalid package entry")
            continue
        name = package["name"]
        version = package.get("version")
        key = f"{name}@{version}"
        if key in actual:
            errors.append(f"Cargo.lock contains a duplicate package {key!r}")
        actual[key] = package

    expected_keys = {f"{name}@{data['version']}" for name, data in EXPECTED_REGISTRY.items()}
    expected_keys.update(f"{name}@0.1.0" for name in EXPECTED_WORKSPACE_DEPENDENCIES)
    if set(actual) != expected_keys:
        missing = sorted(expected_keys - set(actual))
        extra = sorted(set(actual) - expected_keys)
        if missing:
            errors.append("Cargo.lock missing packages: " + ",".join(missing))
        if extra:
            errors.append("Cargo.lock has unexpected packages: " + ",".join(extra))

    for name, expected in EXPECTED_REGISTRY.items():
        package = actual.get(f"{name}@{expected['version']}")
        if package is None:
            continue
        if package.get("source") != REGISTRY_SOURCE:
            errors.append(f"Cargo.lock source drift for {name}")
        if package.get("checksum") != expected["checksum"]:
            errors.append(f"Cargo.lock checksum drift for {name}")
        dependencies = {
            dependency
            for dependency in package.get("dependencies", [])
            if isinstance(dependency, str)
        }
        if dependencies != expected["dependencies"]:
            errors.append(f"Cargo.lock dependency graph drift for {name}")

    for name, expected in EXPECTED_WORKSPACE_DEPENDENCIES.items():
        package = actual.get(f"{name}@0.1.0")
        if package is None:
            continue
        if "source" in package or "checksum" in package:
            errors.append(f"workspace package {name} must not have registry provenance")
        dependencies = {
            dependency
            for dependency in package.get("dependencies", [])
            if isinstance(dependency, str)
        }
        if dependencies != expected:
            errors.append(f"Cargo.lock dependency graph drift for workspace package {name}")


def run_metadata(root: Path, errors: list[str]) -> dict[str, Any] | None:
    result = subprocess.run(
        ["cargo", "metadata", "--locked", "--all-features", "--format-version", "1"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        errors.append("cargo metadata --locked failed")
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        errors.append("cargo metadata returned invalid JSON")
        return None


def check_metadata(metadata: dict[str, Any], errors: list[str]) -> None:
    packages = metadata.get("packages")
    if not isinstance(packages, list):
        errors.append("cargo metadata package list is missing")
        return
    registry_packages = {
        package["name"]: package
        for package in packages
        if isinstance(package, dict)
        and isinstance(package.get("source"), str)
        and package["source"] == REGISTRY_SOURCE
    }
    if set(registry_packages) != set(EXPECTED_REGISTRY):
        missing = sorted(set(EXPECTED_REGISTRY) - set(registry_packages))
        extra = sorted(set(registry_packages) - set(EXPECTED_REGISTRY))
        if missing:
            errors.append("metadata missing registry packages: " + ",".join(missing))
        if extra:
            errors.append("metadata has unexpected registry packages: " + ",".join(extra))
    for name, expected in EXPECTED_REGISTRY.items():
        package = registry_packages.get(name)
        if package is None:
            continue
        if package.get("version") != expected["version"]:
            errors.append(f"metadata version drift for {name}")
        if package.get("license") != expected["license"]:
            errors.append(f"metadata license drift for {name}")
        if package.get("source") != REGISTRY_SOURCE:
            errors.append(f"metadata source drift for {name}")

    package_names_by_id = {
        package["id"]: package["name"]
        for package in packages
        if isinstance(package, dict)
        and isinstance(package.get("id"), str)
        and isinstance(package.get("name"), str)
    }
    nodes = metadata.get("resolve", {}).get("nodes", [])
    nodes_by_name = {
        package_names_by_id.get(node["id"], node["id"]): node
        for node in nodes
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    for name, expected_dependencies in EXPECTED_REGISTRY.items():
        node = nodes_by_name.get(name)
        if node is None:
            errors.append(f"metadata resolution is missing {name}")
            continue
        dependencies = {
            package_names_by_id.get(dependency, dependency)
            for dependency in node.get("dependencies", [])
            if isinstance(dependency, str)
        }
        if dependencies != EXPECTED_REGISTRY[name]["dependencies"]:
            errors.append(f"metadata dependency graph drift for {name}")
    for name, expected_dependencies in EXPECTED_WORKSPACE_DEPENDENCIES.items():
        node = nodes_by_name.get(name)
        if node is None:
            errors.append(f"metadata resolution is missing workspace package {name}")
            continue
        dependencies = {
            package_names_by_id.get(dependency, dependency)
            for dependency in node.get("dependencies", [])
            if isinstance(dependency, str)
        }
        if dependencies != expected_dependencies:
            errors.append(f"metadata dependency graph drift for workspace package {name}")

    direct_features = {"png": [], "tiny-skia": ["std"]}
    for name, expected_features in direct_features.items():
        node = nodes_by_name.get(name)
        if node is None:
            continue
        actual_features = sorted(node.get("features", []))
        if actual_features != sorted(expected_features):
            errors.append(f"metadata feature drift for {name}")

    build_scripts = set()
    for package in packages:
        if not isinstance(package, dict) or package.get("source") != REGISTRY_SOURCE:
            continue
        for target in package.get("targets", []):
            if isinstance(target, dict) and "custom-build" in target.get("kind", []):
                build_scripts.add(package.get("name"))
                if Path(str(target.get("src_path", ""))).name != "build.rs":
                    errors.append(f"build script target drift for {package.get('name')}")
    if build_scripts != {"crc32fast"}:
        errors.append("dependency build-script inventory drift")


def dependency_unsafe_evidence(metadata: dict[str, Any]) -> tuple[list[str], list[str]]:
    unsafe_packages: list[str] = []
    for package in metadata.get("packages", []):
        if not isinstance(package, dict) or package.get("source") != REGISTRY_SOURCE:
            continue
        manifest_path = package.get("manifest_path")
        if not isinstance(manifest_path, str):
            continue
        package_root = Path(manifest_path).parent
        count = 0
        for source_path in package_root.rglob("*.rs"):
            try:
                count += len(re.findall(r"\bunsafe\b", source_path.read_text(encoding="utf-8")))
            except (OSError, UnicodeError):
                continue
        if count:
            unsafe_packages.append(f"{package['name']}:{count}")
    build_scripts = [
        package["name"]
        for package in metadata.get("packages", [])
        if isinstance(package, dict)
        and package.get("source") == REGISTRY_SOURCE
        and any(
            isinstance(target, dict) and "custom-build" in target.get("kind", [])
            for target in package.get("targets", [])
        )
    ]
    return sorted(unsafe_packages), sorted(build_scripts)


def check(root: Path) -> tuple[list[str], list[str], list[str]]:
    errors: list[str] = []
    check_lock(root, errors)
    metadata = run_metadata(root, errors)
    if metadata is None:
        return errors, [], []
    check_metadata(metadata, errors)
    unsafe_packages, build_scripts = dependency_unsafe_evidence(metadata)
    return errors, unsafe_packages, build_scripts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    args = parser.parse_args(argv)
    errors, unsafe_packages, build_scripts = check(args.root.resolve())
    if errors:
        for error in sorted(set(errors)):
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("phase2b dependency graph: OK")
    print("dependency unsafe evidence: " + (", ".join(unsafe_packages) if unsafe_packages else "none"))
    print("dependency build-script evidence: " + (", ".join(build_scripts) if build_scripts else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
