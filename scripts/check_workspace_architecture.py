#!/usr/bin/env python3
"""Check the accepted Rust workspace and conditional Phase-3A facade boundary.

This checker intentionally uses only the Python standard library.  It validates
repository structure and negative public-surface guards without compiling or
importing product code.  The hidden Phase-3A facade is absent before
implementation and, when present, must match its exact owned inventory.
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
EXPECTED_ENGINE_SOURCE_FILES = {
    "src/lib.rs",
    "src/error.rs",
    "src/bridge.rs",
    "src/frame.rs",
    "src/data/mod.rs",
    "src/data/sample.rs",
    "src/data/topology.rs",
    "src/data/chunk.rs",
    "src/lod/mod.rs",
    "src/lod/summary.rs",
    "src/lod/m4.rs",
    "src/lod/arbitrary.rs",
    "src/scene/mod.rs",
    "src/scene/ids.rs",
    "src/scene/revision.rs",
    "src/scene/state.rs",
    "src/scene/transaction.rs",
    "src/scene/snapshot.rs",
}
EXPECTED_EXPORT_SOURCE_FILES = {
    "src/lib.rs",
    "src/error.rs",
    "src/raster.rs",
    "src/compositor.rs",
    "src/png.rs",
}
EXPORT_TYPES = {"ExportErrorKind", "ExportError", "PngSpec"}
EXPORT_ENUM_VARIANTS = {
    "ExportErrorKind": {
        "InvalidInput",
        "UnsupportedCapability",
        "CapacityExceeded",
        "AllocationFailed",
        "EncodingFailed",
        "Internal",
    },
}
EXPORT_METHODS = {
    "ExportError": {"kind", "message"},
    "PngSpec": {"new"},
}
EXPORT_DERIVES = {
    "ExportErrorKind": {"Clone", "Copy", "Debug", "Eq", "Hash", "PartialEq"},
    "ExportError": {"Clone", "Eq", "PartialEq"},
    "PngSpec": set(),
}
EXPORT_BRIDGE_EXPORTS = {
    "ExportError",
    "ExportErrorKind",
    "PngSpec",
    "encode_line_frame_png",
}
EXPORT_SIGNATURES = {
    ("ExportError", "kind"): "pub fn kind(&self) -> ExportErrorKind",
    ("ExportError", "message"): "pub fn message(&self) -> &str",
    ("PngSpec", "new"): "pub fn new(output_dpi: f64) -> Result<Self, ExportError>",
    ("__free__", "encode_line_frame_png"): "pub fn encode_line_frame_png(frame: &lumenplot_engine::bridge::LineFrame, spec: &PngSpec) -> Result<Vec<u8>, ExportError>",
}
EXPECTED_FACADE_SOURCE_FILES = {
    "src/lib.rs",
    "src/error.rs",
    "src/view.rs",
    "src/series.rs",
    "src/scene.rs",
}
FACADE_TYPES = {
    "PlotScene",
    "SceneTransaction",
    "SceneSnapshot",
    "SceneRevision",
    "SeriesId",
    "CommitReceipt",
    "AxisRange",
    "AxisScale",
    "Viewport",
    "AxisScales",
    "SeriesTopology",
    "SeriesData",
    "PublicError",
    "ErrorCode",
    "ErrorCategory",
}
FACADE_ROOT_EXPORTS = FACADE_TYPES
FACADE_NON_EXHAUSTIVE = {"ErrorCode", "ErrorCategory", "AxisScale", "SeriesTopology"}
FACADE_ENUM_VARIANTS = {
    "ErrorCode": {
        "InvalidInput",
        "UnsupportedCapability",
        "Closed",
        "InvalidState",
        "HostLoopMisuse",
        "Reentrancy",
        "BackendUnavailable",
        "DeviceLost",
        "RecoveryFailed",
        "OutOfMemory",
        "ResourceInvalid",
        "Internal",
    },
    "ErrorCategory": {
        "Input",
        "Capability",
        "Lifecycle",
        "Host",
        "Backend",
        "Resource",
        "Internal",
    },
    "AxisScale": {"Linear", "Log10"},
    "SeriesTopology": {"MonotonicX", "ArbitraryXY"},
}
FACADE_METHODS = {
    "ErrorCode": {"as_str"},
    "ErrorCategory": {"as_str"},
    "PublicError": {"code", "category", "message"},
    "AxisRange": {"new", "min", "max"},
    "Viewport": {"new", "from_bounds", "x", "y"},
    "AxisScales": {"new", "x", "y", "validate"},
    "SeriesData": {
        "from_owned_xy",
        "from_owned_xy_segments",
        "topology",
        "source_len",
        "point_count",
        "is_empty",
    },
    "PlotScene": {"new", "transaction", "snapshot", "revision"},
    "SceneTransaction": {
        "replace_canonical_view",
        "set_viewport",
        "set_axis_scales",
        "add_series",
        "append_series",
        "commit",
        "abort",
    },
    "SceneSnapshot": {"revision", "canonical_view", "viewport", "axis_scales"},
    "CommitReceipt": {"revision", "changed"},
}
FACADE_DERIVES = {
    "SceneRevision": {"Copy", "Clone", "Debug", "Eq", "PartialEq", "Hash"},
    "SeriesId": {"Copy", "Clone", "Debug", "Eq", "PartialEq", "Hash"},
    "SceneSnapshot": {"Clone"},
}
FACADE_TRAIT_IMPLS = {
    ("PublicError", "Debug"),
    ("PublicError", "Display"),
    ("PublicError", "Error"),
}
HIDDEN_FACADE_SOURCE_FILE = "src/__private.rs"
HIDDEN_FACADE_TYPES = {
    "LinePngGeometry",
    "LinePngStyle",
    "OwnedLinePngRequest",
    "BridgeError",
}
HIDDEN_FACADE_METHODS = {
    "LinePngGeometry": {"new"},
    "LinePngStyle": {"new"},
    "OwnedLinePngRequest": {"new"},
    "BridgeError": {"code", "category", "message"},
}
HIDDEN_FACADE_SIGNATURES = {
    ("LinePngGeometry", "new"): (
        "pub fn new(viewport: [f64; 4], canvas: [f64; 2], "
        "plot_rect: [f64; 4], logical_units_per_inch: f64) "
        "-> Result<Self, BridgeError>"
    ),
    ("LinePngStyle", "new"): (
        "pub fn new(line_rgba: [u8; 4], line_width: f64, "
        "background_rgba: [u8; 4]) -> Result<Self, BridgeError>"
    ),
    ("OwnedLinePngRequest", "new"): (
        "pub fn new(x: Vec<f64>, y: Vec<f64>, "
        "valid_segments: Vec<Range<usize>>, geometry: LinePngGeometry, "
        "style: LinePngStyle, output_dpi: f64) -> Result<Self, BridgeError>"
    ),
    ("BridgeError", "code"): "pub fn code(&self) -> ErrorCode",
    ("BridgeError", "category"): "pub fn category(&self) -> ErrorCategory",
    ("BridgeError", "message"): "pub fn message(&self) -> &str",
}
HIDDEN_FACADE_TRAIT_IMPLS = {
    ("BridgeError", "Debug"),
    ("BridgeError", "Display"),
    ("BridgeError", "Error"),
}
HIDDEN_FACADE_FREE_SIGNATURE = (
    "pub fn render_line_png(request: OwnedLinePngRequest) "
    "-> Result<Vec<u8>, BridgeError>"
)
FACADE_RAW_TOKENS = (
    "lumenplot_engine",
    "bridge",
    "Engine",
    "SceneError",
    "SceneErrorKind",
    "SeriesInput",
    "Topology",
    "Chunk",
    "Segment",
    "Lod",
    "LOD",
    "Index",
    "Selection",
    "DataEpoch",
    "ChunkRevision",
    "ComponentRevision",
    "SceneState",
    "RenderPacket",
    "lumenplot_runtime",
    "lumenplot_render",
    "lumenplot_python",
)
HIDDEN_FACADE_RAW_TOKENS = FACADE_RAW_TOKENS + (
    "PlotScene",
    "SceneTransaction",
    "SceneSnapshot",
    "ExportError",
    "ExportErrorKind",
    "PngSpec",
    "tiny_skia",
    "png",
    "*const",
    "*mut",
    "dyn",
    "extern",
    "serde",
    "pyo3",
    "numpy",
    "python",
    "matplotlib",
)
BRIDGE_TYPES = {
    "SceneErrorKind",
    "SceneError",
    "AxisRange",
    "AxisScale",
    "Viewport",
    "AxisScales",
    "SeriesTopology",
    "SeriesData",
    "PlotScene",
    "SceneTransaction",
    "SceneSnapshot",
    "SceneRevision",
    "SeriesId",
    "CommitReceipt",
    "LogicalSize",
    "LogicalRect",
    "SrgbRgba8",
    "LineStyle",
    "LineFrameSpec",
    "LineFrame",
    "LineSeries",
    "LineSegment",
    "LinePoint",
}
BRIDGE_METHODS = {
    "kind",
    "message",
    "new",
    "min",
    "max",
    "from_bounds",
    "x",
    "y",
    "validate",
    "from_owned_xy",
    "from_owned_xy_segments",
    "topology",
    "source_len",
    "point_count",
    "is_empty",
    "transaction",
    "snapshot",
    "revision",
    "replace_canonical_view",
    "set_viewport",
    "set_axis_scales",
    "add_series",
    "append_series",
    "commit",
    "abort",
    "canonical_view",
    "viewport",
    "axis_scales",
    "changed",
    "width",
    "height",
    "x_min",
    "y_min",
    "x_max",
    "y_max",
    "r",
    "g",
    "b",
    "a",
    "color",
    "resolve_line_frame",
    "canvas",
    "plot_rect",
    "logical_units_per_inch",
    "background",
    "series",
    "id",
    "style",
    "segments",
    "points",
}
BRIDGE_METHODS_BY_TYPE = {
    "SceneErrorKind": set(),
    "SceneError": {"kind", "message"},
    "AxisRange": {"new", "min", "max"},
    "AxisScale": set(),
    "Viewport": {"new", "from_bounds", "x", "y"},
    "AxisScales": {"new", "x", "y", "validate"},
    "SeriesTopology": set(),
    "SeriesData": {
        "from_owned_xy",
        "from_owned_xy_segments",
        "topology",
        "source_len",
        "point_count",
        "is_empty",
    },
    "PlotScene": {"new", "transaction", "snapshot", "revision"},
    "SceneTransaction": {
        "replace_canonical_view",
        "set_viewport",
        "set_axis_scales",
        "add_series",
        "append_series",
        "commit",
        "abort",
    },
    "SceneSnapshot": {
        "revision",
        "canonical_view",
        "viewport",
        "axis_scales",
        "resolve_line_frame",
    },
    "SceneRevision": set(),
    "SeriesId": set(),
    "CommitReceipt": {"revision", "changed"},
    "LogicalSize": {"new", "width", "height"},
    "LogicalRect": {"new", "x_min", "y_min", "x_max", "y_max"},
    "SrgbRgba8": {"new", "r", "g", "b", "a"},
    "LineStyle": {"new", "color", "width"},
    "LineFrameSpec": {"new"},
    "LineFrame": {
        "revision",
        "canvas",
        "plot_rect",
        "logical_units_per_inch",
        "background",
        "series",
    },
    "LineSeries": {"id", "style", "segments"},
    "LineSegment": {"points"},
    "LinePoint": {"x", "y"},
}
BRIDGE_PHASE2_SIGNATURES = {
    "LogicalSize": {
        "new": "pub fn new(width: f64, height: f64) -> Result<Self, SceneError>",
        "width": "pub fn width(&self) -> f64",
        "height": "pub fn height(&self) -> f64",
    },
    "LogicalRect": {
        "new": "pub fn new(x_min: f64, y_min: f64, x_max: f64, y_max: f64) -> Result<Self, SceneError>",
        "x_min": "pub fn x_min(&self) -> f64",
        "y_min": "pub fn y_min(&self) -> f64",
        "x_max": "pub fn x_max(&self) -> f64",
        "y_max": "pub fn y_max(&self) -> f64",
    },
    "SrgbRgba8": {
        "new": "pub fn new(r: u8, g: u8, b: u8, a: u8) -> Self",
        "r": "pub fn r(&self) -> u8",
        "g": "pub fn g(&self) -> u8",
        "b": "pub fn b(&self) -> u8",
        "a": "pub fn a(&self) -> u8",
    },
    "LineStyle": {
        "new": "pub fn new(color: SrgbRgba8, width: f64) -> Result<Self, SceneError>",
        "color": "pub fn color(&self) -> SrgbRgba8",
        "width": "pub fn width(&self) -> f64",
    },
    "LineFrameSpec": {
        "new": "pub fn new(canvas: LogicalSize, plot_rect: LogicalRect, logical_units_per_inch: f64, line_style: LineStyle, background: SrgbRgba8) -> Result<Self, SceneError>",
    },
    "LineFrame": {
        "revision": "pub fn revision(&self) -> SceneRevision",
        "canvas": "pub fn canvas(&self) -> LogicalSize",
        "plot_rect": "pub fn plot_rect(&self) -> LogicalRect",
        "logical_units_per_inch": "pub fn logical_units_per_inch(&self) -> f64",
        "background": "pub fn background(&self) -> SrgbRgba8",
        "series": "pub fn series(&self) -> &[LineSeries]",
    },
    "LineSeries": {
        "id": "pub fn id(&self) -> SeriesId",
        "style": "pub fn style(&self) -> LineStyle",
        "segments": "pub fn segments(&self) -> &[LineSegment]",
    },
    "LineSegment": {
        "points": "pub fn points(&self) -> &[LinePoint]",
    },
    "LinePoint": {
        "x": "pub fn x(&self) -> f64",
        "y": "pub fn y(&self) -> f64",
    },
    "SceneSnapshot": {
        "resolve_line_frame": "pub fn resolve_line_frame(&self, spec: &LineFrameSpec) -> Result<LineFrame, SceneError>",
    },
}
BRIDGE_DERIVES = {
    "SceneErrorKind": {"Clone", "Copy", "Debug", "Eq", "Hash", "Ord", "PartialEq", "PartialOrd"},
    "SceneError": {"Clone", "Debug", "Eq", "PartialEq"},
    "AxisRange": {"Clone", "Copy", "Debug", "PartialEq"},
    "AxisScale": {"Clone", "Copy", "Debug", "Eq", "Hash", "PartialEq"},
    "Viewport": {"Clone", "Copy", "Debug", "PartialEq"},
    "AxisScales": {"Clone", "Copy", "Debug", "Eq", "Hash", "PartialEq"},
    "SeriesTopology": {"Clone", "Copy", "Debug", "Eq", "Hash", "PartialEq"},
    "SeriesData": set(),
    "PlotScene": set(),
    "SceneTransaction": set(),
    "SceneSnapshot": {"Clone"},
    "SceneRevision": {"Clone", "Copy", "Debug", "Eq", "Hash", "Ord", "PartialEq", "PartialOrd"},
    "SeriesId": {"Clone", "Copy", "Debug", "Eq", "Hash", "Ord", "PartialEq", "PartialOrd"},
    "CommitReceipt": {"Clone", "Copy", "Debug", "Eq", "PartialEq"},
    "LogicalSize": {"Clone", "Copy", "PartialEq"},
    "LogicalRect": {"Clone", "Copy", "PartialEq"},
    "SrgbRgba8": {"Clone", "Copy", "Eq", "PartialEq"},
    "LineStyle": {"Clone", "Copy", "PartialEq"},
    "LineFrameSpec": set(),
    "LineFrame": set(),
    "LineSeries": set(),
    "LineSegment": set(),
    "LinePoint": {"Clone", "Copy", "PartialEq"},
}
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
EXPECTED_EXPORT_EXTERNAL_DEPENDENCIES = {
    "tiny-skia": {
        "version": "=0.12.0",
        "default-features": False,
        "features": ["std"],
    },
    "png": {
        "version": "=0.18.1",
        "default-features": False,
    },
}
INHERITED_PACKAGE_FIELDS = ("edition", "version", "license", "repository", "readme")
DEPENDENCY_TABLE_NAMES = {"dependencies", "dev-dependencies", "build-dependencies"}

PUBLIC_ITEM_RE = re.compile(
    r"^\s*pub(?:\s*\([^)]*\))?\s+"
    r"(?:use|struct|enum|trait|fn|type|const|static|mod|macro|union|extern|impl)\b",
    re.MULTILINE,
)
PUBLIC_REEXPORT_RE = re.compile(r"^\s*pub\s+use\b", re.MULTILINE)
PUBLIC_BARE_ITEM_RE = re.compile(
    r"^\s*pub\s+(?:use|struct|enum|trait|fn|type|const|static|mod|macro|union|extern|impl)\b",
    re.MULTILINE,
)
PUBLIC_SCOPED_RE = re.compile(
    r"^\s*pub\s*\((?:crate|super|self|in\s+[^)]*)\)\s+",
    re.MULTILINE,
)
PUBLIC_TYPE_RE = re.compile(r"^\s*pub\s+(?:struct|enum)\s+(\w+)\b", re.MULTILINE)
PUBLIC_FN_RE = re.compile(r"^\s*pub\s+fn\s+(\w+)\b", re.MULTILINE)
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
FACADE_FORBIDDEN_CODE_PATTERNS = (
    ("unsafe code", re.compile(r"\bunsafe\b")),
    (
        "serialization or wire code",
        re.compile(r"\b(?:serde|bincode|postcard|rmp|wire|persistence|serialize|deserialize)\b"),
    ),
    (
        "concrete frontend/backend code",
        re.compile(r"\b(?:wgpu|winit|window|surface|python|matplotlib|numpy|pyo3|runtime)\b", re.I),
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


def _check_forbidden_code(package_name: str, code: str, errors: list[str]) -> None:
    for label, pattern in FORBIDDEN_CODE_PATTERNS:
        if pattern.search(code):
            errors.append(f"package {package_name}: {label} is not allowed")


def _check_stub_source(package_name: str, source_dir: Path, root: Path, errors: list[str]) -> None:
    rust_files = (
        sorted(path.relative_to(source_dir.parent).as_posix() for path in source_dir.rglob("*.rs"))
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
    _check_forbidden_code(package_name, code, errors)


def _find_matching_brace(code: str, opening: int) -> int:
    depth = 0
    for position in range(opening, len(code)):
        if code[position] == "{":
            depth += 1
        elif code[position] == "}":
            depth -= 1
            if depth == 0:
                return position
    return len(code)


def _facade_type_declarations(code: str) -> list[tuple[re.Match[str], str, str]]:
    declaration = re.compile(
        r"(?P<attributes>(?:^\s*#\[[^\n]*\]\s*\n)*)"
        r"^\s*pub\s+(?P<kind>struct|enum)\s+(?P<name>\w+)\b",
        re.MULTILINE,
    )
    declarations: list[tuple[re.Match[str], str, str]] = []
    for match in declaration.finditer(code):
        opening = code.find("{", match.end())
        body = "" if opening < 0 else code[opening + 1 : _find_matching_brace(code, opening)]
        declarations.append((match, match.group("kind"), body))
    return declarations


def _facade_derive_traits(attributes: str) -> set[str]:
    traits: set[str] = set()
    for derive in re.findall(r"#\[\s*derive\s*\(([^)]*)\)\s*\]", attributes):
        traits.update(part.strip().split("::")[-1] for part in derive.split(",") if part.strip())
    return traits


def _facade_public_impls(code: str) -> list[tuple[int, int, str, str | None, str]]:
    impl_re = re.compile(r"^\s*impl\b", re.MULTILINE)
    implementations: list[tuple[int, int, str, str | None, str]] = []
    for match in impl_re.finditer(code):
        opening = code.find("{", match.end())
        if opening < 0:
            continue
        closing = _find_matching_brace(code, opening)
        head = code[match.end() : opening].strip()
        body = code[opening + 1 : closing]
        trait_match = re.search(r"\bfor\s+([A-Za-z_]\w*)\b", head)
        if trait_match is not None:
            target = trait_match.group(1)
            trait = head[: trait_match.start()].strip().split("::")[-1]
            trait = trait.split("<", 1)[0].strip()
            implementations.append((match.start(), closing, "trait", target, trait))
            continue
        inherent_head = re.sub(r"^<[^>]*>\s*", "", head)
        type_match = re.match(r"([A-Za-z_]\w*)\b", inherent_head)
        target = type_match.group(1) if type_match is not None else ""
        implementations.append((match.start(), closing, "inherent", target, body))
    return implementations


def _facade_token_pattern(token: str) -> str:
    if token == "Engine":
        return r"\bEngine[A-Za-z0-9_]*"
    if token.startswith("*"):
        return re.escape(token)
    if token.endswith("_"):
        return token
    return rf"\b{re.escape(token)}\b"


def _check_facade_public_surface(sources: dict[str, str], errors: list[str]) -> None:
    all_code = "\n".join(sources.values())
    declarations = _facade_type_declarations(all_code)
    declared_names = [match.group("name") for match, _, _ in declarations]
    declared_types = set(declared_names)
    unexpected = sorted(declared_types - FACADE_TYPES)
    missing = sorted(FACADE_TYPES - declared_types)
    if unexpected:
        errors.append("package lumenplot: public type is not allowed " + ",".join(unexpected))
    if missing:
        errors.append(
            "package lumenplot: facade type inventory mismatch (missing " + ",".join(missing) + ")"
        )
    duplicates = sorted(name for name in set(declared_names) if declared_names.count(name) > 1)
    if duplicates:
        errors.append("package lumenplot: facade type is declared more than once " + ",".join(duplicates))

    for match, kind, body in declarations:
        name = match.group("name")
        attributes = match.group("attributes")
        non_exhaustive = re.search(r"#\[\s*non_exhaustive\s*\]", attributes) is not None
        if name in FACADE_NON_EXHAUSTIVE and not non_exhaustive:
            errors.append(f"package lumenplot: facade enum {name!r} must remain non-exhaustive")
        if name not in FACADE_NON_EXHAUSTIVE and non_exhaustive:
            errors.append(f"package lumenplot: facade type {name!r} is unexpectedly non-exhaustive")

        actual_derives = _facade_derive_traits(attributes)
        expected_derives = FACADE_DERIVES.get(name, set())
        if actual_derives != expected_derives:
            if name in FACADE_DERIVES:
                errors.append(f"package lumenplot: trait inventory mismatch for {name!r}")
            elif actual_derives:
                errors.append(f"package lumenplot: incidental public traits on {name!r} are not allowed")

        if re.search(r"^\s*pub\s+(?!\()", body, re.MULTILINE):
            errors.append(f"package lumenplot: facade type {name!r} exposes a public field")
        if re.search(r"\bpub\s+struct\s+\w+\s*\([^;]*\bpub\b", all_code):
            errors.append("package lumenplot: facade tuple field is public")

        if kind == "enum":
            expected_variants = FACADE_ENUM_VARIANTS.get(name)
            if expected_variants is None:
                continue
            actual_variants = set(
                re.findall(r"^\s*([A-Z][A-Za-z0-9_]*)\s*(?:,|$)", body, re.MULTILINE)
            )
            if actual_variants != expected_variants:
                errors.append(f"package lumenplot: facade enum {name!r} variant inventory mismatch")

    method_inventory: dict[str, set[str]] = {}
    impl_ranges: list[tuple[int, int]] = []
    for start, end, implementation_kind, target, body_or_trait in _facade_public_impls(all_code):
        impl_ranges.append((start, end))
        if implementation_kind == "trait":
            if target is None or (target, body_or_trait) not in FACADE_TRAIT_IMPLS:
                errors.append(
                    f"package lumenplot: public trait implementation {body_or_trait!r} for {target!r} is not allowed"
                )
            continue
        body = body_or_trait
        if target not in FACADE_TYPES:
            errors.append(f"package lumenplot: inherent implementation for {target!r} is not allowed")
            continue
        methods = re.findall(r"^\s*pub\s+fn\s+(\w+)\b", body, re.MULTILINE)
        method_inventory.setdefault(target, set()).update(methods)
        unexpected_methods = sorted(set(methods) - FACADE_METHODS.get(target, set()))
        for method in unexpected_methods:
            errors.append(f"package lumenplot: public method {method!r} on {target!r} is not allowed")
        for method_match in re.finditer(r"^\s*pub\s+fn\s+(\w+)\b", body, re.MULTILINE):
            signature_start = method_match.start()
            opening = body.find("{", signature_start)
            signature = body[signature_start:] if opening < 0 else body[signature_start:opening]
            for token in FACADE_RAW_TOKENS:
                pattern = _facade_token_pattern(token)
                if re.search(pattern, signature):
                    errors.append(
                        f"package lumenplot: public method {method_match.group(1)!r} leaks an internal type"
                    )
                    break

    for type_name, expected_methods in FACADE_METHODS.items():
        actual_methods = method_inventory.get(type_name, set())
        if actual_methods != expected_methods:
            errors.append(f"package lumenplot: public method inventory mismatch for {type_name!r}")

    for match in PUBLIC_FN_RE.finditer(all_code):
        if not any(start <= match.start() <= end for start, end in impl_ranges):
            errors.append(f"package lumenplot: public free function {match.group(1)!r} is not allowed")
    non_root_code = "\n".join(
        code for relative, code in sources.items() if relative != "src/lib.rs"
    )
    for line in non_root_code.splitlines():
        if re.match(r"^\s*pub\s+(?:trait|type|const|static|mod|macro|union|extern|use)\b", line):
            errors.append("package lumenplot: public item is not allowlisted")
            break


def _extract_hidden_facade_module(
    root_code: str,
    errors: list[str],
) -> tuple[str | None, bool, str]:
    declarations = list(re.finditer(r"^\s*pub\s+mod\s+__private\b", root_code, re.MULTILINE))
    if not declarations:
        return None, False, root_code
    if len(declarations) != 1:
        errors.append("package lumenplot: hidden facade module must be declared exactly once")
        return None, False, root_code

    declaration = declarations[0]
    line_start = root_code.rfind("\n", 0, declaration.start()) + 1
    preceding = root_code[max(0, line_start - 256) : line_start]
    if re.search(r"#\[\s*doc\s*\(\s*hidden\s*\)\s*\]\s*$", preceding.strip()) is None:
        errors.append("package lumenplot: hidden facade module must be doc-hidden")

    suffix = root_code[declaration.end() :]
    whitespace = len(suffix) - len(suffix.lstrip())
    first = declaration.end() + whitespace
    if first >= len(root_code):
        errors.append("package lumenplot: hidden facade module declaration is malformed")
        return None, False, root_code
    if root_code[first] == ";":
        return None, True, root_code[: declaration.start()] + root_code[first + 1 :]
    if root_code[first] != "{":
        errors.append("package lumenplot: hidden facade module declaration is malformed")
        return None, False, root_code

    closing = _find_matching_brace(root_code, first)
    if closing >= len(root_code):
        errors.append("package lumenplot: hidden facade module body is not closed")
        return None, False, root_code
    body = root_code[first + 1 : closing]
    root_without_module = root_code[: declaration.start()] + root_code[closing + 1 :]
    return body, False, root_without_module


def _check_hidden_facade(code: str, errors: list[str]) -> None:
    declarations = _facade_type_declarations(code)
    declared_names = [match.group("name") for match, _, _ in declarations]
    declared_types = set(declared_names)
    unexpected = sorted(declared_types - HIDDEN_FACADE_TYPES)
    missing = sorted(HIDDEN_FACADE_TYPES - declared_types)
    if unexpected:
        errors.append("package lumenplot: hidden facade public type is not allowed " + ",".join(unexpected))
    if missing:
        errors.append(
            "package lumenplot: hidden facade type inventory mismatch (missing "
            + ",".join(missing)
            + ")"
        )
    duplicates = sorted(name for name in set(declared_names) if declared_names.count(name) > 1)
    if duplicates:
        errors.append("package lumenplot: hidden facade type is declared more than once " + ",".join(duplicates))

    for match, kind, body in declarations:
        name = match.group("name")
        if kind != "struct":
            errors.append(f"package lumenplot: hidden facade type {name!r} must be a struct")
        actual_derives = _facade_derive_traits(match.group("attributes"))
        if actual_derives:
            errors.append(f"package lumenplot: hidden facade incidental public traits on {name!r} are not allowed")
        if re.search(r"^\s*pub(?:\s*\([^)]*\))?\s+", body, re.MULTILINE):
            errors.append(f"package lumenplot: hidden facade type {name!r} exposes a public field")
        if re.search(r"\bpub\s+struct\s+\w+\s*\(\s*pub(?:\s*\([^)]*\))?\b", code):
            errors.append("package lumenplot: hidden facade tuple field is public")

    method_inventory: dict[str, set[str]] = {}
    trait_impls: set[tuple[str, str]] = set()
    impl_ranges: list[tuple[int, int]] = []
    for start, end, implementation_kind, target, body_or_trait in _facade_public_impls(code):
        impl_ranges.append((start, end))
        if implementation_kind == "trait":
            if target is None or (target, body_or_trait) not in HIDDEN_FACADE_TRAIT_IMPLS:
                errors.append(
                    f"package lumenplot: hidden facade public trait implementation "
                    f"{body_or_trait!r} for {target!r} is not allowed"
                )
            else:
                trait_impls.add((target, body_or_trait))
            continue

        body = body_or_trait
        if target not in HIDDEN_FACADE_TYPES:
            errors.append(f"package lumenplot: hidden facade inherent implementation for {target!r} is not allowed")
            continue
        methods = re.findall(r"^\s*pub\s+fn\s+(\w+)\b", body, re.MULTILINE)
        method_inventory.setdefault(target, set()).update(methods)
        for method in sorted(set(methods) - HIDDEN_FACADE_METHODS[target]):
            errors.append(
                f"package lumenplot: hidden facade public method {method!r} on {target!r} is not allowed"
            )
        for method_match in re.finditer(r"^\s*pub\s+fn\s+(\w+)\b", body, re.MULTILINE):
            method = method_match.group(1)
            signature_start = method_match.start()
            opening = body.find("{", signature_start)
            signature = body[signature_start:] if opening < 0 else body[signature_start:opening]
            expected_signature = HIDDEN_FACADE_SIGNATURES.get((target, method))
            if expected_signature is not None and (
                _normalize_bridge_signature(signature)
                != _normalize_bridge_signature(expected_signature)
            ):
                errors.append(
                    f"package lumenplot: hidden facade public method {method!r} on {target!r} "
                    "has an unexpected signature"
                )
            for token in HIDDEN_FACADE_RAW_TOKENS:
                if re.search(_facade_token_pattern(token), signature):
                    errors.append(f"package lumenplot: hidden facade method {method!r} leaks an internal type")
                    break

    for type_name, expected_methods in HIDDEN_FACADE_METHODS.items():
        if method_inventory.get(type_name, set()) != expected_methods:
            errors.append(f"package lumenplot: hidden facade public method inventory mismatch for {type_name!r}")
    if trait_impls != HIDDEN_FACADE_TRAIT_IMPLS:
        errors.append("package lumenplot: hidden facade trait inventory mismatch for 'BridgeError'")

    public_functions = list(PUBLIC_FN_RE.finditer(code))
    free_functions = [
        match
        for match in public_functions
        if not any(start <= match.start() <= end for start, end in impl_ranges)
    ]
    expected_public_functions = {"new", "code", "category", "message", "render_line_png"}
    if {match.group(1) for match in public_functions} != expected_public_functions:
        errors.append("package lumenplot: hidden facade public function inventory mismatch")
    if len(free_functions) != 1 or free_functions[0].group(1) != "render_line_png":
        errors.append("package lumenplot: hidden facade public free function inventory mismatch")
    else:
        match = free_functions[0]
        opening = code.find("{", match.start())
        signature = code[match.start():] if opening < 0 else code[match.start():opening]
        if _normalize_bridge_signature(signature) != _normalize_bridge_signature(HIDDEN_FACADE_FREE_SIGNATURE):
            errors.append("package lumenplot: hidden facade render_line_png has an unexpected signature")
        for token in HIDDEN_FACADE_RAW_TOKENS:
            if re.search(_facade_token_pattern(token), signature):
                errors.append("package lumenplot: hidden facade render_line_png leaks an internal type")
                break

    for line in code.splitlines():
        if not re.match(r"^\s*pub\s+", line):
            continue
        if re.match(r"^\s*pub\s+(?:struct|enum|fn)\b", line):
            continue
        errors.append("package lumenplot: hidden facade public item is not allowlisted")
        break


def _check_facade_root(root_code: str, errors: list[str]) -> None:
    module_names = set(re.findall(r"^\s*mod\s+(\w+)\s*;", root_code, re.MULTILINE))
    expected_modules = {"error", "view", "series", "scene"}
    if module_names != expected_modules:
        errors.append("package lumenplot: private module inventory mismatch")
    if re.search(r"^\s*pub\s+mod\b", root_code, re.MULTILINE):
        errors.append("package lumenplot: public module is not allowed")
    if NO_MANGLE_RE.search(root_code):
        errors.append("package lumenplot: exported ABI is not allowed")

    exports: list[str] = []
    for match in re.finditer(r"^\s*pub\s+use\s+(?P<statement>[^;]+);", root_code, re.MULTILINE | re.DOTALL):
        statement = match.group("statement").strip()
        if "lumenplot_engine" in statement:
            errors.append("package lumenplot: internal re-export is not allowed")
        if re.search(r"\bas\b", statement):
            errors.append("package lumenplot: export aliases are not allowed")
        if "{" in statement and statement.endswith("}"):
            prefix, names = statement.split("{", 1)
            if not prefix.rstrip().endswith("::"):
                errors.append("package lumenplot: root export path is not allowlisted")
            exports.extend(re.findall(r"\b([A-Z][A-Za-z0-9_]*)\b", names))
        else:
            name = statement.rsplit("::", 1)[-1].strip()
            exports.append(name)
        for token in FACADE_RAW_TOKENS:
            if re.search(_facade_token_pattern(token), statement):
                errors.append("package lumenplot: root export leaks an engine or internal type")
                break

    if set(exports) != FACADE_ROOT_EXPORTS or len(exports) != len(set(exports)):
        errors.append("package lumenplot: exact root export inventory mismatch")

    root_without_exports = re.sub(r"^\s*pub\s+use\b.*?;", "", root_code, flags=re.MULTILINE | re.DOTALL)
    if PUBLIC_BARE_ITEM_RE.search(root_without_exports):
        errors.append("package lumenplot: public item is not allowed")


def _check_facade_source(package_dir: Path, root: Path, errors: list[str]) -> None:
    source_dir = package_dir / "src"
    rust_files = (
        {path.relative_to(package_dir).as_posix() for path in source_dir.rglob("*.rs")}
        if source_dir.is_dir()
        else set()
    )
    root_path = source_dir / "lib.rs"
    try:
        root_code = _strip_rust_comments_and_literals(root_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        errors.append(f"package lumenplot: cannot read src/lib.rs")
        return
    expected_source_files = EXPECTED_FACADE_SOURCE_FILES | (
        {HIDDEN_FACADE_SOURCE_FILE} if HIDDEN_FACADE_SOURCE_FILE in rust_files else set()
    )
    if rust_files != expected_source_files:
        missing = sorted(expected_source_files - rust_files)
        extra = sorted(rust_files - expected_source_files)
        details: list[str] = []
        if missing:
            details.append("missing " + ",".join(missing))
        if extra:
            details.append("extra " + ",".join(extra))
        errors.append(
            "package lumenplot: source inventory mismatch"
            + (" (" + "; ".join(details) + ")" if details else "")
        )
        return

    sources: dict[str, str] = {}
    for relative in sorted(rust_files):
        path = package_dir / relative
        try:
            code = _strip_rust_comments_and_literals(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError):
            errors.append(f"package lumenplot: cannot read {relative}")
            continue
        sources[relative] = code
        for label, pattern in FACADE_FORBIDDEN_CODE_PATTERNS:
            if pattern.search(code):
                errors.append(f"package lumenplot: {label} is not allowed")

    if not sources:
        return
    hidden_code, external_hidden_module, root_without_hidden = _extract_hidden_facade_module(
        sources["src/lib.rs"], errors
    )
    if external_hidden_module:
        if HIDDEN_FACADE_SOURCE_FILE not in sources:
            errors.append("package lumenplot: external hidden facade module source is missing")
        else:
            hidden_code = sources[HIDDEN_FACADE_SOURCE_FILE]
    elif HIDDEN_FACADE_SOURCE_FILE in sources:
        errors.append("package lumenplot: hidden facade source requires a module declaration")
    visible_sources = {
        relative: code for relative, code in sources.items() if relative != HIDDEN_FACADE_SOURCE_FILE
    }
    visible_sources["src/lib.rs"] = root_without_hidden
    _check_facade_root(root_without_hidden, errors)
    _check_facade_public_surface(visible_sources, errors)
    if hidden_code is not None:
        _check_hidden_facade(hidden_code, errors)


def _normalize_bridge_signature(signature: str) -> str:
    """Normalize formatting while preserving the exact public signature."""

    normalized = " ".join(signature.split())
    normalized = re.sub(r"\s*->\s*", "->", normalized)
    normalized = re.sub(r"\s*([(),:<>\[\]&])\s*", r"\1", normalized)
    return normalized.replace(",)", ")")


def _check_engine_bridge(code: str, errors: list[str]) -> None:
    if PUBLIC_REEXPORT_RE.search(code):
        errors.append("package lumenplot-engine: bridge re-export is not allowed")
    if re.search(r"\bRenderPacket\b", code):
        errors.append("package lumenplot-engine: bridge public signature uses forbidden RenderPacket")

    declared_types = set(PUBLIC_TYPE_RE.findall(code))
    unexpected_types = sorted(declared_types - BRIDGE_TYPES)
    if unexpected_types:
        errors.append(
            "package lumenplot-engine: bridge public type is not allowed "
            + ",".join(unexpected_types)
        )
    missing_types = sorted(BRIDGE_TYPES - declared_types)
    if missing_types:
        errors.append(
            "package lumenplot-engine: bridge type inventory mismatch (missing "
            + ",".join(missing_types)
            + ")"
        )

    declarations = re.compile(
        r"(?P<attributes>(?:^\s*#\[[^\n]*\]\s*\n)*)"
        r"^\s*pub\s+(?P<kind>struct|enum)\s+(?P<name>\w+)\b",
        re.MULTILINE,
    )
    for declaration in declarations.finditer(code):
        name = declaration.group("name")
        actual_derives = _facade_derive_traits(declaration.group("attributes"))
        expected_derives = BRIDGE_DERIVES.get(name, set())
        if actual_derives != expected_derives:
            errors.append(f"package lumenplot-engine: bridge trait inventory mismatch for {name!r}")

    for name in PUBLIC_FN_RE.findall(code):
        if name not in BRIDGE_METHODS:
            errors.append(f"package lumenplot-engine: bridge public method {name!r} is not allowed")

    method_inventory: dict[str, set[str]] = {}
    for _, _, implementation_kind, target, body_or_trait in _facade_public_impls(code):
        if implementation_kind != "inherent" or target not in BRIDGE_METHODS_BY_TYPE:
            continue
        body = body_or_trait
        methods = set(re.findall(r"^\s*pub\s+fn\s+(\w+)\b", body, re.MULTILINE))
        method_inventory.setdefault(target, set()).update(methods)
        unexpected = sorted(methods - BRIDGE_METHODS_BY_TYPE[target])
        for method in unexpected:
            errors.append(
                f"package lumenplot-engine: bridge public method {method!r} on {target!r} is not allowed"
            )
        for method_match in re.finditer(r"^\s*pub\s+fn\s+(\w+)\b", body, re.MULTILINE):
            method = method_match.group(1)
            expected_signature = BRIDGE_PHASE2_SIGNATURES.get(target, {}).get(method)
            if expected_signature is None:
                continue
            signature_start = method_match.start()
            opening = body.find("{", signature_start)
            signature = body[signature_start:] if opening < 0 else body[signature_start:opening]
            if _normalize_bridge_signature(signature) != _normalize_bridge_signature(expected_signature):
                errors.append(
                    f"package lumenplot-engine: bridge public method {method!r} on {target!r} has an unexpected signature"
                )
    for type_name, expected_methods in BRIDGE_METHODS_BY_TYPE.items():
        if method_inventory.get(type_name, set()) != expected_methods:
            errors.append(
                f"package lumenplot-engine: bridge public method inventory mismatch for {type_name!r}"
            )

    for line in code.splitlines():
        if not re.match(r"^\s*pub\s+", line):
            continue
        if re.match(r"^\s*pub\s+(?:struct|enum|fn)\b", line):
            continue
        errors.append("package lumenplot-engine: bridge public item is not allowlisted")
        break

    for match in re.finditer(
        r"pub\s+(?:struct|enum)\s+(\w+)(?:\s*<[^>{}]*>)?\s*\{(.*?)\}",
        code,
        re.DOTALL,
    ):
        if re.search(r"\bpub\b", match.group(2)):
            errors.append(
                f"package lumenplot-engine: bridge type {match.group(1)!r} exposes a field"
            )
    if re.search(r"pub\s+struct\s+\w+\s*\(\s*pub\b", code):
        errors.append("package lumenplot-engine: bridge tuple field is public")

    enum_variants = {
        "SceneErrorKind": {
            "InvalidInput",
            "UnsupportedCapability",
            "InvalidState",
            "SeriesNotFound",
            "TopologyViolation",
            "NonFiniteCanonical",
            "CapacityExceeded",
            "AllocationFailed",
            "IdentityExhausted",
            "RevisionExhausted",
            "Internal",
        },
        "AxisScale": {"Linear", "Log10"},
        "SeriesTopology": {"MonotonicX", "ArbitraryXY"},
    }
    for name, expected in enum_variants.items():
        match = re.search(
            rf"pub\s+enum\s+{name}\b[^{{]*\{{(.*?)\}}",
            code,
            re.DOTALL,
        )
        if match is None:
            continue
        actual = set(re.findall(r"^\s*([A-Z][A-Za-z0-9_]*)\s*(?:,|$)", match.group(1), re.MULTILINE))
        if actual != expected:
            errors.append(f"package lumenplot-engine: bridge enum {name!r} variant inventory mismatch")

    series_data = re.search(
        r"(?P<attributes>(?:^\s*#\[[^\n]*\]\s*\n)*)^\s*pub\s+struct\s+SeriesData\b",
        code,
        re.MULTILINE,
    )
    if series_data is not None and re.search(r"\bDebug\b", series_data.group("attributes")):
        errors.append("package lumenplot-engine: SeriesData raw formatting is not allowed")
    if re.search(
        r"\bimpl(?:\s*<[^>{}]*>)?\s+(?:(?:std|core)::)?(?:fmt::)?"
        r"(?:Debug|Display|Binary|LowerHex|UpperHex|Octal|Pointer)\s+for\s+SeriesData\b",
        code,
    ):
        errors.append("package lumenplot-engine: SeriesData raw formatting is not allowed")

    raw_tokens = (
        "crate::",
        "Engine",
        "SeriesInput",
        "Topology",
        "Chunk",
        "Lod",
        "SceneState",
        "DataEpoch",
        "ChunkRevision",
        "ComponentRevision",
        "BTreeMap",
        "Arc<",
    )
    for match in PUBLIC_FN_RE.finditer(code):
        start = match.start()
        end = code.find("{", start)
        signature = code[start:] if end < 0 else code[start:end]
        if any(
            (token in signature if token.endswith("<") else re.search(rf"\b{re.escape(token)}\b", signature))
            for token in raw_tokens
        ):
            errors.append(f"package lumenplot-engine: bridge method {match.group(1)!r} leaks an internal type")


def _check_engine_source(package_dir: Path, root: Path, errors: list[str]) -> None:
    source_dir = package_dir / "src"
    rust_files = (
        {path.relative_to(package_dir).as_posix() for path in source_dir.rglob("*.rs")}
        if source_dir.is_dir()
        else set()
    )
    if rust_files != EXPECTED_ENGINE_SOURCE_FILES:
        missing = sorted(EXPECTED_ENGINE_SOURCE_FILES - rust_files)
        extra = sorted(rust_files - EXPECTED_ENGINE_SOURCE_FILES)
        details: list[str] = []
        if missing:
            details.append("missing " + ",".join(missing))
        if extra:
            details.append("extra " + ",".join(extra))
        errors.append(
            "package lumenplot-engine: source inventory mismatch"
            + (" (" + "; ".join(details) + ")" if details else "")
        )
        return

    sources: dict[str, str] = {}
    for relative in sorted(rust_files):
        path = package_dir / relative
        try:
            sources[relative] = _strip_rust_comments_and_literals(
                path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError):
            errors.append(f"package lumenplot-engine: cannot read {relative}")
    if not sources:
        return

    root_code = sources["src/lib.rs"]
    for module in ("error", "frame", "data", "lod", "scene"):
        if not re.search(rf"^\s*mod\s+{module}\s*;", root_code, re.MULTILINE):
            errors.append(f"package lumenplot-engine: private root module {module!r} is missing")
    hidden_bridge = re.compile(
        r"#\s*\[\s*doc\s*\(\s*hidden\s*\)\s*\]\s*pub\s+mod\s+bridge\s*;",
        re.DOTALL,
    )
    if hidden_bridge.search(root_code) is None:
        errors.append("package lumenplot-engine: only the hidden bridge may be public")
    root_without_bridge = hidden_bridge.sub("", root_code)
    if re.search(r"^\s*pub\s*(?:\([^)]*\))?\s+mod\b", root_without_bridge, re.MULTILINE):
        errors.append("package lumenplot-engine: root module visibility is too broad")
    if PUBLIC_REEXPORT_RE.search(root_without_bridge):
        errors.append("package lumenplot-engine: root re-export is not allowed")
    if PUBLIC_BARE_ITEM_RE.search(root_without_bridge):
        errors.append("package lumenplot-engine: root public item is not allowed")

    for relative, code in sources.items():
        _check_forbidden_code("lumenplot-engine", code, errors)
        if relative in {"src/lib.rs", "src/bridge.rs"}:
            continue
        if PUBLIC_REEXPORT_RE.search(code) or PUBLIC_BARE_ITEM_RE.search(code):
            errors.append(f"package lumenplot-engine: public item outside bridge in {relative}")
    _check_engine_bridge(sources["src/bridge.rs"], errors)


def _check_export_source(package_dir: Path, root: Path, errors: list[str]) -> None:
    source_dir = package_dir / "src"
    rust_files = (
        {path.relative_to(package_dir).as_posix() for path in source_dir.rglob("*.rs")}
        if source_dir.is_dir()
        else set()
    )
    if rust_files != EXPECTED_EXPORT_SOURCE_FILES:
        missing = sorted(EXPECTED_EXPORT_SOURCE_FILES - rust_files)
        extra = sorted(rust_files - EXPECTED_EXPORT_SOURCE_FILES)
        details: list[str] = []
        if missing:
            details.append("missing " + ",".join(missing))
        if extra:
            details.append("extra " + ",".join(extra))
        errors.append(
            "package lumenplot-export: source inventory mismatch"
            + (" (" + "; ".join(details) + ")" if details else "")
        )
        return

    sources: dict[str, str] = {}
    for relative in sorted(rust_files):
        path = package_dir / relative
        try:
            sources[relative] = _strip_rust_comments_and_literals(
                path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError):
            errors.append(f"package lumenplot-export: cannot read {relative}")
    if not sources:
        return

    all_code = "\n".join(sources.values())
    forbidden = (
        ("unsafe code", re.compile(r"\bunsafe\b")),
        (
            "serialization or wire code",
            re.compile(r"\b(?:serde|bincode|postcard|rmp|wire|persistence|serialize|deserialize)\b"),
        ),
        (
            "forbidden Pixmap color sink",
            re.compile(r"\bPixmap(?:Mut|Ref)?\b"),
        ),
        ("forbidden RenderPacket boundary", re.compile(r"\bRenderPacket\b")),
        (
            "concrete frontend/backend code",
            re.compile(r"\b(?:wgpu|winit|window|surface|device|python|matplotlib|numpy|pyo3)\b", re.I),
        ),
    )
    for label, pattern in forbidden:
        if pattern.search(all_code):
            errors.append(f"package lumenplot-export: {label} is not allowed")

    root_code = sources["src/lib.rs"]
    module_pattern = re.compile(r"^\s*mod\s+(compositor|error|png|raster)\s*;", re.MULTILINE)
    if {match.group(1) for match in module_pattern.finditer(root_code)} != {
        "compositor",
        "error",
        "png",
        "raster",
    }:
        errors.append("package lumenplot-export: private module inventory mismatch")
    hidden_bridge = re.compile(
        r"#\s*\[\s*doc\s*\(\s*hidden\s*\)\s*\]\s*"
        r"pub\s+mod\s+bridge\s*\{(?P<body>.*)\}",
        re.DOTALL,
    )
    bridge_matches = list(hidden_bridge.finditer(root_code))
    if len(bridge_matches) != 1:
        errors.append("package lumenplot-export: exactly one hidden bridge is required")
        bridge_body = ""
    else:
        bridge_body = bridge_matches[0].group("body")
    root_without_bridge = hidden_bridge.sub("", root_code)
    if re.search(r"^\s*pub\s+(?:mod|use|struct|enum|fn|type|const|static|trait)\b", root_without_bridge, re.MULTILINE):
        errors.append("package lumenplot-export: public item outside hidden bridge is not allowed")
    bridge_statements = re.findall(r"^\s*pub\s+use\s+([^;]+);", bridge_body, re.MULTILINE)
    bridge_exports: set[str] = set()
    for statement in bridge_statements:
        if "{" in statement and "}" in statement:
            names = statement.split("{", 1)[1].rsplit("}", 1)[0]
            bridge_exports.update(name.strip() for name in names.split(",") if name.strip())
        else:
            bridge_exports.add(statement.rsplit("::", 1)[-1].strip())
    if bridge_exports != EXPORT_BRIDGE_EXPORTS:
        errors.append("package lumenplot-export: exact bridge export inventory mismatch")
    if re.search(r"^\s*pub\s+(?:mod|use|struct|enum|fn|type|const|static|trait)\b", bridge_body, re.MULTILINE):
        # The allowlisted bridge surface is made only of re-exports.
        if not all(re.match(r"^\s*pub\s+use\b", statement) for statement in bridge_body.splitlines() if statement.strip()):
            errors.append("package lumenplot-export: bridge contains a non-re-exported public item")

    for relative, code in sources.items():
        if relative == "src/lib.rs":
            continue
        if re.search(r"^\s*pub\s+(?:mod|use)\b", code, re.MULTILINE):
            errors.append(f"package lumenplot-export: public module or re-export outside bridge in {relative}")
        if re.search(r"^\s*pub\s+(?!\(?(?:struct|enum|fn)\b)", code, re.MULTILINE):
            errors.append(f"package lumenplot-export: public item outside the exact surface in {relative}")

    declarations = _facade_type_declarations(all_code)
    declared_names = [match.group("name") for match, _, _ in declarations]
    if set(declared_names) != EXPORT_TYPES or len(declared_names) != len(set(declared_names)):
        errors.append("package lumenplot-export: exact public type inventory mismatch")
    for match, _, body in declarations:
        name = match.group("name")
        actual_derives = _facade_derive_traits(match.group("attributes"))
        if actual_derives != EXPORT_DERIVES.get(name, set()):
            errors.append(f"package lumenplot-export: trait inventory mismatch for {name!r}")
        if re.search(r"\bpub\b", body):
            errors.append(f"package lumenplot-export: type {name!r} exposes a public field")

    for name, expected_variants in EXPORT_ENUM_VARIANTS.items():
        variant_match = re.search(rf"pub\s+enum\s+{name}\b[^{{]*\{{(.*?)\}}", all_code, re.DOTALL)
        actual_variants = (
            set(re.findall(r"^\s*([A-Z][A-Za-z0-9_]*)\s*(?:,|$)", variant_match.group(1), re.MULTILINE))
            if variant_match is not None
            else set()
        )
        if actual_variants != expected_variants:
            errors.append(f"package lumenplot-export: enum {name!r} variant inventory mismatch")

    implementations = _facade_public_impls(all_code)
    method_inventory: dict[str, set[str]] = {}
    trait_impls: set[tuple[str, str]] = set()
    impl_ranges: list[tuple[int, int]] = []
    for start, end, implementation_kind, target, body_or_trait in implementations:
        impl_ranges.append((start, end))
        if implementation_kind == "trait":
            if target in EXPORT_TYPES:
                trait_impls.add((target, body_or_trait))
            continue
        if target not in EXPORT_METHODS:
            continue
        body = body_or_trait
        methods = set(re.findall(r"^\s*pub\s+fn\s+(\w+)\b", body, re.MULTILINE))
        method_inventory.setdefault(target, set()).update(methods)
        for method in sorted(methods - EXPORT_METHODS[target]):
            errors.append(f"package lumenplot-export: public method {method!r} on {target!r} is not allowed")
        for method_match in re.finditer(r"^\s*pub\s+fn\s+(\w+)\b", body, re.MULTILINE):
            method = method_match.group(1)
            expected_signature = EXPORT_SIGNATURES.get((target, method))
            if expected_signature is None:
                continue
            opening = body.find("{", method_match.start())
            signature = body[method_match.start():] if opening < 0 else body[method_match.start():opening]
            if _normalize_bridge_signature(signature) != _normalize_bridge_signature(expected_signature):
                errors.append(f"package lumenplot-export: public method {method!r} on {target!r} has an unexpected signature")
    for target, expected_methods in EXPORT_METHODS.items():
        if method_inventory.get(target, set()) != expected_methods:
            errors.append(f"package lumenplot-export: public method inventory mismatch for {target!r}")
    if trait_impls != {("ExportError", "Debug"), ("ExportError", "Display"), ("ExportError", "Error")}:
        errors.append("package lumenplot-export: ExportError trait inventory mismatch")

    public_functions = re.findall(r"^\s*pub\s+fn\s+(\w+)\b", all_code, re.MULTILINE)
    free_functions = []
    for match in re.finditer(r"^\s*pub\s+fn\s+(\w+)\b", all_code, re.MULTILINE):
        if not any(start <= match.start() <= end for start, end in impl_ranges):
            free_functions.append(match)
    if set(public_functions) != {"kind", "message", "new", "encode_line_frame_png"}:
        errors.append("package lumenplot-export: public function inventory mismatch")
    if len(free_functions) != 1 or free_functions[0].group(1) != "encode_line_frame_png":
        errors.append("package lumenplot-export: public free function inventory mismatch")
    else:
        match = free_functions[0]
        opening = all_code.find("{", match.start())
        signature = all_code[match.start():] if opening < 0 else all_code[match.start():opening]
        expected_signature = EXPORT_SIGNATURES[("__free__", "encode_line_frame_png")]
        if _normalize_bridge_signature(signature) != _normalize_bridge_signature(expected_signature):
            errors.append("package lumenplot-export: encode_line_frame_png has an unexpected signature")

    public_signature_code = "\n".join(
        line for line in all_code.splitlines() if re.match(r"^\s*pub\s+fn\b", line)
    )
    if re.search(r"\b(?:tiny_skia|png|Mask|Path|Stroke|Pixmap|RenderPacket)\b", public_signature_code):
        errors.append("package lumenplot-export: public signature leaks a dependency or renderer type")


def _check_package_source(package_name: str, package_dir: Path, root: Path, errors: list[str]) -> None:
    if package_name == "lumenplot-engine":
        _check_engine_source(package_dir, root, errors)
    elif package_name == "lumenplot-export":
        _check_export_source(package_dir, root, errors)
    elif package_name == "lumenplot":
        _check_facade_source(package_dir, root, errors)
    else:
        _check_stub_source(package_name, package_dir / "src", root, errors)


def _check_dependencies(
    package_name: str,
    manifest: dict[str, Any],
    errors: list[str],
) -> None:
    expected_edges = EXPECTED_EDGES[package_name]
    expected_external = (
        EXPECTED_EXPORT_EXTERNAL_DEPENDENCIES if package_name == "lumenplot-export" else {}
    )
    actual_edges: set[str] = set()
    actual_external: set[str] = set()
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
                expected_specification = expected_external.get(dependency_name)
                if expected_specification is None:
                    errors.append(
                        f"package {package_name}: external dependency {dependency_name!r} is not allowed"
                    )
                elif specification != expected_specification:
                    errors.append(
                        f"package {package_name}: external dependency {dependency_name!r} has an unexpected specification"
                    )
                else:
                    actual_external.add(dependency_name)
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
    if actual_external != set(expected_external):
        missing = sorted(set(expected_external) - actual_external)
        extra = sorted(actual_external - set(expected_external))
        details = []
        if missing:
            details.append(f"missing {','.join(missing)}")
        if extra:
            details.append(f"extra {','.join(extra)}")
        if details:
            errors.append(
                f"package {package_name}: exact external dependency inventory mismatch ({'; '.join(details)})"
            )


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
