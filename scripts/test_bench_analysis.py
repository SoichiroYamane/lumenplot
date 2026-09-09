#!/usr/bin/env python3
"""Unit tests for scripts/bench_analysis.py (ADR 0006 SS O-08 tooling)."""

from __future__ import annotations

import ast
import importlib.util
import json
import random
import statistics
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bench_analysis.py"

_SPEC = importlib.util.spec_from_file_location("bench_analysis_under_test", SCRIPT)
bench = importlib.util.module_from_spec(_SPEC)
sys.modules["bench_analysis_under_test"] = bench
_SPEC.loader.exec_module(bench)


RUN_ID = "27b0a5e7-3ef2-4c1a-9d4f-6f9d8e8a1234"
STAMP = "2026-08-24T00:00:00Z"

BLOCKS_P50 = [10_000_000.0, 11_000_000.0, 12_000_000.0, 13_000_000.0, 14_000_000.0]
BLOCKS_P95 = [20_000_000.0, 21_000_000.0, 22_000_000.0, 23_000_000.0, 24_000_000.0]
BLOCKS_P99 = [100_000_000.0, 105_000_000.0, 110_000_000.0, 115_000_000.0, 120_000_000.0]


def make_manifest(profile: str = "strict") -> dict:
    """Return a fresh canonical-valid manifest document."""
    return {
        "schema_version": 1,
        "run_id": RUN_ID,
        "generated_at_utc": STAMP,
        "profile": profile,
        "fixture": {
            "id": "monotonicx-10m",
            "points": 10_000_000,
            "canvas_px": [1920, 1080],
            "dpi": 96.0,
        },
        "environment": {
            "os": "Ubuntu",
            "os_version": "24.04 LTS",
            "arch": "x86_64",
            "kernel": "6.12.103",
            "cpu": "test-cpu",
            "display_scale": 1.0,
            "compositor": "X11",
            "present_mode": "fifo",
            "gpu": {
                "vendor": "test-vendor",
                "device": "test-device",
                "driver": "test-driver",
                "api": "Vulkan",
                "feature_level": "1.3",
            },
        },
        "protocol": {
            "blocks": 5,
            "min_frames_per_block": 1000,
            "quantile_method": "nearest-rank",
            "trimming": "none",
            "bootstrap": {
                "resamples": 10000,
                "ci": 0.95,
                "seed": 20260824,
                "method": "percentile",
            },
        },
        "clocks": [
            {
                "name": "event_accept_to_present_requested",
                "domain": "scheduler",
                "unit": "ns",
                "available": True,
                "description": "CPU monotonic acceptance interval",
            },
            {
                "name": "render_gpu",
                "domain": "gpu",
                "unit": "ns",
                "available": True,
                "description": "GPU timestamp interval",
            },
            {
                "name": "queue_completion",
                "domain": "queue",
                "unit": "ns",
                "available": True,
                "description": "queue completion observation",
            },
            {
                "name": "scanout_marker",
                "domain": "scanout",
                "unit": "ns",
                "available": True,
                "description": "scanout marker observation",
            },
        ],
        "blocks": [
            {
                "block_index": index,
                "pid": 1000 + index,
                "started_at_utc": STAMP,
                "frame_count": 1000,
                "p50_ns": BLOCKS_P50[index],
                "p95_ns": BLOCKS_P95[index],
                "p99_ns": BLOCKS_P99[index],
                "raw_samples_path": f"artifacts/bench/{RUN_ID}-block-{index}.jsonl",
            }
            for index in range(5)
        ],
        "pooled": {
            "clock": "event_accept_to_present_requested",
            "frame_count": 5000,
            "p50_ns": 11_800_000.0,
            "p95_ns": 23_900_000.0,
            "p99_ns": 119_700_000.0,
        },
        "max_block_p99_ns": 120_000_000.0,
        "status": "complete",
        "inconclusive_reasons": [],
    }


def write_json(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def run_cli(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *argv],
        capture_output=True,
        text=True,
        timeout=300,
    )


class NearestRankQuantileTests(unittest.TestCase):
    def test_known_values(self) -> None:
        values = [3.0, 1.0, 4.0, 1.0, 5.0]
        self.assertEqual(bench.nearest_rank(values, 0.50), 3.0)
        self.assertEqual(bench.nearest_rank(values, 0.95), 5.0)
        self.assertEqual(bench.nearest_rank(values, 0.99), 5.0)

    def test_quantile_never_falls_below_minimum(self) -> None:
        values = [7.0, 8.0, 9.0]
        self.assertEqual(bench.nearest_rank(values, 0.05), 7.0)

    def test_zero_quantile_clamps_to_minimum(self) -> None:
        self.assertEqual(bench.nearest_rank([5.0, 3.0, 4.0], 0.0), 3.0)

    def test_percentile_of_hundred_samples(self) -> None:
        values = [float(value) for value in range(1, 101)]
        self.assertEqual(bench.nearest_rank(values, 0.99), 99.0)

    def test_does_not_mutate_input(self) -> None:
        values = [3.0, 1.0, 2.0]
        bench.nearest_rank(values, 0.5)
        self.assertEqual(values, [3.0, 1.0, 2.0])

    def test_empty_list_raises(self) -> None:
        with self.assertRaises(ValueError):
            bench.nearest_rank([], 0.5)

    def test_malformed_quantile_or_sample_is_rejected(self) -> None:
        for quantile in (-0.1, float("nan"), float("inf"), 1.1):
            with self.subTest(quantile=quantile):
                with self.assertRaises(ValueError):
                    bench.nearest_rank([1.0, 2.0], quantile)
        with self.assertRaises(ValueError):
            bench.nearest_rank([1.0, float("nan")], 0.5)


