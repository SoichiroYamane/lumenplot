#!/usr/bin/env python3
"""Mutation tests for the Phase-1A workspace architecture checker."""

from __future__ import annotations

import os
import json
import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_workspace_architecture.py"
BASELINE_PYTHON_MANIFEST = """[package]
name = "lumenplot-python"
edition.workspace = true
version.workspace = true
publish = false
license.workspace = true
repository.workspace = true
readme.workspace = true

[lib]
crate-type = ["cdylib"]

[dependencies]
lumenplot = { path = "../lumenplot", version = "0.1.0" }
"""
BASELINE_PYTHON_SOURCE = """//! Private Phase-0 documentation stub for the future language bridge edge.
//!
//! Binding implementation is deferred until its accepted bridge contract lands.
"""


def reset_python_bridge_to_baseline(root: Path) -> None:
    manifest = root / "crates/lumenplot-python/Cargo.toml"
    source = root / "crates/lumenplot-python/src/lib.rs"
    source_dir = root / "crates/lumenplot-python/src"
    # Fixtures model the Phase-0 baseline: the working tree may carry the
    # accepted Phase-3B lane files (e.g. src/frame.rs) alongside lib.rs,
    # but the baseline bridge crate ships documentation-only src/lib.rs.
    if source_dir.is_dir():
        for stale in sorted(source_dir.iterdir()):
            if stale.name == "lib.rs":
                continue
            if stale.is_dir():
                shutil.rmtree(stale)
            else:
                stale.unlink()
    manifest.write_text(BASELINE_PYTHON_MANIFEST, encoding="utf-8")
    source.write_text(BASELINE_PYTHON_SOURCE, encoding="utf-8")


