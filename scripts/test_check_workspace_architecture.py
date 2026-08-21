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

    def assert_mutation_rejected(self, mutate, expected: str) -> None:
        with self.fixture() as temporary:
            fixture_root = Path(temporary)
            mutate(fixture_root)
            returncode, output = self.run_checker(fixture_root)
            self.assertNotEqual(returncode, 0, output)
            self.assertIn(expected, output)
            self.assertNotIn(str(fixture_root), output)

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


if __name__ == "__main__":
    unittest.main()
