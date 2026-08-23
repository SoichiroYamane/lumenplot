#!/usr/bin/env python3
"""Check the accepted Rust workspace and conditional Phase-3A boundaries.

This checker intentionally uses only the Python standard library.  It validates
repository structure and negative public-surface guards without compiling or
importing product code.  The hidden Phase-3A facade is absent before
implementation and, when present, must match its exact owned inventory.  The
Phase-3A2 wheel gate is also absent before implementation; it activates only
when an implementation sentinel appears and then fails closed on every missing
package, workflow, or static input invariant.  Its CI-local runtime manifest is
checked only when the explicit evidence mode is requested.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import hashlib
import re
import shlex
import subprocess
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
FACADE_DERIVE_ATTRIBUTES = {
    "SceneRevision": "#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]",
    "SeriesId": "#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]",
    "SceneSnapshot": "#[derive(Clone)]",
}
FACADE_TRAIT_IMPLS = {
    ("PublicError", "Debug"),
    ("PublicError", "Display"),
    ("PublicError", "Error"),
}
FACADE_SOURCE_TYPES = {
    "src/error.rs": {"ErrorCode", "ErrorCategory", "PublicError"},
    "src/view.rs": {"AxisRange", "AxisScale", "Viewport", "AxisScales"},
    "src/series.rs": {"SeriesTopology", "SeriesData"},
    "src/scene.rs": {
        "PlotScene",
        "SceneTransaction",
        "SceneSnapshot",
        "SceneRevision",
        "SeriesId",
        "CommitReceipt",
    },
}
FACADE_ROOT_EXPORT_GROUPS = (
    ("error", ("ErrorCategory", "ErrorCode", "PublicError")),
    (
        "scene",
        (
            "CommitReceipt",
            "PlotScene",
            "SceneRevision",
            "SceneSnapshot",
            "SceneTransaction",
            "SeriesId",
        ),
    ),
    ("series", ("SeriesData", "SeriesTopology")),
    ("view", ("AxisRange", "AxisScale", "AxisScales", "Viewport")),
)
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
HIDDEN_FACADE_IMPL_HEADERS = {
    "LinePngGeometry",
    "LinePngStyle",
    "OwnedLinePngRequest",
    "BridgeError",
    "fmt::Debug for BridgeError",
    "fmt::Display for BridgeError",
    "std::error::Error for BridgeError",
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

PHASE3A2_IMAGE = (
    "quay.io/pypa/manylinux_2_28_x86_64:2026.08.15-1@"
    "sha256:0c87ccb5996dab6c3b7612ee4fda7b80c4ab3c44a86c2541e4a872afdf4f131b"
)
PHASE3A2_IMAGE_CONFIG_DIGEST = "sha256:fd0c576d9673648a125bffeaea6acb762d8bc52d97da9034dfdbe00f98a17dd5"
PHASE3A2_MATURIN_WHEEL_SHA256 = "dfc54ae32e6fcb18302193ab9a30b0b25eefffba994ae13238974805533ef75e"
# Probed from
# https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init
# and cross-checked against the published rustup-init.sha256 sidecar.
PHASE3A2_RUSTUP_INIT_SHA256 = "4acc9acc76d5079515b46346a485974457b5a79893cfb01112423c89aeb5aa10"
PHASE3A2_NUMPY_WHEEL_SHA256 = {
    "cp311": "89cd468399cfd2504718f0ba50e410dca55a170b61a02ad92bb18c8a65186e93",
    "cp312": "90f9849678c75fe7afa2d348ac842c168b0a4d3d61919687216dfc547976d853",
    "cp313": "a7830bab239b79cda9c08c2da014761cafb48da6150e1da17ac06283f43b6089",
    "cp314": "a2c306dea656c12c68f51f4cea133cbe78ca7435eb28c735eac1d3ebe73be6e8",
}
PHASE3A2_SCHEMA = "lumenplot.phase3a2-wheel-evidence.v1"
PHASE3A2_INTERPRETERS = {
    "3.11": "/opt/python/cp311-cp311/bin/python",
    "3.12": "/opt/python/cp312-cp312/bin/python",
    "3.13": "/opt/python/cp313-cp313/bin/python",
    "3.14": "/opt/python/cp314-cp314/bin/python",
}
PHASE3A2_ACTION_PINS = {
    "actions/checkout": ("11bd71901bbe5b1630ceea73d27597364c9af683", "v4.2.2"),
    "dtolnay/rust-toolchain": ("032958afbdc797a9164d3bc0b56325c1308924a5", "1.97.1"),
    "actions/upload-artifact": ("043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", "v7.0.1"),
}
PHASE3A2_PYTHON_DEPENDENCIES = {
    "pyo3": {
        "version": "=0.29.2",
        "default-features": False,
        "features": ["macros", "extension-module", "abi3-py311"],
    },
    "numpy": {"version": "=0.29.0", "default-features": False},
}
# Phase-3B raster pipeline additions (workstream-manager decision on task
# t_52f05497): identical pins to lumenplot-export's accepted declarations,
# admitted only while the Phase-3B static allowance is active.
PHASE3A2_PHASE3B_PYTHON_DEPENDENCIES = {
    "png": {"version": "=0.18.1", "default-features": False},
    "tiny-skia": {"version": "=0.12.0", "default-features": False, "features": ["std"]},
}
PHASE3A2_MANIFEST_KEYS = {
    "schema",
    "builder",
    "checks",
    "claim_boundary",
    "runtime_cells",
    "source",
    "wheel",
}
PHASE3A2_SOURCE_KEYS = {"commit", "cargo_lock_sha256", "distribution", "cargo_version"}
PHASE3A2_BUILDER_KEYS = {
    "image",
    "platform",
    "config_digest",
    "glibc",
    "auditwheel_version",
    "abi3audit_version",
    "rust_version",
    "maturin_version",
    "maturin_wheel_sha256",
}
# Observed mode adds runtime-recorded ELF evidence to the pinned builder set.
PHASE3A2_OBSERVED_BUILDER_KEYS = PHASE3A2_BUILDER_KEYS | {"elf_runpath"}
PHASE3A2_WHEEL_KEYS = {
    "filename",
    "sha256",
    "tag",
    "cargo_expected_version",
    "metadata_version",
    "zip",
    "metadata",
    "wheel",
    "record",
    "elf",
    "abi3",
    "sbom",
    "sbom_format",
}
PHASE3A2_CHECK_KEYS = {
    "cargo_locked_sources_checksums_licenses",
    "same_wheel",
    "metadata_version",
    "auditwheel",
    "elf_rpath",
    "abi3audit",
    "private_helper_fixtures",
    "redaction_ownership",
}
PHASE3A2_CLAIM_KEYS = {
    "private_helper_only",
    "release_artifact",
    "platform_support_claim",
    "publication_authorized",
}

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


INVALID_RUST_SYNTAX = "\x00"


def _blank_rust_range(chars: list[str], source: str, start: int, end: int) -> None:
    for position in range(start, end):
        if source[position] != "\n":
            chars[position] = " "


def _strip_rust_comments_and_literals(source: str) -> str:
    """Remove comments and literals while preserving line structure.

    The checker is intentionally stdlib-only, so this is a small lexical pass
    rather than a Rust parser.  Raw strings and nested block comments must be
    handled before code-only scans; otherwise braces, attributes, or forbidden
    words in an otherwise private literal can change the apparent public
    inventory.  An unterminated literal/comment leaves a sentinel for the
    caller to reject instead of silently dropping malformed source.
    """

    chars = list(source)
    length = len(source)
    position = 0
    raw_string = re.compile(r'(?:br|r)(?P<hashes>#{0,255})"(?s:.*?)"(?P=hashes)')
    raw_prefix = re.compile(r'(?:br|r)#{0,255}"')

    while position < length:
        if source.startswith("//", position):
            end = source.find("\n", position + 2)
            if end < 0:
                end = length
            _blank_rust_range(chars, source, position, end)
            position = end
            continue

        if source.startswith("/*", position):
            start = position
            depth = 1
            position += 2
            while position < length and depth:
                if source.startswith("/*", position):
                    depth += 1
                    position += 2
                elif source.startswith("*/", position):
                    depth -= 1
                    position += 2
                else:
                    position += 1
            end = position
            _blank_rust_range(chars, source, start, end)
            if depth:
                chars[start] = INVALID_RUST_SYNTAX
            continue

        raw_match = None
        if (position == 0 or not (source[position - 1].isalnum() or source[position - 1] == "_")):
            raw_match = raw_string.match(source, position)
        if raw_match is not None:
            end = raw_match.end()
            _blank_rust_range(chars, source, position, end)
            position = end
            continue

        if raw_prefix.match(source, position) is not None:
            _blank_rust_range(chars, source, position, length)
            chars[position] = INVALID_RUST_SYNTAX
            break

        string_start = position
        if source[position] == '"':
            position += 1
        elif source.startswith('b"', position):
            position += 2
        else:
            string_start = -1
        if string_start >= 0:
            escaped = False
            while position < length:
                character = source[position]
                position += 1
                if character == "\n":
                    break
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    _blank_rust_range(chars, source, string_start, position)
                    break
            else:
                _blank_rust_range(chars, source, string_start, length)
                chars[string_start] = INVALID_RUST_SYNTAX
                break
            if position > 0 and source[position - 1] == '"':
                continue
            _blank_rust_range(chars, source, string_start, position)
            chars[string_start] = INVALID_RUST_SYNTAX
            continue

        if source[position] == "'":
            closing = position + 1
            escaped = False
            while closing < length and source[closing] != "\n":
                character = source[closing]
                if not escaped and character == "'":
                    literal = source[position : closing + 1]
                    if len(literal) >= 3 and not any(char.isspace() for char in literal[1:-1]):
                        _blank_rust_range(chars, source, position, closing + 1)
                        position = closing + 1
                    else:
                        position += 1
                    break
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                closing += 1
            else:
                position += 1
            continue

        position += 1

    return "".join(chars)


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
    allowed_files = ["src/lib.rs"]
    if package_name == "lumenplot-python" and _phase3b_activation_reason(root) is not None:
        # Phase-3B splits the private raster pipeline into src/frame.rs
        # (accepted lane implementation); admit exactly that layout while
        # the Phase-3B static allowance is active.
        allowed_files = ["src/frame.rs", "src/lib.rs"]
    if rust_files != allowed_files:
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


def _find_matching_square_bracket(code: str, opening: int) -> int:
    depth = 0
    for position in range(opening, len(code)):
        if code[position] == "[":
            depth += 1
        elif code[position] == "]":
            depth -= 1
            if depth == 0:
                return position
    return len(code)


def _hidden_attribute_spans(code: str, errors: list[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"#", code):
        opening = match.end()
        while opening < len(code) and code[opening].isspace():
            opening += 1
        if opening >= len(code) or code[opening] != "[":
            errors.append("package lumenplot: hidden facade attribute syntax is malformed")
            continue
        closing = _find_matching_square_bracket(code, opening)
        if closing >= len(code):
            errors.append("package lumenplot: hidden facade attribute is not closed")
            continue
        spans.append((match.start(), closing + 1))
    return spans


def _hidden_attributes_before(
    code: str,
    spans: list[tuple[int, int]],
    item_start: int,
) -> str:
    selected: list[tuple[int, int]] = []
    cursor = item_start
    for attribute_start, attribute_end in reversed(spans):
        if attribute_end > cursor:
            continue
        if code[attribute_end:cursor].strip():
            break
        selected.append((attribute_start, attribute_end))
        cursor = attribute_start
    return "".join(code[start:end] for start, end in reversed(selected))


@dataclass(frozen=True)
class _HiddenRustToken:
    text: str
    start: int
    end: int


_HIDDEN_RUST_OPENERS = {"{", "(", "["}
_HIDDEN_RUST_CLOSERS = {")": "(", "]": "[", "}": "{"}
_HIDDEN_RUST_MULTI_PUNCTUATION = (
    "..=",
    "::",
    "=>",
    "->",
    "==",
    "!=",
    "<=",
    ">=",
    "&&",
    "||",
    "<<",
    ">>",
)


def _hidden_identifier_end(code: str, start: int) -> int | None:
    if code.startswith("r#", start):
        identifier_start = start + 2
        if identifier_start >= len(code) or not (
            code[identifier_start].isalpha() or code[identifier_start] == "_"
        ):
            return None
        position = identifier_start + 1
    elif code[start].isalpha() or code[start] == "_":
        position = start + 1
    else:
        return None
    while position < len(code) and (code[position].isalnum() or code[position] == "_"):
        position += 1
    return position


def _hidden_rust_tokens(
    code: str,
    errors: list[str],
    delimiter_error: str,
) -> tuple[list[_HiddenRustToken], dict[int, int], list[int], bool]:
    """Tokenize stripped Rust and return delimiter/scope evidence."""

    tokens: list[_HiddenRustToken] = []
    pairs: dict[int, int] = {}
    curly_depths: list[int] = []
    stack: list[tuple[str, int]] = []
    curly_depth = 0
    malformed = False
    position = 0
    while position < len(code):
        character = code[position]
        if character.isspace():
            position += 1
            continue

        identifier_end = _hidden_identifier_end(code, position)
        if identifier_end is not None:
            token = _HiddenRustToken(code[position:identifier_end], position, identifier_end)
            position = identifier_end
        elif character.isdigit():
            end = position + 1
            while end < len(code) and (code[end].isalnum() or code[end] in "_."):
                end += 1
            token = _HiddenRustToken(code[position:end], position, end)
            position = end
        else:
            punctuation = next(
                (
                    candidate
                    for candidate in _HIDDEN_RUST_MULTI_PUNCTUATION
                    if code.startswith(candidate, position)
                ),
                None,
            )
            if punctuation is None:
                punctuation = character
            token = _HiddenRustToken(punctuation, position, position + len(punctuation))
            position += len(punctuation)

        token_index = len(tokens)
        tokens.append(token)
        curly_depths.append(curly_depth)
        if token.text in _HIDDEN_RUST_OPENERS:
            stack.append((token.text, token_index))
            if token.text == "{":
                curly_depth += 1
            continue
        if token.text not in _HIDDEN_RUST_CLOSERS:
            continue

        expected_opening = _HIDDEN_RUST_CLOSERS[token.text]
        if not stack or stack[-1][0] != expected_opening:
            malformed = True
            continue
        opening, opening_index = stack.pop()
        pairs[opening_index] = token_index
        pairs[token_index] = opening_index
        if opening == "{":
            curly_depth -= 1

    if stack:
        malformed = True
    if malformed and delimiter_error not in errors:
        errors.append(delimiter_error)
    return tokens, pairs, curly_depths, not malformed


def _hidden_item_body(
    tokens: list[_HiddenRustToken],
    pairs: dict[int, int],
    curly_depths: list[int],
    start: int,
    base_depth: int,
) -> tuple[int, int] | None:
    """Find an item body at the item's own brace depth, if it has one."""

    nested_delimiters = 0
    for index in range(start + 1, len(tokens)):
        token = tokens[index].text
        depth = curly_depths[index]
        if depth < base_depth:
            return None
        if token in {"(", "["}:
            nested_delimiters += 1
            continue
        if token in {")", "]"}:
            nested_delimiters = max(0, nested_delimiters - 1)
            continue
        if token == "{" and depth == base_depth and nested_delimiters == 0:
            closing = pairs.get(index)
            return None if closing is None else (index, closing)
        if token == ";" and depth == base_depth and nested_delimiters == 0:
            return None
    return None


