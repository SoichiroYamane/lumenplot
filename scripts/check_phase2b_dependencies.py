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
    "autocfg": {
        "version": "1.5.1",
        "checksum": "f2032f911046de80f0a198e0901378627c33f59ea0ac00e363d481118bd70a53",
        "license": "Apache-2.0 OR MIT",
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
    "heck": {
        "version": "0.5.0",
        "checksum": "2304e00983f87ffb38b55b444b5e3b60a884b5d30c0fca7d82fe33449bbe55ea",
        "license": "MIT OR Apache-2.0",
        "dependencies": set(),
    },
    "libc": {
        "version": "0.2.189",
        "checksum": "3eaf3ede3fee6db1a4c2ee091bf8a8b4dccdc6d17f656fb07896ee72867612f2",
        "license": "MIT OR Apache-2.0",
        "dependencies": set(),
    },
    "log": {
        "version": "0.4.33",
        "checksum": "0ceec5bc11778974d1bcb055b18002eba7f4b3518b6a0081b3af5f21666da9ad",
        "license": "MIT OR Apache-2.0",
        "dependencies": set(),
    },
    "matrixmultiply": {
        "version": "0.3.11",
        "checksum": "3f607c237553f086e7043417a51df26b2eb899d3caff94e6a67592ff992fedc7",
        "license": "MIT/Apache-2.0",
        "dependencies": {"autocfg", "rawpointer"},
    },
    "miniz_oxide": {
        "version": "0.8.9",
        "checksum": "1fa76a2c86f704bdb222d66965fb3d63269ce38518b83cb0575fca855ebb6316",
        "license": "MIT OR Zlib OR Apache-2.0",
        "dependencies": {"adler2", "simd-adler32"},
    },
    "ndarray": {
        "version": "0.17.2",
        "checksum": "520080814a7a6b4a6e9070823bb24b4531daac8c4627e08ba5de8c5ef2f2752d",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"matrixmultiply", "num-complex", "num-integer", "num-traits", "portable-atomic", "portable-atomic-util", "rawpointer"},
    },
    "num-complex": {
        "version": "0.4.6",
        "checksum": "73f88a1307638156682bada9d7604135552957b7818057dcef22705b4d509495",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"num-traits"},
    },
    "num-integer": {
        "version": "0.1.47",
        "checksum": "7ce2d95d4b3734dc35aa2f45e1aa22cd416814592a4f9d9205e11affd5b8e10b",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"num-traits"},
    },
    "num-traits": {
        "version": "0.2.19",
        "checksum": "071dfc062690e90b734c0b2273ce72ad0ffa95f0c74596bc250dcfd960262841",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"autocfg"},
    },
    "numpy": {
        "version": "0.29.0",
        "checksum": "6a5b15d63a5ff39e378daed0e1340d3a5964703ea9712eb09a0dc66fade996f4",
        "license": "BSD-2-Clause",
        "dependencies": {"libc", "ndarray", "num-complex", "num-integer", "num-traits", "pyo3", "pyo3-build-config", "rustc-hash"},
    },
    "once_cell": {
        "version": "1.21.4",
        "checksum": "9f7c3e4beb33f85d45ae3e3a1792185706c8e16d043238c593331cc7cd313b50",
        "license": "MIT OR Apache-2.0",
        "dependencies": set(),
    },
    "png": {
        "version": "0.18.1",
        "checksum": "60769b8b31b2a9f263dae2776c37b1b28ae246943cf719eb6946a1db05128a61",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"bitflags", "crc32fast", "fdeflate", "flate2", "miniz_oxide"},
    },
    "portable-atomic": {
        "version": "1.15.0",
        "checksum": "05c8b63e8d9609db387f0324918f81d68fe27748f084ef092fb35954d0539a85",
        "license": "Apache-2.0 OR MIT",
        "dependencies": set(),
    },
    "portable-atomic-util": {
        "version": "0.2.7",
        "checksum": "c2a106d1259c23fac8e543272398ae0e3c0b8d33c88ed73d0cc71b0f1d902618",
        "license": "Apache-2.0 OR MIT",
        "dependencies": {"portable-atomic"},
    },
    "proc-macro2": {
        "version": "1.0.107",
        "checksum": "985e7ec9bb745e6ce6535b544d84d6cd6f7ad8bd711c398938ae983b91a766d9",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"unicode-ident"},
    },
    "pyo3": {
        "version": "0.29.2",
        "checksum": "4688ddedf473e32662b9b067670129a8afb8c18e351482c70d62ba4a88171e8b",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"libc", "once_cell", "portable-atomic", "pyo3-build-config", "pyo3-ffi", "pyo3-macros"},
    },
    "pyo3-build-config": {
        "version": "0.29.2",
        "checksum": "f41027e41b4bd03f6e60f9f417fe24a6341a6bb744edd62b6f709f2a52ea30e9",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"target-lexicon"},
    },
    "pyo3-ffi": {
        "version": "0.29.2",
        "checksum": "e591a95526fead067432c3b3a33fc74770b87b1e04e73671090d9c2055a2b327",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"libc", "pyo3-build-config"},
    },
    "pyo3-macros": {
        "version": "0.29.2",
        "checksum": "73225868fc1cd84eef2c3c230ddb91273bf1de46aeb8a4248da76d32a0924a1c",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"proc-macro2", "pyo3-macros-backend", "quote", "syn"},
    },
    "pyo3-macros-backend": {
        "version": "0.29.2",
        "checksum": "571575aa3749fa6216757dd47d2a3e7ef360f329a40f0666a9fbd14889024952",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"heck", "proc-macro2", "quote", "syn"},
    },
    "quote": {
        "version": "1.0.47",
        "checksum": "1fbf4db142a473a8d80c26bbf18454ed458bf8d26c8219c331daecfdbd079001",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"proc-macro2"},
    },
    "rawpointer": {
        "version": "0.2.1",
        "checksum": "60a357793950651c4ed0f3f52338f53b2f809f32d83a07f72909fa13e4c6c1e3",
        "license": "MIT/Apache-2.0",
        "dependencies": set(),
    },
    "rustc-hash": {
        "version": "2.1.3",
        "checksum": "6b1e7f9a428571be2dc5bc0505c13fb6bf936822b894ec87abf8a08a4e51742d",
        "license": "Apache-2.0 OR MIT",
        "dependencies": set(),
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
    "syn": {
        "version": "2.0.119",
        "checksum": "872831b642d1a07999a962a351ed35b955ea2cfc8f3862091e2a240a84f17297",
        "license": "MIT OR Apache-2.0",
        "dependencies": {"proc-macro2", "quote", "unicode-ident"},
    },
    "target-lexicon": {
        "version": "0.13.5",
        "checksum": "adb6935a6f5c20170eeceb1a3835a49e12e19d792f6dd344ccc76a985ca5a6ca",
        "license": "Apache-2.0 WITH LLVM-exception",
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
    "unicode-ident": {
        "version": "1.0.24",
        "checksum": "e6e4313cd5fcd3dad5cafa179702e2b244f760991f45397d14d4ebf38247da75",
        "license": "(MIT OR Apache-2.0) AND Unicode-3.0",
        "dependencies": set(),
    },
}

EXPECTED_WORKSPACE_DEPENDENCIES = {
    "lumenplot": {"lumenplot-engine", "lumenplot-export"},
    "lumenplot-bench": {"lumenplot"},
    "lumenplot-engine": set(),
    "lumenplot-export": {"lumenplot-engine", "png", "tiny-skia"},
    "lumenplot-python": {"lumenplot", "numpy", "pyo3"},
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
    if build_scripts != {
        "crc32fast",
        "libc",
        "matrixmultiply",
        "num-traits",
        "numpy",
        "portable-atomic",
        "portable-atomic-util",
        "proc-macro2",
        "pyo3",
        "pyo3-ffi",
        "quote",
        "target-lexicon",
    }:
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
