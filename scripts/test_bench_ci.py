#!/usr/bin/env python3
"""Mutation and workflow-contract tests for the benchmark CI evidence lane."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from . import bench_analysis
    from . import bench_ci
except ImportError:  # pragma: no cover - supports unittest discover -s scripts.
    import bench_analysis
    import bench_ci


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bench_ci.py"
WORKFLOW = ROOT / ".github" / "workflows" / "bench-nightly.yml"
RUN_ID = "27b0a5e7-3ef2-4c1a-9d4f-6f9d8e8a1234"
STAMP = "2026-08-24T00:00:00Z"


def make_run(root: Path, profile: str = "strict") -> dict:
    """Write a valid current-run-shaped output and return its manifest."""
    all_values: list[float] = []
    blocks: list[dict[str, object]] = []
    for block_index in range(5):
        values = [float(100_000 + block_index * 1_000 + frame) for frame in range(1000)]
        all_values.extend(values)
        rows = [
            {
                "block_index": block_index,
                "frame_index": frame,
                "clocks": {
                    "event_accept_to_present_return": int(value),
                    "gpu_frame_timestamp_span": None,
                    "queue_completion_readback": None,
                    "scanout_present_marker": None,
                },
            }
            for frame, value in enumerate(values)
        ]
        (root / f"samples-{block_index}.jsonl").write_text(
            "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
            encoding="utf-8",
        )
        blocks.append(
            {
                "block_index": block_index,
                "pid": 1000 + block_index,
                "started_at_utc": STAMP,
                "frame_count": 1000,
                "p50_ns": bench_analysis.nearest_rank(values, 0.50),
                "p95_ns": bench_analysis.nearest_rank(values, 0.95),
                "p99_ns": bench_analysis.nearest_rank(values, 0.99),
                "raw_samples_path": f"samples-{block_index}.jsonl",
            }
        )

    manifest: dict[str, object] = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "generated_at_utc": STAMP,
        "profile": profile,
        "fixture": {
            "id": "line-10k",
            "points": 10_000,
            "canvas_px": [800, 600],
            "dpi": 100.0,
        },
        "environment": {
            "os": "linux",
            "os_version": "test",
            "arch": "x86_64",
            "kernel": "test",
            "cpu": "test-cpu",
            "gpu": None,
            "compositor": None,
            "display_scale": 1.0,
            "present_mode": None,
        },
        "protocol": {
            "blocks": 5,
            "min_frames_per_block": 1000,
            "quantile_method": "nearest-rank",
            "bootstrap": {
                "resamples": 10_000,
                "ci": 0.95,
                "seed": 20260824,
                "method": "percentile",
            },
            "trimming": "none",
        },
        "clocks": [
            {
                "name": "event_accept_to_present_return",
                "domain": "scheduler",
                "unit": "ns",
                "available": True,
            },
            {
                "name": "gpu_frame_timestamp_span",
                "domain": "gpu",
                "unit": "ns",
                "available": False,
            },
            {
                "name": "queue_completion_readback",
                "domain": "queue",
                "unit": "ns",
                "available": False,
            },
            {
                "name": "scanout_present_marker",
                "domain": "scanout",
                "unit": "ns",
                "available": False,
            },
        ],
        "blocks": blocks,
        "pooled": {
            "note": "descriptive only; gate uses max_block_p99_ns",
            "frame_count": 5000,
            "p50_ns": bench_analysis.nearest_rank(all_values, 0.50),
            "p95_ns": bench_analysis.nearest_rank(all_values, 0.95),
            "p99_ns": bench_analysis.nearest_rank(all_values, 0.99),
        },
        "max_block_p99_ns": max(block["p99_ns"] for block in blocks),
        "status": "inconclusive",
        "inconclusive_reasons": ["GPU/queue/scanout are unavailable on this host"],
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


class ProbeValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="lumenplot-bench-ci-")
        self.root = Path(self.temporary.name)
        self.manifest = make_run(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def rewrite_manifest(self) -> None:
        (self.root / "manifest.json").write_text(
            json.dumps(self.manifest, indent=2), encoding="utf-8"
        )

    def run_cli(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--validate-run",
                str(self.root),
                "--profile",
                "strict",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_valid_run_is_admitted(self) -> None:
        self.assertEqual(bench_ci.validate_run(self.root, "strict"), [])
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("benchmark evidence valid", completed.stdout)

    def test_manifest_profile_mismatch_is_rejected(self) -> None:
        self.assertTrue(bench_ci.validate_run(self.root, "hybrid"))

    def test_missing_manifest_is_rejected(self) -> None:
        (self.root / "manifest.json").unlink()
        errors = bench_ci.validate_run(self.root, "strict")
        self.assertTrue(any("required manifest" in error for error in errors), errors)
        self.assertEqual(self.run_cli().returncode, 2)

    def test_missing_raw_file_is_rejected(self) -> None:
        (self.root / "samples-3.jsonl").unlink()
        errors = bench_ci.validate_run(self.root, "strict")
        self.assertTrue(any("referenced raw sample file is missing" in error for error in errors), errors)

    def test_malformed_raw_json_is_rejected(self) -> None:
        (self.root / "samples-0.jsonl").write_text("{not-json}\n", encoding="utf-8")
        completed = self.run_cli()
        self.assertEqual(completed.returncode, 2)
        self.assertIn("invalid JSON", completed.stderr)

    def test_raw_row_count_is_rejected(self) -> None:
        path = self.root / "samples-0.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        errors = bench_ci.validate_run(self.root, "strict")
        self.assertTrue(any("expected 1000 rows" in error for error in errors), errors)

    def test_raw_frame_order_and_shape_are_rejected(self) -> None:
        path = self.root / "samples-0.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[0]["frame_index"] = 1
        rows[1]["unexpected"] = True
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        errors = bench_ci.validate_run(self.root, "strict")
        self.assertTrue(any("frame_index must be 0" in error for error in errors), errors)
        self.assertTrue(any("exactly the per-frame keys" in error for error in errors), errors)

    def test_path_mutation_cannot_escape_or_change_upload_allowlist(self) -> None:
        self.manifest["blocks"][0]["raw_samples_path"] = "../samples-0.jsonl"
        self.rewrite_manifest()
        errors = bench_ci.validate_run(self.root, "strict")
        self.assertTrue(any("must be exactly 'samples-0.jsonl'" in error for error in errors), errors)
        self.assertTrue(any("unexpected file" in error for error in errors), errors)

    def test_unexpected_glob_match_is_rejected(self) -> None:
        (self.root / "samples-extra.jsonl").write_text("not-uploadable\n", encoding="utf-8")
        errors = bench_ci.validate_run(self.root, "strict")
        self.assertTrue(any("unexpected file" in error for error in errors), errors)

    def test_reported_quantile_must_match_raw_samples(self) -> None:
        self.manifest["blocks"][2]["p99_ns"] += 1
        self.rewrite_manifest()
        errors = bench_ci.validate_run(self.root, "strict")
        self.assertTrue(any("p99_ns" in error and "does not match raw" in error for error in errors), errors)

    def test_unavailable_clock_must_remain_null(self) -> None:
        path = self.root / "samples-1.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[0]["clocks"]["gpu_frame_timestamp_span"] = 1
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        errors = bench_ci.validate_run(self.root, "strict")
        self.assertTrue(any("unavailable clock" in error for error in errors), errors)

    def test_nonfinite_json_numbers_are_rejected(self) -> None:
        self.manifest["max_block_p99_ns"] = float("inf")
        self.rewrite_manifest()
        errors = bench_ci.validate_run(self.root, "strict")
        self.assertTrue(any("non-finite numbers" in error for error in errors), errors)

        path = self.root / "samples-0.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows[0]["clocks"]["event_accept_to_present_return"] = float("nan")
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        errors = bench_ci.validate_run(self.root, "strict")
        self.assertTrue(any("must be a non-negative number" in error for error in errors), errors)

    def test_complete_status_with_unavailable_clock_is_rejected(self) -> None:
        self.manifest["status"] = "complete"
        self.manifest["inconclusive_reasons"] = []
        self.rewrite_manifest()
        errors = bench_ci.validate_run(self.root, "strict")
        self.assertTrue(any("complete is not allowed" in error for error in errors), errors)


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_triggers_are_nightly_or_manual_not_pull_request(self) -> None:
        self.assertIn("schedule:", self.text)
        self.assertIn("workflow_dispatch:", self.text)
        self.assertNotIn("\n  pull_request:", self.text)
        self.assertNotIn("\n  push:", self.text)

    def test_scheduled_profiles_and_manual_native_boundary_are_explicit(self) -> None:
        self.assertIn("profiles='[\"strict\",\"hybrid\",\"accelerated\"]'", self.text)
        self.assertIn("strict|hybrid|accelerated|native", self.text)
        self.assertIn("profiles=\"[\\\"$PROFILE\\\"]\"", self.text)
        self.assertIn("profile: ${{ fromJSON(needs.select_profiles.outputs.profiles) }}", self.text)
        self.assertIn("native cell is offered only for an explicit manual attempt", self.text)

    def test_validation_precedes_upload_and_upload_requires_success(self) -> None:
        benchmark = self.text.index("cargo run --release --locked -p lumenplot-bench")
        manifest = self.text.index("scripts/bench_analysis.py --validate")
        raw = self.text.index("scripts/bench_ci.py --validate-run")
        upload = self.text.index("Upload validated benchmark evidence")
        self.assertLess(benchmark, manifest)
        self.assertLess(manifest, raw)
        self.assertLess(raw, upload)
        self.assertIn("success()", self.text[upload:])
        self.assertIn("if-no-files-found: error", self.text)
        self.assertIn("set -euo pipefail", self.text)
        self.assertNotIn("|| true", self.text)
        self.assertNotIn("continue-on-error", self.text)

    def test_workflow_uses_existing_full_action_pins(self) -> None:
        self.assertIn("actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683", self.text)
        self.assertIn("dtolnay/rust-toolchain@032958afbdc797a9164d3bc0b56325c1308924a5", self.text)
        self.assertIn("actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", self.text)
        self.assertIn("contents: read", self.text)
        self.assertIn("cancel-in-progress: false", self.text)


if __name__ == "__main__":
    unittest.main()
