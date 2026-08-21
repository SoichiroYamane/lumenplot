#!/usr/bin/env python3
"""Mutation tests for the Phase-1A workspace architecture checker."""

from __future__ import annotations

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
    impl fmt::Debug for BridgeError {}
    impl fmt::Display for BridgeError {}
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


if __name__ == "__main__":
    unittest.main()
