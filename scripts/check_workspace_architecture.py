#!/usr/bin/env python3
"""Check the accepted Phase-0 Cargo workspace boundary.

This checker intentionally uses only the Python standard library.  It validates
repository structure and negative public-surface guards without compiling or
importing product code.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Iterable
import tomllib


EXPECTED_PACKAGE_PATHS = {
    "lumenplot": "crates/lumenplot",
    "lumenplot-engine": "crates/lumenplot-engine",
    "lumenplot-export": "crates/lumenplot-export",
    "lumenplot-render-api": "crates/lumenplot-render-api",
    "lumenplot-render-wgpu": "crates/lumenplot-render-wgpu",
    "lumenplot-runtime": "crates/lumenplot-runtime",
    "lumenplot-viewer": "crates/lumenplot-viewer",
    "lumenplot-python": "crates/lumenplot-python",
    "lumenplot-bench": "crates/lumenplot-bench",
}
EXPECTED_WORKSPACE_MEMBERS = list(EXPECTED_PACKAGE_PATHS.values())
EXPECTED_EDGES = {
    "lumenplot": {"lumenplot-engine", "lumenplot-export"},
    "lumenplot-engine": set(),
    "lumenplot-export": {"lumenplot-engine"},
    "lumenplot-render-api": {"lumenplot-engine"},
    "lumenplot-render-wgpu": {"lumenplot-render-api"},
    "lumenplot-runtime": {"lumenplot-render-wgpu"},
    "lumenplot-viewer": {"lumenplot", "lumenplot-runtime"},
    "lumenplot-python": {"lumenplot"},
    "lumenplot-bench": {"lumenplot"},
}
INHERITED_PACKAGE_FIELDS = ("edition", "version", "license", "repository", "readme")
DEPENDENCY_TABLE_NAMES = {"dependencies", "dev-dependencies", "build-dependencies"}

PUBLIC_ITEM_RE = re.compile(
    r"^\s*pub(?:\s*\([^)]*\))?\s+"
    r"(?:use|struct|enum|trait|fn|type|const|static|mod|macro|union|extern|impl)\b",
    re.MULTILINE,
)
PUBLIC_REEXPORT_RE = re.compile(r"^\s*pub\s+use\b", re.MULTILINE)
NO_MANGLE_RE = re.compile(r"#\s*\[\s*(?:no_mangle|export_name)\b")
FORBIDDEN_CODE_PATTERNS = (
    ("unsafe code", re.compile(r"\bunsafe\b")),
    (
        "serialization or wire code",
        re.compile(r"\b(?:serde|bincode|postcard|rmp|wire|persistence|serialize|deserialize)\b"),
    ),
    (
        "concrete frontend/backend code",
        re.compile(r"\b(?:wgpu|winit|window|surface|device|python|matplotlib|numpy|pyo3)\b", re.I),
    ),
)


def _logical_path(path: Path, root: Path) -> str:
    """Return a stable repository-relative path for public diagnostics."""

    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _read_toml(path: Path, root: Path, errors: list[str]) -> dict[str, Any] | None:
    try:
        with path.open("rb") as source:
            value = tomllib.load(source)
    except FileNotFoundError:
        errors.append(f"missing manifest {_logical_path(path, root)}")
        return None
    except (OSError, tomllib.TOMLDecodeError):
        errors.append(f"invalid TOML {_logical_path(path, root)}")
        return None
    if not isinstance(value, dict):
        errors.append(f"manifest {_logical_path(path, root)} must contain a TOML table")
        return None
    return value


def _walk_tables(value: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], Any]]:
    if not isinstance(value, dict):
        return
    for key, child in value.items():
        child_path = path + (key,)
        if key in DEPENDENCY_TABLE_NAMES:
            yield child_path, child
            continue
        if isinstance(child, dict):
            yield from _walk_tables(child, child_path)


def _strip_rust_comments_and_literals(source: str) -> str:
    """Remove documentation/comments and literals before code-only scans."""

    block_comment = re.compile(r"/\*.*?\*/", re.DOTALL)
    line_comment = re.compile(r"//[^\n]*")
    string_literal = re.compile(r"(?:b)?\"(?:\\.|[^\"\\])*\"")
    char_literal = re.compile(r"'(?:\\.|[^'\\])'")
    without_comments = block_comment.sub("", source)
    without_comments = line_comment.sub("\n", without_comments)
    without_literals = string_literal.sub("\"\"", without_comments)
    return char_literal.sub("''", without_literals)


def _expected_dependency_path(package_name: str, dependency_name: str) -> str:
    dependency_path = Path(EXPECTED_PACKAGE_PATHS[dependency_name])
    return Path("..", dependency_path.name).as_posix()


def _check_package_source(package_name: str, package_dir: Path, root: Path, errors: list[str]) -> None:
    source_dir = package_dir / "src"
    rust_files = (
        sorted(path.relative_to(package_dir).as_posix() for path in source_dir.rglob("*.rs"))
        if source_dir.is_dir()
        else []
    )
    if rust_files != ["src/lib.rs"]:
        errors.append(f"package {package_name}: source must contain only src/lib.rs")
        return

    source_path = source_dir / "lib.rs"
    try:
        source = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        errors.append(f"package {package_name}: cannot read {_logical_path(source_path, root)}")
        return

    code = _strip_rust_comments_and_literals(source)
    if code.strip():
        errors.append(f"package {package_name}: source must be documentation-only")

    if package_name == "lumenplot" and PUBLIC_REEXPORT_RE.search(code):
        errors.append(f"package {package_name}: internal re-export is not allowed")
    if PUBLIC_ITEM_RE.search(code):
        errors.append(f"package {package_name}: public item is not allowed in Phase-0 stub")
    if NO_MANGLE_RE.search(code):
        errors.append(f"package {package_name}: exported ABI is not allowed")

    for label, pattern in FORBIDDEN_CODE_PATTERNS:
        if pattern.search(code):
            errors.append(f"package {package_name}: {label} is not allowed")


def _check_dependencies(
    package_name: str,
    manifest: dict[str, Any],
    errors: list[str],
) -> None:
    expected_edges = EXPECTED_EDGES[package_name]
    actual_edges: set[str] = set()
    for table_path, dependencies in _walk_tables(manifest):
        if not isinstance(dependencies, dict):
            errors.append(f"package {package_name}: dependency table is invalid")
            continue
        if table_path != ("dependencies",):
            if dependencies:
                errors.append(f"package {package_name}: only runtime path dependencies are allowed")
            continue
        for dependency_name in sorted(dependencies):
            specification = dependencies[dependency_name]
            if dependency_name not in EXPECTED_PACKAGE_PATHS:
                errors.append(
                    f"package {package_name}: external dependency {dependency_name!r} is not allowed"
                )
                continue
            if dependency_name not in expected_edges:
                errors.append(
                    f"package {package_name}: dependency edge {dependency_name!r} is not allowed"
                )
                continue
            if not isinstance(specification, dict) or set(specification) != {"path", "version"}:
                errors.append(
                    f"package {package_name}: dependency {dependency_name!r} must be a versioned path workspace edge"
                )
                continue
            expected_path = _expected_dependency_path(package_name, dependency_name)
            if (
                specification.get("path") != expected_path
                or specification.get("version") != "0.1.0"
            ):
                errors.append(
                    f"package {package_name}: dependency edge {dependency_name!r} has the wrong path or version"
                )
                continue
            actual_edges.add(dependency_name)

    if actual_edges != expected_edges:
        missing = sorted(expected_edges - actual_edges)
        extra = sorted(actual_edges - expected_edges)
        details: list[str] = []
        if missing:
            details.append(f"missing {','.join(missing)}")
        if extra:
            details.append(f"extra {','.join(extra)}")
        if details:
            errors.append(f"package {package_name}: exact dependency graph mismatch ({'; '.join(details)})")


def check_workspace(root: Path) -> list[str]:
    """Return deterministic, public-safe architecture diagnostics for *root*."""

    root = root.resolve()
    errors: list[str] = []
    root_manifest_path = root / "Cargo.toml"
    root_manifest = _read_toml(root_manifest_path, root, errors)
    if root_manifest is None:
        return sorted(set(errors))

    workspace = root_manifest.get("workspace")
    if not isinstance(workspace, dict):
        errors.append("workspace: missing [workspace] table")
        return sorted(set(errors))

    members = workspace.get("members")
    if members != EXPECTED_WORKSPACE_MEMBERS:
        if not isinstance(members, list):
            errors.append("workspace: members must be the exact Phase-0 package list")
        else:
            missing = sorted(set(EXPECTED_WORKSPACE_MEMBERS) - set(members))
            extra = sorted(set(members) - set(EXPECTED_WORKSPACE_MEMBERS))
            details: list[str] = []
            if missing:
                details.append(f"missing {','.join(missing)}")
            if extra:
                details.append(f"extra {','.join(extra)}")
            if not details and members != EXPECTED_WORKSPACE_MEMBERS:
                details.append("order differs")
            errors.append(f"workspace: members mismatch ({'; '.join(details)})")

    workspace_package = workspace.get("package")
    if not isinstance(workspace_package, dict):
        errors.append("workspace: missing [workspace.package] metadata")
    else:
        for field in INHERITED_PACKAGE_FIELDS:
            if workspace_package.get(field) is None:
                errors.append(f"workspace: missing inherited package field {field!r}")

    workspace_dependencies = workspace.get("dependencies")
    if workspace_dependencies:
        errors.append("workspace: external or shared dependencies are not allowed")

    crates_dir = root / "crates"
    actual_manifest_paths = (
        sorted(path.relative_to(root).as_posix() for path in crates_dir.glob("*/Cargo.toml"))
        if crates_dir.is_dir()
        else []
    )
    expected_manifest_paths = sorted(f"{path}/Cargo.toml" for path in EXPECTED_WORKSPACE_MEMBERS)
    for path in sorted(set(expected_manifest_paths) - set(actual_manifest_paths)):
        errors.append(f"workspace: missing package path {path}")
    for path in sorted(set(actual_manifest_paths) - set(expected_manifest_paths)):
        errors.append(f"workspace: unexpected package path {path}")

    manifests: dict[str, tuple[Path, dict[str, Any]]] = {}
    for package_name, relative_path in EXPECTED_PACKAGE_PATHS.items():
        manifest_path = root / relative_path / "Cargo.toml"
        manifest = _read_toml(manifest_path, root, errors)
        if manifest is None:
            continue
        manifests[package_name] = (manifest_path, manifest)
        package = manifest.get("package")
        if not isinstance(package, dict):
            errors.append(f"package {package_name}: missing [package] table")
            continue
        actual_name = package.get("name")
        if actual_name != package_name:
            errors.append(
                f"package at {relative_path}: expected name {package_name!r}, found {actual_name!r}"
            )
        if package.get("publish") is not False:
            errors.append(f"package {package_name}: publish must be false")
        for field in INHERITED_PACKAGE_FIELDS:
            if package.get(field) != {"workspace": True}:
                errors.append(f"package {package_name}: {field} must inherit workspace metadata")
        if "features" in manifest:
            errors.append(f"package {package_name}: features are not allowed in Phase-0 stub")

        lib = manifest.get("lib")
        if package_name == "lumenplot-python":
            if not isinstance(lib, dict) or lib.get("crate-type") != ["cdylib"]:
                errors.append("package lumenplot-python: lib crate-type must be exactly cdylib")
        elif isinstance(lib, dict) and "crate-type" in lib:
            errors.append(f"package {package_name}: only the future Python edge may set crate-type")

        _check_dependencies(package_name, manifest, errors)
        _check_package_source(package_name, manifest_path.parent, root, errors)

    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    args = parser.parse_args(argv)
    errors = check_workspace(args.root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("workspace architecture: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