class PairedBootstrapTests(unittest.TestCase):
    DELTAS = [-15_000_000.0, -10_000_000.0, -5_000_000.0, 0.0, 5_000_000.0]

    def test_deterministic_for_fixed_seed(self) -> None:
        first = bench.paired_bootstrap_ci(
            self.DELTAS, seed=20260824, resamples=2000, ci_level=0.95
        )
        second = bench.paired_bootstrap_ci(
            self.DELTAS, seed=20260824, resamples=2000, ci_level=0.95
        )
        self.assertEqual(first, second)

    def test_seed_pins_the_draw_sequence(self) -> None:
        # Replicates the implementation's documented draw order (per-index
        # resample of rng.randrange(count)) to pin the fixed-seed contract.
        rng = random.Random(20260824)
        deltas = self.DELTAS
        expected_means = [
            statistics.fmean(deltas[rng.randrange(len(deltas))] for _ in range(len(deltas)))
            for _ in range(500)
        ]
        _, low, high = bench.paired_bootstrap_ci(
            deltas, seed=20260824, resamples=500, ci_level=0.95
        )
        self.assertEqual(low, bench.nearest_rank(expected_means, 0.025))
        self.assertEqual(high, bench.nearest_rank(expected_means, 0.975))

    def test_point_estimate_is_delta_mean(self) -> None:
        point, _, _ = bench.paired_bootstrap_ci(
            self.DELTAS, seed=20260824, resamples=1000, ci_level=0.95
        )
        self.assertAlmostEqual(point, -5_000_000.0)

    def test_interval_brackets_point_estimate(self) -> None:
        point, low, high = bench.paired_bootstrap_ci(
            self.DELTAS, seed=20260824, resamples=10000, ci_level=0.95
        )
        self.assertLessEqual(low, point)
        self.assertLessEqual(point, high)
        self.assertLessEqual(low, high)

    def test_empty_deltas_raise(self) -> None:
        with self.assertRaises(ValueError):
            bench.paired_bootstrap_ci([], seed=20260824, resamples=100, ci_level=0.95)


