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


class WorkspaceArchitectureMutationTests(unittest.TestCase):
    def fixture(self) -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory(prefix="lumenplot-architecture-")
        fixture_root = Path(temporary.name)
        shutil.copy2(ROOT / "Cargo.toml", fixture_root / "Cargo.toml")
        shutil.copytree(ROOT / "crates", fixture_root / "crates")
        scripts_dir = fixture_root / "scripts"
        scripts_dir.mkdir()
        shutil.copy2(CHECKER, scripts_dir / CHECKER.name)
        return temporary

    def run_checker(self, fixture_root: Path) -> tuple[int, str]:
        result = subprocess.run(
            [sys.executable, str(fixture_root / "scripts" / CHECKER.name), "--root", str(fixture_root)],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout + result.stderr

    def add_valid_hidden_facade(self, root: Path) -> None:
        path = root / "crates/lumenplot/src/lib.rs"
        path.write_text(
            path.read_text(encoding="utf-8")
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
                "multiline free function",
                "pub fn render_line_png(request: OwnedLinePngRequest) -> Result<Vec<u8>, BridgeError> {",
                "pub fn render_line_png(\n        request: OwnedLinePngRequest,\n    ) -> Result<Vec<u8>, BridgeError> {",
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
        (root / "phase3a2-wheel-evidence.json").write_text(
            json.dumps(self.valid_manifest(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return temporary

    def valid_workflow(self) -> str:
        hashes = "\n".join(f"# {key} NumPy wheel sha256={value}" for key, value in self.NUMPY_HASHES.items())
        interpreters = "\n".join(
            f"            {path} -m venv --clear /tmp/lp-{version}"
            for version, path in (
                ("3.11", "/opt/python/cp311-cp311/bin/python"),
                ("3.12", "/opt/python/cp312-cp312/bin/python"),
                ("3.13", "/opt/python/cp313-cp313/bin/python"),
                ("3.14", "/opt/python/cp314-cp314/bin/python"),
            )
        )
        return f"""name: Phase-3A2 wheel evidence

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

jobs:
  wheel:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
      - uses: dtolnay/rust-toolchain@032958afbdc797a9164d3bc0b56325c1308924a5 # 1.97.1
      - name: Build in pinned manylinux image
        run: |
          IMAGE='{self.IMAGE}'
          docker pull --platform=linux/amd64 "$IMAGE"
          docker image inspect "$IMAGE" # config digest sha256:fd0c576d9673648a125bffeaea6acb762d8bc52d97da9034dfdbe00f98a17dd5
          docker run --rm --platform=linux/amd64 --network=bridge --read-only --user 1000:1000 --cap-drop=ALL --security-opt=no-new-privileges --tmpfs /tmp -v "$PWD:/src:ro" "$IMAGE" bash -eu -o pipefail -c '
            export RUSTUP_TOOLCHAIN=1.89.0
            rustc --version
            cargo --version
            cargo fetch --locked
            cargo metadata --locked --format-version 1 > /cache/cargo-metadata.json
            CARGO_VERSION=0.1.0
            cargo deny check --all-features
            python -m pip install --no-index --no-cache-dir --require-hashes --only-binary=:all: --find-links=/cache/wheelhouse maturin==1.14.1 --hash=sha256:{self.MATURIN_HASH}
          '
          docker run --rm --platform=linux/amd64 --network=none --read-only --user 1000:1000 --cap-drop=ALL --security-opt=no-new-privileges --tmpfs /tmp -v "$PWD:/src:ro" "$IMAGE" bash -eu -o pipefail -c '
            export RUSTUP_TOOLCHAIN=1.89.0
            maturin build --release --locked --offline --interpreter /opt/python/cp311-cp311/bin/python --compatibility manylinux_2_28
            WHEEL=dist/lumenplot_mpl-0.1.0-cp311-abi3-manylinux_2_28_x86_64.whl
            sha256sum "$WHEEL" > "$WHEEL.sha256"
            sha256sum --check "$WHEEL.sha256"
            INPUT_WHEEL_SHA256="$(sha256sum "$WHEEL" | cut -d' ' -f1)"
            unzip -t "$WHEEL"
            unzip -p "$WHEEL" '*/METADATA' | grep '^Version:'
            unzip -p "$WHEEL" '*/WHEEL' | grep 'cp311-abi3-manylinux_2_28_x86_64'
            unzip -p "$WHEEL" '*/RECORD' | python /cache/check-record.py
            WHEEL_VERSION=0.1.0
            test "$WHEEL_VERSION" = "$CARGO_VERSION"
            auditwheel show --json "$WHEEL"
            auditwheel check "$WHEEL" --auditwheel check
            readelf -d "$WHEEL" # DT_NEEDED and RPATH/RUNPATH; reject unexpected shared library
            abi3audit "$WHEEL"
            # CycloneDX 1.5 SBOM and RECORD/ZIP/metadata checks are written to CI-local evidence.
{hashes}
{interpreters}
            sha256sum --check "$WHEEL.sha256"
            INSTALLED_VERSION=0.1.0
            test "$INSTALLED_VERSION" = "$CARGO_VERSION"
            python -m pip install --no-index --no-cache-dir --require-hashes --only-binary=:all: --find-links=/cache/wheelhouse numpy==2.4.6
            test -f phase3a2-wheel-evidence.json
          '
      - uses: actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1
        if: github.ref == 'refs/heads/main' && github.event_name == 'push'
        with:
          name: phase3a2-wheel-evidence
          path: phase3a2-wheel-evidence.json
          if-no-files-found: error
          retention-days: 7
          compression-level: 0
"""

    def valid_manifest(self) -> dict[str, object]:
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
                "commit": "b" * 40,
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

    def run_checker(self, root: Path) -> tuple[int, str]:
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / CHECKER.name), "--root", str(root)],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode, result.stdout + result.stderr

    def assert_rejected(self, mutate, expected: str) -> None:
        with self.fixture() as temporary:
            root = Path(temporary)
            mutate(root)
            returncode, output = self.run_checker(root)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn(expected, output)
            self.assertNotIn(str(root), output)

    def test_activated_contract_fixture_passes(self) -> None:
        with self.fixture() as temporary:
            returncode, output = self.run_checker(Path(temporary))
            self.assertEqual(returncode, 0, output)
            self.assertIn("workspace architecture: OK", output)
            self.assertIn("phase3a2 wheel evidence: OK", output)

    def test_baseline_fixture_is_inactive(self) -> None:
        with self.fixture() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").unlink()
            shutil.rmtree(root / "python")
            shutil.rmtree(root / ".github")
            (root / "phase3a2-wheel-evidence.json").unlink()
            shutil.copy2(ROOT / "crates/lumenplot-python/Cargo.toml", root / "crates/lumenplot-python/Cargo.toml")
            shutil.copy2(ROOT / "crates/lumenplot-python/src/lib.rs", root / "crates/lumenplot-python/src/lib.rs")
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

    def test_auditwheel_repair_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("# CycloneDX", "auditwheel repair # CycloneDX"),
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
                    " # config digest sha256:fd0c576d9673648a125bffeaea6acb762d8bc52d97da9034dfdbe00f98a17dd5",
                    "",
                ),
                encoding="utf-8",
            ),
            "image config digest verification",
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
                + "\n# maturin build\n",
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
                .replace("auditwheel check", "auditwheel inspect"),
                encoding="utf-8",
            ),
            "auditwheel check",
        )

    def test_missing_elf_check_is_rejected(self) -> None:
        self.assert_rejected(
            lambda root: (root / ".github/workflows/phase3a2-wheel.yml").write_text(
                (root / ".github/workflows/phase3a2-wheel.yml")
                .read_text(encoding="utf-8")
                .replace("readelf -d", "elf-inspect", 1),
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
        )

    def test_manifest_schema_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "phase3a2-wheel-evidence.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            del value["claim_boundary"]
            path.write_text(json.dumps(value), encoding="utf-8")

        self.assert_rejected(mutate, "top-level manifest keys are not exact")

    def test_manifest_schema_identifier_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "phase3a2-wheel-evidence.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["schema"] = "lumenplot.phase3a2-wheel-evidence.dev"
            path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self.assert_rejected(mutate, "schema identifier is not the accepted Phase-3A2 v1 value")

    def test_runtime_cell_order_is_exact(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "phase3a2-wheel-evidence.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["runtime_cells"].reverse()
            path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        self.assert_rejected(mutate, "runtime cells must be ordered 3.11, 3.12, 3.13, 3.14")

    def test_manifest_redaction_is_enforced(self) -> None:
        def mutate(root: Path) -> None:
            path = root / "phase3a2-wheel-evidence.json"
            value = json.loads(path.read_text(encoding="utf-8"))
            value["source"]["commit"] = "GITHUB_TOKEN"
            path.write_text(json.dumps(value), encoding="utf-8")

        self.assert_rejected(mutate, "private path or credential text is not redacted")


if __name__ == "__main__":
    unittest.main()