def _hidden_normalize_impl_header(tokens: list[_HiddenRustToken]) -> str:
    normalized = " ".join(token.text for token in tokens)
    return re.sub(r"\s*::\s*", "::", normalized)


def _hidden_is_identifier(token: str) -> bool:
    return bool(re.fullmatch(r"(?:r#[A-Za-z_]\w*|[A-Za-z_]\w*)", token))


def _hidden_inside_function_body(
    token_index: int,
    function_bodies: set[tuple[int, int]],
) -> bool:
    return any(opening < token_index < closing for opening, closing in function_bodies)


def _check_hidden_scope_expansions(
    tokens: list[_HiddenRustToken],
    function_bodies: set[tuple[int, int]],
    test_modules: set[tuple[int, int]],
    test_module_indices: set[int],
    errors: list[str],
) -> None:
    """Reject module/item expansion that the lexical checker cannot audit."""

    for index, token in enumerate(tokens):
        if index in test_module_indices or _hidden_inside_function_body(index, test_modules):
            continue
        if token.text == "mod" and index + 2 < len(tokens):
            if _hidden_is_identifier(tokens[index + 1].text) and tokens[index + 2].text in {"{", ";"}:
                errors.append("package lumenplot: hidden facade nested module declarations are not allowed")

        if token.text == "macro_rules" and index + 1 < len(tokens):
            if tokens[index + 1].text == "!":
                errors.append("package lumenplot: hidden facade macro_rules definitions are not allowed")

        if token.text != "!" or index + 1 >= len(tokens):
            continue
        if tokens[index + 1].text not in _HIDDEN_RUST_OPENERS:
            continue
        if index == 0 or not _hidden_is_identifier(tokens[index - 1].text):
            continue
        if not _hidden_inside_function_body(index, function_bodies):
            errors.append("package lumenplot: hidden facade module-scope macro invocation is not allowed")


def _hidden_public_item_error(errors: list[str]) -> None:
    message = "package lumenplot: hidden facade public item is not allowlisted"
    if message not in errors:
        errors.append(message)


def _hidden_attribute_error(errors: list[str]) -> None:
    message = "package lumenplot: hidden facade attributes are not allowed"
    if message not in errors:
        errors.append(message)


def _hidden_identifier_value(token: str) -> str:
    return token[2:] if token.startswith("r#") else token


def _hidden_attribute_start(
    code: str,
    spans: list[tuple[int, int]],
    item_start: int,
) -> int:
    cursor = item_start
    start = item_start
    for attribute_start, attribute_end in reversed(spans):
        if attribute_end > cursor:
            continue
        if code[attribute_end:cursor].strip():
            break
        start = attribute_start
        cursor = attribute_start
    return start


def _hidden_all_delimiter_depths(tokens: list[_HiddenRustToken]) -> list[int]:
    depths: list[int] = []
    depth = 0
    for token in tokens:
        depths.append(depth)
        if token.text in _HIDDEN_RUST_OPENERS:
            depth += 1
        elif token.text in _HIDDEN_RUST_CLOSERS:
            depth -= 1
    return depths


def _hidden_root_macro_scans(
    tokens: list[_HiddenRustToken],
    delimiter_depths: list[int],
    errors: list[str],
) -> None:
    """Reject root macro expansion that could change the audited inventory."""

    for index, token in enumerate(tokens):
        if delimiter_depths[index] != 0:
            continue
        if token.text == "macro_rules" and index + 1 < len(tokens):
            if tokens[index + 1].text == "!":
                errors.append(
                    "package lumenplot: crate-root macro_rules definition is not allowed"
                )
        if token.text != "!" or index == 0 or index + 1 >= len(tokens):
            continue
        if tokens[index + 1].text not in _HIDDEN_RUST_OPENERS:
            continue
        if not _hidden_is_identifier(tokens[index - 1].text):
            continue
        errors.append("package lumenplot: crate-root macro invocation is not allowed")


def _hidden_root_pub_use_statements(
    code: str,
    tokens: list[_HiddenRustToken],
    delimiter_depths: list[int],
) -> list[str]:
    statements: list[str] = []
    for index, token in enumerate(tokens):
        if token.text != "pub" or delimiter_depths[index] != 0:
            continue
        if index + 1 >= len(tokens) or tokens[index + 1].text != "use":
            continue
        end = None
        for candidate in range(index + 2, len(tokens)):
            if tokens[candidate].text == ";" and delimiter_depths[candidate] == 0:
                end = candidate
                break
        if end is None:
            statements.append(code[token.start :].strip())
        else:
            statements.append(code[token.start : tokens[end].end].strip())
    return statements


def _hidden_root_private_modules(
    tokens: list[_HiddenRustToken],
    delimiter_depths: list[int],
) -> list[str]:
    names: list[str] = []
    for index, token in enumerate(tokens):
        if token.text != "mod" or delimiter_depths[index] != 0:
            continue
        if index + 2 >= len(tokens) or not _hidden_is_identifier(tokens[index + 1].text):
            continue
        if tokens[index + 2].text == ";":
            names.append(_hidden_identifier_value(tokens[index + 1].text))
    return names


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


@dataclass(frozen=True)
class _FacadeImplRecord:
    index: int
    opening: int
    closing: int
    kind: str
    target: str
    trait: str | None


def _facade_is_conditional(attributes: str) -> bool:
    return re.search(r"#\[\s*(?:cfg|cfg_attr)\b", attributes) is not None


def _facade_is_test_only(attributes: str) -> bool:
    return re.search(r"#\[\s*cfg\s*\(\s*test\s*\)\s*\]", attributes) is not None


def _facade_attribute_lines(attributes: str) -> list[str]:
    return [" ".join(line.split()) for line in attributes.splitlines() if line.strip()]


def _facade_has_unallowlisted_attributes(attributes: str, allowed: set[str]) -> bool:
    return any(line not in allowed for line in _facade_attribute_lines(attributes))


def _facade_strip_leading_generics(text: str) -> str:
    text = text.strip()
    if not text.startswith("<"):
        return text
    depth = 0
    for index, character in enumerate(text):
        if character == "<":
            depth += 1
        elif character == ">":
            depth -= 1
            if depth == 0:
                return text[index + 1 :].strip()
    return text


def _facade_path_tail(text: str) -> str:
    text = text.split("<", 1)[0].strip()
    identifiers = re.findall(r"(?:r#[A-Za-z_]\w*|[A-Za-z_]\w*)", text)
    return _hidden_identifier_value(identifiers[-1]) if identifiers else ""


def _facade_impl_records(
    tokens: list[_HiddenRustToken],
    pairs: dict[int, int],
    curly_depths: list[int],
) -> list[_FacadeImplRecord]:
    records: list[_FacadeImplRecord] = []
    all_depths = _hidden_all_delimiter_depths(tokens)
    for index, token in enumerate(tokens):
        if token.text != "impl":
            continue
        body = _hidden_item_body(tokens, pairs, curly_depths, index, curly_depths[index])
        if body is None:
            continue
        opening, closing = body
        header_tokens = tokens[index + 1 : opening]
        header = _hidden_normalize_impl_header(header_tokens)
        for_index = next(
            (
                candidate
                for candidate in range(index + 1, opening)
                if tokens[candidate].text == "for"
                and all_depths[candidate] == all_depths[index]
            ),
            None,
        )
        if for_index is not None:
            trait_header = _hidden_normalize_impl_header(tokens[index + 1 : for_index])
            target_header = _hidden_normalize_impl_header(tokens[for_index + 1 : opening])
            trait = _facade_path_tail(_facade_strip_leading_generics(trait_header))
            target = _facade_path_tail(target_header)
            records.append(_FacadeImplRecord(index, opening, closing, "trait", target, trait))
        else:
            target = _facade_path_tail(_facade_strip_leading_generics(header))
            records.append(_FacadeImplRecord(index, opening, closing, "inherent", target, None))
    return records


def _facade_type_body(
    tokens: list[_HiddenRustToken],
    pairs: dict[int, int],
    curly_depths: list[int],
    name_index: int,
) -> tuple[str, int, int] | None:
    base_depth = curly_depths[name_index]
    for index in range(name_index + 1, len(tokens)):
        if curly_depths[index] < base_depth:
            return None
        if curly_depths[index] != base_depth:
            continue
        if tokens[index].text in {"{", "("}:
            closing = pairs.get(index)
            if closing is None:
                return None
            return tokens[index].text, index, closing
        if tokens[index].text == ";":
            return None
    return None


def _facade_public_field(
    tokens: list[_HiddenRustToken],
    all_depths: list[int],
    opening: int,
    closing: int,
) -> bool:
    body_depth = all_depths[opening] + 1
    for index in range(opening + 1, closing):
        if all_depths[index] != body_depth or tokens[index].text != "pub":
            continue
        next_token = tokens[index + 1].text if index + 1 < closing else ""
        if next_token != "(":
            return True
    return False


def _facade_enum_variants(
    tokens: list[_HiddenRustToken],
    all_depths: list[int],
    opening: int,
    closing: int,
) -> set[str]:
    body_depth = all_depths[opening] + 1
    return {
        _hidden_identifier_value(token.text)
        for index, token in enumerate(tokens[opening + 1 : closing], opening + 1)
        if all_depths[index] == body_depth
        and _hidden_is_identifier(token.text)
        and token.text[0].isupper()
    }


def _facade_public_associated_items(
    code: str,
    tokens: list[_HiddenRustToken],
    pairs: dict[int, int],
    curly_depths: list[int],
    all_depths: list[int],
    opening: int,
    closing: int,
    attribute_spans: list[tuple[int, int]],
    errors: list[str],
) -> list[tuple[str, str, int, str, int | None]]:
    """Return externally visible associated items at the impl's direct scope."""

    items: list[tuple[str, str, int, str, int | None]] = []
    body_depth = all_depths[opening] + 1
    index = opening + 1
    while index < closing:
        if all_depths[index] != body_depth or tokens[index].text != "pub":
            index += 1
            continue
        next_index = index + 1
        next_token = tokens[next_index].text if next_index < closing else ""
        if next_token == "(":
            index += 1
            continue
        while next_token in {"async", "unsafe", "extern"} and next_index + 1 < closing:
            next_index += 1
            next_token = tokens[next_index].text
        if next_token not in {"fn", "const", "type"}:
            index += 1
            continue
        name_index = next_index + 1
        if name_index >= closing or not _hidden_is_identifier(tokens[name_index].text):
            errors.append("package lumenplot: malformed public associated item")
            index += 1
            continue
        kind = next_token
        name = _hidden_identifier_value(tokens[name_index].text)
        attributes = _hidden_attributes_before(code, attribute_spans, tokens[index].start)
        if _facade_is_conditional(attributes):
            errors.append(
                f"package lumenplot: conditional public associated {kind} {name!r} is not allowed"
            )
        body = _hidden_item_body(tokens, pairs, curly_depths, next_index, curly_depths[next_index])
        body_opening = None if body is None else body[0]
        items.append((kind, name, index, attributes, body_opening))
        index = name_index + 1
    return items


def _facade_scope_ranges(
    code: str,
    tokens: list[_HiddenRustToken],
    pairs: dict[int, int],
    curly_depths: list[int],
    attribute_spans: list[tuple[int, int]],
) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    function_bodies: set[tuple[int, int]] = set()
    test_modules: set[tuple[int, int]] = set()
    for index, token in enumerate(tokens):
        if token.text == "fn":
            body = _hidden_item_body(tokens, pairs, curly_depths, index, curly_depths[index])
            if body is not None:
                function_bodies.add(body)
        if token.text != "mod":
            continue
        body = _hidden_item_body(tokens, pairs, curly_depths, index, curly_depths[index])
        if body is None:
            continue
        attributes = _hidden_attributes_before(code, attribute_spans, token.start)
        if _facade_is_test_only(attributes):
            test_modules.add(body)
    return function_bodies, test_modules


def _facade_test_module_indices(
    code: str,
    tokens: list[_HiddenRustToken],
    pairs: dict[int, int],
    curly_depths: list[int],
    attribute_spans: list[tuple[int, int]],
) -> set[int]:
    indices: set[int] = set()
    for index, token in enumerate(tokens):
        if token.text != "mod":
            continue
        attributes = _hidden_attributes_before(code, attribute_spans, token.start)
        if not _facade_is_test_only(attributes):
            continue
        indices.add(index)
    return indices


def _facade_scan_module_attributes(
    code: str,
    tokens: list[_HiddenRustToken],
    curly_depths: list[int],
    attribute_spans: list[tuple[int, int]],
    errors: list[str],
) -> None:
    for index, token in enumerate(tokens):
        if token.text != "mod":
            continue
        attributes = _hidden_attributes_before(code, attribute_spans, token.start)
        if re.search(r"#\[\s*path\b", attributes):
            errors.append("package lumenplot: facade module path redirection is not allowed")
        if curly_depths[index] == 0 and _facade_is_conditional(attributes):
            name = (
                _hidden_identifier_value(tokens[index + 1].text)
                if index + 1 < len(tokens) and _hidden_is_identifier(tokens[index + 1].text)
                else "<unknown>"
            )
            if name in {"error", "view", "series", "scene", "__private"}:
                errors.append(f"package lumenplot: required module {name!r} is conditional")


def _facade_scan_item_macros(
    code: str,
    tokens: list[_HiddenRustToken],
    pairs: dict[int, int],
    curly_depths: list[int],
    attribute_spans: list[tuple[int, int]],
    errors: list[str],
) -> None:
    function_bodies, test_modules = _facade_scope_ranges(
        code, tokens, pairs, curly_depths, attribute_spans
    )

    def in_test_module(index: int) -> bool:
        return _hidden_inside_function_body(index, test_modules)

    for index, token in enumerate(tokens):
        if in_test_module(index) or _hidden_inside_function_body(index, function_bodies):
            continue
        if token.text == "macro_rules" and index + 1 < len(tokens):
            if tokens[index + 1].text == "!":
                attributes = _hidden_attributes_before(code, attribute_spans, token.start)
                if not _facade_is_test_only(attributes):
                    errors.append("package lumenplot: facade production macro_rules definition is not allowed")
                continue
        if token.text != "!" or index == 0 or index + 1 >= len(tokens):
            continue
        if tokens[index + 1].text not in _HIDDEN_RUST_OPENERS:
            continue
        if not _hidden_is_identifier(tokens[index - 1].text):
            continue
        errors.append("package lumenplot: facade production macro invocation is not allowed")