class ManifestValidationTests(unittest.TestCase):
    def validate(self, manifest: object) -> list[str]:
        return bench.validate_manifest(manifest)

    def test_canonical_manifest_is_valid(self) -> None:
        self.assertEqual(self.validate(make_manifest()), [])

    def test_non_object_manifest_rejected(self) -> None:
        self.assertTrue(self.validate([1, 2, 3]))

    def test_every_required_field_is_enforced(self) -> None:
        for field in bench.REQUIRED_TOP_LEVEL:
            with self.subTest(field=field):
                manifest = make_manifest()
                del manifest[field]
                errors = self.validate(manifest)
                self.assertTrue(any(field in error for error in errors), errors)

    def test_schema_version_must_be_exact(self) -> None:
        manifest = make_manifest()
        manifest["schema_version"] = 2
        self.assertIn("schema_version", " ".join(self.validate(manifest)))

    def test_run_id_must_be_uuid4(self) -> None:
        manifest = make_manifest()
        manifest["run_id"] = str(uuid.uuid1())
        errors = self.validate(manifest)
        self.assertTrue(any("run_id" in error for error in errors), errors)

    def test_timestamps_require_timezone(self) -> None:
        manifest = make_manifest()
        manifest["generated_at_utc"] = "2026-08-24T00:00:00"
        errors = self.validate(manifest)
        self.assertTrue(any("generated_at_utc" in error for error in errors), errors)

    def test_offset_timestamps_are_accepted(self) -> None:
        manifest = make_manifest()
        manifest["generated_at_utc"] = "2026-08-24T09:00:00+09:00"
        self.assertEqual(self.validate(manifest), [])

    def test_unknown_profile_rejected(self) -> None:
        manifest = make_manifest()
        manifest["profile"] = "turbo"
        self.assertTrue(any("profile" in error for error in self.validate(manifest)))

    def test_protocol_constants_are_pinned_to_adr_values(self) -> None:
        cases = [
            (("protocol", "blocks"), 4),
            (("protocol", "min_frames_per_block"), 999),
            (("protocol", "quantile_method"), "mean"),
            (("protocol", "trimming"), "winsorized"),
            (("protocol", "bootstrap", "resamples"), 100),
            (("protocol", "bootstrap", "ci"), 0.9),
            (("protocol", "bootstrap", "seed"), 42),
            (("protocol", "bootstrap", "method"), "bca"),
        ]
        for path, bad_value in cases:
            with self.subTest(path=path):
                manifest = make_manifest()
                target = manifest
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = bad_value
                joined = " ".join(self.validate(manifest))
                self.assertTrue(path[-1] in joined, joined)

    def test_clock_rules(self) -> None:
        manifest = make_manifest()
        manifest["clocks"] = []
        self.assertTrue(any("clocks" in e for e in self.validate(manifest)))

        manifest = make_manifest()
        manifest["clocks"][1]["name"] = manifest["clocks"][0]["name"]
        self.assertTrue(any("duplicate clock name" in e for e in self.validate(manifest)))

        manifest = make_manifest()
        manifest["clocks"][0].update(name="frame_time", domain="scheduler")
        self.assertTrue(
            any('event_accept_to_' in e for e in self.validate(manifest)), 
            self.validate(manifest),
        )

        manifest = make_manifest()
        manifest["clocks"][0].update(name="event_accept_to_input", domain="scheduler")
        manifest["clocks"][1].update(name="queue_gpu_done", domain="queue")
        manifest["clocks"][2].update(name="scanout_marker", domain="scanout")
        manifest["clocks"][3].update(name="blit_gpu", domain="gpu", available=False)
        manifest["pooled"]["clock"] = "event_accept_to_input"
        manifest["status"] = "inconclusive"
        manifest["inconclusive_reasons"] = ["GPU clock unavailable"]
        errors = self.validate(manifest)
        self.assertEqual(errors, [], errors)

        manifest = make_manifest()
        manifest["clocks"][1].update(name="completion", domain="queue")
        self.assertTrue(any("queue_" in e for e in self.validate(manifest)))

        manifest = make_manifest()
        manifest["clocks"][1]["domain"] = "wall"
        self.assertTrue(any("domain" in e for e in self.validate(manifest)))

    def test_block_rules(self) -> None:
        manifest = make_manifest()
        manifest["blocks"] = manifest["blocks"][:4]
        self.assertTrue(any("blocks" in e for e in self.validate(manifest)))

        manifest = make_manifest()
        manifest["blocks"][2]["block_index"] = 1
        self.assertTrue(
            any("block_index" in e for e in self.validate(manifest)),
            self.validate(manifest),
        )

        manifest = make_manifest()
        manifest["blocks"][0]["frame_count"] = 999
        self.assertTrue(any("frame_count" in e for e in self.validate(manifest)))

        manifest = make_manifest()
        manifest["blocks"][0]["p50_ns"] = manifest["blocks"][0]["p99_ns"] + 1
        self.assertTrue(any("p50_ns <= p95_ns <= p99_ns" in e for e in self.validate(manifest)))

        manifest = make_manifest()
        manifest["blocks"][0]["p99_ns"] = -1.0
        self.assertTrue(any("non-negative number" in e for e in self.validate(manifest)))

        manifest = make_manifest()
        manifest["blocks"][0]["pid"] = 0
        self.assertTrue(any("pid" in e for e in self.validate(manifest)))

        manifest = make_manifest()
        manifest["blocks"][1]["pid"] = manifest["blocks"][0]["pid"]
        self.assertTrue(any("distinct pid" in e for e in self.validate(manifest)))

        manifest = make_manifest()
        manifest["blocks"][0]["started_at_utc"] = "not-a-stamp"
        self.assertTrue(any("started_at_utc" in e for e in self.validate(manifest)))

    def test_status_and_reasons_coherence(self) -> None:
        manifest = make_manifest()
        manifest["status"] = "failed"
        self.assertTrue(any("status" in e for e in self.validate(manifest)))

        manifest = make_manifest()
        manifest["status"] = "inconclusive"
        self.assertTrue(any("requires at least one reason" in e for e in self.validate(manifest)))

        manifest = make_manifest()
        manifest["status"] = "inconclusive"
        manifest["inconclusive_reasons"] = ["scanout markers unsupported"]
        self.assertEqual(self.validate(manifest), [])

        manifest = make_manifest()
        manifest["status"] = "complete"
        manifest["inconclusive_reasons"] = ["stale"]
        self.assertTrue(any("forbids" in e for e in self.validate(manifest)))

        # Round-5 finding 2: an explicit null is a validation error under
        # every status (null is not absent); absence and [] both count as
        # "nothing recorded".
        manifest = make_manifest()
        manifest["status"] = "complete"
        manifest["inconclusive_reasons"] = None
        errors = self.validate(manifest)
        self.assertTrue(
            any("inconclusive_reasons" in e and "got null" in e for e in errors),
            errors,
        )

        manifest = make_manifest()
        manifest["status"] = "inconclusive"
        manifest["inconclusive_reasons"] = None
        errors = self.validate(manifest)
        self.assertTrue(
            any("inconclusive_reasons" in e and "got null" in e for e in errors),
            errors,
        )

        manifest = make_manifest()
        del manifest["inconclusive_reasons"]
        # Required-top-level membership: absence keeps reporting the plain
        # missing-field error, never a null message.
        self.assertIn(
            "inconclusive_reasons: required field is missing", self.validate(manifest)
        )

        manifest = make_manifest()
        manifest["inconclusive_reasons"] = []
        self.assertEqual(self.validate(manifest), [])

        manifest = make_manifest()
        manifest["status"] = "inconclusive"
        manifest["inconclusive_reasons"] = []
        self.assertTrue(
            any("requires at least one reason" in e for e in self.validate(manifest))
        )

    def test_required_nested_fields_are_enforced(self) -> None:
        cases = [
            (("fixture",), bench.REQUIRED_FIXTURE_FIELDS),
            (("environment",), bench.REQUIRED_ENVIRONMENT_FIELDS),
            (("protocol",), bench.REQUIRED_PROTOCOL_FIELDS),
            (("protocol", "bootstrap"), bench.REQUIRED_BOOTSTRAP_FIELDS),
            (("blocks", 0), bench.REQUIRED_BLOCK_FIELDS),
        ]
        for base, fields in cases:
            for field in fields:
                with self.subTest(base=base, field=field):
                    manifest = make_manifest()
                    target = manifest
                    for key in base:
                        target = target[key]
                    del target[field]
                    errors = self.validate(manifest)
                    self.assertTrue(
                        any(field in error for error in errors),
                        errors,
                    )

        manifest = make_manifest()
        del manifest["clocks"][0]["name"]
        self.assertTrue(any("clocks[0].name" in e for e in self.validate(manifest)))
        manifest = make_manifest()
        del manifest["clocks"][1]["domain"]
        self.assertTrue(any("clocks[1].domain" in e for e in self.validate(manifest)))

    def test_present_but_wrong_typed_containers_are_rejected(self) -> None:
        # Round-3 finding A: present-but-non-object containers must be
        # rejected like main does; silently accepting them let --compare
        # crash on manifest["protocol"]["bootstrap"] afterwards.
        cases = [
            (("fixture",), "hello", "fixture"),
            (("environment",), [1], "environment"),
            (("protocol",), "nope", "protocol"),
            (("protocol", "bootstrap"), "x", "protocol.bootstrap"),
            (("blocks",), {"block_index": 0}, "blocks"),
        ]
        for keys, value, label in cases:
            with self.subTest(keys=keys, value=value):
                manifest = make_manifest()
                target = manifest
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                errors = self.validate(manifest)
                self.assertTrue(
                    any(label in error and "expected" in error for error in errors),
                    errors,
                )

        # A present-but-non-object entry inside blocks keeps its per-entry error.
        manifest = make_manifest()
        manifest["blocks"] = [{}]
        errors = self.validate(manifest)
        self.assertTrue(any("blocks[0]" in error for error in errors), errors)

        # Null stays accepted exactly where D1 marks |null. inconclusive_
        # reasons is deliberately absent here: since round-5 finding 2 an
        # explicit null there is a validation error under every status.
        manifest = make_manifest()
        manifest["environment"]["gpu"] = None
        manifest["environment"]["compositor"] = None
        manifest["environment"]["present_mode"] = None
        manifest["max_block_p99_ns"] = None
        manifest["pooled"] = None
        self.assertEqual(self.validate(manifest), [])

    def test_nullable_fields_accept_none(self) -> None:
        manifest = make_manifest()
        manifest["environment"]["gpu"] = None
        manifest["environment"]["compositor"] = None
        manifest["environment"]["present_mode"] = None
        manifest["max_block_p99_ns"] = None
        self.assertEqual(self.validate(manifest), [])

    def test_block_quantiles_nullable_only_when_inconclusive(self) -> None:
        def inconclusive() -> dict:
            manifest = make_manifest()
            manifest["status"] = "inconclusive"
            manifest["inconclusive_reasons"] = ["GPU timestamp stream truncated"]
            return manifest

        manifest = inconclusive()
        for block in manifest["blocks"]:
            block["p50_ns"] = block["p95_ns"] = block["p99_ns"] = None
        self.assertEqual(self.validate(manifest), [])

        manifest = inconclusive()
        for block in manifest["blocks"]:
            del block["p99_ns"]
        self.assertTrue(
            any("p99_ns" in e for e in self.validate(manifest)),
            "absent quantile must be rejected even when inconclusive",
        )

        manifest = make_manifest()
        manifest["blocks"][2]["p99_ns"] = None
        self.assertTrue(
            any("p99_ns" in e for e in self.validate(manifest)),
            "null quantile under a complete run must be rejected",
        )

    def test_every_clock_domain_is_required(self) -> None:
        manifest = make_manifest()
        manifest["clocks"] = manifest["clocks"][:-1]
        errors = self.validate(manifest)
        self.assertTrue(any("scanout" in error and "missing" in error for error in errors), errors)

    def test_complete_status_requires_available_clock_observations(self) -> None:
        manifest = make_manifest()
        manifest["clocks"][2]["available"] = False
        errors = self.validate(manifest)
        self.assertTrue(any("complete status requires" in error for error in errors), errors)

    def test_pooled_and_gate_quantiles_have_valid_shapes(self) -> None:
        manifest = make_manifest()
        manifest["pooled"]["p95_ns"] = manifest["pooled"]["p50_ns"] - 1
        errors = self.validate(manifest)
        self.assertTrue(any("pooled" in error and "p50_ns" in error for error in errors), errors)

        manifest = make_manifest()
        manifest["pooled"]["frame_count"] -= 1
        errors = self.validate(manifest)
        self.assertTrue(any("pooled.frame_count" in error for error in errors), errors)

        manifest = make_manifest()
        manifest["max_block_p99_ns"] -= 1
        errors = self.validate(manifest)
        self.assertTrue(any("max_block_p99_ns" in error for error in errors), errors)

    def test_present_but_null_fields_are_rejected(self) -> None:
        # Round-4 finding B: an explicit JSON null satisfies neither the
        # required-field loop nor the type checks (``value is not None and
        # ...``), so every non-nullable field must reject null ahead of its
        # type check. Absent fields keep reporting only "required field is
        # missing"; the D1-nullable set keeps accepting null (pinned below).
        top_level_cases = [
            ("schema_version", "expected int 1"),
            ("run_id", "expected a uuid4 string"),
            ("generated_at_utc", "expected an RFC3339 UTC timestamp"),
            ("profile", "expected one of"),
            ("fixture", "expected a JSON object"),
            ("environment", "expected a JSON object"),
            ("protocol", "expected a JSON object"),
            ("clocks", "expected a non-empty JSON array"),
            ("blocks", "expected a JSON array"),
            ("status", "expected one of"),
        ]
        for field, expected_text in top_level_cases:
            with self.subTest(field=field):
                manifest = make_manifest()
                manifest[field] = None
                errors = self.validate(manifest)
                self.assertTrue(
                    any(field in error and expected_text in error for error in errors),
                    errors,
                )

        nested_cases = [
            (("fixture",), "points"),
            (("fixture",), "canvas_px"),
            (("fixture",), "dpi"),
            (("environment",), "display_scale"),
            (("protocol",), "blocks"),
            (("protocol",), "min_frames_per_block"),
            (("protocol",), "quantile_method"),
            (("protocol",), "trimming"),
            (("protocol",), "bootstrap"),
            (("protocol", "bootstrap"), "resamples"),
            (("protocol", "bootstrap"), "ci"),
            (("protocol", "bootstrap"), "seed"),
            (("protocol", "bootstrap"), "method"),
        ]
        for base, field in nested_cases:
            with self.subTest(base=base, field=field):
                manifest = make_manifest()
                target = manifest
                for key in base:
                    target = target[key]
                target[field] = None
                label = ".".join((*base, field))
                errors = self.validate(manifest)
                self.assertTrue(
                    any(label in error and "got null" in error for error in errors),
                    errors,
                )

        block_scalar_fields = (
            "block_index",
            "pid",
            "started_at_utc",
            "frame_count",
            "raw_samples_path",
        )
        for index, field in enumerate(block_scalar_fields):
            with self.subTest(where=f"blocks[{index}]", field=field):
                manifest = make_manifest()
                manifest["blocks"][index][field] = None
                errors = self.validate(manifest)
                self.assertTrue(
                    any(
                        f"blocks[{index}].{field}" in e and "got null" in e
                        for e in errors
                    ),
                    errors,
                )

        # Null quantiles stay rejected under a complete run.
        manifest = make_manifest()
        manifest["blocks"][2]["p99_ns"] = None
        self.assertTrue(any("p99_ns" in e for e in self.validate(manifest)))

        # Clock name/domain nulls are rejected per entry.
        manifest = make_manifest()
        manifest["clocks"][0]["name"] = None
        manifest["clocks"][1]["domain"] = None
        errors = self.validate(manifest)
        self.assertTrue(any("clocks[0].name" in e and "got null" in e for e in errors))
        self.assertTrue(any("clocks[1].domain" in e and "got null" in e for e in errors))

        # Round-5 finding 1: an explicit unit=null is rejected while the
        # missing key keeps the field optional.
        manifest = make_manifest()
        manifest["clocks"][0]["unit"] = None
        errors = self.validate(manifest)
        self.assertTrue(
            any("clocks[0].unit" in e and 'got null' in e for e in errors), errors
        )
        manifest = make_manifest()
        del manifest["clocks"][0]["unit"]
        self.assertEqual(self.validate(manifest), [])

    def test_absent_fields_still_report_missing_not_null(self) -> None:
        manifest = make_manifest()
        del manifest["fixture"]
        del manifest["protocol"]["bootstrap"]
        del manifest["status"]
        del manifest["blocks"][0]["pid"]
        errors = self.validate(manifest)
        self.assertIn("fixture: required field is missing", errors)
        self.assertIn("protocol.bootstrap: required field is missing", errors)
        self.assertIn("status: required field is missing", errors)
        self.assertIn("blocks[0].pid: required field is missing", errors)
        self.assertFalse(any("got null" in error for error in errors), errors)

    def test_environment_and_fixture_shapes(self) -> None:
        manifest = make_manifest()
        manifest["environment"]["gpu"]["driver"] = ""
        self.assertTrue(any("gpu.driver" in e for e in self.validate(manifest)))

        manifest = make_manifest()
        manifest["environment"]["display_scale"] = 0
        self.assertTrue(any("display_scale" in e for e in self.validate(manifest)))

        manifest = make_manifest()
        manifest["fixture"]["canvas_px"] = [1920, 0]
        self.assertTrue(any("canvas_px" in e for e in self.validate(manifest)))

        manifest = make_manifest()
        manifest["fixture"]["points"] = 0
        self.assertTrue(any("points" in e for e in self.validate(manifest)))