class WorkspaceArchitectureMutationTests(unittest.TestCase):
    def fixture(self) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory(prefix="lumenplot-architecture-")
        fixture_root = Path(temporary.name)
        shutil.copy2(ROOT / "Cargo.toml", fixture_root / "Cargo.toml")
        # The offline external-consumer probes resolve the full workspace
        # graph, so the lockfile (with the `png` entry and every other
        # transitive pin) must travel with the fixture.
        shutil.copy2(ROOT / "Cargo.lock", fixture_root / "Cargo.lock")
        shutil.copytree(ROOT / "crates", fixture_root / "crates")
        reset_python_bridge_to_baseline(fixture_root)
        scripts_dir = fixture_root / "scripts"
        scripts_dir.mkdir()
        shutil.copy2(CHECKER, scripts_dir / CHECKER.name)
        return temporary

    def run_checker(self, fixture_root: Path, *, evidence: bool = False) -> tuple[int, str]:
        command = [sys.executable, str(fixture_root / "scripts" / CHECKER.name), "--root", str(fixture_root)]
        if evidence:
            command.append("--phase3a2-evidence")
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout + result.stderr

    def remove_hidden_facade(self, root: Path) -> None:
        path = root / "crates/lumenplot/src/lib.rs"
        source = path.read_text(encoding="utf-8")
        marker = "#[doc(hidden)]\npub mod __private {"
        if marker in source:
            path.write_text(source[: source.index(marker)], encoding="utf-8")

    def add_valid_hidden_facade(self, root: Path) -> None:
        self.remove_hidden_facade(root)
        path = root / "crates/lumenplot/src/lib.rs"
        source = path.read_text(encoding="utf-8")
        path.write_text(
            source
            + """

#[doc(hidden)]
pub mod __private {
    use std::fmt;
    use std::ops::Range;
    use super::{ErrorCategory, ErrorCode};

    pub struct LinePngGeometry {
        viewport: [f64; 4],
        canvas: [f64; 2],
        plot_rect: [f64; 4],
        logical_units_per_inch: f64,
    }

    pub struct LinePngStyle {
        line_rgba: [u8; 4],
        line_width: f64,
        background_rgba: [u8; 4],
    }

    pub struct OwnedLinePngRequest {
        x: Vec<f64>,
        y: Vec<f64>,
        valid_segments: Vec<Range<usize>>,
        geometry: LinePngGeometry,
        style: LinePngStyle,
        output_dpi: f64,
    }

    pub struct BridgeError {
        code: ErrorCode,
        category: ErrorCategory,
        message: String,
    }

    impl LinePngGeometry {
        pub fn new(viewport: [f64; 4], canvas: [f64; 2], plot_rect: [f64; 4], logical_units_per_inch: f64) -> Result<Self, BridgeError> { unreachable!() }
    }
    impl LinePngStyle {
        pub fn new(line_rgba: [u8; 4], line_width: f64, background_rgba: [u8; 4]) -> Result<Self, BridgeError> { unreachable!() }
    }
    impl OwnedLinePngRequest {
        pub fn new(x: Vec<f64>, y: Vec<f64>, valid_segments: Vec<Range<usize>>, geometry: LinePngGeometry, style: LinePngStyle, output_dpi: f64) -> Result<Self, BridgeError> { unreachable!() }
    }
    impl BridgeError {
        pub fn code(&self) -> ErrorCode { unreachable!() }
        pub fn category(&self) -> ErrorCategory { unreachable!() }
        pub fn message(&self) -> &str { unreachable!() }
    }
    impl fmt::Debug for BridgeError {
        fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.debug_struct("BridgeError").finish()
        }
    }
    impl fmt::Display for BridgeError {
        fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            formatter.write_str(&self.message)
        }
    }
    impl std::error::Error for BridgeError {}

    pub fn render_line_png(request: OwnedLinePngRequest) -> Result<Vec<u8>, BridgeError> { unreachable!() }
}
""",
            encoding="utf-8",
        )

    def assert_mutation_rejected(self, mutate, expected: str) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            mutate(fixture_root)
            returncode, output = self.run_checker(fixture_root)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn(expected, output)
            self.assertNotIn(str(fixture_root), output)

    def assert_hidden_replacement_rejected(self, old: str, new: str, expected: str) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            source = path.read_text(encoding="utf-8")
            self.assertIn(old, source)
            path.write_text(source.replace(old, new, 1), encoding="utf-8")

        self.assert_mutation_rejected(mutate, expected)

    def assert_hidden_insertion_rejected(self, insertion: str, expected: str = "hidden facade") -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            source = path.read_text(encoding="utf-8")
            marker = "pub mod __private {\n"
            self.assertIn(marker, source)
            path.write_text(source.replace(marker, marker + insertion + "\n", 1), encoding="utf-8")

        self.assert_mutation_rejected(mutate, expected)

    def assert_root_insertion_rejected(self, insertion: str, expected: str = "crate-root") -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8") + "\n" + insertion + "\n",
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, expected)

    def run_external_consumer(
        self,
        fixture_root: Path,
        source: str,
        flags: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="lumenplot-consumer-") as temporary:
            consumer = Path(temporary)
            (consumer / "src").mkdir()
            dependency_path = (fixture_root / "crates/lumenplot").as_posix().replace('"', '\\"')
            (consumer / "Cargo.toml").write_text(
                f"""[package]
name = "external-consumer"
version = "0.1.0"
edition = "2021"

[dependencies]
lumenplot = {{ path = "{dependency_path}" }}
""",
                encoding="utf-8",
            )
            (consumer / "src/main.rs").write_text(source, encoding="utf-8")
            environment = dict(os.environ)
            environment["CARGO_NET_OFFLINE"] = "true"
            environment["CARGO_TARGET_DIR"] = str(fixture_root / "target-external-consumer")
            return subprocess.run(
                ["cargo", "check", "--manifest-path", str(consumer / "Cargo.toml"), *flags],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

    def assert_external_consumer_matrix(self, fixture_root: Path, source: str) -> None:
        for flags in ((), ("--all-features", "--all-targets")):
            result = self.run_external_consumer(fixture_root, source, flags)
            self.assertEqual(
                result.returncode,
                0,
                f"external consumer failed for flags {flags}:\n{result.stdout}\n{result.stderr}",
            )

    @staticmethod
    def required_surface_consumer() -> str:
        return """
use lumenplot::{
    AxisRange, AxisScale, AxisScales, CommitReceipt, ErrorCategory, ErrorCode, PlotScene,
    PublicError, SceneRevision, SceneSnapshot, SceneTransaction, SeriesData, SeriesId,
    SeriesTopology, Viewport,
};

fn main() {
    let _ = ErrorCategory::as_str;
    let _ = ErrorCode::as_str;
    let _ = PublicError::code;
    let _ = AxisRange::new;
    let _ = AxisRange::min;
    let _ = AxisRange::max;
    let _ = AxisScale::Linear;
    let _ = AxisScale::Log10;
    let _ = AxisScales::new;
    let _ = AxisScales::x;
    let _ = AxisScales::y;
    let _ = AxisScales::validate;
    let _ = Viewport::new;
    let _ = Viewport::from_bounds;
    let _ = Viewport::x;
    let _ = Viewport::y;
    let _ = SeriesTopology::MonotonicX;
    let _ = SeriesTopology::ArbitraryXY;
    let _ = SeriesData::from_owned_xy;
    let _ = SeriesData::from_owned_xy_segments;
    let _ = SeriesData::topology;
    let _ = SeriesData::source_len;
    let _ = SeriesData::point_count;
    let _ = SeriesData::is_empty;
    let _ = PlotScene::new;
    let _ = PlotScene::transaction;
    let _ = PlotScene::snapshot;
    let _ = PlotScene::revision;
    let _ = SceneTransaction::replace_canonical_view;
    let _ = SceneTransaction::set_viewport;
    let _ = SceneTransaction::set_axis_scales;
    let _ = SceneTransaction::add_series;
    let _ = SceneTransaction::append_series;
    let _ = SceneTransaction::commit;
    let _ = SceneTransaction::abort;
    let _ = SceneSnapshot::revision;
    let _ = SceneSnapshot::canonical_view;
    let _ = SceneSnapshot::viewport;
    let _ = SceneSnapshot::axis_scales;
    let _: Option<CommitReceipt> = None;
    let _: Option<SceneRevision> = None;
    let _: Option<SceneSnapshot> = None;
    let _: Option<SceneTransaction<'static>> = None;
    let _: Option<SeriesId> = None;
    let _: Option<AxisScale> = None;
    let _ = lumenplot::__private::LinePngGeometry::new;
    let _ = lumenplot::__private::LinePngStyle::new;
    let _ = lumenplot::__private::OwnedLinePngRequest::new;
    let _ = lumenplot::__private::BridgeError::code;
    let _ = lumenplot::__private::BridgeError::category;
    let _ = lumenplot::__private::BridgeError::message;
    let _ = lumenplot::__private::render_line_png;
}
"""

    def wrap_hidden_facade(self, root: Path, opener: str) -> None:
        path = root / "crates/lumenplot/src/lib.rs"
        source = path.read_text(encoding="utf-8")
        marker = "#[doc(hidden)]\npub mod __private {"
        start = source.index(marker)
        hidden = source[start:].replace(
            "use super::{ErrorCategory, ErrorCode};",
            "use crate::{ErrorCategory, ErrorCode};",
            1,
        )
        path.write_text(source[:start] + opener + "\n" + hidden + "}\n", encoding="utf-8")

    def test_external_consumer_compiles_required_surface_in_both_feature_modes(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            self.add_valid_hidden_facade(fixture_root)
            returncode, output = self.run_checker(fixture_root)
            self.assertEqual(returncode, 0, output)
            self.assert_external_consumer_matrix(fixture_root, self.required_surface_consumer())

    def test_external_oracle_reaches_same_line_cross_file_inherent_impl(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            view_path = fixture_root / "crates/lumenplot/src/view.rs"
            view_path.write_text(
                view_path.read_text(encoding="utf-8")
                + "\nmod nested { use super::AxisRange; impl AxisRange { pub fn leaked(&self) -> f64 { self.min() } } }\n",
                encoding="utf-8",
            )
            consumer = "use lumenplot::AxisRange; fn main() { let _ = AxisRange::leaked; }\n"
            self.assert_external_consumer_matrix(fixture_root, consumer)
            returncode, output = self.run_checker(fixture_root)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn("public method 'leaked' on 'AxisRange' is not allowed", output)

    def test_external_oracle_preserves_unreachable_private_and_block_pub_controls(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            root_path = fixture_root / "crates/lumenplot/src/lib.rs"
            root_path.write_text(
                root_path.read_text(encoding="utf-8")
                + "\nmod lexical_control { pub struct HiddenFromRoot; }\n"
                + "const _: () = { pub struct BlockOnly; () };\n",
                encoding="utf-8",
            )
            consumer = """
fn main() {
    let _: Option<lumenplot::HiddenFromRoot> = None;
    let _: Option<lumenplot::BlockOnly> = None;
}
"""
            result = self.run_external_consumer(fixture_root, consumer)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            returncode, output = self.run_checker(fixture_root)
            self.assertEqual(returncode, 0, output)

    def test_external_oracle_rejects_public_associated_const_inventory_expansion(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            view_path = fixture_root / "crates/lumenplot/src/view.rs"
            view_path.write_text(
                view_path.read_text(encoding="utf-8")
                + "\nimpl AxisRange { pub const LEAK: u8 = 1; }\n",
                encoding="utf-8",
            )
            consumer = "use lumenplot::AxisRange; fn main() { let _ = AxisRange::LEAK; }\n"
            self.assert_external_consumer_matrix(fixture_root, consumer)
            returncode, output = self.run_checker(fixture_root)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn("public associated const 'LEAK' on 'AxisRange' is not allowed", output)

    def test_external_oracle_rejects_unknown_root_export_attribute(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            self.add_valid_hidden_facade(fixture_root)
            root_path = fixture_root / "crates/lumenplot/src/lib.rs"
            source = root_path.read_text(encoding="utf-8")
            marker = "pub use view::{AxisRange, AxisScale, AxisScales, Viewport};"
            self.assertIn(marker, source)
            root_path.write_text(source.replace(marker, "#[doc(hidden)]\n" + marker, 1), encoding="utf-8")
            self.assert_external_consumer_matrix(fixture_root, self.required_surface_consumer())
            returncode, output = self.run_checker(fixture_root)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn("root export attributes are not allowlisted", output)

    def test_external_oracle_rejects_unknown_public_impl_attribute(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            view_path = fixture_root / "crates/lumenplot/src/view.rs"
            view_path.write_text(
                view_path.read_text(encoding="utf-8")
                + "\n#[allow(dead_code)]\nimpl AxisRange { pub fn attributed(&self) -> f64 { self.min() } }\n",
                encoding="utf-8",
            )
            consumer = "use lumenplot::AxisRange; fn main() { let _ = AxisRange::attributed; }\n"
            self.assert_external_consumer_matrix(fixture_root, consumer)
            returncode, output = self.run_checker(fixture_root)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn("facade impl for 'AxisRange' has unallowlisted attributes", output)

    def test_external_oracle_rejects_cfg_attr_on_required_root_export(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            self.add_valid_hidden_facade(fixture_root)
            root_path = fixture_root / "crates/lumenplot/src/lib.rs"
            source = root_path.read_text(encoding="utf-8")
            marker = "pub use view::{AxisRange, AxisScale, AxisScales, Viewport};"
            self.assertIn(marker, source)
            root_path.write_text(
                source.replace(marker, '#[cfg_attr(feature = "never", doc(hidden))]\n' + marker, 1),
                encoding="utf-8",
            )
            self.assert_external_consumer_matrix(fixture_root, self.required_surface_consumer())
            returncode, output = self.run_checker(fixture_root)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn("required root export is conditional", output)

    def test_external_oracle_rejects_cfg_on_required_root_export(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            self.add_valid_hidden_facade(fixture_root)
            root_path = fixture_root / "crates/lumenplot/src/lib.rs"
            source = root_path.read_text(encoding="utf-8")
            marker = "pub use view::{AxisRange, AxisScale, AxisScales, Viewport};"
            self.assertIn(marker, source)
            root_path.write_text(
                source.replace(marker, '#[cfg(feature = "never")]\n' + marker, 1),
                encoding="utf-8",
            )
            consumer = self.required_surface_consumer()
            for flags in ((), ("--all-features", "--all-targets")):
                result = self.run_external_consumer(fixture_root, consumer, flags)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            returncode, output = self.run_checker(fixture_root)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn("required root export is conditional", output)

    def test_external_oracle_rejects_nameable_path_redirected_required_module(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            self.add_valid_hidden_facade(fixture_root)
            original = fixture_root / "crates/lumenplot/src/error.rs"
            redirected = fixture_root / "crates/lumenplot/redirected_error.rs"
            redirected.write_text(original.read_text(encoding="utf-8"), encoding="utf-8")
            root_path = fixture_root / "crates/lumenplot/src/lib.rs"
            source = root_path.read_text(encoding="utf-8")
            self.assertIn("mod error;", source)
            root_path.write_text(
                source.replace("mod error;", '#[path = "../redirected_error.rs"]\nmod error;', 1),
                encoding="utf-8",
            )
            self.assert_external_consumer_matrix(fixture_root, self.required_surface_consumer())
            returncode, output = self.run_checker(fixture_root)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn("module path redirection is not allowed", output)

    def test_external_oracle_rejects_item_macro_generated_root_api(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            root_path = fixture_root / "crates/lumenplot/src/lib.rs"
            root_path.write_text(
                root_path.read_text(encoding="utf-8")
                + "\nmacro_rules! generated { () => { pub fn generated() {} }; }\ngenerated!();\n",
                encoding="utf-8",
            )
            consumer = "fn main() { let _ = lumenplot::generated; }\n"
            self.assert_external_consumer_matrix(fixture_root, consumer)
            returncode, output = self.run_checker(fixture_root)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn("crate-root macro", output)

    def test_external_oracle_rejects_compile_valid_hidden_derive_attribute(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            self.add_valid_hidden_facade(fixture_root)
            hidden_path = fixture_root / "crates/lumenplot/src/lib.rs"
            source = hidden_path.read_text(encoding="utf-8")
            marker = "    pub struct LinePngGeometry {"
            self.assertIn(marker, source)
            hidden_path.write_text(source.replace(marker, "    #[derive(Debug)]\n" + marker, 1), encoding="utf-8")
            self.assert_external_consumer_matrix(fixture_root, self.required_surface_consumer())
            returncode, output = self.run_checker(fixture_root)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn("hidden facade incidental public traits", output)

    def test_external_oracle_allows_non_api_attribute_inside_hidden_method_body(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            self.add_valid_hidden_facade(fixture_root)
            hidden_path = fixture_root / "crates/lumenplot/src/lib.rs"
            source = hidden_path.read_text(encoding="utf-8")
            marker = "pub fn render_line_png(request: OwnedLinePngRequest) -> Result<Vec<u8>, BridgeError> { unreachable!() }"
            replacement = "pub fn render_line_png(request: OwnedLinePngRequest) -> Result<Vec<u8>, BridgeError> { #[allow(unused_variables)] let _ = request; unreachable!() }"
            self.assertIn(marker, source)
            hidden_path.write_text(source.replace(marker, replacement, 1), encoding="utf-8")
            self.assert_external_consumer_matrix(fixture_root, self.required_surface_consumer())
            returncode, output = self.run_checker(fixture_root)
            self.assertEqual(returncode, 0, output)

    def test_cfg_test_private_hidden_module_is_a_non_shipping_control(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            self.add_valid_hidden_facade(fixture_root)
            hidden_path = fixture_root / "crates/lumenplot/src/lib.rs"
            source = hidden_path.read_text(encoding="utf-8")
            marker = "    pub fn render_line_png(request: OwnedLinePngRequest) -> Result<Vec<u8>, BridgeError> { unreachable!() }\n"
            insertion = """
    #[cfg(test)]
    mod tests {
        macro_rules! test_only_item { () => { pub struct TestOnly; }; }
        test_only_item!();
        #[allow(dead_code)]
        pub fn test_only_function() {}
    }
"""
            self.assertIn(marker, source)
            hidden_path.write_text(source.replace(marker, marker + insertion, 1), encoding="utf-8")
            self.assert_external_consumer_matrix(fixture_root, self.required_surface_consumer())
            returncode, output = self.run_checker(fixture_root)
            self.assertEqual(returncode, 0, output)

    def test_cfg_test_private_module_and_body_macro_are_non_shipping_controls(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            root_path = fixture_root / "crates/lumenplot/src/lib.rs"
            root_path.write_text(
                root_path.read_text(encoding="utf-8")
                + """

#[cfg(test)]
mod tests {
    macro_rules! test_only_item { () => { pub struct TestOnly; }; }
    test_only_item!();
    #[allow(dead_code)]
    pub fn test_only_function() {}
}
""",
                encoding="utf-8",
            )
            result = self.run_external_consumer(fixture_root, "fn main() {}\n", ("--all-features", "--all-targets"))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            returncode, output = self.run_checker(fixture_root)
            self.assertEqual(returncode, 0, output)

    def test_external_oracle_rejects_hidden_type_impl_moved_across_facade_file(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            self.add_valid_hidden_facade(fixture_root)
            view_path = fixture_root / "crates/lumenplot/src/view.rs"
            view_path.write_text(
                view_path.read_text(encoding="utf-8")
                + "\nuse crate::__private::BridgeError;\nimpl BridgeError { pub fn leaked(&self) -> &str { self.message() } }\n",
                encoding="utf-8",
            )
            consumer = "use lumenplot::__private::BridgeError; fn main() { let _ = BridgeError::leaked; }\n"
            self.assert_external_consumer_matrix(fixture_root, consumer)
            returncode, output = self.run_checker(fixture_root)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn("hidden facade implementation for 'BridgeError' is misplaced", output)

    def test_external_scope_matrix_distinguishes_unreachable_decoys_and_impl_members(self) -> None:
        cases = (
            (
                "nested private struct",
                "mod lexical_struct { pub struct HiddenFromRoot; }",
                "fn main() { let _: Option<lumenplot::HiddenFromRoot> = None; }\n",
                False,
            ),
            (
                "nested private function",
                "mod lexical_function { pub fn hidden_from_root() {} }",
                "fn main() { let _ = lumenplot::hidden_from_root; }\n",
                False,
            ),
            (
                "block private struct",
                "const _: () = { pub struct BlockOnly; () };",
                "fn main() { let _: Option<lumenplot::BlockOnly> = None; }\n",
                False,
            ),
            (
                "nested protected impl",
                "mod nested { use super::AxisRange; impl AxisRange { pub fn leaked_nested(&self) -> f64 { self.min() } } }",
                "use lumenplot::AxisRange; fn main() { let _ = AxisRange::leaked_nested; }\n",
                True,
            ),
            (
                "block protected impl",
                "const _: () = { impl crate::AxisRange { pub fn leaked_block(&self) -> f64 { self.min() } } () };",
                "use lumenplot::AxisRange; fn main() { let _ = AxisRange::leaked_block; }\n",
                True,
            ),
        )
        for label, insertion, consumer, externally_nameable in cases:
            with self.subTest(label=label):
                with self.fixture() as temporary:
                    fixture_root = Path(temporary)
                    target = fixture_root / "crates/lumenplot/src/view.rs" if "impl" in label else fixture_root / "crates/lumenplot/src/lib.rs"
                    target.write_text(target.read_text(encoding="utf-8") + "\n" + insertion + "\n", encoding="utf-8")
                    for flags in ((), ("--all-features", "--all-targets")):
                        result = self.run_external_consumer(fixture_root, consumer, flags)
                        if externally_nameable:
                            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        else:
                            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                    returncode, output = self.run_checker(fixture_root)
                    if externally_nameable:
                        self.assertNotEqual(returncode, 0, output)
                        self.assertIn("public method", output)
                    else:
                        self.assertEqual(returncode, 0, output)

    def test_valid_hidden_facade_is_conditional_and_passes(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            self.add_valid_hidden_facade(fixture_root)
            returncode, output = self.run_checker(fixture_root)
            self.assertEqual(returncode, 0, output)
            self.assertEqual(output, "workspace architecture: OK\n")

    def test_hidden_facade_requires_doc_hidden(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace("#[doc(hidden)]\npub mod __private", "pub mod __private", 1),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "hidden facade module must be doc-hidden")

    def test_hidden_facade_type_inventory_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "    pub struct BridgeError {",
                    "    pub struct Unexpected {",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "hidden facade public type is not allowed Unexpected")

    def test_hidden_facade_method_inventory_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "pub fn message(&self) -> &str { unreachable!() }",
                    "pub fn raw(&self) {}\n        pub fn message(&self) -> &str { unreachable!() }",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "hidden facade public method 'raw' on 'BridgeError' is not allowed",
        )

    def test_hidden_facade_signature_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "Result<Vec<u8>, BridgeError>",
                    "Result<Vec<u16>, BridgeError>",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "hidden facade render_line_png has an unexpected signature",
        )

    def test_hidden_facade_public_field_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "        viewport: [f64; 4],",
                    "        pub viewport: [f64; 4],",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "hidden facade type 'LinePngGeometry' exposes a public field")

    def test_hidden_facade_raw_formatting_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "    pub struct LinePngGeometry {",
                    "    #[derive(Debug)]\n    pub struct LinePngGeometry {",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "hidden facade incidental public traits on 'LinePngGeometry' are not allowed",
        )

    def test_hidden_facade_root_reexport_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            with path.open("a", encoding="utf-8") as source:
                source.write("\npub use __private::render_line_png;\n")

        self.assert_mutation_rejected(mutate, "package lumenplot: exact root export inventory mismatch")

    def test_hidden_facade_forbidden_signature_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "pub fn render_line_png(request: OwnedLinePngRequest)",
                    "pub fn render_line_png(request: *const u8)",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "hidden facade render_line_png leaks an internal type",
        )

    def test_hidden_facade_type_kind_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "    pub struct LinePngGeometry {",
                    "    pub enum LinePngGeometry {",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "hidden facade type 'LinePngGeometry' must be a struct",
        )

    def test_hidden_facade_type_generics_and_where_are_rejected(self) -> None:
        mutations = (
            ("type", "    pub struct LinePngGeometry {", "    pub struct LinePngGeometry<T> {"),
            ("lifetime", "    pub struct LinePngStyle {", "    pub struct LinePngStyle<'a> {"),
            (
                "const",
                "    pub struct OwnedLinePngRequest {",
                "    pub struct OwnedLinePngRequest<const N: usize> {",
            ),
            (
                "default",
                "    pub struct LinePngGeometry {",
                "    pub struct LinePngGeometry<T = f64> {",
            ),
            (
                "where",
                "    pub struct BridgeError {",
                "    pub struct BridgeError where T: Copy {",
            ),
        )
        for label, old, new in mutations:
            with self.subTest(label=label):
                self.assert_hidden_replacement_rejected(old, new, "hidden facade")

    def test_hidden_facade_multiline_type_declaration_is_rejected(self) -> None:
        self.assert_hidden_replacement_rejected(
            "    pub struct LinePngGeometry {",
            "    pub struct LinePngGeometry\n    {",
            "hidden facade type 'LinePngGeometry' has an unexpected declaration",
        )

    def test_hidden_facade_public_function_signatures_are_exact(self) -> None:
        mutations = (
            (
                "method generic",
                "pub fn new(viewport:",
                "pub fn new<T>(viewport:",
            ),
            (
                "method lifetime",
                "pub fn code(&self)",
                "pub fn code<'a>(&self)",
            ),
            (
                "method const",
                "pub fn new(viewport:",
                "pub fn new<const N: usize>(viewport:",
            ),
            (
                "method default",
                "pub fn new(viewport:",
                "pub fn new<T = f64>(viewport:",
            ),
            (
                "method where",
                "pub fn code(&self) -> ErrorCode {",
                "pub fn code(&self) -> ErrorCode where T: Copy {",
            ),
            (
                "free function generic",
                "pub fn render_line_png(",
                "pub fn render_line_png<T>(",
            ),
            (
                "free function where",
                "pub fn render_line_png(request: OwnedLinePngRequest) -> Result<Vec<u8>, BridgeError> {",
                "pub fn render_line_png(request: OwnedLinePngRequest) -> Result<Vec<u8>, BridgeError> where T: Copy {",
            ),
        )
        for label, old, new in mutations:
            with self.subTest(label=label):
                self.assert_hidden_replacement_rejected(old, new, "hidden facade")

    def test_hidden_facade_multiline_attribute_is_rejected(self) -> None:
        self.assert_hidden_replacement_rejected(
            "    pub struct LinePngGeometry {",
            "    #[repr(\n        C\n    )]\n    pub struct LinePngGeometry {",
            "hidden facade attributes",
        )

    def test_hidden_facade_forbidden_attributes_are_rejected(self) -> None:
        mutations = (
            ("no_mangle", "#[no_mangle]\n    pub fn render_line_png("),
            ("unsafe no_mangle", "#[unsafe(no_mangle)]\n    pub fn render_line_png("),
            ("export_name", "#[export_name = \"lp_render\"]\n    pub fn render_line_png("),
            (
                "unsafe export_name",
                "#[unsafe(export_name = \"lp_render\")]\n    pub fn render_line_png(",
            ),
            ("link_name", "#[link_name = \"lp_render\"]\n    pub fn render_line_png("),
            ("link_section", "#[link_section = \".text\"]\n    pub fn render_line_png("),
            ("used", "#[used]\n    pub fn render_line_png("),
            ("repr C", "#[repr(C)]\n    pub struct LinePngGeometry {"),
            ("repr transparent", "#[repr(transparent)]\n    pub struct LinePngStyle {"),
            ("non exhaustive", "#[non_exhaustive]\n    pub struct BridgeError {"),
            ("unknown type", "#[allow(dead_code)]\n    pub struct LinePngGeometry {"),
            ("unknown function", "#[inline]\n    pub fn render_line_png("),
            ("unknown method", "#[allow(dead_code)]\n        pub fn code(&self) -> ErrorCode {"),
        )
        for label, replacement in mutations:
            with self.subTest(label=label):
                if "pub struct" in replacement:
                    old = replacement.split("\n", 1)[1]
                elif "pub fn code" in replacement:
                    old = replacement.split("\n", 1)[1]
                else:
                    old = "    pub fn render_line_png("
                self.assert_hidden_replacement_rejected(old, replacement, "hidden facade attributes")

    def test_hidden_facade_nested_public_items_do_not_satisfy_direct_scope(self) -> None:
        mutations = (
            ("nested block", "    { pub struct NestedBlock {} }"),
            ("private inline module", "    mod nested { pub struct NestedModule {} }"),
            ("public inline module", "    pub mod nested { pub struct NestedPublicModule {} }"),
            ("nested method block", "    { pub fn nested<T>() {} }"),
            ("attribute plus nested item", "    #[doc(hidden)]\n    { pub fn nested() {} }"),
        )
        for label, insertion in mutations:
            with self.subTest(label=label):
                self.assert_hidden_insertion_rejected(insertion)

    def test_hidden_facade_complete_inventory_nested_in_inline_module_is_rejected(self) -> None:
        for visibility in ("private", "public"):
            with self.subTest(visibility=visibility):
                def mutate(root: Path, visibility: str = visibility) -> None:
                    self.add_valid_hidden_facade(root)
                    path = root / "crates/lumenplot/src/lib.rs"
                    source = path.read_text(encoding="utf-8")
                    marker = "pub mod __private {\n"
                    self.assertIn(marker, source)
                    source = source.replace(marker, marker + f"    {visibility} mod nested {{\n", 1)
                    self.assertTrue(source.endswith("}\n"))
                    source = source[:-2] + "    }\n}\n"
                    path.write_text(source, encoding="utf-8")

                self.assert_mutation_rejected(mutate, "hidden facade")

    def test_hidden_facade_external_module_declaration_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            source = path.read_text(encoding="utf-8")
            marker = "#[doc(hidden)]\npub mod __private {"
            start = source.index(marker)
            path.write_text(source[:start] + "#[doc(hidden)]\npub mod __private;\n", encoding="utf-8")

        self.assert_mutation_rejected(mutate, "external hidden facade module is not allowed")

    def test_hidden_facade_module_scope_expansions_are_rejected(self) -> None:
        mutations = (
            ("external module", "    mod generated;"),
            ("macro rules", "    macro_rules! helper { () => { pub struct Extra {} }; }"),
            ("allowlisted expansion", "    helper! { pub struct LinePngGeometry {} }"),
            ("extra expansion", "    helper! { pub fn leak() {} }"),
            ("include inside src", '    include!("generated.rs");'),
            ("include outside src", '    include!("../../outside.rs");'),
            ("include string", '    include_str!("../outside.txt");'),
            ("include bytes", '    include_bytes!("../outside.bin");'),
            ("cfg helper", '    cfg!(feature = "private");'),
            ("path qualified", "    crate::helper! { }"),
            ("multiline", "    helper!\n    { }"),
            ("raw identifier", "    r#helper! [ ]"),
            ("path qualified raw identifier", "    crate::r#helper! { }"),
        )
        for label, insertion in mutations:
            with self.subTest(label=label):
                self.assert_hidden_insertion_rejected(insertion)

    def test_hidden_facade_wrapped_at_non_root_scope_is_rejected(self) -> None:
        for label, opener in (
            ("outer private module", "mod outer {"),
            ("outer public module", "pub mod outer {"),
            ("outer block", "{"),
        ):
            with self.subTest(label=label):
                def mutate(root: Path, opener: str = opener) -> None:
                    self.add_valid_hidden_facade(root)
                    self.wrap_hidden_facade(root, opener)

                self.assert_mutation_rejected(mutate, "at crate root")

    def test_nested_hidden_module_declarations_are_rejected_even_with_direct_facade(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\nmod decoy { pub mod __private { } }\n",
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "declared exactly once")

    def test_nested_hidden_module_declarations_inside_non_brace_delimiters_are_rejected(self) -> None:
        for label, wrapper in (
            ("parentheses", "const DECOY: () = (#[doc(hidden)] pub mod __private {});"),
            ("brackets", "const DECOY: &[()] = &[#[doc(hidden)] pub mod __private {}];"),
        ):
            with self.subTest(label=label):
                def mutate(root: Path, wrapper: str = wrapper) -> None:
                    self.remove_hidden_facade(root)
                    path = root / "crates/lumenplot/src/lib.rs"
                    path.write_text(
                        path.read_text(encoding="utf-8") + "\n" + wrapper + "\n",
                        encoding="utf-8",
                    )

                self.assert_mutation_rejected(mutate, "at crate root")

    def test_root_public_inventory_ignores_nested_decoy_exports(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            source = path.read_text(encoding="utf-8")
            exports = """pub use error::{ErrorCategory, ErrorCode, PublicError};
pub use scene::{
    CommitReceipt, PlotScene, SceneRevision, SceneSnapshot, SceneTransaction, SeriesId,
};
pub use series::{SeriesData, SeriesTopology};
pub use view::{AxisRange, AxisScale, AxisScales, Viewport};"""
            self.assertIn(exports, source)
            replacement = "mod decoy {\n" + "\n".join(
                "    " + line if line else line for line in exports.splitlines()
            ) + "\n}\n"
            path.write_text(source.replace(exports, replacement, 1), encoding="utf-8")

        self.assert_mutation_rejected(mutate, "exact root export inventory mismatch")

    def test_root_macro_expansion_matrix_is_rejected(self) -> None:
        mutations = (
            ("include outside src", 'include!("../generated.rs");'),
            ("include inside src", 'include!("generated.rs");'),
            ("include string", 'const TEXT: &str = include_str!("../generated.txt");'),
            ("include bytes", 'const BYTES: &[u8] = include_bytes!("../generated.bin");'),
            ("macro rules wrapper", 'macro_rules! helper { () => { include!("generated.rs"); }; }'),
            ("macro wrapper invocation", 'helper! { include!("generated.rs"); }'),
            ("cfg helper", 'cfg!(feature = "private");'),
            ("path qualified", "crate::helper! { }"),
            ("raw identifier", "r#helper! [ ]"),
            ("multiline", "helper!\n{ }"),
            ("path qualified raw identifier", "crate::r#helper! { }"),
        )
        for label, insertion in mutations:
            with self.subTest(label=label):
                self.assert_root_insertion_rejected(insertion)

    def test_root_macro_decoys_in_comments_and_literals_are_ignored(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            source = path.read_text(encoding="utf-8")
            path.write_text(
                source
                + r'''
const TEXT: &str = "} include!(\"outside\"); macro_rules! fake { }";
const RAW: &str = r###"crate::fake! { pub mod __private {} }"###;
// include!("outside") macro_rules! fake { }
/* crate::fake! { pub mod __private {} } */
''',
                encoding="utf-8",
            )

        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            mutate(fixture_root)
            returncode, output = self.run_checker(fixture_root)
            self.assertEqual(returncode, 0, output)
            self.assertEqual(output, "workspace architecture: OK\n")

    def test_nested_test_and_body_macro_controls_are_allowed(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8")
                + """

#[cfg(test)]
mod tests {
    macro_rules! local_helper { () => { let _ = 1; }; }

    #[test]
    fn local_macro_is_below_root_scope() {
        local_helper!();
    }
}

fn body_macro_is_below_root_scope() {
    let values = vec![1, 2];
    let _ = matches!(values.first(), Some(_));
}
""",
                encoding="utf-8",
            )

        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            mutate(fixture_root)
            returncode, output = self.run_checker(fixture_root)
            self.assertEqual(returncode, 0, output)
            self.assertEqual(output, "workspace architecture: OK\n")

    def test_root_malformed_delimiters_are_rejected_fail_closed(self) -> None:
        for label, insertion in (
            ("unclosed root block", "const BROKEN: () = {"),
            ("unmatched root close", ")"),
            ("mismatched root delimiters", "helper!([}"),
        ):
            with self.subTest(label=label):
                self.assert_root_insertion_rejected(insertion, "delimiters")

    def test_hidden_facade_body_local_macro_controls_are_allowed(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            source = path.read_text(encoding="utf-8")
            old = "pub fn render_line_png(request: OwnedLinePngRequest) -> Result<Vec<u8>, BridgeError> { unreachable!() }"
            new = (
                "pub fn render_line_png(request: OwnedLinePngRequest) -> Result<Vec<u8>, BridgeError> { "
                "let values = vec![1, 2]; "
                "let matched = matches!(values.first(), Some(_)); "
                "let _ = (request, values, matched); "
                "unreachable!() }"
            )
            self.assertIn(old, source)
            path.write_text(source.replace(old, new, 1), encoding="utf-8")

        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            mutate(fixture_root)
            returncode, output = self.run_checker(fixture_root)
            self.assertEqual(returncode, 0, output)
            self.assertEqual(output, "workspace architecture: OK\n")

    def test_hidden_facade_literals_and_comments_do_not_create_scope_items(self) -> None:
        insertion = """
    const ORDINARY: &str = "} include! { pub struct Fake {}";
    const RAW: &str = r###"#[doc(hidden)] mod fake { helper! { pub fn fake() {} } }"###;
    // } include_bytes!("outside") pub struct Fake {}
    /* mod fake { macro_rules! fake { () => {} } } */
"""
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            self.add_valid_hidden_facade(fixture_root)
            path = fixture_root / "crates/lumenplot/src/lib.rs"
            source = path.read_text(encoding="utf-8")
            marker = "pub mod __private {\n"
            path.write_text(source.replace(marker, marker + insertion, 1), encoding="utf-8")
            returncode, output = self.run_checker(fixture_root)
            self.assertEqual(returncode, 0, output)
            self.assertEqual(output, "workspace architecture: OK\n")

    def test_hidden_facade_malformed_delimiters_are_rejected(self) -> None:
        for label, insertion in (
            ("mismatched", "    helper!([}"),
            ("unclosed block", "    const BROKEN: () = {"),
            ("unmatched close", "    )"),
        ):
            with self.subTest(label=label):
                self.assert_hidden_insertion_rejected(insertion, "delimiters")

    def test_hidden_facade_public_items_cannot_share_a_line(self) -> None:
        mutations = (
            (
                "extra type",
                "    }\n\n    impl LinePngGeometry",
                "    } pub struct Unexpected {}\n\n    impl LinePngGeometry",
            ),
            (
                "extra free function",
                "pub fn render_line_png(request: OwnedLinePngRequest) -> Result<Vec<u8>, BridgeError> { unreachable!() }",
                "pub fn render_line_png(request: OwnedLinePngRequest) -> Result<Vec<u8>, BridgeError> { unreachable!() } pub fn leak() {}",
            ),
            (
                "extra method",
                "pub fn code(&self) -> ErrorCode { unreachable!() }",
                "pub fn code(&self) -> ErrorCode { unreachable!() } pub fn raw(&self) {}",
            ),
            (
                "public field",
                "        viewport: [f64; 4],",
                "        viewport: [f64; 4], pub exposed: u8,",
            ),
            (
                "extra trait",
                "    }\n\n    impl LinePngGeometry",
                "    } pub trait Unexpected {}\n\n    impl LinePngGeometry",
            ),
        )
        for label, old, new in mutations:
            with self.subTest(label=label):
                self.assert_hidden_replacement_rejected(old, new, "hidden facade public item is not allowlisted")

    def test_hidden_facade_raw_strings_are_ignored_by_code_scans(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            source = path.read_text(encoding="utf-8")
            source = source.replace(
                "pub mod __private {\n",
                'pub mod __private {\n    const RAW: &str = r#"} #[doc(hidden)] pub fn leak() {"#;\n',
                1,
            )
            path.write_text(source, encoding="utf-8")

        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            mutate(fixture_root)
            returncode, output = self.run_checker(fixture_root)
            self.assertEqual(returncode, 0, output)
            self.assertEqual(output, "workspace architecture: OK\n")

    def test_hidden_facade_unterminated_raw_string_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            self.add_valid_hidden_facade(root)
            path = root / "crates/lumenplot/src/lib.rs"
            source = path.read_text(encoding="utf-8")
            source = source.replace(
                "pub mod __private {\n",
                'pub mod __private {\n    const RAW: &str = r#"unterminated;\n',
                1,
            )
            path.write_text(source, encoding="utf-8")

        self.assert_mutation_rejected(mutate, "malformed Rust syntax")

    def test_unmodified_fixture_passes(self) -> None:
        with self.fixture() as temporary:
            returncode, output = self.run_checker(Path(temporary))
            self.assertEqual(returncode, 0, output)
            self.assertEqual(output, "workspace architecture: OK\n")

    def test_missing_package_is_rejected(self) -> None:
        self.assert_mutation_rejected(
            lambda root: (root / "crates/lumenplot-export/Cargo.toml").unlink(),
            "missing package path crates/lumenplot-export",
        )

    def test_extra_package_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            extra = root / "crates/lumenplot-extra"
            extra.mkdir()
            (extra / "Cargo.toml").write_text(
                "[package]\nname = \"lumenplot-extra\"\nversion = \"0.1.0\"\n",
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "unexpected package path crates/lumenplot-extra/Cargo.toml")

    def test_wrong_package_name_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot/Cargo.toml"
            path.write_text(
                path.read_text(encoding="utf-8").replace('name = "lumenplot"', 'name = "not-lumenplot"'),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "expected name 'lumenplot'")

    def test_publish_guard_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/Cargo.toml"
            path.write_text(
                path.read_text(encoding="utf-8").replace("publish = false", "publish = true"),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "package lumenplot-engine: publish must be false")

    def test_external_dependency_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/Cargo.toml"
            path.write_text(
                path.read_text(encoding="utf-8") + '\n[dependencies]\nserde = "1"\n',
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "external dependency 'serde' is not allowed")

    def test_wrong_edge_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-export/Cargo.toml"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    'lumenplot-engine = { path = "../lumenplot-engine", version = "0.1.0" }',
                    'lumenplot-render-api = { path = "../lumenplot-render-api", version = "0.1.0" }',
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot-export: dependency edge 'lumenplot-render-api' is not allowed",
        )

    def test_facade_public_expansion_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(path.read_text(encoding="utf-8") + "\npub struct Unexpected;\n", encoding="utf-8")

        self.assert_mutation_rejected(mutate, "package lumenplot: public item is not allowed")

    def test_render_api_to_wgpu_edge_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-render-api/Cargo.toml"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "[dependencies]\n",
                    '[dependencies]\nlumenplot-render-wgpu = { path = "../lumenplot-render-wgpu", version = "0.1.0" }\n',
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot-render-api: dependency edge 'lumenplot-render-wgpu' is not allowed",
        )

    def test_facade_internal_reexport_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(path.read_text(encoding="utf-8") + "\npub use lumenplot_engine;\n", encoding="utf-8")

        self.assert_mutation_rejected(mutate, "package lumenplot: internal re-export is not allowed")

    def test_unsafe_code_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/lib.rs"
            path.write_text(path.read_text(encoding="utf-8") + "\nunsafe fn forbidden() {}\n", encoding="utf-8")

        self.assert_mutation_rejected(mutate, "unsafe code is not allowed")

    def test_engine_root_module_exposure_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace("mod data;", "pub mod data;"),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "root module visibility is too broad")

    def test_engine_bridge_must_remain_hidden(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace("#[doc(hidden)]\npub mod bridge;", "pub mod bridge;"),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "only the hidden bridge may be public")

    def test_engine_frame_module_must_remain_private(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace("mod frame;", "pub mod frame;"),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "root module visibility is too broad")

    def test_engine_frame_source_file_is_required(self) -> None:
        self.assert_mutation_rejected(
            lambda root: (root / "crates/lumenplot-engine/src/frame.rs").unlink(),
            "missing src/frame.rs",
        )

    def test_engine_bridge_reexport_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/bridge.rs"
            path.write_text(
                path.read_text(encoding="utf-8") + "\npub use crate::data::Point;\n",
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "bridge re-export is not allowed")

    def test_engine_bridge_extra_type_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/bridge.rs"
            path.write_text(path.read_text(encoding="utf-8") + "\npub struct RawChunk;\n", encoding="utf-8")

        self.assert_mutation_rejected(mutate, "bridge public type is not allowed RawChunk")

    def test_engine_bridge_raw_method_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/bridge.rs"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\nimpl PlotScene {\n    pub fn raw(&self) -> crate::data::Chunk { unreachable!() }\n}\n",
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "bridge public method 'raw' is not allowed")

    def test_engine_bridge_line_frame_method_inventory_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/bridge.rs"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\nimpl LineFrame { pub fn raw(&self) {} }\n",
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "bridge public method 'raw' on 'LineFrame' is not allowed",
        )

    def test_engine_bridge_line_frame_public_field_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/bridge.rs"
            source = path.read_text(encoding="utf-8")
            path.write_text(
                source.replace("    revision: SceneRevision,", "    pub revision: SceneRevision,", 1),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "bridge type 'LineFrame' exposes a field",
        )

    def test_engine_bridge_line_frame_trait_inventory_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/bridge.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "pub struct LineFrame {",
                    "#[derive(Debug)]\npub struct LineFrame {",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "bridge trait inventory mismatch for 'LineFrame'",
        )

    def test_engine_bridge_line_frame_resolver_is_required(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/bridge.rs"
            source = path.read_text(encoding="utf-8")
            path.write_text(
                source.replace(
                    "    pub fn resolve_line_frame(&self, spec: &LineFrameSpec) -> Result<LineFrame, SceneError> {\n        crate::frame::resolve_line_frame(&self.inner, spec).map_err(Into::into)\n    }\n",
                    "",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "bridge public method inventory mismatch for 'SceneSnapshot'",
        )

    def test_engine_bridge_render_packet_signature_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/bridge.rs"
            source = path.read_text(encoding="utf-8")
            path.write_text(
                source.replace(
                    "pub fn series(&self) -> &[LineSeries] {",
                    "pub fn series(&self) -> RenderPacket {",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "bridge public signature uses forbidden RenderPacket",
        )

    def test_engine_bridge_phase2_signature_return_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/bridge.rs"
            source = path.read_text(encoding="utf-8")
            path.write_text(
                source.replace(
                    "pub fn segments(&self) -> &[LineSegment] {",
                    "pub fn segments(&self) -> &[LinePoint] {",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "bridge public method 'segments' on 'LineSeries' has an unexpected signature",
        )

    def test_engine_bridge_tuple_field_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/bridge.rs"
            source = path.read_text(encoding="utf-8")
            path.write_text(source.replace("pub struct SceneRevision(u64);", "pub struct SceneRevision(pub u64);"), encoding="utf-8")

        self.assert_mutation_rejected(mutate, "bridge tuple field is public")

    def test_series_data_debug_derivation_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/bridge.rs"
            source = path.read_text(encoding="utf-8")
            path.write_text(
                source.replace("pub struct SeriesData {", "#[derive(Debug)]\npub struct SeriesData {"),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "SeriesData raw formatting is not allowed")

    def test_series_data_formatting_impl_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/bridge.rs"
            with path.open("a", encoding="utf-8") as source:
                source.write("\nimpl fmt::Display for SeriesData {}\n")

        self.assert_mutation_rejected(mutate, "SeriesData raw formatting is not allowed")

    def test_engine_concrete_backend_code_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-engine/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8") + "\nfn forbidden() { let _: wgpu::Thing; }\n",
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "concrete frontend/backend code is not allowed")

    def test_facade_extra_source_module_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            (root / "crates/lumenplot/src/extra.rs").write_text("", encoding="utf-8")

        self.assert_mutation_rejected(mutate, "package lumenplot: source inventory mismatch")

    def test_facade_public_module_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace("mod error;", "pub mod error;"),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "package lumenplot: public module is not allowed")

    def test_facade_root_export_expansion_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8") + "\npub use scene::PlotScene as Scene;\n",
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "package lumenplot: export aliases are not allowed")

    def test_facade_public_method_expansion_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot/src/view.rs"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\nimpl AxisRange { pub fn raw(&self) {} }\n",
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot: public method 'raw' on 'AxisRange' is not allowed",
        )

    def test_facade_non_exhaustive_enum_removal_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot/src/error.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "#[non_exhaustive]\npub enum ErrorCode {",
                    "pub enum ErrorCode {",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot: facade enum 'ErrorCode' must remain non-exhaustive",
        )

    def test_facade_identity_trait_expansion_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot/src/scene.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash)]\npub struct SceneRevision",
                    "#[derive(Copy, Clone, Debug, Eq, PartialEq, Hash, Ord)]\npub struct SceneRevision",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "trait inventory mismatch for 'SceneRevision'")

    def test_facade_snapshot_trait_expansion_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot/src/scene.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "#[derive(Clone)]\npub struct SceneSnapshot",
                    "#[derive(Clone, Debug)]\npub struct SceneSnapshot",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "trait inventory mismatch for 'SceneSnapshot'")

    def test_facade_public_field_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot/src/view.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "    inner: EngineAxisRange,",
                    "    pub inner: EngineAxisRange,",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot: facade type 'AxisRange' exposes a public field",
        )

    def test_facade_public_signature_leak_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot/src/view.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "pub fn min(&self) -> f64 {",
                    "pub fn min(&self) -> EngineAxisRange {",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot: public method 'min' leaks an internal type",
        )

    def test_facade_default_impl_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot/src/view.rs"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\nimpl Default for AxisRange { fn default() -> Self { unreachable!() } }\n",
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "public trait implementation 'Default' for 'AxisRange' is not allowed",
        )

    def test_facade_unsafe_code_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(path.read_text(encoding="utf-8") + "\nunsafe fn forbidden() {}\n", encoding="utf-8")

        self.assert_mutation_rejected(mutate, "package lumenplot: unsafe code is not allowed")

    def test_facade_serialization_code_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot/src/lib.rs"
            path.write_text(path.read_text(encoding="utf-8") + "\nfn forbidden() { let _ = serde; }\n", encoding="utf-8")

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot: serialization or wire code is not allowed",
        )

    def test_facade_runtime_dependency_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot/Cargo.toml"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    'lumenplot-export = { path = "../lumenplot-export", version = "0.1.0" }',
                    'lumenplot-runtime = { path = "../lumenplot-runtime", version = "0.1.0" }',
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot: dependency edge 'lumenplot-runtime' is not allowed",
        )

    def test_export_source_inventory_is_exact(self) -> None:
        self.assert_mutation_rejected(
            lambda root: (root / "crates/lumenplot-export/src/raster.rs").unlink(),
            "package lumenplot-export: source inventory mismatch",
        )

    def test_export_extra_source_module_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            (root / "crates/lumenplot-export/src/extra.rs").write_text("", encoding="utf-8")

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot-export: source inventory mismatch",
        )

    def test_export_pixmap_sink_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-export/src/raster.rs"
            path.write_text(
                path.read_text(encoding="utf-8") + "\nfn forbidden() { let _ = tiny_skia::Pixmap::new(1, 1); }\n",
                encoding="utf-8",
            )

        self.assert_mutation_rejected(mutate, "forbidden Pixmap color sink is not allowed")

    def test_export_bridge_inventory_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-export/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "pub mod bridge {",
                    "pub mod bridge {\n    pub use crate::png::CappedWriter;",
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot-export: exact bridge export inventory mismatch",
        )

    def test_export_public_method_inventory_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-export/src/png.rs"
            path.write_text(
                path.read_text(encoding="utf-8") + "\nimpl PngSpec { pub fn raw(&self) {} }\n",
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot-export: public method 'raw' on 'PngSpec' is not allowed",
        )

    def test_export_dependency_feature_set_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-export/Cargo.toml"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    'features = ["std"]',
                    'features = ["std", "png-format"]',
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "external dependency 'tiny-skia' has an unexpected specification",
        )

    def test_export_rejected_dependency_is_not_allowlisted(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-export/Cargo.toml"
            path.write_text(
                path.read_text(encoding="utf-8") + '\nserde = "1"\n',
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "external dependency 'serde' is not allowed",
        )

    def test_export_public_signature_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-export/src/png.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "lumenplot_engine::bridge::LineFrame",
                    "lumenplot_engine::bridge::SceneSnapshot",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "encode_line_frame_png has an unexpected signature",
        )


    def add_bench_module_files(self, root: Path) -> None:
        """Write the exact accepted bench inventory except ``src/lib.rs``."""

        source_dir = root / "crates/lumenplot-bench/src"
        bodies = {
            "main.rs": "#![forbid(unsafe_code)]\n\nfn main() {}\n",
            "clocks.rs": "pub(crate) fn scheduler_now_ns() -> u64 {\n    0\n}\n",
            "manifest.rs": "pub(crate) fn emit() -> String {\n    String::new()\n}\n",
            "runner.rs": "pub(crate) fn blocks() -> usize {\n    5\n}\n",
        }
        for name, body in bodies.items():
            (source_dir / name).write_text(body, encoding="utf-8")

    def write_bench_lib(self, root: Path, source: str) -> None:
        path = root / "crates/lumenplot-bench/src/lib.rs"
        path.write_text(source, encoding="utf-8")

    def activate_bench_lane(self, root: Path) -> None:
        self.add_bench_module_files(root)
        self.write_bench_lib(
            root,
            "//! Private O-08 benchmark harness documentation stub.\n"
            "//!\n"
            "//! The runner lives in the binary target modules.\n",
        )

    def test_bench_stub_source_still_enforced_without_sentinel(self) -> None:
        def mutate(root: Path) -> None:
            self.write_bench_lib(
                root,
                "//! stub\n\nfn hidden() {}\n",
            )

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot-bench: source must be documentation-only",
        )

    def test_bench_active_inventory_accepts_the_exact_file_set(self) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            self.activate_bench_lane(fixture_root)
            returncode, output = self.run_checker(fixture_root)
            self.assertEqual(returncode, 0, output)

    def test_bench_active_inventory_rejects_missing_module_file(self) -> None:
        def mutate(root: Path) -> None:
            self.activate_bench_lane(root)
            (root / "crates/lumenplot-bench/src/clocks.rs").unlink()

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot-bench: source must contain exactly",
        )

    def test_bench_active_inventory_rejects_extra_module_file(self) -> None:
        def mutate(root: Path) -> None:
            self.activate_bench_lane(root)
            path = root / "crates/lumenplot-bench/src/extra.rs"
            path.write_text("pub(crate) fn stray() {}\n", encoding="utf-8")

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot-bench: source must contain exactly",
        )

    def test_bench_active_inventory_rejects_nested_module_directory(self) -> None:
        def mutate(root: Path) -> None:
            self.activate_bench_lane(root)
            nested = root / "crates/lumenplot-bench/src/util"
            nested.mkdir()
            (nested / "mod.rs").write_text("pub(crate) fn deep() {}\n", encoding="utf-8")

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot-bench: source must contain exactly",
        )

    def test_bench_active_lib_rs_public_item_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            self.add_bench_module_files(root)
            self.write_bench_lib(
                root,
                "//! stub\n\npub fn exported() {}\n",
            )

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot-bench: public item is not allowed",
        )

    def test_bench_active_dependency_edge_drift_remains_rejected(self) -> None:
        def mutate(root: Path) -> None:
            self.activate_bench_lane(root)
            path = root / "crates/lumenplot-bench/Cargo.toml"
            text = path.read_text(encoding="utf-8")
            marker = "[dependencies]\n"
            self.assertIn(marker, text)
            path.write_text(text.replace(marker, marker + 'serde = "1"\n'), encoding="utf-8")

        self.assert_mutation_rejected(
            mutate,
            "external dependency 'serde' is not allowed",
        )

    def test_bench_active_dev_dependency_table_remains_rejected(self) -> None:
        def mutate(root: Path) -> None:
            self.activate_bench_lane(root)
            path = root / "crates/lumenplot-bench/Cargo.toml"
            path.write_text(
                path.read_text(encoding="utf-8") + '\n[dev-dependencies]\ntrybuild = "1"\n',
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "only runtime path dependencies are allowed",
        )


    def test_export_public_field_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-export/src/png.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "    output_dpi: f64,",
                    "    pub output_dpi: f64,",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_mutation_rejected(
            mutate,
            "package lumenplot-export: type 'PngSpec' exposes a public field",
        )