def _check_facade_public_surface(
    sources: dict[str, str],
    errors: list[str],
    hidden_present: bool = False,
) -> None:
    token_sources: dict[
        str,
        tuple[
            str,
            list[_HiddenRustToken],
            dict[int, int],
            list[int],
            list[int],
            list[tuple[int, int]],
            set[tuple[int, int]],
        ],
    ] = {}
    declarations: list[tuple[str, str, str, str, list[_HiddenRustToken], dict[int, int], list[int], list[int], int, int, int]] = []

    for relative, code in sources.items():
        attribute_spans = _hidden_attribute_spans(code, errors)
        tokens, pairs, curly_depths, well_formed = _hidden_rust_tokens(
            code,
            errors,
            "package lumenplot: Rust delimiters are malformed",
        )
        if not well_formed:
            continue
        all_depths = _hidden_all_delimiter_depths(tokens)
        _, test_modules = _facade_scope_ranges(
            code, tokens, pairs, curly_depths, attribute_spans
        )
        token_sources[relative] = (
            code,
            tokens,
            pairs,
            curly_depths,
            all_depths,
            attribute_spans,
            test_modules,
        )
        _facade_scan_module_attributes(code, tokens, curly_depths, attribute_spans, errors)
        _facade_scan_item_macros(code, tokens, pairs, curly_depths, attribute_spans, errors)
        expected_source_types = FACADE_SOURCE_TYPES.get(relative, set())
        for index, token in enumerate(tokens):
            if token.text != "pub" or curly_depths[index] != 0:
                continue
            if index + 2 >= len(tokens) or tokens[index + 1].text not in {"struct", "enum"}:
                continue
            name_token = tokens[index + 2]
            if not _hidden_is_identifier(name_token.text):
                errors.append("package lumenplot: malformed public type declaration")
                continue
            name = _hidden_identifier_value(name_token.text)
            if name not in expected_source_types:
                continue
            body = _facade_type_body(tokens, pairs, curly_depths, index + 2)
            body_kind = ""
            body_opening = body_closing = None
            if body is not None:
                body_kind, body_opening, body_closing = body
            attributes = _hidden_attributes_before(code, attribute_spans, token.start)
            declarations.append(
                (
                    relative,
                    tokens[index + 1].text,
                    name,
                    attributes,
                    tokens,
                    pairs,
                    curly_depths,
                    all_depths,
                    index,
                    body_opening if body_opening is not None else -1,
                    body_closing if body_closing is not None else -1,
                )
            )

    declared_names = [record[2] for record in declarations]
    declared_types = set(declared_names)
    missing = sorted(FACADE_TYPES - declared_types)
    if missing:
        errors.append(
            "package lumenplot: facade type inventory mismatch (missing " + ",".join(missing) + ")"
        )
    duplicates = sorted(name for name in set(declared_names) if declared_names.count(name) > 1)
    if duplicates:
        errors.append("package lumenplot: facade type is declared more than once " + ",".join(duplicates))

    for relative, kind, name, attributes, tokens, pairs, curly_depths, all_depths, index, opening, closing in declarations:
        if _facade_is_conditional(attributes):
            errors.append(f"package lumenplot: facade type {name!r} is conditional")
        non_exhaustive = re.search(r"#\[\s*non_exhaustive\s*\]", attributes) is not None
        if name in FACADE_NON_EXHAUSTIVE and not non_exhaustive:
            errors.append(f"package lumenplot: facade enum {name!r} must remain non-exhaustive")
        if name not in FACADE_NON_EXHAUSTIVE and non_exhaustive:
            errors.append(f"package lumenplot: facade type {name!r} is unexpectedly non-exhaustive")
        actual_derives = _facade_derive_traits(attributes)
        expected_derives = FACADE_DERIVES.get(name, set())
        if actual_derives != expected_derives:
            errors.append(f"package lumenplot: trait inventory mismatch for {name!r}")
        allowed_attributes: set[str] = set()
        if name in FACADE_NON_EXHAUSTIVE:
            allowed_attributes.add("#[non_exhaustive]")
        if name in FACADE_DERIVE_ATTRIBUTES:
            allowed_attributes.add(FACADE_DERIVE_ATTRIBUTES[name])
        if _facade_has_unallowlisted_attributes(attributes, allowed_attributes):
            errors.append(f"package lumenplot: facade type {name!r} has unallowlisted attributes")
        if opening >= 0 and _facade_public_field(tokens, all_depths, opening, closing):
            errors.append(f"package lumenplot: facade type {name!r} exposes a public field")
        if kind == "enum" and opening >= 0:
            expected_variants = FACADE_ENUM_VARIANTS.get(name, set())
            if _facade_enum_variants(tokens, all_depths, opening, closing) != expected_variants:
                errors.append(f"package lumenplot: facade enum {name!r} variant inventory mismatch")

    method_inventory: dict[str, set[str]] = {}
    method_counts: dict[tuple[str, str], int] = {}
    trait_inventory: set[tuple[str, str]] = set()
    protected_hidden_types = HIDDEN_FACADE_TYPES if hidden_present else set()
    for relative, source in token_sources.items():
        code, tokens, pairs, curly_depths, all_depths, attribute_spans, test_modules = source
        for record in _facade_impl_records(tokens, pairs, curly_depths):
            target = record.target
            if target not in FACADE_TYPES and target not in protected_hidden_types:
                continue
            if _hidden_inside_function_body(record.index, test_modules):
                continue
            attributes = _hidden_attributes_before(code, attribute_spans, tokens[record.index].start)
            if _facade_is_conditional(attributes):
                errors.append(f"package lumenplot: conditional impl for {target!r} is not allowed")
            if attributes:
                errors.append(f"package lumenplot: facade impl for {target!r} has unallowlisted attributes")
            if target in protected_hidden_types:
                errors.append(f"package lumenplot: hidden facade implementation for {target!r} is misplaced")
                continue
            if record.kind == "trait":
                key = (target, record.trait or "")
                if key not in FACADE_TRAIT_IMPLS:
                    errors.append(
                        f"package lumenplot: public trait implementation {record.trait!r} for {target!r} is not allowed"
                    )
                elif key in trait_inventory:
                    errors.append(
                        f"package lumenplot: public trait implementation {record.trait!r} for {target!r} is duplicated"
                    )
                trait_inventory.add(key)
                continue
            items = _facade_public_associated_items(
                code,
                tokens,
                pairs,
                curly_depths,
                all_depths,
                record.opening,
                record.closing,
                attribute_spans,
                errors,
            )
            for kind, name, item_index, attributes, body_opening in items:
                if attributes:
                    errors.append(
                        f"package lumenplot: public associated {kind} {name!r} on {target!r} has unallowlisted attributes"
                    )
                if kind != "fn":
                    errors.append(
                        f"package lumenplot: public associated {kind} {name!r} on {target!r} is not allowed"
                    )
                    continue
                method_inventory.setdefault(target, set()).add(name)
                method_counts[(target, name)] = method_counts.get((target, name), 0) + 1
                if name not in FACADE_METHODS.get(target, set()):
                    errors.append(f"package lumenplot: public method {name!r} on {target!r} is not allowed")
                if body_opening is None:
                    signature = code[tokens[item_index].start :]
                else:
                    signature = code[tokens[item_index].start : tokens[body_opening].start]
                for raw_token in FACADE_RAW_TOKENS:
                    if re.search(_facade_token_pattern(raw_token), signature):
                        errors.append(
                            f"package lumenplot: public method {name!r} leaks an internal type"
                        )
                        break

    for type_name, expected_methods in FACADE_METHODS.items():
        actual_methods = method_inventory.get(type_name, set())
        if actual_methods != expected_methods:
            errors.append(f"package lumenplot: public method inventory mismatch for {type_name!r}")
    for (target, method), count in method_counts.items():
        if count > 1:
            errors.append(f"package lumenplot: public method {method!r} on {target!r} is duplicated")
    if trait_inventory != FACADE_TRAIT_IMPLS:
        errors.append("package lumenplot: public trait implementation inventory mismatch")


def _extract_hidden_facade_module(
    root_code: str,
    errors: list[str],
) -> tuple[str | None, bool, str]:
    attribute_spans = _hidden_attribute_spans(root_code, errors)
    tokens, pairs, _, well_formed = _hidden_rust_tokens(
        root_code,
        errors,
        "package lumenplot: Rust delimiters are malformed",
    )
    if not well_formed:
        return None, False, root_code
    delimiter_depths = _hidden_all_delimiter_depths(tokens)

    declarations: list[int] = []
    private_references: list[int] = []
    for index, token in enumerate(tokens):
        if _hidden_identifier_value(token.text) != "__private":
            continue
        private_references.append(index)
        if index > 0 and tokens[index - 1].text == "mod":
            declarations.append(index - 1)

    if not declarations:
        if private_references:
            errors.append("package lumenplot: hidden facade module declaration is malformed")
        return None, False, root_code
    if len(declarations) != 1 or len(private_references) != 1:
        errors.append("package lumenplot: hidden facade module must be declared exactly once")
        return None, False, root_code

    module_index = declarations[0]
    name_index = module_index + 1
    if delimiter_depths[module_index] != 0:
        errors.append("package lumenplot: hidden facade module declaration must be at crate root")
        return None, False, root_code
    if module_index == 0 or tokens[module_index - 1].text != "pub":
        errors.append("package lumenplot: hidden facade module declaration is malformed")
        return None, False, root_code

    attributes = _hidden_attributes_before(
        root_code,
        attribute_spans,
        tokens[module_index - 1].start,
    )
    if _facade_is_conditional(attributes):
        errors.append("package lumenplot: hidden facade module is conditional")
    if re.search(r"#\[\s*path\b", attributes):
        errors.append("package lumenplot: hidden facade module path redirection is not allowed")
    attribute_lines = [line.strip() for line in attributes.splitlines() if line.strip()]
    if attribute_lines != ["#[doc(hidden)]"]:
        errors.append("package lumenplot: hidden facade module must be doc-hidden")
    if len(attribute_lines) >= 2 and attribute_lines[-2].startswith("#"):
        errors.append("package lumenplot: hidden facade module has an unexpected attribute")

    body_index = name_index + 1
    if body_index >= len(tokens):
        errors.append("package lumenplot: hidden facade module declaration is malformed")
        return None, False, root_code
    if tokens[body_index].text == ";":
        errors.append("package lumenplot: external hidden facade module is not allowed")
        item_start = _hidden_attribute_start(
            root_code,
            attribute_spans,
            tokens[module_index - 1].start,
        )
        return None, True, root_code[:item_start] + root_code[tokens[body_index].end :]
    if tokens[body_index].text != "{":
        errors.append("package lumenplot: hidden facade module declaration is malformed")
        return None, False, root_code

    opening = body_index
    closing = pairs.get(opening)
    if closing is None:
        errors.append("package lumenplot: hidden facade module body is not closed")
        return None, False, root_code
    body = root_code[tokens[opening].end : tokens[closing].start]
    item_start = _hidden_attribute_start(
        root_code,
        attribute_spans,
        tokens[module_index - 1].start,
    )
    root_without_module = root_code[:item_start] + root_code[tokens[closing].end :]
    return body, False, root_without_module


def _check_hidden_public_signature(
    signature: str,
    expected_signature: str,
    description: str,
    errors: list[str],
) -> None:
    # Rustfmt may wrap long constructors; the normalized comparison below keeps
    # the signature exact without making whitespace part of the contract.
    if re.search(r"\bfn[ \t]+\w+[ \t]*<", signature) or re.search(r"\bwhere\b", signature):
        errors.append(
            f"package lumenplot: hidden facade {description} has forbidden generic parameters or a where clause"
        )
    if _normalize_bridge_signature(signature) != _normalize_bridge_signature(expected_signature):
        errors.append(f"package lumenplot: hidden facade {description} has an unexpected signature")