class StdlibPurityTests(unittest.TestCase):
    def test_script_imports_stdlib_only(self) -> None:
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        allowed = {
            "__future__",
            "argparse",
            "contextlib",
            "datetime",
            "json",
            "math",
            "pathlib",
            "random",
            "re",
            "statistics",
            "sys",
            "typing",
            "uuid",
        }
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(imported - allowed, set(), imported)


class ValidateCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="lumenplot-bench-analysis-")
        root = Path(self.temporary.name)
        self.valid_path = write_json(root / "valid.json", make_manifest())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_valid_manifest_exits_zero(self) -> None:
        completed = run_cli("--validate", str(self.valid_path))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("manifest valid", completed.stdout)

    def test_missing_blocks_exits_two_with_actionable_error(self) -> None:
        manifest = make_manifest()
        del manifest["blocks"]
        path = write_json(Path(self.temporary.name) / "broken.json", manifest)
        completed = run_cli("--validate", str(path))
        self.assertEqual(completed.returncode, 2)
        self.assertIn("required field is missing", completed.stderr)

    def test_invalid_json_exits_two(self) -> None:
        path = Path(self.temporary.name) / "garbage.json"
        path.write_text("{nope", encoding="utf-8")
        completed = run_cli("--validate", str(path))
        self.assertEqual(completed.returncode, 2)
        self.assertIn("invalid JSON", completed.stderr)

    def test_missing_file_exits_two(self) -> None:
        completed = run_cli("--validate", str(Path(self.temporary.name) / "absent.json"))
        self.assertEqual(completed.returncode, 2)