class Phase3A2WheelEvidenceMutationTests(unittest.TestCase):
    IMAGE = (
        "quay.io/pypa/manylinux_2_28_x86_64:2026.08.15-1@"
        "sha256:0c87ccb5996dab6c3b7612ee4fda7b80c4ab3c44a86c2541e4a872afdf4f131b"
    )
    CONFIG_DIGEST = "sha256:fd0c576d9673648a125bffeaea6acb762d8bc52d97da9034dfdbe00f98a17dd5"
    MATURIN_HASH = "dfc54ae32e6fcb18302193ab9a30b0b25eefffba994ae13238974805533ef75e"
    RUSTUP_INIT_HASH = "4acc9acc76d5079515b46346a485974457b5a79893cfb01112423c89aeb5aa10"
    NUMPY_HASHES = {
        "cp311": "89cd468399cfd2504718f0ba50e410dca55a170b61a02ad92bb18c8a65186e93",
        "cp312": "90f9849678c75fe7afa2d348ac842c168b0a4d3d61919687216dfc547976d853",
        "cp313": "a7830bab239b79cda9c08c2da014761cafb48da6150e1da17ac06283f43b6089",
        "cp314": "a2c306dea656c12c68f51f4cea133cbe78ca7435eb28c735eac1d3ebe73be6e8",
    }

    def fixture(self) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory(prefix="lumenplot-phase3a2-wheel-")
        root = Path(temporary.name)
        shutil.copy2(ROOT / "Cargo.toml", root / "Cargo.toml")
        shutil.copy2(ROOT / "Cargo.lock", root / "Cargo.lock")
        shutil.copytree(ROOT / "crates", root / "crates")
        reset_python_bridge_to_baseline(root)
        scripts = root / "scripts"
        scripts.mkdir()
        shutil.copy2(CHECKER, scripts / CHECKER.name)
        inventory = root / "docs" / "security"
        inventory.mkdir(parents=True)
        shutil.copy2(ROOT / "docs/security/pinned-actions.yml", inventory / "pinned-actions.yml")

        bridge_manifest = root / "crates/lumenplot-python/Cargo.toml"
        bridge_manifest.write_text(
            bridge_manifest.read_text(encoding="utf-8").replace(
                'lumenplot = { path = "../lumenplot", version = "0.1.0" }',
                'lumenplot = { path = "../lumenplot", version = "0.1.0" }\n'
                'pyo3 = { version = "=0.29.2", default-features = false, features = ["macros", "extension-module", "abi3-py311"] }\n'
                'numpy = { version = "=0.29.0", default-features = false }',
            ),
            encoding="utf-8",
        )
        (root / "crates/lumenplot-python/src/lib.rs").write_text(
            """use pyo3::prelude::*;

#[pyfunction]
fn render_line_png() -> PyResult<Vec<u8>> {
    Ok(Vec::new())
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(render_line_png, module)?)?;
    Ok(())
}
""",
            encoding="utf-8",
        )
        (root / "pyproject.toml").write_text(
            """[build-system]
requires = ["maturin==1.14.1"]
build-backend = "maturin"

[project]
name = "lumenplot-mpl"
version = "0.1.0"
requires-python = ">=3.11,<3.15"
dependencies = ["numpy==2.4.6"]
""",
            encoding="utf-8",
        )
        package = root / "python/lumenplot_mpl"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(
            """from ._native import render_line_png


class LumenPlotError(RuntimeError):
    pass
""",
            encoding="utf-8",
        )
        (package / "_native.pyi").write_text("def render_line_png() -> bytes: ...\n", encoding="utf-8")
        (package / "py.typed").write_text("", encoding="utf-8")
        workflows = root / ".github/workflows"
        workflows.mkdir(parents=True)
        (workflows / "phase3a2-wheel.yml").write_text(self.valid_workflow(), encoding="utf-8")
        subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "fixture"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "fixture source"], cwd=root, check=True)
        source_commit = subprocess.check_output(
            ["git", "rev-parse", "--verify", "HEAD"], cwd=root, text=True
        ).strip()
        (root / "phase3a2-wheel-evidence.json").write_text(
            json.dumps(self.valid_manifest(source_commit), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return temporary

    def valid_workflow(self) -> str:
        return f"""name: Phase-3A2 wheel evidence

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

env:
  # Hash-pinned rustup-init bootstrap binary for x86_64-unknown-linux-gnu.
  PHASE3A2_RUSTUP_INIT_SHA256: "{self.RUSTUP_INIT_HASH}"

jobs:
  wheel:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
      - uses: dtolnay/rust-toolchain@032958afbdc797a9164d3bc0b56325c1308924a5 # 1.97.1
      - name: Build in pinned manylinux image
        run: |
          IMAGE='{self.IMAGE}'
          mkdir -p wheelhouse evidence
          docker pull --platform=linux/amd64 "$IMAGE"
          IMAGE_CONFIG_DIGEST="$(docker image inspect --format '{{{{.Id}}}}' "$IMAGE")"
          test "$IMAGE_CONFIG_DIGEST" = "{self.CONFIG_DIGEST}"
          docker run --rm --platform=linux/amd64 --network=bridge --read-only --user 1000:1000 --cap-drop=ALL --security-opt=no-new-privileges -e PHASE3A2_RUSTUP_INIT_SHA256 --tmpfs /tmp:rw,noexec,nosuid,nodev --tmpfs /tmp/work:rw,exec,nosuid,nodev -v "$PWD:/src:ro" -v "$PWD/wheelhouse:/cache/wheelhouse:rw" "$IMAGE" bash -eu -o pipefail -c "$(cat <<'PREFETCH'
            printf '%s\\n' "prefetch-inner-shell: heredoc reached container shell, cwd=$(pwd)"
            export CARGO_HOME=/usr/local/cargo
            export RUSTUP_HOME=/usr/local/cargo/rustup
            # /tmp stays noexec: cargo's default per-install staging target lives
            # under $TMPDIR, where build-script binaries cannot be executed.
            export CARGO_TARGET_DIR=/tmp/work/cargo-target
            printf '%s  rustup-init\\n' "$PHASE3A2_RUSTUP_INIT_SHA256" > /tmp/rustup-init.sha256
            curl --proto '=https' --tlsv1.2 --silent --show-error --location https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/rustup-init > /tmp/work/rustup-init
            printf '%s\\n' "prefetch-inner-shell: digest file staged, cwd=$(pwd)"
            # The checksum file lists the bare name `rustup-init`, so the check
            # must resolve it against the exec-capable staging directory; the
            # workdir is read-only /src.
            ( cd /tmp/work && sha256sum --check /tmp/rustup-init.sha256 )
            # curl redirection creates the file mode 0644; direct execve needs the
            # executable bit set before the bootstrap can start.
            chmod +x /tmp/work/rustup-init
            # /tmp stays noexec; the verified ELF bootstrap is executed directly
            # from the exec-mounted work tmpfs.
            /tmp/work/rustup-init -y --no-modify-path --profile minimal --default-toolchain 1.89.0
            export PATH=/usr/local/cargo/bin:$PATH
            rustc --version
            cargo --version
            cargo fetch --locked
            cargo metadata --locked --format-version 1 > /cache/wheelhouse/cargo-metadata.json
            cargo install --locked cargo-deny@0.20.2
            cargo deny check
            # pip's `--hash` is a requirements-file-only option: no pip release
            # registers it as a CLI flag, so each reviewed input carries its pin
            # in a one-line requirements file consumed with --require-hashes.
            printf '%s\\n' 'maturin==1.14.1 --hash=sha256:{self.MATURIN_HASH}' > /tmp/wheelhouse-maturin.txt
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --require-hashes --dest /cache/wheelhouse -r /tmp/wheelhouse-maturin.txt
            printf '%s\\n' 'numpy==2.4.6 --hash=sha256:{self.NUMPY_HASHES['cp311']}' > /tmp/wheelhouse-numpy311.txt
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --require-hashes --dest /cache/wheelhouse --platform manylinux_2_28_x86_64 --implementation cp --python-version 311 --abi cp311 -r /tmp/wheelhouse-numpy311.txt
            printf '%s\\n' 'numpy==2.4.6 --hash=sha256:{self.NUMPY_HASHES['cp312']}' > /tmp/wheelhouse-numpy312.txt
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --require-hashes --dest /cache/wheelhouse --platform manylinux_2_28_x86_64 --implementation cp --python-version 312 --abi cp312 -r /tmp/wheelhouse-numpy312.txt
            printf '%s\\n' 'numpy==2.4.6 --hash=sha256:{self.NUMPY_HASHES['cp313']}' > /tmp/wheelhouse-numpy313.txt
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --require-hashes --dest /cache/wheelhouse --platform manylinux_2_28_x86_64 --implementation cp --python-version 313 --abi cp313 -r /tmp/wheelhouse-numpy313.txt
            printf '%s\\n' 'numpy==2.4.6 --hash=sha256:{self.NUMPY_HASHES['cp314']}' > /tmp/wheelhouse-numpy314.txt
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --require-hashes --dest /cache/wheelhouse --platform manylinux_2_28_x86_64 --implementation cp --python-version 314 --abi cp314 -r /tmp/wheelhouse-numpy314.txt
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --dest /cache/wheelhouse auditwheel==6.8.0
            sha256sum /cache/wheelhouse/auditwheel-6.8.0-*.whl > /cache/wheelhouse/auditwheel-sha256.txt
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --dest /cache/wheelhouse abi3audit==0.0.26
            sha256sum /cache/wheelhouse/abi3audit-0.0.26-*.whl > /cache/wheelhouse/abi3audit-sha256.txt
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse packaging==26.3
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse pyelftools==0.33
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse abi3info==2025.11.29
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse kaitaistruct==0.11
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse pefile==2024.8.26
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse requests==2.34.2
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse charset-normalizer==3.5.1
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse requests-cache==1.3.3
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse url-normalize==1.4.3
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse attrs==26.1.0
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse cattrs==24.1.2
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse urllib3==2.7.0
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse certifi==2026.7.22
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse idna==3.19
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse six==1.17.0
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse rich==15.0.0
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse markdown-it-py==4.2.0
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse pygments==2.21.0
            /opt/python/cp311-cp311/bin/python -m pip download --no-deps --only-binary=:all: --dest /cache/wheelhouse mdurl==0.1.2
          PREFETCH
          )"
          docker run --rm --platform=linux/amd64 --network=none --read-only --user 1000:1000 --cap-drop=ALL --security-opt=no-new-privileges --tmpfs /tmp:rw,noexec,nosuid,nodev --tmpfs /tmp/work:rw,exec,nosuid,nodev -v "$PWD:/src:ro" -v "$PWD/wheelhouse:/cache/wheelhouse:ro" -v "$PWD/evidence:/evidence:rw" "$IMAGE" bash -eu -o pipefail -c "$(cat <<'BUILD'
            cd /src
            export CARGO_HOME=/usr/local/cargo
            export RUSTUP_HOME=/usr/local/cargo/rustup
            export PATH=/usr/local/cargo/bin:$PATH
            RUSTUP_TOOLCHAIN=1.89.0 rustc --version
            CARGO_VERSION="$(cargo metadata --locked --offline --format-version 1 | python -c 'import json,sys; print(next(p["version"] for p in json.load(sys.stdin)["packages"] if p["name"] == "lumenplot-python"))')"
            SOURCE_COMMIT="$(git rev-parse --verify HEAD)"
            python -m pip install --no-index --no-cache-dir --only-binary=:all: --require-hashes --find-links=/cache/wheelhouse maturin==1.14.1 --hash=sha256:{self.MATURIN_HASH}
            export PYTHONPATH=/tmp/work/build-site
            cargo build --release --locked --offline
            maturin build --release --locked --offline --interpreter /opt/python/cp311-cp311/bin/python --compatibility manylinux_2_28
            WHEEL="dist/lumenplot_mpl-$CARGO_VERSION-cp311-abi3-manylinux_2_28_x86_64.whl"
            NATIVE_OBJECT=target/release/liblumenplot_python.so
            WHEEL_SHA256="$(sha256sum "$WHEEL" | cut -d' ' -f1)"
            sha256sum "$WHEEL" > "$WHEEL.sha256"
            sha256sum --check "$WHEEL.sha256"
            unzip -t "$WHEEL"
            unzip -p "$WHEEL" '*/METADATA' | grep '^Version:'
            unzip -p "$WHEEL" '*/WHEEL' | grep 'cp311-abi3-manylinux_2_28_x86_64'
            unzip -p "$WHEEL" '*/RECORD' | python /cache/check-record.py
            WHEEL_VERSION="$(unzip -p "$WHEEL" '*/METADATA' | awk -F': ' '$1 == "Version" {{print $2}}')"
            test "$WHEEL_VERSION" = "$CARGO_VERSION"
            auditwheel show --json "$WHEEL" > /evidence/auditwheel.json
            /opt/python/cp311-cp311/bin/python -c 'import json; d=json.load(open("/evidence/auditwheel.json")); tag=d.get("overall_tag",""); assert "manylinux_2_28" in tag, d'
            READELF_OUT="$(readelf -d "$NATIVE_OBJECT")"
            printf '%s\\n' "$READELF_OUT"
            test -n "$READELF_OUT"
            test "$(printf '%s\\n' "$READELF_OUT" | grep -cE '\\(NEEDED\)')" -gt 0
            test "$(printf '%s\\n' "$READELF_OUT" | grep -cE '\\(RPATH\)')" = "0"
            RUNPATH_VALUE="$(printf '%s\\n' "$READELF_OUT" | sed -n '/(\\(RUNPATH\))/s/.*\\[\\([^]]*\)\].*/\\1/p')"
            if printf '%s\\n' "$READELF_OUT" | grep -Eq 'libpython|libcuda'; then printf '%s\\n' 'unexpected shared library' >&2; exit 1; fi
            abi3audit "$WHEEL"
            python /cache/check-sbom.py --format 'CycloneDX 1.5' --cargo-metadata /cache/wheelhouse/cargo-metadata.json
            /opt/python/cp311-cp311/bin/python -m venv --clear /tmp/lp-3.11
            /tmp/lp-3.11/bin/python -m pip install --no-index --no-cache-dir --only-binary=:all: --require-hashes --find-links=/cache/wheelhouse numpy==2.4.6 --hash=sha256:{self.NUMPY_HASHES['cp311']}
            # pip's --hash only exists inside requirements files.
            printf '%s\\n' "$WHEEL --hash=sha256:$WHEEL_SHA256" > /tmp/helper-wheel311.txt
            /tmp/lp-3.11/bin/python -m pip install --no-index --no-cache-dir --only-binary=:all: --require-hashes --find-links=/cache/wheelhouse -r /tmp/helper-wheel311.txt
            sha256sum --check "$WHEEL.sha256"
            INPUT_WHEEL_SHA256="$(sha256sum "$WHEEL" | cut -d' ' -f1)"
            test "$INPUT_WHEEL_SHA256" = "$WHEEL_SHA256"
            /tmp/lp-3.11/bin/python -c 'from lumenplot_mpl import _native, LumenPlotError; _native.render_line_png("invalid-input"); print("invalid-input"); _native.render_line_png(np.array([0.0, 1.0]), np.array([0.0, 1.0]), viewport=(0.0, 1.0, 0.0, 1.0), canvas=(4.0, 4.0), plot_rect=(0.0, 0.0, 4.0, 4.0), logical_units_per_inch=72.0, output_dpi=72.0, line_rgba=(0, 0, 0, 255), line_width=1.0, background_rgba=(255, 255, 255, 255)); print("helper-success")'
            INSTALLED_VERSION="$(/tmp/lp-3.11/bin/python -c 'import importlib.metadata; print(importlib.metadata.version("lumenplot-mpl"))')"
            test "$INSTALLED_VERSION" = "$CARGO_VERSION"
            /opt/python/cp312-cp312/bin/python -m venv --clear /tmp/lp-3.12
            /tmp/lp-3.12/bin/python -m pip install --no-index --no-cache-dir --only-binary=:all: --require-hashes --find-links=/cache/wheelhouse numpy==2.4.6 --hash=sha256:{self.NUMPY_HASHES['cp312']}
            # pip's --hash only exists inside requirements files.
            printf '%s\\n' "$WHEEL --hash=sha256:$WHEEL_SHA256" > /tmp/helper-wheel312.txt
            /tmp/lp-3.12/bin/python -m pip install --no-index --no-cache-dir --only-binary=:all: --require-hashes --find-links=/cache/wheelhouse -r /tmp/helper-wheel312.txt
            sha256sum --check "$WHEEL.sha256"
            INPUT_WHEEL_SHA256="$(sha256sum "$WHEEL" | cut -d' ' -f1)"
            test "$INPUT_WHEEL_SHA256" = "$WHEEL_SHA256"
            /tmp/lp-3.12/bin/python -c 'from lumenplot_mpl import _native, LumenPlotError; _native.render_line_png("invalid-input"); print("invalid-input"); _native.render_line_png(np.array([0.0, 1.0]), np.array([0.0, 1.0]), viewport=(0.0, 1.0, 0.0, 1.0), canvas=(4.0, 4.0), plot_rect=(0.0, 0.0, 4.0, 4.0), logical_units_per_inch=72.0, output_dpi=72.0, line_rgba=(0, 0, 0, 255), line_width=1.0, background_rgba=(255, 255, 255, 255)); print("helper-success")'
            INSTALLED_VERSION="$(/tmp/lp-3.12/bin/python -c 'import importlib.metadata; print(importlib.metadata.version("lumenplot-mpl"))')"
            test "$INSTALLED_VERSION" = "$CARGO_VERSION"
            /opt/python/cp313-cp313/bin/python -m venv --clear /tmp/lp-3.13
            /tmp/lp-3.13/bin/python -m pip install --no-index --no-cache-dir --only-binary=:all: --require-hashes --find-links=/cache/wheelhouse numpy==2.4.6 --hash=sha256:{self.NUMPY_HASHES['cp313']}
            # pip's --hash only exists inside requirements files.
            printf '%s\\n' "$WHEEL --hash=sha256:$WHEEL_SHA256" > /tmp/helper-wheel313.txt
            /tmp/lp-3.13/bin/python -m pip install --no-index --no-cache-dir --only-binary=:all: --require-hashes --find-links=/cache/wheelhouse -r /tmp/helper-wheel313.txt
            sha256sum --check "$WHEEL.sha256"
            INPUT_WHEEL_SHA256="$(sha256sum "$WHEEL" | cut -d' ' -f1)"
            test "$INPUT_WHEEL_SHA256" = "$WHEEL_SHA256"
            /tmp/lp-3.13/bin/python -c 'from lumenplot_mpl import _native, LumenPlotError; _native.render_line_png("invalid-input"); print("invalid-input"); _native.render_line_png(np.array([0.0, 1.0]), np.array([0.0, 1.0]), viewport=(0.0, 1.0, 0.0, 1.0), canvas=(4.0, 4.0), plot_rect=(0.0, 0.0, 4.0, 4.0), logical_units_per_inch=72.0, output_dpi=72.0, line_rgba=(0, 0, 0, 255), line_width=1.0, background_rgba=(255, 255, 255, 255)); print("helper-success")'
            INSTALLED_VERSION="$(/tmp/lp-3.13/bin/python -c 'import importlib.metadata; print(importlib.metadata.version("lumenplot-mpl"))')"
            test "$INSTALLED_VERSION" = "$CARGO_VERSION"
            /opt/python/cp314-cp314/bin/python -m venv --clear /tmp/lp-3.14
            /tmp/lp-3.14/bin/python -m pip install --no-index --no-cache-dir --only-binary=:all: --require-hashes --find-links=/cache/wheelhouse numpy==2.4.6 --hash=sha256:{self.NUMPY_HASHES['cp314']}
            # pip's --hash only exists inside requirements files.
            printf '%s\\n' "$WHEEL --hash=sha256:$WHEEL_SHA256" > /tmp/helper-wheel314.txt
            /tmp/lp-3.14/bin/python -m pip install --no-index --no-cache-dir --only-binary=:all: --require-hashes --find-links=/cache/wheelhouse -r /tmp/helper-wheel314.txt
            sha256sum --check "$WHEEL.sha256"
            INPUT_WHEEL_SHA256="$(sha256sum "$WHEEL" | cut -d' ' -f1)"
            test "$INPUT_WHEEL_SHA256" = "$WHEEL_SHA256"
            /tmp/lp-3.14/bin/python -c 'from lumenplot_mpl import _native, LumenPlotError; _native.render_line_png("invalid-input"); print("invalid-input"); _native.render_line_png(np.array([0.0, 1.0]), np.array([0.0, 1.0]), viewport=(0.0, 1.0, 0.0, 1.0), canvas=(4.0, 4.0), plot_rect=(0.0, 0.0, 4.0, 4.0), logical_units_per_inch=72.0, output_dpi=72.0, line_rgba=(0, 0, 0, 255), line_width=1.0, background_rgba=(255, 255, 255, 255)); print("helper-success")'
            INSTALLED_VERSION="$(/tmp/lp-3.14/bin/python -c 'import importlib.metadata; print(importlib.metadata.version("lumenplot-mpl"))')"
            test "$INSTALLED_VERSION" = "$CARGO_VERSION"
            GLIBC_VERSION="$(ldd --version | head -n1 | awk '{{print $NF}}')"
            UNAME_ARCH="$(uname -m)"
            MANIFEST_ARGS=(--wheel "$WHEEL" --wheel-sha256 "$WHEEL_SHA256" --cargo-version "$CARGO_VERSION" --cargo-lock-sha256 "$CARGO_LOCK_SHA256" --source-commit "$SOURCE_COMMIT" --sbom /evidence/sbom.json)
          if [ -f /evidence/observed.json ]; then
            MANIFEST_ARGS+=(--observed /evidence/observed.json)
          fi
            /opt/python/cp311-cp311/bin/python /src/scripts/phase3a2-manifest.py "${{MANIFEST_ARGS[@]}}" > /evidence/phase3a2-wheel-evidence.json
          BUILD
          )"
          mkdir -p evidence
          test -f evidence/phase3a2-wheel-evidence.json
          cp evidence/phase3a2-wheel-evidence.json phase3a2-wheel-evidence.json
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        if: github.ref == 'refs/heads/main' && github.event_name == 'push'
        with:
          name: phase3a2-wheel-evidence
          path: phase3a2-wheel-evidence.json
          if-no-files-found: error
          retention-days: 7
          compression-level: 0
"""

    def valid_manifest(self, source_commit: str) -> dict[str, object]:
        wheel_hash = "a" * 64
        cells = []
        for version, interpreter in (
            ("3.11", "/opt/python/cp311-cp311/bin/python"),
            ("3.12", "/opt/python/cp312-cp312/bin/python"),
            ("3.13", "/opt/python/cp313-cp313/bin/python"),
            ("3.14", "/opt/python/cp314-cp314/bin/python"),
        ):
            cells.append(
                {
                    "python": version,
                    "interpreter": interpreter,
                    "numpy_version": "2.4.6",
                    "numpy_wheel_sha256": self.NUMPY_HASHES["cp" + version.replace(".", "")],
                    "wheel_sha256": wheel_hash,
                    "input_wheel_sha256": wheel_hash,
                    "cargo_expected_version": "0.1.0",
                    "installed_distribution_version": "0.1.0",
                    "result": "pass",
                }
            )
        return {
            "schema": "lumenplot.phase3a2-wheel-evidence.v1",
            "builder": {
                "image": self.IMAGE,
                "platform": "linux/amd64",
                "config_digest": self.CONFIG_DIGEST,
                "glibc": "2.28",
                "auditwheel_version": "6.8.0",
                "abi3audit_version": "0.0.26",
                "rust_version": "1.89.0",
                "maturin_version": "1.14.1",
                "maturin_wheel_sha256": self.MATURIN_HASH,
            },
            "checks": {
                "cargo_locked_sources_checksums_licenses": True,
                "same_wheel": True,
                "metadata_version": True,
                "auditwheel": True,
                "elf_rpath": True,
                "abi3audit": True,
                "private_helper_fixtures": True,
                "redaction_ownership": True,
            },
            "claim_boundary": {
                "private_helper_only": True,
                "release_artifact": False,
                "platform_support_claim": False,
                "publication_authorized": False,
            },
            "runtime_cells": cells,
            "source": {
                "commit": source_commit,
                "cargo_lock_sha256": hashlib.sha256((ROOT / "Cargo.lock").read_bytes()).hexdigest(),
                "distribution": "lumenplot-mpl",
                "cargo_version": "0.1.0",
            },
            "wheel": {
                "filename": "lumenplot_mpl-0.1.0-cp311-abi3-manylinux_2_28_x86_64.whl",
                "sha256": wheel_hash,
                "tag": "cp311-abi3-manylinux_2_28_x86_64",
                "cargo_expected_version": "0.1.0",
                "metadata_version": "0.1.0",
                "zip": True,
                "metadata": True,
                "wheel": True,
                "record": True,
                "elf": True,
                "abi3": True,
                "sbom": True,
                "sbom_format": "CycloneDX 1.5",
            },
        }

    def run_checker(self, root: Path, *, evidence: bool = False) -> tuple[int, str]:
        command = [sys.executable, str(root / "scripts" / CHECKER.name), "--root", str(root)]
        if evidence:
            command.append("--phase3a2-evidence")
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout + result.stderr

    def assert_rejected(self, mutate, expected: str, *, evidence: bool = False) -> None:
        with self.fixture() as temporary:
            root = Path(temporary)
            mutate(root)
            returncode, output = self.run_checker(root, evidence=evidence)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn(expected, output)
            self.assertNotIn(str(root), output)

    def test_activated_contract_fixture_passes(self) -> None:
        with self.fixture() as temporary:
            root = Path(temporary)
            returncode, output = self.run_checker(root)
            self.assertEqual(returncode, 0, output)
            self.assertEqual(
                output,
                "workspace architecture: OK\nphase3a2 static contract: OK\n",
            )
            returncode, output = self.run_checker(root, evidence=True)
            self.assertEqual(returncode, 0, output)
            self.assertEqual(
                output,
                "workspace architecture: OK\nphase3a2 static contract: OK\nphase3a2 wheel evidence: OK\n",
            )

    def test_static_contract_does_not_require_runtime_manifest(self) -> None:
        with self.fixture() as temporary:
            root = Path(temporary)
            (root / "phase3a2-wheel-evidence.json").unlink()
            returncode, output = self.run_checker(root)
            self.assertEqual(returncode, 0, output)
            self.assertEqual(
                output,
                "workspace architecture: OK\nphase3a2 static contract: OK\n",
            )

    def test_comment_only_control_mutations_are_rejected(self) -> None:
        mutations = (
            ("--network=bridge", "prefetch and offline containers must be separate"),
            ("--cap-drop=ALL", "missing dropped container capabilities"),
            ("docker image inspect --format '{{.Id}}' \"$IMAGE\"", "image config digest inspection"),
            ("maturin build --release --locked --offline", "offline container is missing the wheel build"),
            ("/opt/python/cp311-cp311/bin/python -m venv --clear", "lacks fresh venv isolation"),
            ("from lumenplot_mpl import _native", "runtime cell 3.11 lacks private helper import"),
        )
        for fragment, expected in mutations:
            def mutate(root: Path, fragment: str = fragment) -> None:
                path = root / ".github/workflows/phase3a2-wheel.yml"
                lines = path.read_text(encoding="utf-8").splitlines()
                path.write_text(
                    "\n".join(
                        f"# disabled control: {line}" if fragment in line else line
                        for line in lines
                    )
                    + "\n",
                    encoding="utf-8",
                )

            self.assert_rejected(mutate, expected)

    def test_same_wheel_runtime_install_is_required(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(
                    '/tmp/lp-3.11/bin/python -m pip install --no-index --no-cache-dir --only-binary=:all: --require-hashes --find-links=/cache/wheelhouse -r /tmp/helper-wheel311.txt',
                    "# helper wheel install omitted",
                    1,
                ),
                encoding="utf-8",
            ),
            "identical helper wheel must be installed in all four cells",
        )

    def test_manifest_generation_is_required(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                "\n".join(
                    line
                    for line in (root / ".github/workflows/phase3a2-wheel.yml")
                    .read_text(encoding="utf-8")
                    .splitlines()
                    if "phase3a2-manifest.py" not in line
                )
                + "\n",
                encoding="utf-8",
            ),
            "evidence manifest generation is missing",
        )

    def test_build_wheelhouse_mount_must_be_read_only(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(":/cache/wheelhouse:ro", ":/cache/wheelhouse:rw", 1),
                encoding="utf-8",
            ),
            "build/runtime wheelhouse must be read-only",
        )

    def test_native_object_elf_check_cannot_inspect_wheel_zip(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(
                    'readelf -d "$NATIVE_OBJECT"',
                    'readelf -d "$WHEEL"',
                    1,
                ),
                encoding="utf-8",
            ),
            "ELF dependency check must target the native object",
        )

    def test_manifest_source_commit_must_match_checked_out_head(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "phase3a2-wheel-evidence.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["source"]["commit"] = "0" * 40
            path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self.assert_rejected(mutate, "source commit does not match checked-out revision", evidence=True)

    def test_manifest_cargo_version_must_match_workspace_metadata(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "phase3a2-wheel-evidence.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            version = "9.9.9"
            value["source"]["cargo_version"] = version
            value["wheel"]["filename"] = value["wheel"]["filename"].replace("0.1.0", version)
            value["wheel"]["cargo_expected_version"] = version
            value["wheel"]["metadata_version"] = version
            for cell in value["runtime_cells"]:
                cell["cargo_expected_version"] = version
                cell["installed_distribution_version"] = version
            path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self.assert_rejected(mutate, "Cargo-derived version does not match workspace metadata", evidence=True)

    def test_baseline_fixture_is_inactive(self) -> None:
        with self.fixture() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").unlink()
            shutil.rmtree(root / "python")
            shutil.rmtree(root / ".github")
            (root / "phase3a2-wheel-evidence.json").unlink()
            shutil.copy2(ROOT / "crates/lumenplot-python/Cargo.toml", root / "crates/lumenplot-python/Cargo.toml")
            shutil.copy2(ROOT / "crates/lumenplot-python/src/lib.rs", root / "crates/lumenplot-python/src/lib.rs")
            reset_python_bridge_to_baseline(root)
            returncode, output = self.run_checker(root)
            self.assertEqual(returncode, 0, output)
            self.assertNotIn("phase3a2 wheel evidence", output)

    def test_partial_root_pyproject_only_activates_and_fails_closed(self) -> None:
        def mutate(root: Path) -> None:
            shutil.rmtree(root / "python")
            shutil.rmtree(root / ".github")
            (root / "phase3a2-wheel-evidence.json").unlink()
            shutil.copy2(ROOT / "crates/lumenplot-python/Cargo.toml", root / "crates/lumenplot-python/Cargo.toml")
            shutil.copy2(ROOT / "crates/lumenplot-python/src/lib.rs", root / "crates/lumenplot-python/src/lib.rs")

        self.assert_rejected(mutate, "phase3a2: missing Python package directory")

    def test_python_dependency_sentinel_activates(self) -> None:
        def mutate(root: Path) -> None:
            (root / "pyproject.toml").unlink()
            shutil.rmtree(root / "python")
            shutil.rmtree(root / ".github")
            (root / "phase3a2-wheel-evidence.json").unlink()
            shutil.copy2(ROOT / "crates/lumenplot-python/Cargo.toml", root / "crates/lumenplot-python/Cargo.toml")
            reset_python_bridge_to_baseline(root)
            path = root / "crates/lumenplot-python/Cargo.toml"
            path.write_text(
                path.read_text(encoding="utf-8")
                + '\npyo3 = { version = "=0.29.2", default-features = false }\n',
                encoding="utf-8",
            )

        self.assert_rejected(mutate, "phase3a2: missing root pyproject.toml")

    def test_missing_python_package_directory_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: shutil.rmtree(root / "python"),
            "phase3a2: missing Python package directory",
        )

    def test_non_cpython_interpreter_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("cp314-cp314/bin/python", "cp314t-cp314t/bin/python"),
                encoding="utf-8",
            ),
            "free-threaded CPython paths are forbidden",
        )

    def test_abi3t_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("cp311-abi3", "cp311-abi3t"),
                encoding="utf-8",
            ),
            "free-threaded abi3 is forbidden",
        )

    def test_locked_build_is_required(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("--locked", ""),
                encoding="utf-8",
            ),
            "missing locked Cargo prefetch",
        )

    def test_exact_image_tag_and_digest_are_required(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(self.IMAGE, self.IMAGE.replace("2026.08.15-1", "latest")),
                encoding="utf-8",
            ),
            "builder image must use the exact tag@digest",
        )

    def test_network_none_is_required(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("--network=none", "--network=bridge"),
                encoding="utf-8",
            ),
            "missing offline build/test container",
        )

    def test_prefetch_container_must_forward_rustup_init_digest(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("-e PHASE3A2_RUSTUP_INIT_SHA256 --tmpfs", "--tmpfs"),
                encoding="utf-8",
            ),
            "prefetch container must forward the pinned rustup-init digest",
        )

    def test_offline_container_must_not_forward_rustup_init_digest(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(
                    "--security-opt=no-new-privileges --tmpfs /tmp:rw,noexec,nosuid,nodev"
                    " --tmpfs /tmp/work",
                    "--security-opt=no-new-privileges -e PHASE3A2_RUSTUP_INIT_SHA256"
                    " --tmpfs /tmp:rw,noexec,nosuid,nodev --tmpfs /tmp/work",
                ),
                encoding="utf-8",
            ),
            "offline build/test container must not forward the rustup-init digest",
        )

    def test_prefetch_container_must_mount_exec_capable_work_tmpfs(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(
                    "-e PHASE3A2_RUSTUP_INIT_SHA256 --tmpfs /tmp:rw,noexec,nosuid,nodev"
                    " --tmpfs /tmp/work:rw,exec,nosuid,nodev",
                    "-e PHASE3A2_RUSTUP_INIT_SHA256 --tmpfs /tmp:rw,noexec,nosuid,nodev",
                    1,
                ),
                encoding="utf-8",
            ),
            "prefetch container must mount an exec-capable work tmpfs for rustup-init",
        )

    def test_prefetch_rustup_init_must_run_from_exec_tmpfs(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(
                    "/tmp/work/rustup-init -y --no-modify-path --profile minimal"
                    " --default-toolchain 1.89.0",
                    "bash /tmp/rustup-init -y --no-modify-path --profile minimal"
                    " --default-toolchain 1.89.0",
                    1,
                ),
                encoding="utf-8",
            ),
            "pinned rustup provisioning",
        )

    def test_missing_rustup_init_chmod_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("chmod +x /tmp/work/rustup-init\n", "", 1),
                encoding="utf-8",
            ),
            "rustup-init executable-bit provisioning",
        )

    def test_prefetch_missing_cargo_target_dir_export_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("export CARGO_TARGET_DIR=/tmp/work/cargo-target", "", 1),
                encoding="utf-8",
            ),
            "prefetch script must point CARGO_TARGET_DIR at the exec-capable work tmpfs",
        )

    def test_auditwheel_repair_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(
                    'auditwheel show --json "$WHEEL"',
                    'auditwheel repair "$WHEEL"',
                ),
                encoding="utf-8",
            ),
            "auditwheel repair is forbidden",
        )

    def test_maturin_version_is_exact(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("maturin==1.14.1", "maturin==1.14.2"),
                encoding="utf-8",
            ),
            "hash-pinned maturin version",
        )

    def test_maturin_hash_is_exact(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(self.MATURIN_HASH, "0" * 64),
                encoding="utf-8",
            ),
            "hash-pinned maturin wheel",
        )

    def test_numpy_hash_is_exact(self) -> None:
        digest = self.NUMPY_HASHES["cp314"]
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(digest, "0" * 64, 1),
                encoding="utf-8",
            ),
            "hash-pinned NumPy 2.4.6 runtime wheel",
        )

    def test_all_matrix_cells_are_required(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("/opt/python/cp314-cp314/bin/python", "/opt/python/cp314-missing/bin/python"),
                encoding="utf-8",
            ),
            "missing runtime interpreter /opt/python/cp314-cp314/bin/python",
        )

    def test_find_interpreter_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("maturin build", "maturin build --find-interpreter"),
                encoding="utf-8",
            ),
            "interpreter discovery is forbidden",
        )

    def test_permissive_pip_install_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("--require-hashes", ""),
                encoding="utf-8",
            ),
            "hash-required pip install",
        )

    def test_upload_artifact_requires_error_guard(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("          if-no-files-found: error\n", ""),
                encoding="utf-8",
            ),
            "upload-artifact requires if-no-files-found: error",
        )

    def test_fresh_venv_isolation_is_required(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(" -m venv --clear", " -m venv"),
                encoding="utf-8",
            ),
            "lacks fresh venv isolation",
        )

    def test_unpinned_action_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(
                    "uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
                    "uses: actions/upload-artifact",
                ),
                encoding="utf-8",
            ),
            "actions/upload-artifact' is not pinned to a full SHA",
        )

    def test_image_config_digest_is_required_in_workflow(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(
                    'test "$IMAGE_CONFIG_DIGEST" = "sha256:fd0c576d9673648a125bffeaea6acb762d8bc52d97da9034dfdbe00f98a17dd5"',
                    'test "$IMAGE_CONFIG_DIGEST" = "sha256:' + "0" * 64 + '"',
                ),
                encoding="utf-8",
            ),
            "image config digest comparison",
        )

    def test_each_docker_run_must_use_the_reviewed_image_operand(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace('"$IMAGE" bash', '"$UNPINNED_IMAGE" bash'),
                encoding="utf-8",
            ),
            "every container must use the exact builder image operand",
        )

    def test_each_docker_run_must_bind_the_reviewed_source(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace('"$PWD:/src:ro"', '"/tmp/unreviewed:/src:ro"'),
                encoding="utf-8",
            ),
            "every container source mount must bind $PWD to /src read-only",
        )

    def test_each_docker_run_must_bind_the_reviewed_wheelhouse(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(
                    '"$PWD/wheelhouse:/cache/wheelhouse:rw"',
                    '"/tmp/unreviewed-wheelhouse:/cache/wheelhouse:rw"',
                ),
                encoding="utf-8",
            ),
            "prefetch wheelhouse must bind $PWD/wheelhouse read-write",
        )

    def test_root_container_user_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("--user 1000:1000", "--user 0:0"),
                encoding="utf-8",
            ),
            "container user must not be root",
        )

    def test_invalid_container_user_forms_are_rejected(self) -> None:
        for replacement in ("0:1000", "root:root", "not-a-user"):
            with self.subTest(replacement=replacement):
                self.assert_rejected(
                    lambda root, replacement=replacement: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                        (root / ".github/workflows/phase3a2-wheel.yml")
                        .read_text(encoding="utf-8")
                        .replace("--user 1000:1000", f"--user {replacement}"),
                        encoding="utf-8",
                    ),
                    "every container must use an explicit numeric non-root user",
                )

    def test_unreviewed_prefetch_download_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / ".github/workflows/phase3a2-wheel.yml"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "cargo install --locked cargo-deny@0.20.2",
                    "cargo deny check\n            python -m pip download --no-deps --only-binary=:all: --require-hashes --dest /cache/wheelhouse evil-package==9.9.9 --hash=sha256:"
                    + "0" * 64,
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_rejected(mutate, "prefetch download inventory is not exactly reviewed")

    def test_bare_python_in_prefetch_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / ".github/workflows/phase3a2-wheel.yml"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "/opt/python/cp311-cp311/bin/python -m pip download",
                    "python -m pip download",
                ),
                encoding="utf-8",
            )

        self.assert_rejected(mutate, "prefetch must not invoke a bare python interpreter")

    def test_missing_requirements_file_hash_staging_is_rejected(self) -> None:
        # pip's --hash is a requirements-file-only option, so removing the
        # printf staging line drops the digest pin from the workflow entirely.
        def mutate(root: Path) -> None:
            path = root / ".github/workflows/phase3a2-wheel.yml"
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if "/tmp/wheelhouse-maturin.txt" in line and "printf" in line:
                    text = text.replace(line + "\n", "", 1)
                    break
            path.write_text(text, encoding="utf-8")

        self.assert_rejected(
            mutate,
            "prefetch lacks an exact requirements-file hash pin for a reviewed wheelhouse input",
        )

    def test_missing_build_site_pythonpath_export_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / ".github/workflows/phase3a2-wheel.yml"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "            export PYTHONPATH=/tmp/work/build-site\n",
                    "",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_rejected(
            mutate,
            "must export PYTHONPATH=/tmp/work/build-site before the first auditwheel/abi3audit invocation",
        )

    def test_late_build_site_pythonpath_export_is_rejected(self) -> None:
        # Moving the export below the first console-script invocation recreates
        # the ModuleNotFoundError this guard exists to prevent.
        def mutate(root: Path) -> None:
            path = root / ".github/workflows/phase3a2-wheel.yml"
            text = path.read_text(encoding="utf-8")
            export_line = "            export PYTHONPATH=/tmp/work/build-site\n"
            text = text.replace(export_line, "", 1)
            anchor = '            auditwheel show --json "$WHEEL" > /evidence/auditwheel.json\n'
            assert anchor in text
            text = text.replace(anchor, anchor + export_line, 1)
            path.write_text(text, encoding="utf-8")

        self.assert_rejected(
            mutate,
            "must export PYTHONPATH=/tmp/work/build-site before the first auditwheel/abi3audit invocation",
        )

    def test_unreviewed_prefetch_network_fetch_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / ".github/workflows/phase3a2-wheel.yml"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "cargo install --locked cargo-deny@0.20.2",
                    "cargo deny check\n            curl https://example.invalid/unreviewed.tar.gz",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_rejected(mutate, "prefetch contains an unreviewed network fetch")

    def test_unreviewed_curl_url_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / ".github/workflows/phase3a2-wheel.yml"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "cargo install --locked cargo-deny@0.20.2",
                    "curl https://static.rust-lang.org/rustup/dist/x86_64-unknown-linux-gnu/evil.sh -o /tmp/evil.sh",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_rejected(mutate, "prefetch contains an unreviewed network fetch")

    def test_missing_rustup_init_digest_verification_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / ".github/workflows/phase3a2-wheel.yml"
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if "( cd /tmp/work && sha256sum --check /tmp/rustup-init.sha256 )" in line:
                    text = text.replace(line + "\n", "", 1)
                    break
            path.write_text(text, encoding="utf-8")

        self.assert_rejected(mutate, "missing rustup-init digest verification")

    def test_unguarded_rustup_init_digest_check_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / ".github/workflows/phase3a2-wheel.yml"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "( cd /tmp/work && sha256sum --check /tmp/rustup-init.sha256 )",
                    "sha256sum --check /tmp/rustup-init.sha256",
                ),
                encoding="utf-8",
            )

        self.assert_rejected(mutate, "rustup-init digest verification")

    def test_tampered_rustup_init_digest_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / ".github/workflows/phase3a2-wheel.yml"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    self.RUSTUP_INIT_HASH,
                    "b" * 64,
                ),
                encoding="utf-8",
            )

        self.assert_rejected(mutate, "hash-pinned rustup-init bootstrap digest")

    def test_evidence_manifest_must_remain_untracked(self) -> None:
        def mutate(root: Path) -> None:
            subprocess.run(
                ["git", "add", "phase3a2-wheel-evidence.json"],
                cwd=root,
                check=True,
            )

        self.assert_rejected(mutate, "CI-local evidence manifest must not be tracked", evidence=True)

    def test_extra_private_native_pyfunction_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "crates/lumenplot-python/src/lib.rs"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "#[pyfunction]\nfn render_line_png()",
                    "#[pyfunction]\nfn leaked() -> PyResult<Vec<u8>> { Ok(Vec::new()) }\n\n#[pyfunction]\nfn render_line_png()",
                    1,
                ),
                encoding="utf-8",
            )

        self.assert_rejected(mutate, "private native export inventory is not exact")

    def test_second_permissive_pip_command_is_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / ".github/workflows/phase3a2-wheel.yml"
            path.write_text(
                path.read_text(encoding="utf-8") + "\npython -m pip install numpy==2.4.6\n",
                encoding="utf-8",
            )

        self.assert_rejected(mutate, "pip command is missing hash-required pip install")

    def test_wrong_action_sha_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", "0" * 40),
                encoding="utf-8",
            ),
            "actions/upload-artifact' is not pinned to the reviewed SHA",
        )

    def test_multiple_wheel_builds_are_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml").read_text(encoding="utf-8")
                .replace(
                    "maturin build --release --locked --offline",
                    "maturin build --release --locked --offline\n            maturin build --release --locked --offline",
                    1,
                ),
                encoding="utf-8",
            ),
            "exactly one wheel build is required",
        )

    def test_self_equality_version_check_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(
                    'test "$INSTALLED_VERSION" = "$CARGO_VERSION"',
                    'test "$INSTALLED_VERSION" = "$INSTALLED_VERSION"',
                ),
                encoding="utf-8",
            ),
            "self-equality version check is forbidden",
        )

    def test_missing_per_cell_wheel_rehash_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace('sha256sum --check "$WHEEL.sha256"', "", 1),
                encoding="utf-8",
            ),
            "every runtime cell must recheck the input wheel hash",
        )

    def test_cache_action_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml").read_text(encoding="utf-8")
                + "\n      - uses: actions/cache@0000000000000000000000000000000000000000\n",
                encoding="utf-8",
            ),
            "action 'actions/cache' is not allowed",
        )

    def test_setup_python_builder_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml").read_text(encoding="utf-8")
                + "\n      - uses: actions/setup-python@0000000000000000000000000000000000000000\n",
                encoding="utf-8",
            ),
            "action 'actions/setup-python' is not allowed",
        )

    def test_maturin_action_builder_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml").read_text(encoding="utf-8")
                + "\n      - uses: PyO3/maturin-action@0000000000000000000000000000000000000000\n",
                encoding="utf-8",
            ),
            "action 'PyO3/maturin-action' is not allowed",
        )

    def test_missing_record_check_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("unzip -p \"$WHEEL\" '*/RECORD'", "unzip -p \"$WHEEL\" '*/record-omitted'"),
                encoding="utf-8",
            ),
            "wheel RECORD check",
        )

    def test_read_only_root_is_required(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("--read-only", "", 1),
                encoding="utf-8",
            ),
            "read-only container root",
        )

    def test_capability_drop_is_required(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("--cap-drop=ALL", "", 1),
                encoding="utf-8",
            ),
            "dropped container capabilities",
        )

    def test_missing_auditwheel_check_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(
                    'assert "manylinux_2_28" in tag',
                    'pass',
                ),
                encoding="utf-8",
            ),
            'manylinux_2_28 tag assertion from auditwheel JSON',
        )

    def test_missing_elf_check_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace(
                    'readelf -d "$NATIVE_OBJECT"',
                    'elf-inspect "$NATIVE_OBJECT"',
                    1,
                ),
                encoding="utf-8",
            ),
            "ELF dependency check",
        )

    def test_unexpected_library_guard_is_required(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("unexpected shared library", "library policy omitted"),
                encoding="utf-8",
            ),
            "unexpected library rejection",
        )

    def test_missing_cyclonedx_sbom_check_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("CycloneDX 1.5", "SBOM unspecified"),
                encoding="utf-8",
            ),
            "CycloneDX 1.5 SBOM check",
        )

    def test_repository_toolchain_pin_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / "rust-toolchain").write_text("1.89.0\n", encoding="utf-8"),
            "repository rust-toolchain pin is forbidden",
        )

    def test_matplotlib_surface_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / "python/lumenplot_mpl/__init__.py").write_text(
                (root / "python/lumenplot_mpl/__init__.py").read_text(encoding="utf-8")
                + "\nimport matplotlib\n",
                encoding="utf-8",
            ),
            "Matplotlib/backend surface is forbidden",
        )

    def test_public_render_png_surface_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / "python/lumenplot_mpl/_native.pyi").write_text(
                (root / "python/lumenplot_mpl/_native.pyi").read_text(encoding="utf-8")
                + "\ndef render_png() -> bytes: ...\n",
                encoding="utf-8",
            ),
            "phase3a2 Python package: public render_png is forbidden",
        )

    def test_pull_request_secret_and_write_permission_are_rejected(self) -> None:
        def mutate(root: Path) -> None:
            path = root / ".github/workflows/phase3a2-wheel.yml"
            source = path.read_text(encoding="utf-8")
            path.write_text(
                source.replace("contents: read", "contents: write")
                + "\n      run: echo ${{ secrets.TOKEN }}\n",
                encoding="utf-8",
            )

        self.assert_rejected(mutate, "missing read-only contents permission")

    def test_pull_request_target_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml").read_text(encoding="utf-8")
                + "\n  pull_request_target:\n    branches: [main]\n",
                encoding="utf-8",
            ),
            "pull_request_target is forbidden",
        )

    def test_missing_evidence_manifest_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / "phase3a2-wheel-evidence.json").unlink(),
            "missing phase3a2-wheel-evidence.json",
            evidence=True,
        )

    def test_manifest_schema_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "phase3a2-wheel-evidence.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            del value["claim_boundary"]
            path.write_text(json.dumps(value), encoding="utf-8")

        self.assert_rejected(mutate, "top-level manifest keys are not exact", evidence=True)

    def test_manifest_schema_identifier_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "phase3a2-wheel-evidence.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["schema"] = "lumenplot.phase3a2-wheel-evidence.dev"
            path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self.assert_rejected(mutate, "schema identifier is not the accepted Phase-3A2 v1 value", evidence=True)

    def test_runtime_cell_order_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "phase3a2-wheel-evidence.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["runtime_cells"].reverse()
            path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self.assert_rejected(
            mutate,
            "runtime cells must be ordered 3.11, 3.12, 3.13, 3.14",
            evidence=True,
        )

    def test_manifest_redaction_is_enforced(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "phase3a2-wheel-evidence.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["source"]["commit"] = "GITHUB_TOKEN"
            path.write_text(json.dumps(value), encoding="utf-8")

        self.assert_rejected(mutate, "private path or credential text is not redacted", evidence=True)


if __name__ == "__main__":
    unittest.main()