def _check_hidden_facade(code: str, errors: list[str]) -> None:
    attribute_spans = _hidden_attribute_spans(code, errors)

    tokens, pairs, curly_depths, well_formed = _hidden_rust_tokens(
        code,
        errors,
        "package lumenplot: hidden facade delimiters are malformed",
    )
    if not well_formed:
        return

    function_bodies, test_modules = _facade_scope_ranges(
        code, tokens, pairs, curly_depths, attribute_spans
    )
    test_module_indices = _facade_test_module_indices(
        code, tokens, pairs, curly_depths, attribute_spans
    )
    _check_hidden_scope_expansions(
        tokens, function_bodies, test_modules, test_module_indices, errors
    )

    all_direct_impls: list[tuple[str, int, int]] = []
    direct_impls: list[tuple[str, int, int]] = []
    for index, token in enumerate(tokens):
        if token.text != "impl":
            continue
        if _hidden_inside_function_body(index, test_modules):
            continue
        if curly_depths[index] != 0:
            errors.append("package lumenplot: hidden facade impl declaration is not allowlisted")
            continue
        body = _hidden_item_body(tokens, pairs, curly_depths, index, 0)
        if body is None:
            errors.append("package lumenplot: hidden facade impl declaration is malformed")
            continue
        opening, closing = body
        attributes = _hidden_attributes_before(code, attribute_spans, token.start)
        if attributes:
            _hidden_attribute_error(errors)
            errors.append("package lumenplot: hidden facade impl has unallowlisted attributes")
        header = _hidden_normalize_impl_header(tokens[index + 1 : opening])
        all_direct_impls.append((header, opening, closing))
        if header not in HIDDEN_FACADE_IMPL_HEADERS:
            errors.append("package lumenplot: hidden facade impl declaration is not allowlisted")
        else:
            direct_impls.append((header, opening, closing))

    expected_impl_headers = set(HIDDEN_FACADE_IMPL_HEADERS)
    actual_impl_headers = [header for header, _, _ in all_direct_impls]
    if set(actual_impl_headers) != expected_impl_headers:
        errors.append("package lumenplot: hidden facade impl inventory mismatch")
    duplicate_impls = sorted(
        header for header in set(actual_impl_headers) if actual_impl_headers.count(header) > 1
    )
    if duplicate_impls:
        errors.append(
            "package lumenplot: hidden facade impl is declared more than once "
            + ",".join(duplicate_impls)
        )

    type_declarations: list[tuple[str, str, int | None, int | None, int]] = []
    for index, token in enumerate(tokens):
        if token.text != "pub" or index + 2 >= len(tokens):
            continue
        if tokens[index + 1].text not in {"struct", "enum"}:
            continue
        if curly_depths[index] != 0 or not _hidden_is_identifier(tokens[index + 2].text):
            continue
        name = tokens[index + 2].text
        body: tuple[int, int] | None = None
        if index + 3 < len(tokens) and tokens[index + 3].text == "{":
            opening = index + 3
            closing = pairs.get(opening)
            if closing is not None:
                body = (opening, closing)
        if body is None:
            errors.append(
                f"package lumenplot: hidden facade type {name!r} has an unexpected declaration"
            )
            type_declarations.append((name, tokens[index + 1].text, None, None, index))
            continue
        opening, closing = body
        declaration_gap = code[token.end : tokens[opening].start]
        if "\n" in declaration_gap or "\r" in declaration_gap:
            errors.append(
                f"package lumenplot: hidden facade type {name!r} has an unexpected declaration"
            )
            type_declarations.append((name, tokens[index + 1].text, None, None, index))
            continue
        attributes = _hidden_attributes_before(code, attribute_spans, token.start)
        if attributes:
            _hidden_attribute_error(errors)
            errors.append(f"package lumenplot: hidden facade type {name!r} has unallowlisted attributes")
        if _facade_derive_traits(attributes):
            errors.append(
                f"package lumenplot: hidden facade incidental public traits on {name!r} are not allowed"
            )
        type_declarations.append((name, tokens[index + 1].text, opening, closing, index))

    type_body_owners = [
        (name, opening, closing)
        for name, _, opening, closing, _ in type_declarations
        if opening is not None and closing is not None
    ]

    def type_owner(index: int) -> str | None:
        for name, opening, closing in type_body_owners:
            if opening < index < closing and curly_depths[index] == 1:
                return name
        return None

    def impl_owner(index: int) -> str | None:
        for header, opening, closing in all_direct_impls:
            if opening < index < closing and curly_depths[index] == 1:
                return header
        return None

    free_functions: list[tuple[str, int | None, int | None, int]] = []
    methods_by_impl: dict[str, list[tuple[str, int | None, int | None, int]]] = {}
    for index, token in enumerate(tokens):
        if token.text != "pub":
            continue
        if _hidden_inside_function_body(index, test_modules):
            continue
        attributes = _hidden_attributes_before(code, attribute_spans, token.start)
        if attributes:
            _hidden_attribute_error(errors)
            _hidden_public_item_error(errors)
        line_start = code.rfind("\n", 0, token.start) + 1
        if code[line_start : token.start].strip():
            _hidden_public_item_error(errors)

        next_token = tokens[index + 1].text if index + 1 < len(tokens) else ""
        if next_token in {"struct", "enum"}:
            if any(declaration[-1] == index for declaration in type_declarations):
                continue
            owner = type_owner(index)
            if owner is not None:
                errors.append(f"package lumenplot: hidden facade type {owner!r} exposes a public field")
            else:
                _hidden_public_item_error(errors)
            continue
        if next_token != "fn":
            owner = type_owner(index)
            if owner is not None:
                errors.append(f"package lumenplot: hidden facade type {owner!r} exposes a public field")
            else:
                _hidden_public_item_error(errors)
            continue
        if index + 2 >= len(tokens) or not _hidden_is_identifier(tokens[index + 2].text):
            _hidden_public_item_error(errors)
            continue
        name = tokens[index + 2].text
        owner = None if curly_depths[index] == 0 else impl_owner(index)
        if curly_depths[index] != 0 and owner is None:
            _hidden_public_item_error(errors)
            continue
        body = _hidden_item_body(tokens, pairs, curly_depths, index, curly_depths[index])
        if body is None:
            errors.append(
                f"package lumenplot: hidden facade public function {name!r} is malformed"
            )
            opening = None
            closing = None
        else:
            opening, closing = body
        candidate = (name, opening, closing, index)
        if owner is None:
            free_functions.append(candidate)
        else:
            methods_by_impl.setdefault(owner, []).append(candidate)

    declared_names = [name for name, _, _, _, _ in type_declarations]
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
    for name, kind, _, _, _ in type_declarations:
        if kind != "struct":
            errors.append(f"package lumenplot: hidden facade type {name!r} must be a struct")

    expected_impl_methods = {
        **HIDDEN_FACADE_METHODS,
        "fmt::Debug for BridgeError": set(),
        "fmt::Display for BridgeError": set(),
        "std::error::Error for BridgeError": set(),
    }
    for header, _, _ in direct_impls:
        methods = methods_by_impl.get(header, [])
        method_names = [name for name, _, _, _ in methods]
        expected_methods = expected_impl_methods[header]
        target = header.rsplit(" for ", 1)[-1]
        for method in sorted(set(method_names) - expected_methods):
            errors.append(
                f"package lumenplot: hidden facade public method {method!r} on {target!r} is not allowed"
            )
        duplicate_methods = sorted(
            method for method in set(method_names) if method_names.count(method) > 1
        )
        if duplicate_methods:
            errors.append(
                f"package lumenplot: hidden facade public method is declared more than once on {target!r} "
                + ",".join(duplicate_methods)
            )
        if set(method_names) != expected_methods:
            errors.append(f"package lumenplot: hidden facade public method inventory mismatch for {target!r}")
        for method, opening, _, index in methods:
            expected_signature = HIDDEN_FACADE_SIGNATURES.get((target, method))
            if expected_signature is None or opening is None:
                continue
            signature = code[tokens[index].start : tokens[opening].start].lstrip(" \t\r\n")
            _check_hidden_public_signature(
                signature,
                expected_signature,
                f"public method {method!r} on {target!r}",
                errors,
            )
            for raw_token in HIDDEN_FACADE_RAW_TOKENS:
                if re.search(_facade_token_pattern(raw_token), signature):
                    errors.append(f"package lumenplot: hidden facade method {method!r} leaks an internal type")
                    break

    expected_trait_headers = {
        "fmt::Debug for BridgeError",
        "fmt::Display for BridgeError",
        "std::error::Error for BridgeError",
    }
    actual_trait_headers = {header for header, _, _ in all_direct_impls if " for " in header}
    if actual_trait_headers != expected_trait_headers:
        errors.append("package lumenplot: hidden facade trait inventory mismatch for 'BridgeError'")

    free_names = [name for name, _, _, _ in free_functions]
    if set(free_names) != {"render_line_png"}:
        errors.append("package lumenplot: hidden facade public function inventory mismatch")
    if len(free_names) != 1 or free_names[0] != "render_line_png":
        errors.append("package lumenplot: hidden facade public free function inventory mismatch")
    else:
        _, opening, _, index = free_functions[0]
        if opening is not None:
            signature = code[tokens[index].start : tokens[opening].start].lstrip(" \t\r\n")
            _check_hidden_public_signature(
                signature,
                HIDDEN_FACADE_FREE_SIGNATURE,
                "render_line_png",
                errors,
            )
            for raw_token in HIDDEN_FACADE_RAW_TOKENS:
                if re.search(_facade_token_pattern(raw_token), signature):
                    errors.append("package lumenplot: hidden facade render_line_png leaks an internal type")
                    break


def _check_facade_root(root_code: str, errors: list[str]) -> None:
    attribute_spans = _hidden_attribute_spans(root_code, errors)
    tokens, _, curly_depths, well_formed = _hidden_rust_tokens(
        root_code,
        errors,
        "package lumenplot: Rust delimiters are malformed",
    )
    if not well_formed:
        return

    delimiter_depths = _hidden_all_delimiter_depths(tokens)
    _hidden_root_macro_scans(tokens, delimiter_depths, errors)
    _facade_scan_module_attributes(root_code, tokens, curly_depths, attribute_spans, errors)

    module_names: list[str] = []
    expected_modules = {"error", "view", "series", "scene"}
    for index, token in enumerate(tokens):
        if token.text != "mod" or delimiter_depths[index] != 0:
            continue
        if index + 1 >= len(tokens) or not _hidden_is_identifier(tokens[index + 1].text):
            continue
        name = _hidden_identifier_value(tokens[index + 1].text)
        attributes = _hidden_attributes_before(root_code, attribute_spans, token.start)
        next_token = tokens[index + 2].text if index + 2 < len(tokens) else ""
        if name in expected_modules:
            if next_token != ";":
                errors.append(f"package lumenplot: required module {name!r} must use its canonical source")
            else:
                module_names.append(name)
            if _facade_is_conditional(attributes):
                errors.append(f"package lumenplot: required module {name!r} is conditional")
        elif next_token == ";" and not _facade_is_test_only(attributes):
            errors.append(f"package lumenplot: external facade module {name!r} is not allowed")
    if set(module_names) != expected_modules or len(module_names) != len(set(module_names)):
        errors.append("package lumenplot: private module inventory mismatch")
    if NO_MANGLE_RE.search(root_code):
        errors.append("package lumenplot: exported ABI is not allowed")

    exports: list[tuple[str, tuple[str, ...]]] = []
    invalid_export = False
    for index, token in enumerate(tokens):
        if token.text != "pub" or delimiter_depths[index] != 0:
            continue
        if index + 1 >= len(tokens) or tokens[index + 1].text != "use":
            continue
        end = next(
            (
                candidate
                for candidate in range(index + 2, len(tokens))
                if tokens[candidate].text == ";" and delimiter_depths[candidate] == 0
            ),
            None,
        )
        statement = (
            root_code[token.start : tokens[end].end].strip()
            if end is not None
            else root_code[token.start :].strip()
        )
        attributes = _hidden_attributes_before(root_code, attribute_spans, token.start)
        if _facade_is_conditional(attributes):
            errors.append("package lumenplot: required root export is conditional")
        if attributes:
            errors.append("package lumenplot: root export attributes are not allowlisted")
        normalized = " ".join(statement.split())
        if "lumenplot_engine" in normalized:
            errors.append("package lumenplot: internal re-export is not allowed")
        if re.search(r"\bas\b", normalized):
            errors.append("package lumenplot: export aliases are not allowed")
        match = re.fullmatch(r"pub use ([A-Za-z_]\w*)::\{([^{}]*)\};", normalized)
        if match is None:
            invalid_export = True
            errors.append("package lumenplot: root export path is not allowlisted")
        else:
            module = match.group(1)
            names = tuple(part.strip() for part in match.group(2).split(",") if part.strip())
            if any(not _hidden_is_identifier(name) for name in names):
                errors.append("package lumenplot: root export inventory is not canonical")
            exports.append((module, names))
        for token in FACADE_RAW_TOKENS:
            if re.search(_facade_token_pattern(token), normalized):
                errors.append("package lumenplot: root export leaks an engine or internal type")
                break

    for index, token in enumerate(tokens):
        if token.text != "pub" or delimiter_depths[index] != 0:
            continue
        next_token = tokens[index + 1].text if index + 1 < len(tokens) else ""
        if next_token == "use":
            continue
        if next_token == "mod":
            errors.append("package lumenplot: public module is not allowed")
        else:
            errors.append("package lumenplot: public item is not allowed")

    if invalid_export or tuple(exports) != FACADE_ROOT_EXPORT_GROUPS:
        errors.append("package lumenplot: exact root export inventory mismatch")


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
    if INVALID_RUST_SYNTAX in root_code:
        errors.append("package lumenplot: malformed Rust syntax")
    _, _, _, root_well_formed = _hidden_rust_tokens(
        root_code,
        errors,
        "package lumenplot: Rust delimiters are malformed",
    )
    if not root_well_formed:
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
        if INVALID_RUST_SYNTAX in code:
            errors.append("package lumenplot: malformed Rust syntax")
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
    _check_facade_public_surface(visible_sources, errors, hidden_code is not None)
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


def _phase3a2_workflow_run_blocks(text: str) -> list[str]:
    """Extract YAML ``run: |`` bodies without treating comments as commands."""

    lines = text.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.match(r"^(?P<indent>[ \t]*)run:\s*\|\s*$", line)
        if match is not None:
            base_indent = len(match.group("indent"))
            index += 1
            body: list[str] = []
            while index < len(lines):
                candidate = lines[index]
                if candidate.strip():
                    candidate_indent = len(candidate) - len(candidate.lstrip(" \t"))
                    if candidate_indent <= base_indent:
                        break
                body.append(candidate)
                index += 1
            blocks.append("\n".join(body))
            continue

        inline = re.match(r"^\s*run:\s*(?P<command>[^|>].*)$", line)
        if inline is not None and inline.group("command").strip():
            blocks.append(inline.group("command"))
        index += 1
    return blocks


def _phase3a2_strip_shell_comments(text: str) -> str:
    """Remove shell/YAML comments while preserving quoted command text."""

    cleaned: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            cleaned.append("")
            continue
        quote: str | None = None
        escaped = False
        end = len(line)
        for index, character in enumerate(line):
            if escaped:
                escaped = False
                continue
            if character == "\\" and quote != "'":
                escaped = True
                continue
            if quote is None and character in {"'", '"'}:
                quote = character
                continue
            if quote == character:
                quote = None
                continue
            if character == "#" and quote is None and (
                index == 0 or line[index - 1].isspace()
            ):
                end = index
                break
        cleaned.append(line[:end])
    return "\n".join(cleaned)


def _phase3a2_docker_run_segments(shell_code: str) -> list[str]:
    """Associate each direct Docker invocation with its following script."""

    lines = shell_code.splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^\s*docker\s+run(?:\s|$)", line)
    ]
    return [
        "\n".join(lines[start : starts[position + 1] if position + 1 < len(starts) else len(lines)])
        for position, start in enumerate(starts)
    ]


def _phase3a2_docker_invocation(segment: str) -> str:
    """Return the Docker option header, excluding the embedded shell script."""

    header: list[str] = []
    for line in segment.splitlines():
        header.append(line)
        if re.search(r"(?:^|\s)-c(?:\s|$)", line):
            break
    return "\n".join(header)


def _phase3a2_docker_command_tokens(segment: str) -> list[str]:
    """Tokenize the Docker command before its embedded shell script."""

    invocation = _phase3a2_docker_invocation(segment).replace("\\\n", " ")
    prefix_match = re.match(r"(?s)^\s*(.*?)(?:\s+-c(?:\s|$))", invocation)
    if prefix_match is None:
        return []
    try:
        return shlex.split(prefix_match.group(1), comments=False, posix=True)
    except ValueError:
        return []


def _phase3a2_docker_image_operand(tokens: list[str]) -> str | None:
    """Return the image operand from a tokenized ``docker run`` command."""

    if tokens[:2] != ["docker", "run"]:
        return None
    options_with_values = {
        "--cap-drop",
        "--env",
        "--mount",
        "--name",
        "--network",
        "--platform",
        "--security-opt",
        "--tmpfs",
        "--user",
        "--volume",
        "--workdir",
        "-e",
        "-v",
        "-w",
    }
    index = 2
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            index += 1
            break
        if not token.startswith("-"):
            return token
        if token in options_with_values:
            index += 2
        else:
            index += 1
    return tokens[index] if index < len(tokens) else None


def _phase3a2_docker_option_values(tokens: list[str], option: str) -> list[str]:
    values: list[str] = []
    index = 2
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            break
        if token == option:
            if index + 1 < len(tokens):
                values.append(tokens[index + 1])
            index += 2
            continue
        prefix = option + "="
        if token.startswith(prefix):
            values.append(token[len(prefix) :])
        index += 1
    return values


def _phase3a2_docker_mount_values(tokens: list[str]) -> list[str]:
    mounts: list[str] = []
    index = 2
    while index < len(tokens):
        token = tokens[index]
        if token in {"-v", "--volume", "--mount"}:
            if index + 1 < len(tokens):
                mounts.append(tokens[index + 1])
            index += 2
            continue
        if token.startswith("--mount="):
            mounts.append(token.split("=", 1)[1])
        index += 1
    return mounts


def _phase3a2_mount_matches(
    mount: str,
    source: str,
    destination: str,
    mode: str,
) -> bool:
    if mount == f"{source}:{destination}:{mode}":
        return True
    fields = {
        key: value
        for key, separator, value in (part.partition("=") for part in mount.split(","))
        if separator
    }
    actual_source = fields.get("source", fields.get("src"))
    actual_destination = fields.get("destination", fields.get("dst"))
    if actual_source != source or actual_destination != destination:
        return False
    read_only = "readonly" in mount.split(",") or fields.get("ro") == "true"
    if mode == "ro":
        return read_only
    return not read_only


def _phase3a2_exact_image_assignment(shell_code: str) -> bool:
    assignments = re.findall(
        r"(?m)^\s*IMAGE\s*=\s*(['\"])([^'\"]+)\1\s*$",
        shell_code,
    )
    return len(assignments) == 1 and assignments[0][1] == PHASE3A2_IMAGE