def sample_jsonl(path: Path, rows_per_block: int = 400) -> tuple[Path, dict[str, list[float]]]:
    rng = random.Random(7)
    available: dict[str, list[float]] = {"event_accept_to_input": [], "render_gpu": []}
    lines: list[str] = []
    for block in range(5):
        for frame in range(rows_per_block):
            base = 1_000_000 * (block + 1)
            scheduler_value = base + rng.randrange(500_000)
            gpu_value = None if frame % 97 == 0 else base // 2 + rng.randrange(250_000)
            available["event_accept_to_input"].append(float(scheduler_value))
            if gpu_value is not None:
                available["render_gpu"].append(float(gpu_value))
            lines.append(
                json.dumps(
                    {
                        "block_index": block,
                        "frame_index": frame,
                        "clocks": {
                            "event_accept_to_input": scheduler_value,
                            "render_gpu": gpu_value,
                        },
                    }
                )
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, available


class QuantilesCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="lumenplot-bench-analysis-")
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_matches_reference_nearest_rank_and_counts_unavailable(self) -> None:
        path, available = sample_jsonl(self.root / "samples.jsonl")
        completed = run_cli("--quantiles", str(path), "--clock", "event_accept_to_input")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["frames"], 2000)
        self.assertEqual(payload["unavailable_frames"], 0)
        self.assertEqual(payload["method"], "nearest-rank")
        self.assertEqual(payload["unit"], "ns")
        self.assertEqual(
            payload["p50_ns"], bench.nearest_rank(available["event_accept_to_input"], 0.50)
        )
        self.assertEqual(
            payload["p99_ns"], bench.nearest_rank(available["event_accept_to_input"], 0.99)
        )

        completed = run_cli("--quantiles", str(path), "--clock", "render_gpu")
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["frames"], 2000)
        self.assertGreater(payload["unavailable_frames"], 0)
        self.assertEqual(payload["available_frames"], len(available["render_gpu"]))
        self.assertEqual(
            payload["p95_ns"], bench.nearest_rank(available["render_gpu"], 0.95)
        )

    def test_all_null_clock_yields_null_quantiles_not_zero(self) -> None:
        path = self.root / "null-clock.jsonl"
        rows = [
            json.dumps(
                {
                    "block_index": index % 5,
                    "frame_index": index,
                    "clocks": {"scanout_marker": None},
                }
            )
            for index in range(20)
        ]
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        completed = run_cli("--quantiles", str(path), "--clock", "scanout_marker")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertIsNone(payload["p99_ns"])
        self.assertEqual(payload["available_frames"], 0)
        self.assertEqual(payload["unavailable_frames"], 20)

    def test_empty_file_yields_null_quantiles(self) -> None:
        path = self.root / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        completed = run_cli("--quantiles", str(path), "--clock", "render_gpu")
        self.assertEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertIsNone(payload["p50_ns"])
        self.assertEqual(payload["frames"], 0)

    def test_malformed_inputs_exit_two(self) -> None:
        cases = {
            "bad-json.jsonl": "{oops}\n",
            "not-object.jsonl": "[1, 2]\n",
            "bad-frame-index.jsonl": json.dumps(
                {"block_index": 0, "frame_index": "zero", "clocks": {}}
            ) + "\n",
            "bad-clock-value.jsonl": json.dumps(
                {"block_index": 0, "frame_index": 0, "clocks": {"t": "slow"}}
            ) + "\n",
            "bad-clocks-shape.jsonl": json.dumps(
                {"block_index": 0, "frame_index": 0, "clocks": []}
            ) + "\n",
            "negative-clock-value.jsonl": json.dumps(
                {"block_index": 0, "frame_index": 0, "clocks": {"t": -1}}
            ) + "\n",
            "nonfinite-clock-value.jsonl": (
                '{"block_index": 0, "frame_index": 0, "clocks": {"t": NaN}}\n'
            ),
        }
        for name, text in cases.items():
            with self.subTest(file=name):
                path = self.root / name
                path.write_text(text, encoding="utf-8")
                completed = run_cli("--quantiles", str(path), "--clock", "t")
                self.assertEqual(completed.returncode, 2, completed.stdout)
                self.assertTrue(completed.stderr.startswith("ERROR:"), completed.stderr)

    def test_missing_requested_clock_exits_two(self) -> None:
        path = self.root / "missing-clock.jsonl"
        path.write_text(
            json.dumps({"block_index": 0, "frame_index": 0, "clocks": {"other": 1}}) + "\n",
            encoding="utf-8",
        )
        completed = run_cli("--quantiles", str(path), "--clock", "requested")
        self.assertEqual(completed.returncode, 2)
        self.assertIn("is missing", completed.stderr)

    def test_requires_clock_argument(self) -> None:
        path, _ = sample_jsonl(self.root / "samples.jsonl")
        completed = run_cli("--quantiles", str(path))
        self.assertEqual(completed.returncode, 2)
        self.assertIn("--clock", completed.stderr)


class CompareCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="lumenplot-bench-analysis-")
        self.root = Path(self.temporary.name)
        self.manifest_a = make_manifest()
        self.manifest_b = make_manifest()
        slower_p99 = [85_000_000.0, 92_000_000.0, 99_000_000.0, 106_000_000.0, 113_000_000.0]
        for index, block in enumerate(self.manifest_b["blocks"]):
            block["p99_ns"] = slower_p99[index]
        self.manifest_b["max_block_p99_ns"] = 113_000_000.0
        self.path_a = write_json(self.root / "a.json", self.manifest_a)
        self.path_b = write_json(self.root / "b.json", self.manifest_b)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def read_report(self) -> str:
        return (self.root / "report.md").read_text(encoding="utf-8")

    def test_report_contains_expected_tables_and_numbers(self) -> None:
        completed = run_cli(
            "--compare", str(self.path_a), str(self.path_b), "--out", str(self.root / "report.md")
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = self.read_report()
        self.assertIn("# O-08 paired benchmark comparison (A/B)", report)
        self.assertIn("| 0 | 1000 | 1000 | 100000000 | 85000000 | -15000000 | -15.00% |", report)
        self.assertIn("| 4 | 1000 | 1000 | 120000000 | 113000000 | -7000000 | -5.83% |", report)
        self.assertIn("Max block p99 (gate statistic, ns)", report)
        self.assertIn('"frame_count": 5000', report)
        self.assertIn("seed=20260824", report)
        self.assertIn("resamples=10000", report)
        self.assertIn("Overall: COMPLETE", report)

    def test_bootstrap_bounds_match_direct_library_call(self) -> None:
        completed = run_cli("--compare", str(self.path_a), str(self.path_b))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        deltas = [
            float(b) - float(a)
            for a, b in zip(BLOCKS_P99, [85e6, 92e6, 99e6, 106e6, 113e6])
        ]
        point, low, high = bench.paired_bootstrap_ci(
            deltas, seed=20260824, resamples=10000, ci_level=0.95
        )
        self.assertIn(f"[{bench._fmt(low)}, {bench._fmt(high)}]", completed.stdout)
        # Exact triple for this manifest pair under the pinned protocol
        # parameters: pins seed handling, resample order, and CI bounds.
        self.assertEqual((point, low, high), (-11000000.0, -13400000.0, -8600000.0))

    def test_report_is_byte_deterministic_across_runs(self) -> None:
        first = run_cli("--compare", str(self.path_a), str(self.path_b))
        second = run_cli("--compare", str(self.path_a), str(self.path_b))
        self.assertEqual(first.stdout, second.stdout)
        self.assertNotIn("2026-", first.stdout.replace(STAMP, ""))

    def test_cross_profile_comparison_refused_with_exit_three(self) -> None:
        manifest_hybrid = make_manifest(profile="hybrid")
        path_hybrid = write_json(self.root / "hybrid.json", manifest_hybrid)
        completed = run_cli("--compare", str(self.path_a), str(path_hybrid))
        self.assertEqual(completed.returncode, 3)
        self.assertIn("refusing cross-profile comparison", completed.stderr)
        self.assertFalse((self.root / "report.md").exists())

    def test_inconclusive_status_propagates_into_report(self) -> None:
        self.manifest_b["status"] = "inconclusive"
        self.manifest_b["inconclusive_reasons"] = ["GPU timestamp stream truncated"]
        path_b = write_json(self.root / "b-inconclusive.json", self.manifest_b)
        completed = run_cli(
            "--compare", str(self.path_a), str(path_b), "--out", str(self.root / "report.md")
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = self.read_report()
        self.assertIn("**INCONCLUSIVE**", report)
        self.assertIn("GPU timestamp stream truncated", report)
        self.assertNotIn("Overall: COMPLETE", report)

    def test_inconclusive_null_quantiles_report_is_total(self) -> None:
        # Round-2 finding 2 repro 1: inconclusive B with null quantiles used
        # to crash compare with TypeError (float(None)); now renders n/a.
        self.manifest_b["status"] = "inconclusive"
        self.manifest_b["inconclusive_reasons"] = ["GPU timestamp stream truncated"]
        for block in self.manifest_b["blocks"]:
            block["p50_ns"] = block["p95_ns"] = block["p99_ns"] = None
        self.manifest_b["max_block_p99_ns"] = None
        self.manifest_b["pooled"] = None
        path_b = write_json(self.root / "b-null-quantiles.json", self.manifest_b)
        first = run_cli(
            "--compare", str(self.path_a), str(path_b), "--out", str(self.root / "report.md")
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        report = self.read_report()
        self.assertIn("**INCONCLUSIVE**", report)
        self.assertIn("GPU timestamp stream truncated", report)
        self.assertIn("| n/a | n/a | n/a |", report.replace("||", "| |"))
        self.assertIn("n/a — no block pair has p99 available on both sides", report)
        self.assertNotIn("None", report)

    def test_compare_survives_null_reasons_and_sparse_blocks(self) -> None:
        # Round-2 finding 2 repro 3: sparse-but-valid blocks (missing pooled,
        # null compositor) used to crash; they stay total and deterministic.
        # Since round-5 finding 2 an explicit inconclusive_reasons=null no
        # longer validates, so this CLI totality repro uses [] instead —
        # semantically identical ("nothing recorded") and still exercises
        # the falsy-reasons report path end to end.
        self.manifest_a["inconclusive_reasons"] = []
        self.manifest_b["inconclusive_reasons"] = []
        path_a = write_json(self.root / "a-empty-reasons.json", self.manifest_a)
        path_b = write_json(self.root / "b-empty-reasons.json", self.manifest_b)
        completed = run_cli("--compare", str(path_a), str(path_b))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, run_cli("--compare", str(path_a), str(path_b)).stdout)

        manifest_a = make_manifest()
        manifest_b = make_manifest()
        slower_p99 = [85_000_000.0, 92_000_000.0, 99_000_000.0, 106_000_000.0, 113_000_000.0]
        for index, block in enumerate(manifest_b["blocks"]):
            block["p99_ns"] = slower_p99[index]
        manifest_b["max_block_p99_ns"] = 113_000_000.0
        for manifest in (manifest_a, manifest_b):
            manifest["pooled"] = None
            manifest["inconclusive_reasons"] = []
            manifest["environment"]["compositor"] = None
        sparse_a = write_json(self.root / "sparse-a.json", manifest_a)
        sparse_b = write_json(self.root / "sparse-b.json", manifest_b)
        completed = run_cli("--compare", str(sparse_a), str(sparse_b))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("| 0 | 1000 | 1000 | 100000000 | 85000000 | -15000000 | -15.00% |", completed.stdout)
        self.assertIn("n/a", completed.stdout)  # pooled section renders null

    def test_null_reasons_manifest_exits_two_not_crash(self) -> None:
        # Round-5 finding 2, CLI level: an explicit inconclusive_reasons=null
        # on a complete pair must exit 2 via the validator, never reach the
        # compare code paths that used to consume it.
        self.manifest_a["inconclusive_reasons"] = None
        path_bad = write_json(self.root / "a-null-reasons.json", self.manifest_a)
        completed = run_cli("--compare", str(path_bad), str(self.path_b))
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertIn(
            "A: inconclusive_reasons: expected an array of non-empty strings, got null",
            completed.stderr,
        )
        self.assertNotIn("TypeError", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_invalid_side_manifest_exits_two_with_label(self) -> None:
        manifest = make_manifest()
        del manifest["protocol"]
        path_bad = write_json(self.root / "bad.json", manifest)
        completed = run_cli("--compare", str(self.path_a), str(path_bad))
        self.assertEqual(completed.returncode, 2)
        self.assertTrue(
            any(line.startswith("ERROR: B:") for line in completed.stderr.splitlines()),
            completed.stderr,
        )

    def test_wrong_typed_container_manifest_exits_two_not_crash(self) -> None:
        # Round-3 finding A, CLI level: a present-but-non-object protocol
        # must exit 2 with the validator error, never an uncaught TypeError.
        manifest = make_manifest()
        manifest["protocol"] = "nope"
        path_bad = write_json(self.root / "wrong-typed.json", manifest)
        completed = run_cli("--compare", str(self.path_a), str(path_bad))
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertIn("protocol: expected a JSON object", completed.stderr)
        self.assertNotIn("TypeError", completed.stderr)

    def test_null_container_manifest_exits_two_not_crash(self) -> None:
        # Round-4 finding B, CLI level: an explicit null where --compare
        # needs an object (protocol.bootstrap on side A feeds
        # _bootstrap_params directly) must exit 2 via the validator, never
        # raise TypeError.
        manifest = make_manifest()
        manifest["protocol"]["bootstrap"] = None
        path_bad = write_json(self.root / "null-bootstrap.json", manifest)
        completed = run_cli("--compare", str(path_bad), str(self.path_b))
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertIn(
            "protocol.bootstrap: expected a JSON object, got null", completed.stderr
        )
        self.assertNotIn("TypeError", completed.stderr)
        self.assertNotIn("Traceback", completed.stderr)

    def test_missing_input_file_exits_two(self) -> None:
        completed = run_cli(
            "--compare", str(self.root / "absent-a.json"), str(self.path_b)
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("cannot read file", completed.stderr)


class CliContractTests(unittest.TestCase):
    def test_no_arguments_prints_usage_and_exits_two(self) -> None:
        completed = run_cli()
        self.assertEqual(completed.returncode, 2)
        self.assertIn("usage:", completed.stderr)

    def test_modes_are_mutually_exclusive(self) -> None:
        completed = run_cli("--validate", "x.json", "--clock", "t")
        self.assertEqual(completed.returncode, 2)

    def test_out_requires_compare(self) -> None:
        completed = run_cli("--validate", "x.json", "--out", "r.md")
        self.assertEqual(completed.returncode, 2)

    def test_clock_requires_quantiles(self) -> None:
        completed = run_cli("--clock", "t")
        self.assertEqual(completed.returncode, 2)

    def test_help_mentions_all_modes(self) -> None:
        completed = run_cli("--help")
        self.assertEqual(completed.returncode, 0)
        for flag in ("--validate", "--quantiles", "--compare", "--clock", "--out"):
            self.assertIn(flag, completed.stdout)


if __name__ == "__main__":
    unittest.main()