def _phase3a2_reassigned_working_directory(shell_code: str) -> bool:
    return re.search(r"(?m)^\s*PWD\s*=", shell_code) is not None


def _phase3a2_valid_container_user(value: str) -> bool:
    match = re.fullmatch(r"([0-9]+)(?::([0-9]+))?", value)
    if match is None:
        return False
    uid, gid = match.groups()
    return int(uid) > 0 and (gid is None or int(gid) > 0)


def _phase3a2_expected_prefetch_downloads() -> list[str]:
    # The pinned manylinux image ships versioned interpreters only and has no
    # bare `python` on PATH, so every prefetch download names the reviewed
    # CPython 3.11 interpreter explicitly.
    #
    # pip's `--hash` is a requirements-file-only option: no pip release
    # registers it as a CLI flag, so each hash-pinned input is staged through
    # a one-line requirements file and consumed with --require-hashes.  The
    # printf staging lines are asserted separately below; this inventory
    # covers exactly the download commands themselves.  Digests are unchanged.
    interpreter = PHASE3A2_INTERPRETERS["3.11"]
    downloads = [
        f"{interpreter} -m pip download --no-deps --only-binary=:all: --require-hashes "
        "--dest /cache/wheelhouse -r /tmp/wheelhouse-maturin.txt",
    ]
    for version in PHASE3A2_NUMPY_WHEEL_SHA256:
        python_version = version.removeprefix("cp")
        downloads.append(
            f"{interpreter} -m pip download --no-deps --only-binary=:all: --require-hashes "
            "--dest /cache/wheelhouse --platform manylinux_2_28_x86_64 "
            f"--implementation cp --python-version {python_version} "
            f"--abi {version} -r /tmp/wheelhouse-numpy{python_version}.txt"
        )
    downloads.append(
        f"{interpreter} -m pip download --no-deps --dest /cache/wheelhouse auditwheel==6.8.0"
    )
    downloads.append(
        f"{interpreter} -m pip download --no-deps --dest /cache/wheelhouse abi3audit==0.0.26"
    )
    # Transitive tool dependencies, each downloaded unpinned here and then
    # digest-recorded into tool-deps.sha256 (asserted below); the offline
    # build container installs them via a hash-pinned requirements file.
    for package in (
        "packaging==26.3",
        "pyelftools==0.33",
        "abi3info==2025.11.29",
        "kaitaistruct==0.11",
        "pefile==2024.8.26",
        "requests==2.34.2",
        "charset-normalizer==3.5.1",
        "requests-cache==1.3.3",
        "url-normalize==1.4.3",
        "attrs==26.1.0",
        "cattrs==24.1.2",
        "urllib3==2.7.0",
        "certifi==2026.7.22",
        "idna==3.19",
        "six==1.17.0",
        "rich==15.0.0",
        "markdown-it-py==4.2.0",
        "pygments==2.21.0",
        "mdurl==0.1.2",
    ):
        downloads.append(
            f"{interpreter} -m pip download --no-deps --only-binary=:all: "
            f"--dest /cache/wheelhouse {package}"
        )
    # Phase-3B golden-matrix seam: matplotlib 3.11.x and its transitive
    # runtime dependencies follow the same unpinned-then-digest-recorded
    # pattern as the audit-tool wheels above.
    for package in (
        "matplotlib==3.11.1",
        "contourpy==1.3.3",
        "cycler==0.12.1",
        "fonttools==4.63.0",
        "kiwisolver==1.5.0",
        "pillow==12.3.0",
        "pyparsing==3.3.2",
        "python-dateutil==2.9.0.post0",
    ):
        downloads.append(
            f"{interpreter} -m pip download --no-deps --only-binary=:all: "
            f"--dest /cache/wheelhouse {package}"
        )
    return downloads


def _phase3a2_manifest_is_tracked(root: Path) -> bool:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--error-unmatch",
                "--",
                "phase3a2-wheel-evidence.json",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _phase3a2_runtime_cell_segments(
    build_segment: str,
) -> list[tuple[str, str]]:
    lines = build_segment.splitlines()
    starts: list[tuple[str, int]] = []
    for version, interpreter in PHASE3A2_INTERPRETERS.items():
        pattern = re.compile(rf"^\s*{re.escape(interpreter)}\s+-m\s+venv\s+--clear\b")
        starts.extend((version, index) for index, line in enumerate(lines) if pattern.search(line))
    starts.sort(key=lambda item: item[1])
    return [
        (
            version,
            "\n".join(
                lines[start : starts[position + 1][1] if position + 1 < len(starts) else len(lines)]
            ),
        )
        for position, (version, start) in enumerate(starts)
    ]


def _phase3a2_checked_out_revision(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = result.stdout.strip()
    return revision if re.fullmatch(r"[0-9a-f]{40}", revision) else None


def _phase3a2_workspace_version(root: Path) -> str | None:
    try:
        with (root / "Cargo.toml").open("rb") as source:
            manifest = tomllib.load(source)
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return None
    workspace = manifest.get("workspace")
    package = workspace.get("package") if isinstance(workspace, dict) else None
    version = package.get("version") if isinstance(package, dict) else None
    return version if isinstance(version, str) else None


def _phase3a2_workflow_paths(root: Path) -> list[Path]:
    workflow_dir = root / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return []
    return sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")))


def _phase3a2_workflow_candidates(root: Path) -> list[tuple[Path, str]]:
    candidates: list[tuple[Path, str]] = []
    signal = re.compile(r"\b(?:auditwheel|manylinux|maturin|wheel)\b", re.IGNORECASE)
    for path in _phase3a2_workflow_paths(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if signal.search(text):
            candidates.append((path, text))
    return candidates


def _phase3a2_activation_reasons(root: Path) -> list[str]:
    reasons: list[str] = []
    if (root / "pyproject.toml").is_file():
        reasons.append("root pyproject.toml")
    if (root / "python" / "lumenplot_mpl").is_dir():
        reasons.append("python/lumenplot_mpl")
    if _phase3a2_workflow_candidates(root):
        reasons.append("Python wheel workflow")
    evidence_manifest = root / "phase3a2-wheel-evidence.json"
    if evidence_manifest.exists():
        reasons.append("phase3a2-wheel-evidence.json")

    bridge_manifest = root / "crates" / "lumenplot-python" / "Cargo.toml"
    try:
        with bridge_manifest.open("rb") as source:
            manifest = tomllib.load(source)
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        manifest = {}
    dependencies = manifest.get("dependencies", {}) if isinstance(manifest, dict) else {}
    if isinstance(dependencies, dict) and {"pyo3", "numpy"} & set(dependencies):
        reasons.append("Python bridge dependency")
    return reasons


PHASE3A2_PHASE3B_PACKAGE_FILES = frozenset({"backend.py", "__init__.py"})
# While the Phase-3B allowance is active, these are the ONLY matplotlib
# shapes still rejected inside the two phase3b-owned package files; every
# other occurrence (qualified chains such as matplotlib.lines.Line2D,
# rcParams access, docstring prose) is admitted because the backend module
# itself is the adapter. Workstream-manager decision on task t_52f05497.
PHASE3A2_PHASE3B_MATPLOTLIB_FORBIDDEN_SHAPES = (
    re.compile(r"^import matplotlib\.pylot"),
    re.compile(r"^from matplotlib import"),
    re.compile(r"^import matplotlib\.pylot as"),
)


def _phase3b_activation_reason(root: Path) -> str | None:
    """Return why the Phase-3B static allowance activates for *root*, or None."""
    if (root / "python" / "lumenplot_mpl" / "backend.py").is_file():
        return "python/lumenplot_mpl/backend.py"
    if any((root / "tests" / "python").glob("test_phase3b*.py")):
        return "tests/python/test_phase3b*.py"
    return None


def _phase3a2_phase3b_matplotlib_forbidden(source: str) -> bool:
    """Detect pyplot-import regressions in the two phase3b-owned files."""
    return any(
        shape.match(line) is not None
        for line in source.splitlines()
        for shape in PHASE3A2_PHASE3B_MATPLOTLIB_FORBIDDEN_SHAPES
    )


def _phase3a2_phase3b_render_png_outside_allowances(source: str) -> bool:
    """Detect render_png occurrences outside the phase3b-allowed shapes.

    Allowed: ``def render_png(`` definitions, dotted calls of the form
    ``<identifier>.render_png(``, and occurrences inside single-backtick
    doc-reference spans (e.g. ``:meth:`FigureCanvasLumenPlot.render_png`` `).
    """
    for line in source.splitlines():
        without_doc_spans = re.sub(r"`[^`]*`", "", line)
        if re.search(r"\bdef\s+render_png\s*\(", without_doc_spans):
            continue
        if re.search(r"\b[A-Za-z_]\w*\.render_png\s*\(", without_doc_spans):
            continue
        if re.search(r"\brender_png\b", without_doc_spans):
            return True
    return False


def _phase3a2_read_text(path: Path, root: Path, errors: list[str], label: str) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(f"phase3a2: missing {label}")
    except (OSError, UnicodeError):
        errors.append(f"phase3a2: cannot read {_logical_path(path, root)}")
    return None


def _phase3a2_check_pyproject(root: Path, errors: list[str]) -> None:
    path = root / "pyproject.toml"
    try:
        with path.open("rb") as source:
            manifest = tomllib.load(source)
    except FileNotFoundError:
        errors.append("phase3a2: missing root pyproject.toml")
        return
    except (OSError, tomllib.TOMLDecodeError):
        errors.append("phase3a2: invalid root pyproject.toml")
        return
    build_system = manifest.get("build-system")
    if not isinstance(build_system, dict):
        errors.append("phase3a2 pyproject: missing [build-system]")
    else:
        requires = build_system.get("requires")
        if not isinstance(requires, list) or "maturin==1.14.1" not in requires:
            errors.append("phase3a2 pyproject: maturin must be exactly 1.14.1")
        if build_system.get("build-backend") != "maturin":
            errors.append("phase3a2 pyproject: build backend must be maturin")
    project = manifest.get("project")
    if not isinstance(project, dict):
        errors.append("phase3a2 pyproject: missing [project]")
        return
    if project.get("name") != "lumenplot-mpl":
        errors.append("phase3a2 pyproject: project name must be lumenplot-mpl")
    if project.get("requires-python") != ">=3.11,<3.15":
        errors.append("phase3a2 pyproject: Requires-Python must be >=3.11,<3.15")
    dependencies = project.get("dependencies", [])
    if isinstance(dependencies, list) and any("matplotlib" in str(item).lower() for item in dependencies):
        errors.append("phase3a2 pyproject: Matplotlib dependency is forbidden")
    phase3b_active = _phase3b_activation_reason(root) is not None
    lowered_project = str(project).lower()
    if "backend" in lowered_project or "matplotlib" in lowered_project:
        # The Phase-3B entry-point table is the one sanctioned public
        # backend surface; while the allowance is active it must be the
        # ONLY entry-point table and must carry the API-0005 §1 identity
        # exactly. Anything else keeps the historical rejection.
        entry_points_table = project.get("entry-points")
        exact_identity = isinstance(entry_points_table, dict) and set(entry_points_table) == {
            "matplotlib.backend"
        } and entry_points_table["matplotlib.backend"] == {"lumenplot": "lumenplot_mpl.backend"}
        if not (phase3b_active and exact_identity):
            errors.append("phase3a2 pyproject: public backend/Matplotlib surface is forbidden")


def _phase3a2_check_python_package(root: Path, errors: list[str]) -> None:
    package_dir = root / "python" / "lumenplot_mpl"
    if not package_dir.is_dir():
        errors.append("phase3a2: missing Python package directory python/lumenplot_mpl")
        return
    required_files = ("__init__.py", "_native.pyi", "py.typed")
    for relative in required_files:
        if not (package_dir / relative).is_file():
            errors.append(f"phase3a2 Python package: missing {relative}")
    phase3b_active = _phase3b_activation_reason(root) is not None
    for path in sorted(package_dir.rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".pyi"}:
            continue
        source = _phase3a2_read_text(path, root, errors, f"Python source {_logical_path(path, root)}")
        if source is None:
            continue
        lowered = source.lower()
        if "matplotlib" in lowered or re.search(r"\bbackend\b", lowered):
            # Phase-3B: backend.py is the adapter itself and __init__.py
            # hosts it; while the allowance is active only pyplot-import
            # shapes stay forbidden inside those two files.
            if not (
                phase3b_active
                and path.name in PHASE3A2_PHASE3B_PACKAGE_FILES
                and not _phase3a2_phase3b_matplotlib_forbidden(source)
            ):
                errors.append("phase3a2 Python package: Matplotlib/backend surface is forbidden")
        if re.search(r"\brender_png\b", source):
            if not (
                phase3b_active
                and path.name in PHASE3A2_PHASE3B_PACKAGE_FILES
                and not _phase3a2_phase3b_render_png_outside_allowances(source)
            ):
                errors.append("phase3a2 Python package: public render_png is forbidden")
    init_path = package_dir / "__init__.py"
    native_stub = package_dir / "_native.pyi"
    if init_path.is_file():
        init_source = _phase3a2_read_text(init_path, root, errors, "Python package initializer")
        if init_source is not None and "LumenPlotError" not in init_source:
            errors.append("phase3a2 Python package: LumenPlotError is missing")
    if native_stub.is_file():
        stub_source = _phase3a2_read_text(native_stub, root, errors, "native Python stub")
        if stub_source is not None and "render_line_png" not in stub_source:
            errors.append("phase3a2 Python package: render_line_png is missing from _native.pyi")


def _check_python_bridge_source(package_dir: Path, root: Path, errors: list[str]) -> None:
    source_dir = package_dir / "src"
    rust_files = sorted(source_dir.rglob("*.rs")) if source_dir.is_dir() else []
    if not rust_files:
        errors.append("phase3a2 Python bridge: missing Rust source")
        return
    combined: list[str] = []
    for path in rust_files:
        source = _phase3a2_read_text(path, root, errors, f"Rust source {_logical_path(path, root)}")
        if source is not None:
            combined.append(_strip_rust_comments_and_literals(source))
    code = "\n".join(combined)
    for label, pattern in (
        ("unsafe code", re.compile(r"\bunsafe\b")),
        ("serialization or wire code", re.compile(r"\b(?:serde|bincode|postcard|rmp|wire|serialize|deserialize)\b")),
        ("Matplotlib/backend code", re.compile(r"\b(?:matplotlib|backend|wgpu|winit)\b", re.IGNORECASE)),
        ("C ABI export", re.compile(r"#\s*\[\s*(?:no_mangle|export_name)\b|extern\s+\"C\"")),
        ("free-threaded ABI", re.compile(r"\b(?:abi3t|free.threaded|cp\d{3}t)\b", re.IGNORECASE)),
        ("direct engine/export dependency", re.compile(r"\b(?:lumenplot_engine|lumenplot_export)\b")),
    ):
        if pattern.search(code):
            errors.append(f"phase3a2 Python bridge: {label} is forbidden")
    pyfunction_attributes = re.findall(r"#\s*\[\s*pyfunction\b", code)
    pyfunction_names = re.findall(
        r"#\s*\[\s*pyfunction(?:\s*\([^]]*\))?\s*\]\s*"
        r"(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)\b",
        code,
    )
    pymodule_names = re.findall(
        r"#\s*\[\s*pymodule(?:\s*\([^]]*\))?\s*\]\s*"
        r"(?:pub\s+)?fn\s+([A-Za-z_]\w*)\b",
        code,
    )
    registered_names = re.findall(
        r"\bwrap_pyfunction!\s*\(\s*([A-Za-z_]\w*)\s*,",
        code,
    )
    # Exact private native export inventory. The expected set depends on
    # the Phase-3B allowance: without its activation signals the historical
    # single-export rule holds verbatim; with them, the whole-frame seam is
    # required as well (fail-closed in both directions).
    phase3b_active = _phase3b_activation_reason(root) is not None
    expected_exports = (
        ["render_frame_png", "render_line_png"] if phase3b_active else ["render_line_png"]
    )
    if (
        len(pyfunction_attributes) != len(expected_exports)
        or sorted(pyfunction_names) != sorted(expected_exports)
        or pymodule_names != ["_native"]
        or sorted(registered_names) != sorted(expected_exports)
    ):
        errors.append("phase3a2 Python bridge: private native export inventory is not exact")
    if "#[pymodule]" not in code or "render_line_png" not in code:
        errors.append("phase3a2 Python bridge: private pymodule/render_line_png surface is incomplete")


def _phase3a2_check_workflow_actions(text: str, errors: list[str]) -> set[str]:
    uses_pattern = re.compile(
        r"^\s*(?:-\s*)?uses:\s*([^@\s#]+)(?:@([^\s#]+))?(?:\s*#\s*(.*))?$",
        re.MULTILINE,
    )
    repositories: set[str] = set()
    for match in uses_pattern.finditer(text):
        repository, reference, comment = match.groups()
        repositories.add(repository)
        expected = PHASE3A2_ACTION_PINS.get(repository)
        if expected is None:
            errors.append(f"phase3a2 workflow: action {repository!r} is not allowed")
            continue
        expected_sha, release = expected
        if reference is None:
            errors.append(f"phase3a2 workflow: action {repository!r} is not pinned to a full SHA")
        elif reference != expected_sha:
            errors.append(f"phase3a2 workflow: action {repository!r} is not pinned to the reviewed SHA")
        if comment is None or release.lower() not in comment.lower():
            errors.append(f"phase3a2 workflow: action {repository!r} is missing its release comment")
        if repository == "actions/upload-artifact" and "if-no-files-found: error" not in _phase3a2_strip_shell_comments(text):
            errors.append("phase3a2 workflow: upload-artifact requires if-no-files-found: error")
    for required in ("actions/checkout", "dtolnay/rust-toolchain"):
        if required not in repositories:
            errors.append(f"phase3a2 workflow: missing pinned action {required}")
    return repositories


def _phase3a2_check_workflow(root: Path, errors: list[str]) -> set[str]:
    candidates = _phase3a2_workflow_candidates(root)
    if not candidates:
        errors.append("phase3a2: missing Python wheel workflow")
        return set()
    text = "\n".join(content for _, content in candidates)
    workflow_code = _phase3a2_strip_shell_comments(text)
    run_blocks = _phase3a2_workflow_run_blocks(text)
    shell_code = _phase3a2_strip_shell_comments("\n".join(run_blocks))
    docker_runs = _phase3a2_docker_run_segments(shell_code)
    repositories = _phase3a2_check_workflow_actions(text, errors)
    required_fragments = (
        ("pull_request", "pull_request trigger"),
        ("push:", "push trigger"),
        ("main", "main branch trigger"),
        ("contents: read", "read-only contents permission"),
        ("docker pull --platform=linux/amd64", "platform-pinned Docker pull"),
        ("docker image inspect", "image digest inspection"),
        ("--network=bridge", "networked prefetch container"),
        ("--network=none", "offline build/test container"),
        ("--read-only", "read-only container root"),
        ("--user", "non-root container user"),
        ("--cap-drop=ALL", "dropped container capabilities"),
        ("--security-opt=no-new-privileges", "no-new-privileges container"),
        ("--tmpfs /tmp", "temporary container home"),
        ("--tmpfs /tmp:rw,noexec,nosuid,nodev", "noexec temporary home hardening"),
        ("cargo fetch --locked", "locked Cargo prefetch"),
        ("cargo metadata --locked", "locked Cargo metadata"),
        ("--locked", "locked build"),
        ("--offline", "offline build"),
        ("RUSTUP_TOOLCHAIN=1.89.0", "builder Rust toolchain"),
        (PHASE3A2_RUSTUP_INIT_SHA256, "hash-pinned rustup-init bootstrap digest"),
        ("export RUSTUP_HOME=/usr/local/cargo/rustup", "rustup home inside the cargo-home volume"),
        (
            "https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init",
            "pinned rustup-init download endpoint",
        ),
        # The checkfile lists the bare name `rustup-init`, so the guarded
        # subshell must resolve it against the exec-capable /tmp/work staging
        # directory; the workdir is read-only /src.
        ("( cd /tmp/work && sha256sum --check /tmp/rustup-init.sha256 )", "rustup-init digest verification"),
        # curl redirection stages the bootstrap mode 0644; the executable bit
        # must be set before direct execve can start it.
        ("chmod +x /tmp/work/rustup-init", "rustup-init executable-bit provisioning"),
        # /tmp itself stays noexec; the verified ELF bootstrap is executed
        # directly from the exec-mounted work tmpfs instead of being
        # misinterpreted by bash.
        ("/tmp/work/rustup-init -y --no-modify-path --profile minimal --default-toolchain 1.89.0", "pinned rustup provisioning"),
        ("export PATH=/usr/local/cargo/bin:$PATH", "provisioned Cargo bin on PATH"),
        ("rustc --version", "in-container Rust verification"),
        ("cargo --version", "in-container Cargo verification"),
        ("maturin==1.14.1", "hash-pinned maturin version"),
        (PHASE3A2_MATURIN_WHEEL_SHA256, "hash-pinned maturin wheel"),
        ("--interpreter /opt/python/cp311-cp311/bin/python", "CPython 3.11 builder"),
        ("--compatibility manylinux_2_28", "manylinux compatibility check"),
        ("auditwheel show --json", "auditwheel JSON evidence"),
        ('assert "manylinux_2_28" in tag', "manylinux_2_28 tag assertion from auditwheel JSON"),
        ("unzip -t", "ZIP integrity check"),
        ("METADATA", "wheel METADATA check"),
        ("WHEEL", "wheel WHEEL check"),
        ('unzip -p "$WHEEL" \'*/RECORD\'', "wheel RECORD check"),
        ("readelf -d", "ELF dependency check"),
        ("\\(NEEDED\\)", "dynamic dependency section gate"),
        ("unexpected shared library", "unexpected library rejection"),
        ("CycloneDX 1.5", "CycloneDX 1.5 SBOM check"),
        ("sha256sum --check", "pre-matrix wheel hash recheck"),
        ("INPUT_WHEEL_SHA256", "per-cell input wheel hash"),
        ('test "$WHEEL_VERSION" = "$CARGO_VERSION"', "Cargo-to-wheel version comparison"),
        ('test "$INSTALLED_VERSION" = "$CARGO_VERSION"', "Cargo-to-installed version comparison"),
        ("phase3a2-wheel-evidence.json", "evidence manifest check"),
        ("cp311-abi3-manylinux_2_28_x86_64", "exact wheel tag"),
        ("--no-index", "offline pip index"),
        ("--no-cache-dir", "non-cache pip install"),
        ("--only-binary=:all:", "binary-only NumPy install"),
        ("--require-hashes", "hash-required pip install"),
        ("--find-links=/cache/wheelhouse", "local wheelhouse install"),
        (PHASE3A2_IMAGE_CONFIG_DIGEST, "image config digest verification"),
        (":/src:ro", "read-only source mount"),
    )
    for fragment, label in required_fragments:
        if fragment not in workflow_code:
            errors.append(f"phase3a2 workflow: missing {label}")
    if PHASE3A2_IMAGE not in workflow_code:
        errors.append("phase3a2 workflow: builder image must use the exact tag@digest")
    if not _phase3a2_exact_image_assignment(shell_code):
        errors.append("phase3a2 workflow: IMAGE must be assigned the exact reviewed tag@digest")
    if _phase3a2_reassigned_working_directory(shell_code):
        errors.append("phase3a2 workflow: working-directory identity must not be reassigned")
    if re.search(r"manylinux_2_28_x86_64:latest\b", workflow_code):
        errors.append("phase3a2 workflow: floating manylinux latest tag is forbidden")
    forbidden = (
        ("pull_request_target", "pull_request_target is forbidden"),
        ("${{ secrets.", "repository secrets are forbidden"),
        ("packages: write", "package write permission is forbidden"),
        ("--privileged", "privileged containers are forbidden"),
        ("--network=host", "host networking is forbidden"),
        ("--find-interpreter", "interpreter discovery is forbidden"),
        ("auditwheel repair", "auditwheel repair is forbidden"),
        ("abi3t", "free-threaded abi3 is forbidden"),
        (re.compile(r"\bcp\d{3}t(?:[-/]|\b)", re.IGNORECASE), "free-threaded CPython paths are forbidden"),
        ("free-threaded", "free-threaded interpreters are forbidden"),
        ("pypy", "non-CPython interpreters are forbidden"),
        ("graalpy", "non-CPython interpreters are forbidden"),
        ("actions/setup-python", "host setup-python is not the builder"),
        ("maturin-action", "maturin-action is not the builder"),
        ("twine upload", "package upload is forbidden"),
        ("gh release", "release publishing is forbidden"),
        ("cosign", "signing is forbidden"),
        ("sigstore", "signing is forbidden"),
        ("actions/cache", "cross-run cache action is forbidden"),
        ("restore-keys", "cross-run cache keys are forbidden"),
        ("cache-hit", "cross-run cache outputs are forbidden"),
        ('test "$INSTALLED_VERSION" = "$INSTALLED_VERSION"', "self-equality version check is forbidden"),
    )
    for fragment, label in forbidden:
        if (fragment.search(workflow_code) if isinstance(fragment, re.Pattern) else fragment.lower() in workflow_code.lower()):
            errors.append(f"phase3a2 workflow: {label}")
    if len(docker_runs) != 2:
        errors.append("phase3a2 workflow: prefetch and offline containers must be separate")
    if len(docker_runs) >= 2:
        invocations = [_phase3a2_docker_invocation(segment) for segment in docker_runs]
        command_tokens = [_phase3a2_docker_command_tokens(segment) for segment in docker_runs]
        for invocation in invocations:
            for fragment, label in (
                ("--platform=linux/amd64", "platform-pinned Docker run"),
                ("--read-only", "read-only container root"),
                ("--user", "non-root container user"),
                ("--cap-drop=ALL", "dropped container capabilities"),
                ("--security-opt=no-new-privileges", "no-new-privileges container"),
                ("--tmpfs /tmp", "temporary container home"),
                ("--tmpfs /tmp:rw,noexec,nosuid,nodev", "noexec temporary home hardening"),
                (":/src:ro", "read-only source mount"),
                (":/cache/wheelhouse:", "job-local wheelhouse mount"),
            ):
                if fragment not in invocation:
                    errors.append(f"phase3a2 workflow: every container lacks {label}")
        for tokens in command_tokens:
            image_operand = _phase3a2_docker_image_operand(tokens)
            if image_operand not in {PHASE3A2_IMAGE, "$IMAGE"}:
                errors.append("phase3a2 workflow: every container must use the exact builder image operand")
            user_values = _phase3a2_docker_option_values(tokens, "--user")
            if len(user_values) != 1 or not _phase3a2_valid_container_user(user_values[0]):
                errors.append("phase3a2 workflow: every container must use an explicit numeric non-root user")
                if len(user_values) == 1 and (
                    user_values[0].split(":", 1)[0].lower() == "root"
                    or user_values[0].split(":", 1)[0] == "0"
                ):
                    errors.append("phase3a2 workflow: container user must not be root")
        prefetch, build = docker_runs
        prefetch_invocation, build_invocation = invocations
        prefetch_mounts = _phase3a2_docker_mount_values(command_tokens[0])
        build_mounts = _phase3a2_docker_mount_values(command_tokens[1])
        if not any(
            _phase3a2_mount_matches(mount, "$PWD", "/src", "ro")
            for mount in prefetch_mounts
        ) or not any(
            _phase3a2_mount_matches(mount, "$PWD", "/src", "ro")
            for mount in build_mounts
        ):
            errors.append("phase3a2 workflow: every container source mount must bind $PWD to /src read-only")
        if not any(
            _phase3a2_mount_matches(mount, "$PWD/wheelhouse", "/cache/wheelhouse", "rw")
            for mount in prefetch_mounts
        ):
            errors.append("phase3a2 workflow: prefetch wheelhouse must bind $PWD/wheelhouse read-write")
        if not any(
            _phase3a2_mount_matches(mount, "$PWD/wheelhouse", "/cache/wheelhouse", "ro")
            for mount in build_mounts
        ):
            errors.append("phase3a2 workflow: build/runtime wheelhouse must bind $PWD/wheelhouse read-only")
        if "--network=bridge" not in prefetch_invocation:
            errors.append("phase3a2 workflow: prefetch container must use --network=bridge")
        if "--network=none" not in build_invocation:
            errors.append("phase3a2 workflow: offline build/test container must use --network=none")
        if "--network=none" in prefetch_invocation:
            errors.append("phase3a2 workflow: prefetch container must remain networked")
        if "--network=bridge" in build_invocation:
            errors.append("phase3a2 workflow: networked wheel build is forbidden")
        # Docker does not export host job-level environment into containers,
        # so the workflow-level pinned rustup-init digest must be forwarded
        # explicitly to the networked prefetch container that consumes it;
        # the offline build/test container has no bootstrap input to forward.
        if "-e PHASE3A2_RUSTUP_INIT_SHA256" not in prefetch_invocation:
            errors.append("phase3a2 workflow: prefetch container must forward the pinned rustup-init digest")
        if "-e PHASE3A2_RUSTUP_INIT_SHA256" in build_invocation:
            errors.append("phase3a2 workflow: offline build/test container must not forward the rustup-init digest")
        if ":/cache/wheelhouse:ro" not in build_invocation:
            errors.append("phase3a2 workflow: build/runtime wheelhouse must be read-only")
        if ":/cache/wheelhouse:rw" not in prefetch_invocation:
            errors.append("phase3a2 workflow: prefetch wheelhouse must be writable")
        # /tmp itself stays noexec; only the nested exec-capable work tmpfs may
        # run binaries, and the prefetch container must stage the verified
        # rustup-init there rather than executing from the noexec /tmp.
        prefetch_work_tmpfs = [
            value
            for value in _phase3a2_docker_option_values(command_tokens[0], "--tmpfs")
            if value.startswith("/tmp/work:")
        ]
        build_work_tmpfs = [
            value
            for value in _phase3a2_docker_option_values(command_tokens[1], "--tmpfs")
            if value.startswith("/tmp/work:")
        ]
        if build_work_tmpfs != ["/tmp/work:rw,exec,nosuid,nodev"]:
            errors.append("phase3a2 workflow: offline build/test container must mount an exec-capable work tmpfs")
        if len(prefetch_work_tmpfs) != 1 or "exec" not in prefetch_work_tmpfs[0]:
            errors.append("phase3a2 workflow: prefetch container must mount an exec-capable work tmpfs for rustup-init")
        # cargo install stages its per-install build tree under $TMPDIR by
        # default, and /tmp is mounted noexec, so build-script binaries fail
        # with EACCES mid-compile. The target dir must live on the exec-capable
        # work tmpfs like it already does in the offline build container.
        # Scoped to the prefetch segment because both container scripts carry
        # this export; a workflow-level match would pass vacuously off the
        # offline leg.
        if "export CARGO_TARGET_DIR=/tmp/work/cargo-target" not in prefetch:
            errors.append(
                "phase3a2 workflow: prefetch script must point CARGO_TARGET_DIR "
                "at the exec-capable work tmpfs"
            )
        if "cargo fetch --locked" not in prefetch:
            errors.append("phase3a2 workflow: locked Cargo prefetch is missing")
        if "cargo metadata --locked" not in prefetch:
            errors.append("phase3a2 workflow: locked Cargo metadata is missing from prefetch")
        if "pip download" not in prefetch:
            errors.append("phase3a2 workflow: reviewed inputs are not downloaded into the wheelhouse")
        prefetch_download_lines = [
            line.strip() for line in prefetch.splitlines() if "pip download" in line
        ]
        if prefetch_download_lines != _phase3a2_expected_prefetch_downloads():
            errors.append("phase3a2 workflow: prefetch download inventory is not exactly reviewed")
        # Bare `python` resolves to nothing in the pinned manylinux image and
        # surfaces as exit 127 deep inside the prefetch leg; every interpreter
        # invocation must name its explicit /opt/python path.
        if re.search(r"(?m)^\s*python\b", prefetch):
            errors.append(
                "phase3a2 workflow: prefetch must not invoke a bare python interpreter"
            )
        # The only permitted direct network fetch is the hash-pinned
        # rustup-init bootstrap; every other download must go through the
        # reviewed pip inventory above.  Backslash continuations are joined
        # first so a wrapped command is scanned as one logical line.
        joined_prefetch = prefetch.replace("\\\n", " ")
        pinned_rustup_fetch = re.compile(
            r"^curl\b.*static\.rust-lang\.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init\b"
        )
        unreviewed_prefetch_fetch = re.compile(
            r"(?:^|[;&|]\s*)(?:curl|wget|aria2c|git\s+(?:clone|fetch|pull)|"
            r"(?:python\s+-m\s+)?pip\s+(?:install|wheel)|cargo\s+(?:add|update))\b"
        )
        for line in joined_prefetch.splitlines():
            stripped = line.strip()
            if pinned_rustup_fetch.search(stripped):
                continue
            if unreviewed_prefetch_fetch.search(stripped):
                errors.append("phase3a2 workflow: prefetch contains an unreviewed network fetch")
                break
        for fragment, label in (
            (
                "printf '%s  rustup-init\\n' \"$PHASE3A2_RUSTUP_INIT_SHA256\" > /tmp/rustup-init.sha256",
                "rustup-init expected-digest file",
            ),
            # curl redirection stages the bootstrap mode 0644; the executable
            # bit must be set before direct execve can start it.
            ("chmod +x /tmp/work/rustup-init", "rustup-init executable-bit provisioning"),
            # /tmp stays noexec; the verified bootstrap must be executed
            # directly from the exec-mounted /tmp/work tmpfs.
            ("/tmp/work/rustup-init -y --no-modify-path --profile minimal --default-toolchain 1.89.0", "pinned rustup provisioning"),
        ):
            if fragment not in prefetch:
                errors.append(f"phase3a2 workflow: prefetch lacks {label}")
        if "cargo install --locked cargo-deny@0.20.2" not in prefetch:
            errors.append("phase3a2 workflow: pinned cargo-deny provisioning is missing")
        if any(
            "cargo install" in line and "cargo-deny@0.20.2" not in line
            for line in prefetch.splitlines()
        ):
            errors.append("phase3a2 workflow: unreviewed Cargo tool installation is forbidden")
        for digest in PHASE3A2_NUMPY_WHEEL_SHA256.values():
            if digest not in prefetch:
                errors.append("phase3a2 workflow: missing hash-pinned NumPy 2.4.6 runtime wheel")
        # pip's --hash is a requirements-file-only option, so the reviewed
        # digests must be staged into one-line requirements files before the
        # download commands consume them; assert each exact staging line.
        staging_lines = (
            f"printf '%s\\n' 'maturin==1.14.1 --hash=sha256:{PHASE3A2_MATURIN_WHEEL_SHA256}' > /tmp/wheelhouse-maturin.txt",
            *(
                f"printf '%s\\n' 'numpy==2.4.6 --hash=sha256:{digest}' > /tmp/wheelhouse-numpy{version.removeprefix('cp')}.txt"
                for version, digest in PHASE3A2_NUMPY_WHEEL_SHA256.items()
            ),
        )
        if any(staging_line not in prefetch for staging_line in staging_lines):
            errors.append(
                "phase3a2 workflow: prefetch lacks an exact requirements-file hash pin "
                "for a reviewed wheelhouse input"
            )
        if "maturin build" not in build:
            errors.append("phase3a2 workflow: offline container is missing the wheel build")
        if "cargo build --release --locked --offline" not in build:
            errors.append("phase3a2 workflow: offline Cargo build is missing")
        # pip installs the builder tools with --target, whose console scripts
        # import their package through PYTHONPATH; the export must therefore
        # precede the first auditwheel/abi3audit invocation or those commands
        # die with ModuleNotFoundError inside the offline container.
        pythonpath_export_index = build.find("export PYTHONPATH=/tmp/work/build-site")
        tool_invocation = re.search(
            r"^\s*auditwheel (?:--version|show|check|repair)\b|"
            r'^\s*AUDITWHEEL_VERSION="\$\(auditwheel\b|'
            r"^\s*abi3audit\b|"
            r'^\s*ABI3AUDIT_VERSION="\$\(abi3audit\b',
            build,
            re.MULTILINE,
        )
        if "auditwheel" not in build:
            errors.append("phase3a2 workflow: offline container is missing the auditwheel policy check")
        elif pythonpath_export_index == -1:
            errors.append(
                "phase3a2 workflow: offline build/test container must export "
                "PYTHONPATH=/tmp/work/build-site before the first auditwheel/abi3audit invocation"
            )
        elif tool_invocation is not None and tool_invocation.start() < pythonpath_export_index:
            errors.append(
                "phase3a2 workflow: offline build/test container must export "
                "PYTHONPATH=/tmp/work/build-site before the first auditwheel/abi3audit invocation"
            )
        if "maturin build" in prefetch:
            errors.append("phase3a2 workflow: wheel build must not run in the networked prefetch container")
    if shell_code.count("maturin build") != 1:
        errors.append("phase3a2 workflow: exactly one wheel build is required")
    if shell_code.count('sha256sum --check "$WHEEL.sha256"') < 5:
        errors.append("phase3a2 workflow: every runtime cell must recheck the input wheel hash")
    if 'readelf -d "$NATIVE_OBJECT"' not in shell_code:
        errors.append("phase3a2 workflow: ELF dependency check must target the native object")
    for fragment, label in (
        ("test \"$(printf '%s\\n' \"$READELF_OUT\" | grep -cE '\\(RPATH\\)')\" = \"0\"", "RPATH zero-count gate"),
        (
            "RUNPATH_VALUE=\"$(printf '%s\\n' \"$READELF_OUT\" | sed -n '/(\\(RUNPATH\\))/s/.*\\[\\([^]]*\\)\\].*/\\1/p')\"",
            "RUNPATH extraction",
        ),
        ("GLIBC_VERSION=\"$(ldd --version", "observed glibc capture"),
        ("UNAME_ARCH=\"$(uname -m)\"", "observed platform capture"),
        (
            "if [ -f /evidence/observed.json ]; then\n            MANIFEST_ARGS+=(--observed /evidence/observed.json)\n          fi",
            "conditional observed-evidence handoff",
        ),
        ('/opt/python/cp311-cp311/bin/python /src/scripts/phase3a2-manifest.py "${MANIFEST_ARGS[@]}"', "argument-array manifest invocation"),
    ):
        if fragment not in shell_code:
            errors.append(f"phase3a2 workflow: ELF evidence gate lacks {label}")
    if ":/src:rw" in workflow_code or "/src:rw" in workflow_code:
        errors.append("phase3a2 workflow: source checkout must be read-only")

    if "docker image inspect --format '{{.Id}}' \"$IMAGE\"" not in shell_code:
        errors.append("phase3a2 workflow: image config digest inspection must be executable")
    if not re.search(
        rf'test\s+"\$IMAGE_CONFIG_DIGEST"\s*=\s*"{re.escape(PHASE3A2_IMAGE_CONFIG_DIGEST)}"',
        shell_code,
    ):
        errors.append("phase3a2 workflow: image config digest comparison is missing")
    if "CARGO_VERSION=\"$(cargo metadata --locked --offline --format-version 1" not in shell_code:
        errors.append("phase3a2 workflow: Cargo version must be derived from locked Cargo metadata")
    if "SOURCE_COMMIT=\"$(git rev-parse --verify HEAD)\"" not in shell_code:
        errors.append("phase3a2 workflow: evidence source commit must be derived from checked-out HEAD")
    if not re.search(r"phase3a2-manifest\.py.*>\s*(?:/[^\s]*/)?phase3a2-wheel-evidence\.json", shell_code):
        errors.append("phase3a2 workflow: evidence manifest generation is missing")
    if "WHEEL=\"" not in shell_code or "$CARGO_VERSION" not in shell_code:
        errors.append("phase3a2 workflow: wheel filename must be derived from Cargo version")

    runtime_cells = _phase3a2_runtime_cell_segments(docker_runs[1] if len(docker_runs) >= 2 else "")
    for interpreter in PHASE3A2_INTERPRETERS.values():
        if interpreter not in workflow_code:
            errors.append(f"phase3a2 workflow: missing runtime interpreter {interpreter}")
        elif f"{interpreter} -m venv --clear" not in workflow_code:
            errors.append(f"phase3a2 workflow: runtime interpreter {interpreter} lacks fresh venv isolation")
    if [version for version, _ in runtime_cells] != list(PHASE3A2_INTERPRETERS):
        errors.append("phase3a2 workflow: runtime cells must be explicit and ordered 3.11, 3.12, 3.13, 3.14")
    for version, interpreter in PHASE3A2_INTERPRETERS.items():
        matching = [segment for cell_version, segment in runtime_cells if cell_version == version]
        if not matching:
            errors.append(f"phase3a2 workflow: missing runtime interpreter {interpreter}")
            continue
        cell = matching[0]
        if f"{interpreter} -m venv --clear" not in cell:
            errors.append(f"phase3a2 workflow: runtime interpreter {interpreter} lacks fresh venv isolation")
        numpy_install = f"numpy==2.4.6 --hash=sha256:{PHASE3A2_NUMPY_WHEEL_SHA256['cp' + version.replace('.', '')]}"
        if numpy_install not in cell:
            errors.append(f"phase3a2 workflow: runtime cell {version} lacks its exact hash-pinned NumPy wheel")
        if version == "3.11":
            # Phase-3B golden matrix: the cp311 evidence cell must stage the
            # reviewed matplotlib stack (MPLREQS311 requirements heredoc) so
            # the backend-adapter tests exercise real Agg instead of
            # self-skipping in the evidence container.
            if "MPLREQS311" not in cell:
                errors.append(
                    f"phase3a2 workflow: runtime cell {version} lacks "
                    "the hash-pinned Phase-3B matplotlib stack"
                )
        for fragment, label in (
            ('-r /tmp/helper-wheel', "identical helper-wheel install"),
            ("--hash=sha256:$WHEEL_SHA256", "hash-pinned helper-wheel install"),
            ('from lumenplot_mpl import _native', "private helper import"),
            ("_native.render_line_png", "private helper fixture execution"),
            ("invalid-input", "invalid-input helper fixture"),
            ("helper-success", "successful helper fixture"),
            ('sha256sum --check "$WHEEL.sha256"', "per-cell input wheel hash"),
            ('INPUT_WHEEL_SHA256=', "per-cell input wheel rehash"),
            ('test "$INSTALLED_VERSION" = "$CARGO_VERSION"', "Cargo-to-installed version comparison"),
        ):
            if fragment not in cell:
                errors.append(f"phase3a2 workflow: runtime cell {version} lacks {label}")
    if shell_code.count('pip install') and shell_code.count('-r /tmp/helper-wheel') < 4:
        errors.append("phase3a2 workflow: identical helper wheel must be installed in all four cells")
    pip_lines = [line for line in workflow_code.splitlines() if "pip install" in line]
    for line in pip_lines:
        for fragment, label in (
            ("--no-index", "offline pip index"),
            ("--no-cache-dir", "non-cache pip install"),
            ("--only-binary=:all:", "binary-only pip install"),
            ("--require-hashes", "hash-required pip install"),
            ("--find-links=/cache/wheelhouse", "local wheelhouse install"),
        ):
            if fragment not in line:
                errors.append(f"phase3a2 workflow: pip command is missing {label}")
        if "maturin" in line and (
            "maturin==1.14.1" not in line
            or f"--hash=sha256:{PHASE3A2_MATURIN_WHEEL_SHA256}" not in shell_code
        ):
            errors.append("phase3a2 workflow: maturin pip command is not exact and hash-pinned")
    download_lines = [line for line in shell_code.splitlines() if "pip download" in line]
    for line in download_lines:
        for fragment, label in (
            ("--dest /cache/wheelhouse", "job-local wheelhouse download"),
        ):
            if fragment not in line:
                errors.append(f"phase3a2 workflow: pip download is missing {label}")
        # Hash-pinned reviewed inputs (maturin, NumPy) must carry both
        # --only-binary and --require-hashes, and their digest travels through
        # a one-line requirements file because pip's `--hash` is a
        # requirements-file-only option (no CLI flag exists on any release).
        # Tool wheels whose digests are re-verified by sha256sum --check
        # inside the offline container are recorded as builder provenance
        # instead of pre-pinned here; they still must be binary-only.
        if "--require-hashes" in line:
            for fragment, label in (
                ("--only-binary=:all:", "binary-only input download"),
                ("--require-hashes", "hash-required input download"),
                ("-r /tmp/wheelhouse-", "requirements-file input hash pin"),
            ):
                if fragment not in line:
                    errors.append(f"phase3a2 workflow: pip download is missing {label}")
        elif "--only-binary=:all:" in line and "auditwheel==" not in line \
                and "abi3audit==" not in line and "-r /tmp/" not in line:
            allowed = (
                "packaging==26.3", "pyelftools==0.33", "abi3info==2025.11.29",
                "kaitaistruct==0.11", "pefile==2024.8.26", "requests==2.34.2",
                "charset-normalizer==3.5.1", "rich==15.0.0",
                "six==1.17.0",
                "markdown-it-py==4.2.0", "pygments==2.21.0", "mdurl==0.1.2",
                "requests-cache==1.3.3", "url-normalize==1.4.3",
                "attrs==26.1.0", "cattrs==24.1.2",
                "urllib3==2.7.0", "certifi==2026.7.22", "idna==3.19",
                # Phase-3B golden-matrix seam runtime stack.
                "matplotlib==3.11.1", "contourpy==1.3.3", "cycler==0.12.1",
                "fonttools==4.63.0", "kiwisolver==1.5.0", "pillow==12.3.0",
                "pyparsing==3.3.2", "python-dateutil==2.9.0.post0",
            )
            if not any(pkg + " " in line or pkg == line.rstrip().split()[-1]
                       for pkg in allowed):
                errors.append(
                    "phase3a2 workflow: tool-wheel download must be a reviewed "
                    "transitive dependency pin, an auditwheel/abi3audit pin, "
                    "or a --require-hashes input"
                )
    if "actions/upload-artifact" in repositories:
        if "if: github.ref == 'refs/heads/main' && github.event_name == 'push'" not in workflow_code:
            errors.append("phase3a2 workflow: upload-artifact is restricted to trusted main")
        if "retention-days: 7" not in workflow_code:
            errors.append("phase3a2 workflow: upload-artifact retention must be seven days")
    return repositories


def _phase3a2_check_pinned_inventory(root: Path, repositories: set[str], errors: list[str]) -> None:
    path = root / "docs" / "security" / "pinned-actions.yml"
    text = _phase3a2_read_text(path, root, errors, "pinned-actions inventory")
    if text is None:
        return
    for repository in sorted(repositories):
        expected = PHASE3A2_ACTION_PINS.get(repository)
        if expected is None:
            continue
        expected_sha, release = expected
        if repository not in text or expected_sha not in text or release not in text:
            errors.append(f"phase3a2 pinned-actions inventory: missing reviewed {repository} entry")


def _phase3a2_exact_mapping(
    value: Any,
    expected_keys: set[str],
    label: str,
    errors: list[str],
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        errors.append(f"phase3a2 evidence: {label} must be an object")
        return None
    if set(value) != expected_keys:
        errors.append(f"phase3a2 evidence: {label} keys are not exact")
        return None
    return value


def _phase3a2_check_redaction(value: Any, root: Path, errors: list[str], key: str = "manifest") -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            if re.search(r"(?:token|password|secret|credential|private[_-]?key|authorization)", child_key, re.IGNORECASE):
                errors.append(f"phase3a2 evidence: secret-bearing field {key}.{child_key} is forbidden")
            _phase3a2_check_redaction(child, root, errors, f"{key}.{child_key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _phase3a2_check_redaction(child, root, errors, f"{key}[{index}]")
    elif isinstance(value, str):
        forbidden = (str(root.resolve()), "/home/", "/tmp/", "\\Users\\", "GITHUB_TOKEN", "github.token")
        if any(fragment in value for fragment in forbidden):
            errors.append("phase3a2 evidence: private path or credential text is not redacted")


def _phase3a2_check_evidence_manifest(root: Path, errors: list[str]) -> None:
    path = root / "phase3a2-wheel-evidence.json"
    if _phase3a2_manifest_is_tracked(root):
        errors.append("phase3a2 evidence: CI-local evidence manifest must not be tracked")
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        errors.append("phase3a2 evidence: missing phase3a2-wheel-evidence.json")
        return
    except OSError:
        errors.append("phase3a2 evidence: cannot read evidence manifest")
        return
    try:
        text = raw.decode("utf-8")
        value = json.loads(text)
    except UnicodeDecodeError:
        errors.append("phase3a2 evidence: manifest must be UTF-8 JSON")
        return
    except json.JSONDecodeError:
        errors.append("phase3a2 evidence: manifest is not valid JSON")
        return
    if "\r" in text:
        errors.append("phase3a2 evidence: manifest must use LF line endings")
    try:
        canonical = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    except (TypeError, ValueError):
        errors.append("phase3a2 evidence: manifest cannot be canonically serialized")
    else:
        if text != canonical:
            errors.append("phase3a2 evidence: manifest is not canonical sorted two-space JSON")
    _phase3a2_check_redaction(value, root, errors)
    manifest = _phase3a2_exact_mapping(value, PHASE3A2_MANIFEST_KEYS, "top-level manifest", errors)
    if manifest is None:
        return
    if manifest["schema"] != PHASE3A2_SCHEMA:
        errors.append("phase3a2 evidence: schema identifier is not the accepted Phase-3A2 v1 value")
    source = _phase3a2_exact_mapping(manifest["source"], PHASE3A2_SOURCE_KEYS, "source", errors)
    builder = _phase3a2_exact_mapping(
        manifest["builder"],
        PHASE3A2_OBSERVED_BUILDER_KEYS if "elf_runpath" in manifest["builder"] else PHASE3A2_BUILDER_KEYS,
        "builder",
        errors,
    )
    wheel = _phase3a2_exact_mapping(manifest["wheel"], PHASE3A2_WHEEL_KEYS, "wheel", errors)
    checks = _phase3a2_exact_mapping(manifest["checks"], PHASE3A2_CHECK_KEYS, "checks", errors)
    claims = _phase3a2_exact_mapping(manifest["claim_boundary"], PHASE3A2_CLAIM_KEYS, "claim_boundary", errors)
    if source is None or builder is None or wheel is None or checks is None or claims is None:
        return

    if not isinstance(source["commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", source["commit"]):
        errors.append("phase3a2 evidence: source commit must be a 40-character hex revision")
    lock_hash = source["cargo_lock_sha256"]
    if not isinstance(lock_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", lock_hash):
        errors.append("phase3a2 evidence: Cargo.lock SHA-256 is invalid")
    else:
        lock_path = root / "Cargo.lock"
        try:
            actual_lock_hash = hashlib.sha256(lock_path.read_bytes()).hexdigest()
        except OSError:
            errors.append("phase3a2 evidence: cannot read Cargo.lock for SHA-256 verification")
        else:
            if lock_hash != actual_lock_hash:
                errors.append("phase3a2 evidence: Cargo.lock SHA-256 does not match the checked-in lockfile")
    if source["distribution"] != "lumenplot-mpl":
        errors.append("phase3a2 evidence: distribution must be lumenplot-mpl")
    cargo_version = source["cargo_version"]
    if not isinstance(cargo_version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", cargo_version):
        errors.append("phase3a2 evidence: Cargo-derived version is invalid")
    else:
        expected_version = _phase3a2_workspace_version(root)
        if expected_version is None:
            errors.append("phase3a2 evidence: checked-in workspace Cargo version is unavailable")
        elif cargo_version != expected_version:
            errors.append("phase3a2 evidence: Cargo-derived version does not match workspace metadata")
    expected_revision = _phase3a2_checked_out_revision(root)
    if expected_revision is None:
        errors.append("phase3a2 evidence: checked-out source revision is unavailable")
    elif source["commit"] != expected_revision:
        errors.append("phase3a2 evidence: source commit does not match checked-out revision")

    expected_builder = {
        "image": PHASE3A2_IMAGE,
        "platform": "linux/amd64",
        "config_digest": PHASE3A2_IMAGE_CONFIG_DIGEST,
        "glibc": "2.28",
        "auditwheel_version": "6.8.0",
        "abi3audit_version": "0.0.26",
        "rust_version": "1.89.0",
        "maturin_version": "1.14.1",
        "maturin_wheel_sha256": PHASE3A2_MATURIN_WHEEL_SHA256,
    }
    for key, expected in expected_builder.items():
        if builder[key] != expected:
            errors.append(f"phase3a2 evidence: builder {key} is not the reviewed immutable input")
    if "elf_runpath" in builder:
        entries = builder["elf_runpath"]
        if (
            not isinstance(entries, list)
            or not entries
            or not all(isinstance(item, str) and item for item in entries)
        ):
            errors.append(
                "phase3a2 evidence: observed elf_runpath must be a non-empty list of strings"
            )

    expected_filename = f"lumenplot_mpl-{cargo_version}-cp311-abi3-manylinux_2_28_x86_64.whl"
    if wheel["filename"] != expected_filename:
        errors.append("phase3a2 evidence: wheel filename/tag is not the exact cp311-abi3 manylinux artifact")
    if not isinstance(wheel["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", wheel["sha256"]):
        errors.append("phase3a2 evidence: wheel SHA-256 is invalid")
    if wheel["tag"] != "cp311-abi3-manylinux_2_28_x86_64":
        errors.append("phase3a2 evidence: wheel tag is not cp311-abi3-manylinux_2_28_x86_64")
    for key in ("cargo_expected_version", "metadata_version"):
        if wheel[key] != cargo_version:
            errors.append(f"phase3a2 evidence: wheel {key} does not match Cargo version")
    for key in ("zip", "metadata", "wheel", "record", "elf", "abi3", "sbom"):
        if wheel[key] is not True:
            errors.append(f"phase3a2 evidence: wheel {key} check is not true")
    if wheel["sbom_format"] != "CycloneDX 1.5":
        errors.append("phase3a2 evidence: SBOM format must be CycloneDX 1.5")
    for key in PHASE3A2_CHECK_KEYS:
        if checks[key] is not True:
            errors.append(f"phase3a2 evidence: required check {key} is not true")
    expected_claims = {
        "private_helper_only": True,
        "release_artifact": False,
        "platform_support_claim": False,
        "publication_authorized": False,
    }
    for key, expected in expected_claims.items():
        if claims[key] is not expected:
            errors.append(f"phase3a2 evidence: claim boundary {key} is incorrect")

    cells = manifest["runtime_cells"]
    if not isinstance(cells, list) or len(cells) != 4:
        errors.append("phase3a2 evidence: runtime matrix must contain exactly four GIL cells")
        return
    cell_keys = {
        "python",
        "interpreter",
        "numpy_version",
        "numpy_wheel_sha256",
        "wheel_sha256",
        "input_wheel_sha256",
        "cargo_expected_version",
        "installed_distribution_version",
        "result",
    }
    seen: set[str] = set()
    expected_cell_order = list(PHASE3A2_INTERPRETERS)
    actual_cell_order = [cell.get("python") for cell in cells if isinstance(cell, dict)]
    if actual_cell_order != expected_cell_order:
        errors.append("phase3a2 evidence: runtime cells must be ordered 3.11, 3.12, 3.13, 3.14")
    for cell in cells:
        if not isinstance(cell, dict) or set(cell) != cell_keys:
            errors.append("phase3a2 evidence: runtime cell schema is not exact")
            continue
        python_version = cell["python"]
        expected_numpy_key = "cp" + python_version.replace(".", "") if isinstance(python_version, str) else ""
        if python_version not in PHASE3A2_INTERPRETERS:
            errors.append("phase3a2 evidence: runtime matrix contains an unsupported interpreter")
            continue
        seen.add(python_version)
        if cell["interpreter"] != PHASE3A2_INTERPRETERS[python_version]:
            errors.append("phase3a2 evidence: runtime interpreter path is not the reviewed GIL path")
        if cell["numpy_version"] != "2.4.6" or cell["numpy_wheel_sha256"] != PHASE3A2_NUMPY_WHEEL_SHA256.get(expected_numpy_key):
            errors.append("phase3a2 evidence: runtime NumPy input is not the exact hash-pinned wheel")
        if cell["wheel_sha256"] != wheel["sha256"]:
            errors.append("phase3a2 evidence: runtime cell did not use the identical wheel hash")
        if cell["input_wheel_sha256"] != wheel["sha256"]:
            errors.append("phase3a2 evidence: runtime cell did not rehash the input wheel")
        if cell["cargo_expected_version"] != cargo_version or cell["installed_distribution_version"] != cargo_version:
            errors.append("phase3a2 evidence: installed distribution version does not match Cargo")
        if cell["result"] != "pass":
            errors.append("phase3a2 evidence: runtime matrix cell did not pass")
    if seen != set(PHASE3A2_INTERPRETERS):
        errors.append("phase3a2 evidence: runtime matrix is missing one or more CPython 3.11-3.14 cells")


def _check_phase3a2(
    root: Path,
    errors: list[str],
    *,
    require_evidence: bool = False,
) -> None:
    """Validate the static Phase-3A2 gate and optional runtime evidence."""

    for relative in ("rust-toolchain", "rust-toolchain.toml"):
        if (root / relative).exists():
            errors.append(f"phase3a2: repository {relative} pin is forbidden")
    _phase3a2_check_pyproject(root, errors)
    _phase3a2_check_python_package(root, errors)
    _check_python_bridge_source(root / "crates" / "lumenplot-python", root, errors)
    repositories = _phase3a2_check_workflow(root, errors)
    _phase3a2_check_pinned_inventory(root, repositories, errors)
    if require_evidence:
        _phase3a2_check_evidence_manifest(root, errors)


def _check_package_source(
    package_name: str,
    package_dir: Path,
    root: Path,
    errors: list[str],
    phase3a2_active: bool = False,
) -> None:
    if package_name == "lumenplot-engine":
        _check_engine_source(package_dir, root, errors)
    elif package_name == "lumenplot-export":
        _check_export_source(package_dir, root, errors)
    elif package_name == "lumenplot":
        _check_facade_source(package_dir, root, errors)
    elif package_name == "lumenplot-python" and phase3a2_active:
        _check_python_bridge_source(package_dir, root, errors)
    else:
        _check_stub_source(package_name, package_dir / "src", root, errors)


def _check_dependencies(
    package_name: str,
    manifest: dict[str, Any],
    errors: list[str],
    phase3a2_active: bool = False,
    phase3b_active: bool = False,
) -> None:
    expected_edges = EXPECTED_EDGES[package_name]
    if package_name == "lumenplot-export":
        expected_external = EXPECTED_EXPORT_EXTERNAL_DEPENDENCIES
    elif package_name == "lumenplot-python" and phase3a2_active:
        expected_external = PHASE3A2_PYTHON_DEPENDENCIES
        if phase3b_active:
            expected_external = {
                **PHASE3A2_PYTHON_DEPENDENCIES,
                **PHASE3A2_PHASE3B_PYTHON_DEPENDENCIES,
            }
    else:
        expected_external = {}
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


def check_workspace(root: Path, *, require_phase3a2_evidence: bool = False) -> list[str]:
    """Return deterministic, public-safe architecture diagnostics for *root*."""

    root = root.resolve()
    errors: list[str] = []
    phase3a2_active = bool(_phase3a2_activation_reasons(root))
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

        _check_dependencies(
            package_name,
            manifest,
            errors,
            phase3a2_active=phase3a2_active,
            phase3b_active=bool(_phase3b_activation_reason(root)),
        )
        _check_package_source(
            package_name,
            manifest_path.parent,
            root,
            errors,
            phase3a2_active=phase3a2_active,
        )

    if require_phase3a2_evidence and not phase3a2_active:
        errors.append("phase3a2 evidence: explicit evidence mode requires an active Phase-3A2 implementation")
    if phase3a2_active:
        _check_phase3a2(root, errors, require_evidence=require_phase3a2_evidence)

    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    parser.add_argument(
        "--phase3a2-evidence",
        action="store_true",
        help="require and validate the CI-local Phase-3A2 runtime evidence manifest",
    )
    args = parser.parse_args(argv)
    errors = check_workspace(args.root, require_phase3a2_evidence=args.phase3a2_evidence)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("workspace architecture: OK")
    if _phase3a2_activation_reasons(args.root.resolve()):
        print("phase3a2 static contract: OK")
    if args.phase3a2_evidence:
        print("phase3a2 wheel evidence: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
