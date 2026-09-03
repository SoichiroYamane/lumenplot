#!/usr/bin/env python3
"""ADR 0006 SS O-08 benchmark manifest analysis tooling (stdlib only).

Implements the R2 analysis contract for the accepted benchmark protocol:
five fresh-process blocks, at least 1000 measured frames per block,
nearest-rank p50/p95/p99 over retained raw samples, no trimming, paired
fixed-seed percentile-bootstrap confidence intervals, and profiles that are
never mixed or compared across. Unavailable instrumentation is reported as
null and propagates as ``inconclusive``; it is never substituted with zero.

Modes (mutually exclusive):

* ``--validate MANIFEST.json``
    Authoritative schema validation for the internal benchmark manifest.
* ``--quantiles SAMPLES.jsonl --clock NAME``
    Nearest-rank p50/p95/p99 for one clock over raw JSONL measurement rows.
* ``--compare A.json B.json [--out REPORT.md]``
    Paired A/B report: per-block p99 deltas, descriptive summaries,
    max-block-p99 comparison, and a bootstrap CI over paired block deltas.
    Block pairs whose p99 is unavailable (null) on either side are rendered
    as ``n/a`` and excluded from the paired statistics instead of crashing.

The manifest and JSONL formats are internal tooling contracts only; they are
not public Scene, RenderPacket, project, or persistence formats.

Exit codes: 0 success, 2 invalid input or schema, 3 cross-profile refusal.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_CROSS_PROFILE = 3

SCHEMA_VERSION = 1
PROFILES = ("strict", "hybrid", "accelerated", "native")
CLOCK_DOMAINS = ("scheduler", "gpu", "queue", "scanout")
REQUIRED_CLOCK_DOMAINS = frozenset(CLOCK_DOMAINS)
STATUSES = ("complete", "inconclusive")
QUANTILE_METHOD = "nearest-rank"
TRIMMING = "none"
BLOCK_COUNT = 5
MIN_FRAMES_PER_BLOCK = 1000
BOOTSTRAP_RESAMPLES = 10000
BOOTSTRAP_CI = 0.95
BOOTSTRAP_SEED = 20260824
BOOTSTRAP_METHOD = "percentile"

REQUIRED_TOP_LEVEL = (
    "schema_version",
    "run_id",
    "generated_at_utc",
    "profile",
    "fixture",
    "environment",
    "protocol",
    "clocks",
    "blocks",
    "pooled",
    "max_block_p99_ns",
    "status",
    "inconclusive_reasons",
)

GPU_FIELDS = ("vendor", "device", "driver", "api", "feature_level")
ENV_STRING_FIELDS = ("os", "os_version", "arch", "kernel", "cpu")

# Pinned D1 decision: every schema field below is mandatory. Fields absent
# from these tuples are optional; the explicitly nullable fields are
# environment.gpu, environment.compositor, environment.present_mode, and
# max_block_p99_ns, plus block p50/p95/p99_ns when status is "inconclusive".
REQUIRED_FIXTURE_FIELDS = ("id", "points", "canvas_px", "dpi")
REQUIRED_ENVIRONMENT_FIELDS = ("os", "os_version", "arch", "kernel", "cpu", "display_scale")
REQUIRED_PROTOCOL_FIELDS = (
    "blocks",
    "min_frames_per_block",
    "quantile_method",
    "trimming",
    "bootstrap",
)
REQUIRED_BOOTSTRAP_FIELDS = ("resamples", "ci", "seed", "method")
REQUIRED_CLOCK_FIELDS = ("name", "domain")
REQUIRED_BLOCK_FIELDS = (
    "block_index",
    "pid",
    "started_at_utc",
    "frame_count",
    "p50_ns",
    "p95_ns",
    "p99_ns",
    "raw_samples_path",
)
REQUIRED_POOLED_FIELDS = ("clock", "frame_count", "p50_ns", "p95_ns", "p99_ns")
NULLABLE_QUANTILE_STATUS = "inconclusive"

RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$"
)


class InputError(Exception):
    """Raised when an input file cannot be read or parsed."""


# Sentinel for "key absent from its container": lets the container validators
# tell a missing field (already reported by the required-field loops) apart
# from an explicit JSON null (rejected by finding B).
_ABSENT = object()


def is_number(value: Any) -> bool:
    """Return True for real JSON numbers (bool excluded)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_finite_number(value: Any) -> bool:
    """Return True for a finite JSON number (bool excluded)."""
    return is_number(value) and (
        not isinstance(value, float) or math.isfinite(value)
    )


def is_finite_nonnegative_number(value: Any) -> bool:
    """Return True for a finite, non-negative JSON number."""
    return is_finite_number(value) and value >= 0


def _nonfinite_number_errors(value: Any, path: str = "manifest") -> list[str]:
    """Find non-standard JSON NaN/Infinity values accepted by ``json.loads``."""
    errors: list[str] = []
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{path}: non-finite numbers are not valid benchmark evidence")
    elif isinstance(value, dict):
        for key, child in value.items():
            errors.extend(_nonfinite_number_errors(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_nonfinite_number_errors(child, f"{path}[{index}]"))
    return errors


def is_int(value: Any) -> bool:
    """Return True for JSON integers (bool excluded)."""
    return isinstance(value, int) and not isinstance(value, bool)


def is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def is_rfc3339_utc(value: Any) -> bool:
    if not isinstance(value, str) or RFC3339_RE.match(value) is None:
        return False
    normalized = value.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def is_uuid4(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.version == 4


def nearest_rank(values: list[float], quantile: float) -> float:
    """Nearest-rank quantile: rank = ceil(q * n) on ascending sort, 1-indexed."""
    if not values:
        raise ValueError("nearest-rank quantile of an empty sample list")
    if not is_finite_number(quantile) or not 0.0 <= quantile <= 1.0:
        raise ValueError("nearest-rank quantile must be finite and between 0 and 1")
    if any(
        not is_number(value)
        or (isinstance(value, float) and not math.isfinite(value))
        for value in values
    ):
        raise ValueError("nearest-rank samples must be finite numbers")
    ordered = sorted(values)
    rank = min(max(math.ceil(quantile * len(ordered)), 1), len(ordered))
    return ordered[rank - 1]


def paired_bootstrap_ci(
    deltas: list[float],
    *,
    seed: int,
    resamples: int,
    ci_level: float,
) -> tuple[float, float, float]:
    """Fixed-seed percentile bootstrap CI for the mean of paired block deltas.

    Returns ``(point_estimate, ci_low, ci_high)`` where the bounds are the
    nearest-rank alpha/2 and 1-alpha/2 quantiles of the resample means. The
    RNG draw sequence depends only on ``seed``, so results are deterministic.
    """
    if not deltas:
        raise ValueError("paired bootstrap over an empty delta list")
    if not is_int(seed):
        raise ValueError("paired bootstrap seed must be an integer")
    if not is_int(resamples) or resamples <= 0:
        raise ValueError("paired bootstrap resamples must be a positive integer")
    if (
        not is_finite_number(ci_level)
        or not 0.0 < ci_level < 1.0
    ):
        raise ValueError("paired bootstrap confidence level must be finite and between 0 and 1")
    if any(
        not is_number(delta)
        or (isinstance(delta, float) and not math.isfinite(delta))
        for delta in deltas
    ):
        raise ValueError("paired bootstrap deltas must be finite numbers")
    rng = random.Random(seed)
    count = len(deltas)
    means: list[float] = []
    for _ in range(resamples):
        sample = [deltas[rng.randrange(count)] for _ in range(count)]
        means.append(statistics.fmean(sample))
    alpha = 1.0 - ci_level
    low = nearest_rank(means, alpha / 2.0)
    high = nearest_rank(means, 1.0 - alpha / 2.0)
    return statistics.fmean(deltas), low, high


# ---------------------------------------------------------------------------
# Manifest schema validation (authoritative per the pinned D1 decision)
# ---------------------------------------------------------------------------


def validate_manifest(manifest: Any) -> list[str]:
    """Validate a decoded manifest document and return actionable errors."""
    errors: list[str] = []

    def add(path: str, message: str) -> None:
        errors.append(f"{path}: {message}")

    if not isinstance(manifest, dict):
        return ["manifest: expected a JSON object"]

    errors.extend(_nonfinite_number_errors(manifest))
    for field in REQUIRED_TOP_LEVEL:
        if field not in manifest:
            add(field, "required field is missing")

    # Round-4 finding B: an explicit JSON null satisfies neither the
    # required-field loop above nor the type checks (every guard reads
    # ``value is not None and ...``), so each non-nullable field rejects
    # null ahead of its type check. Absent fields keep reporting only
    # "required field is missing". The D1-nullable fields -- pooled,
    # max_block_p99_ns, inconclusive_reasons, environment.gpu,
    # environment.compositor, environment.present_mode, clock
    # unit/available/description, and block quantiles while inconclusive --
    # keep accepting null.
    version = manifest.get("schema_version")
    if "schema_version" in manifest:
        if version is None:
            add("schema_version", f"expected int {SCHEMA_VERSION}, got null")
        elif not is_int(version) or version != SCHEMA_VERSION:
            add("schema_version", f"expected int {SCHEMA_VERSION}, got {version!r}")

    run_id = manifest.get("run_id")
    if "run_id" in manifest:
        if run_id is None:
            add("run_id", "expected a uuid4 string, got null")
        elif not is_uuid4(run_id):
            add("run_id", f"expected a uuid4 string, got {run_id!r}")

    generated_at = manifest.get("generated_at_utc")
    if "generated_at_utc" in manifest:
        if generated_at is None:
            add("generated_at_utc", "expected an RFC3339 UTC timestamp, got null")
        elif not is_rfc3339_utc(generated_at):
            add("generated_at_utc", f"expected an RFC3339 UTC timestamp, got {generated_at!r}")

    profile = manifest.get("profile")
    if "profile" in manifest:
        if profile is None:
            add("profile", f"expected one of {list(PROFILES)}, got null")
        elif profile not in PROFILES:
            add("profile", f"expected one of {list(PROFILES)}, got {profile!r}")

    _validate_fixture(manifest.get("fixture", _ABSENT), add)
    _validate_environment(manifest.get("environment", _ABSENT), add)
    _validate_protocol(manifest.get("protocol", _ABSENT), add)
    _validate_clocks(manifest.get("clocks", _ABSENT), add)
    min_frames = _protocol_min_frames(manifest.get("protocol"))
    _validate_blocks(
        manifest.get("blocks", _ABSENT), min_frames, add, manifest.get("status")
    )

    pooled = manifest.get("pooled")
    _validate_pooled(pooled, manifest.get("status"), add)

    max_block_p99 = manifest.get("max_block_p99_ns")
    if max_block_p99 is not None and (
        not is_finite_nonnegative_number(max_block_p99)
    ):
        add("max_block_p99_ns", "expected a non-negative number or null")

    _validate_status(
        manifest.get("status", _ABSENT),
        manifest.get("inconclusive_reasons", _ABSENT),
        add,
    )
    _validate_manifest_consistency(manifest, add)
    return errors


def _validate_fixture(fixture: Any, add: Any) -> None:
    if fixture is _ABSENT:
        return
    if fixture is None:
        add("fixture", "expected a JSON object, got null")
        return
    if not isinstance(fixture, dict):
        add("fixture", "expected a JSON object")
        return
    for field in REQUIRED_FIXTURE_FIELDS:
        if field not in fixture:
            add(f"fixture.{field}", "required field is missing")
    if "id" in fixture:
        if fixture["id"] is None:
            add("fixture.id", "expected a non-empty string, got null")
        elif not is_nonempty_str(fixture["id"]):
            add("fixture.id", "expected a non-empty string")
    points = fixture.get("points")
    if "points" in fixture:
        if points is None:
            add("fixture.points", "expected a positive int, got null")
        elif not is_int(points) or points <= 0:
            add("fixture.points", "expected a positive int")
    canvas = fixture.get("canvas_px")
    if "canvas_px" in fixture:
        if canvas is None:
            add("fixture.canvas_px", "expected [width, height] positive ints, got null")
        elif not isinstance(canvas, list) or len(canvas) != 2 or not all(
            is_int(side) and side > 0 for side in canvas
        ):
            add("fixture.canvas_px", "expected [width, height] positive ints")
    dpi = fixture.get("dpi")
    if "dpi" in fixture:
        if dpi is None:
            add("fixture.dpi", "expected a positive number, got null")
        elif not is_finite_number(dpi) or dpi <= 0:
            add("fixture.dpi", "expected a positive number")


def _validate_environment(environment: Any, add: Any) -> None:
    if environment is _ABSENT:
        return
    if environment is None:
        add("environment", "expected a JSON object, got null")
        return
    if not isinstance(environment, dict):
        add("environment", "expected a JSON object")
        return
    for field in REQUIRED_ENVIRONMENT_FIELDS:
        if field not in environment:
            add(f"environment.{field}", "required field is missing")
    for field in ENV_STRING_FIELDS:
        if field in environment:
            if environment[field] is None:
                add(f"environment.{field}", "expected a non-empty string, got null")
            elif not is_nonempty_str(environment[field]):
                add(f"environment.{field}", "expected a non-empty string")
    scale = environment.get("display_scale")
    if "display_scale" in environment:
        if scale is None:
            add("environment.display_scale", "expected a positive number, got null")
        elif not is_finite_number(scale) or scale <= 0:
            add("environment.display_scale", "expected a positive number")
    for field in ("compositor", "present_mode"):
        if field in environment and environment[field] is not None and not is_nonempty_str(
            environment[field]
        ):
            add(f"environment.{field}", "expected a non-empty string or null")
    gpu = environment.get("gpu")
    if gpu is None:
        return
    if not isinstance(gpu, dict):
        add("environment.gpu", "expected a JSON object or null")
        return
    for field in GPU_FIELDS:
        if field in gpu:
            if gpu[field] is None:
                add(f"environment.gpu.{field}", "expected a non-empty string, got null")
            elif not is_nonempty_str(gpu[field]):
                add(f"environment.gpu.{field}", "expected a non-empty string")


def _validate_pooled(pooled: Any, status: Any, add: Any) -> None:
    """Validate the descriptive pooled summary without accepting fake values."""
    if pooled is None:
        return
    if not isinstance(pooled, dict):
        add("pooled", "expected a JSON object of descriptive statistics or null")
        return
    for field in REQUIRED_POOLED_FIELDS:
        if field not in pooled:
            add(f"pooled.{field}", "required field is missing")

    clock = pooled.get("clock")
    if "clock" in pooled:
        if clock is None:
            add("pooled.clock", "expected a non-empty string, got null")
        elif not is_nonempty_str(clock):
            add("pooled.clock", "expected a non-empty string")

    frame_count = pooled.get("frame_count")
    if "frame_count" in pooled:
        if frame_count is None:
            add("pooled.frame_count", "expected a non-negative int, got null")
        elif not is_int(frame_count) or frame_count < 0:
            add("pooled.frame_count", "expected a non-negative int")

    quantiles: list[float] = []
    for field in ("p50_ns", "p95_ns", "p99_ns"):
        value = pooled.get(field)
        if value is None:
            if status != NULLABLE_QUANTILE_STATUS:
                add(
                    f"pooled.{field}",
                    "expected a non-negative number or null when inconclusive",
                )
            continue
        if not is_finite_nonnegative_number(value):
            add(f"pooled.{field}", "expected a non-negative number")
        else:
            quantiles.append(value)
    if len(quantiles) == 3 and not (
        quantiles[0] <= quantiles[1] <= quantiles[2]
    ):
        add("pooled", "expected p50_ns <= p95_ns <= p99_ns")


def _validate_manifest_consistency(manifest: dict[str, Any], add: Any) -> None:
    """Validate cross-field facts that are knowable without raw JSONL files."""
    clocks = manifest.get("clocks")
    blocks = manifest.get("blocks")
    status = manifest.get("status")
    if isinstance(clocks, list):
        valid_clocks = [clock for clock in clocks if isinstance(clock, dict)]
        clock_names = {
            clock["name"]
            for clock in valid_clocks
            if is_nonempty_str(clock.get("name"))
        }
        scheduler_names = [
            clock["name"]
            for clock in valid_clocks
            if clock.get("domain") == "scheduler"
            and is_nonempty_str(clock.get("name"))
        ]
        if isinstance(manifest.get("pooled"), dict):
            pooled_clock = manifest["pooled"].get("clock")
            if is_nonempty_str(pooled_clock):
                if pooled_clock not in clock_names:
                    add("pooled.clock", "must name a clock in clocks")
                elif scheduler_names and pooled_clock != scheduler_names[0]:
                    add(
                        "pooled.clock",
                        "must name the first scheduler-domain clock used for gate statistics",
                    )
        measurement = manifest.get("measurement")
        if isinstance(measurement, dict):
            scheduler_clock = measurement.get("scheduler_clock")
            if is_nonempty_str(scheduler_clock):
                if scheduler_clock not in scheduler_names:
                    add(
                        "measurement.scheduler_clock",
                        "must name a scheduler-domain clock in clocks",
                    )
            for field in ("present_observed", "scanout_observed"):
                if field in measurement and not isinstance(measurement[field], bool):
                    add(f"measurement.{field}", "expected a bool")
            if status == "complete" and (
                measurement.get("present_observed") is False
                or measurement.get("scanout_observed") is False
            ):
                add(
                    "measurement",
                    "complete status is not allowed when present or scanout observation is unavailable",
                )
        if status == "complete":
            for index, clock in enumerate(valid_clocks):
                if clock.get("available") is not True:
                    add(
                        f"clocks[{index}].available",
                        "complete status requires every clock to be explicitly available",
                    )
    if isinstance(blocks, list) and isinstance(manifest.get("pooled"), dict):
        frame_counts = [
            block["frame_count"]
            for block in blocks
            if isinstance(block, dict) and is_int(block.get("frame_count"))
        ]
        pooled_count = manifest["pooled"].get("frame_count")
        if len(frame_counts) == len(blocks) and is_int(pooled_count):
            expected_count = sum(frame_counts)
            if pooled_count != expected_count:
                add(
                    "pooled.frame_count",
                    f"must equal the sum of block frame counts ({expected_count}), "
                    f"got {pooled_count!r}",
                )
    if isinstance(blocks, list):
        p99_values = [
            block["p99_ns"]
            for block in blocks
            if isinstance(block, dict)
            and is_finite_nonnegative_number(block.get("p99_ns"))
        ]
        reported_max = manifest.get("max_block_p99_ns")
        if p99_values and reported_max is not None:
            expected_max = max(p99_values)
            if reported_max != expected_max:
                add(
                    "max_block_p99_ns",
                    f"must equal the maximum available block p99 ({expected_max!r}), "
                    f"got {reported_max!r}",
                )




def _validate_protocol(protocol: Any, add: Any) -> None:
    if protocol is _ABSENT:
        return
    if protocol is None:
        add("protocol", "expected a JSON object, got null")
        return
    if not isinstance(protocol, dict):
        add("protocol", "expected a JSON object")
        return
    for field in REQUIRED_PROTOCOL_FIELDS:
        if field not in protocol:
            add(f"protocol.{field}", "required field is missing")
    blocks = protocol.get("blocks")
    if "blocks" in protocol:
        if blocks is None:
            add("protocol.blocks", f"expected int {BLOCK_COUNT}, got null")
        elif not is_int(blocks) or blocks != BLOCK_COUNT:
            add("protocol.blocks", f"expected int {BLOCK_COUNT}, got {blocks!r}")
    min_frames = protocol.get("min_frames_per_block")
    if "min_frames_per_block" in protocol:
        if min_frames is None:
            add(
                "protocol.min_frames_per_block",
                f"expected int {MIN_FRAMES_PER_BLOCK}, got null",
            )
        elif not is_int(min_frames) or min_frames != MIN_FRAMES_PER_BLOCK:
            add(
                "protocol.min_frames_per_block",
                f"expected int {MIN_FRAMES_PER_BLOCK}, got {min_frames!r}",
            )
    if "quantile_method" in protocol:
        if protocol.get("quantile_method") is None:
            add("protocol.quantile_method", f"expected \"{QUANTILE_METHOD}\", got null")
        elif protocol["quantile_method"] != QUANTILE_METHOD:
            add(
                "protocol.quantile_method",
                f"expected \"{QUANTILE_METHOD}\", got {protocol['quantile_method']!r}",
            )
    if "trimming" in protocol:
        if protocol.get("trimming") is None:
            add("protocol.trimming", f"expected \"{TRIMMING}\", got null")
        elif protocol["trimming"] != TRIMMING:
            add("protocol.trimming", f"expected \"{TRIMMING}\", got {protocol['trimming']!r}")
    bootstrap = protocol.get("bootstrap")
    if "bootstrap" not in protocol:
        return
    if bootstrap is None:
        add("protocol.bootstrap", "expected a JSON object, got null")
        return
    if not isinstance(bootstrap, dict):
        add("protocol.bootstrap", "expected a JSON object")
        return
    for field in REQUIRED_BOOTSTRAP_FIELDS:
        if field not in bootstrap:
            add("protocol.bootstrap." + field, "required field is missing")
    resamples = bootstrap.get("resamples")
    if "resamples" in bootstrap:
        if resamples is None:
            add(
                "protocol.bootstrap.resamples",
                f"expected int {BOOTSTRAP_RESAMPLES}, got null",
            )
        elif not is_int(resamples) or resamples != BOOTSTRAP_RESAMPLES:
            add(
                "protocol.bootstrap.resamples",
                f"expected int {BOOTSTRAP_RESAMPLES}, got {resamples!r}",
            )
    ci = bootstrap.get("ci")
    if "ci" in bootstrap:
        if ci is None:
            add("protocol.bootstrap.ci", f"expected {BOOTSTRAP_CI}, got null")
        elif not is_number(ci) or ci != BOOTSTRAP_CI:
            add("protocol.bootstrap.ci", f"expected {BOOTSTRAP_CI}, got {ci!r}")
    seed = bootstrap.get("seed")
    if "seed" in bootstrap:
        if seed is None:
            add("protocol.bootstrap.seed", f"expected int {BOOTSTRAP_SEED}, got null")
        elif not is_int(seed) or seed != BOOTSTRAP_SEED:
            add("protocol.bootstrap.seed", f"expected int {BOOTSTRAP_SEED}, got {seed!r}")
    if "method" in bootstrap:
        if bootstrap.get("method") is None:
            add("protocol.bootstrap.method", f"expected \"{BOOTSTRAP_METHOD}\", got null")
        elif bootstrap["method"] != BOOTSTRAP_METHOD:
            add(
                "protocol.bootstrap.method",
                f"expected \"{BOOTSTRAP_METHOD}\", got {bootstrap['method']!r}",
            )


def _protocol_min_frames(protocol: Any) -> int:
    if isinstance(protocol, dict):
        candidate = protocol.get("min_frames_per_block")
        if is_int(candidate) and candidate > 0:
            return candidate
    return MIN_FRAMES_PER_BLOCK


def _validate_clocks(clocks: Any, add: Any) -> None:
    if clocks is _ABSENT:
        return
    if clocks is None:
        add("clocks", "expected a non-empty JSON array, got null")
        return
    if not isinstance(clocks, list):
        add("clocks", "expected a non-empty JSON array")
        return
    if not clocks:
        add("clocks", "expected at least one clock entry")
    seen_names: set[str] = set()
    seen_domains: set[str] = set()
    for index, clock in enumerate(clocks):
        path = f"clocks[{index}]"
        if not isinstance(clock, dict):
            add(path, "expected a JSON object")
            continue
        name = clock.get("name")
        if "name" not in clock:
            add(f"{path}.name", "required field is missing")
        elif name is None:
            add(f"{path}.name", "expected a non-empty string, got null")
        elif not is_nonempty_str(name):
            add(f"{path}.name", "expected a non-empty string")
        elif name in seen_names:
            add(f"{path}.name", f"duplicate clock name {name!r}")
        else:
            seen_names.add(name)
        if "domain" not in clock:
            add(f"{path}.domain", "required field is missing")
            domain = None
        else:
            domain = clock.get("domain")
            if domain is None:
                add(
                    f"{path}.domain",
                    f"expected one of {list(CLOCK_DOMAINS)}, got null",
                )
            elif domain not in CLOCK_DOMAINS:
                add(
                    f"{path}.domain",
                    f"expected one of {list(CLOCK_DOMAINS)}, got {domain!r}",
                )
            else:
                seen_domains.add(domain)
        unit = clock.get("unit")
        if "unit" in clock and unit != "ns":
            # Null is not absent: an explicit unit=null is rejected, while a
            # missing key keeps the field optional (D1 record-only set).
            detail = "null" if unit is None else repr(unit)
            add(f"{path}.unit", f"expected \"ns\", got {detail}")
        available = clock.get("available")
        if available is not None and not isinstance(available, bool):
            add(f"{path}.available", "expected a bool")
        # D2 naming boundaries: scheduler-origin intervals always use the
        # event_accept_to_ prefix; queue-completion observations use queue_.
        if domain == "scheduler" and is_nonempty_str(name):
            if not name.startswith("event_accept_to_"):
                add(
                    f"{path}.name",
                    "scheduler-domain clock names must start with \"event_accept_to_\"",
                )
        if domain == "queue" and is_nonempty_str(name):
            if not name.startswith("queue_"):
                add(f"{path}.name", "queue-domain clock names must start with \"queue_\"")
    for domain in CLOCK_DOMAINS:
        if domain not in seen_domains:
            add(f"clocks.{domain}", "required clock domain is missing")


def _validate_blocks(
    blocks: Any,
    min_frames: int,
    add: Any,
    status: Any = None,
) -> None:
    if blocks is _ABSENT:
        return
    if blocks is None:
        add("blocks", f"expected a JSON array of {BLOCK_COUNT} blocks, got null")
        return
    if not isinstance(blocks, list):
        add("blocks", f"expected a JSON array of {BLOCK_COUNT} blocks")
        return
    if len(blocks) != BLOCK_COUNT:
        add("blocks", f"expected exactly {BLOCK_COUNT} blocks, got {len(blocks)}")
    indexes: list[int] = []
    pids: list[int] = []
    for index, block in enumerate(blocks):
        path = f"blocks[{index}]"
        if not isinstance(block, dict):
            add(path, "expected a JSON object")
            continue
        # Missing required fields are reported by the REQUIRED_BLOCK_FIELDS
        # loop below; the branches here only classify values that are
        # present (null vs wrong-typed).
        if "block_index" in block:
            block_index = block["block_index"]
            if block_index is None:
                add(f"{path}.block_index", "expected an int, got null")
            elif not is_int(block_index):
                add(f"{path}.block_index", "expected an int")
            else:
                indexes.append(block_index)
        if "pid" in block:
            pid = block["pid"]
            if pid is None:
                add(f"{path}.pid", "expected a positive int, got null")
            elif not is_int(pid) or pid <= 0:
                add(f"{path}.pid", "expected a positive int")
            else:
                pids.append(pid)
        started_at = block.get("started_at_utc")
        if "started_at_utc" in block:
            if started_at is None:
                add(f"{path}.started_at_utc", "expected an RFC3339 UTC timestamp, got null")
            elif not is_rfc3339_utc(started_at):
                add(f"{path}.started_at_utc", f"expected an RFC3339 UTC timestamp, got {started_at!r}")
        for field in REQUIRED_BLOCK_FIELDS:
            if field not in block:
                add(f"{path}.{field}", "required field is missing")
        frame_count = block.get("frame_count")
        if "frame_count" in block:
            if frame_count is None:
                add(f"{path}.frame_count", f"expected int >= {min_frames}, got null")
            elif not is_int(frame_count) or frame_count < min_frames:
                add(f"{path}.frame_count", f"expected int >= {min_frames}, got {frame_count!r}")
        quantiles: list[float] = []
        for field in ("p50_ns", "p95_ns", "p99_ns"):
            value = block.get(field)
            if value is None:
                if status == NULLABLE_QUANTILE_STATUS:
                    continue
                add(f"{path}.{field}", "expected a non-negative number or null when inconclusive")
                continue
            if not is_finite_nonnegative_number(value):
                add(f"{path}.{field}", "expected a non-negative number")
            else:
                quantiles.append(value)
        if len(quantiles) == 3 and not (
            quantiles[0] <= quantiles[1] <= quantiles[2]
        ):
            add(path, "expected p50_ns <= p95_ns <= p99_ns")
        raw_path = block.get("raw_samples_path")
        if "raw_samples_path" in block:
            if raw_path is None:
                add(f"{path}.raw_samples_path", "expected a non-empty string, got null")
            elif not is_nonempty_str(raw_path):
                add(f"{path}.raw_samples_path", "expected a non-empty string")
    if indexes and sorted(indexes) != list(range(BLOCK_COUNT)):
        add(
            "blocks[].block_index",
            f"expected block_index 0..{BLOCK_COUNT - 1} exactly once each, got {sorted(indexes)}",
        )
    if len(pids) != len(set(pids)):
        add("blocks[].pid", "each fresh-process block must have a distinct pid")


def _validate_status(status: Any, reasons: Any, add: Any) -> None:
    if status is _ABSENT:
        return
    if status is None:
        add("status", f"expected one of {list(STATUSES)}, got null")
    elif status not in STATUSES:
        add("status", f"expected one of {list(STATUSES)}, got {status!r}")
    # inconclusive_reasons is nullable only as "nothing recorded": an absent
    # field and an empty array are equivalent, but an explicit null is a
    # validation error under every status (null is not absent).
    # An empty array counts as "nothing recorded"; a non-empty array counts
    # as recorded reasons and must match the status exactly.
    if reasons is _ABSENT or (isinstance(reasons, list) and not reasons):
        has_reasons = False
    elif reasons is None:
        add("inconclusive_reasons", "expected an array of non-empty strings, got null")
        return
    elif isinstance(reasons, list) and all(is_nonempty_str(r) for r in reasons):
        has_reasons = True
    else:
        add("inconclusive_reasons", "expected an array of non-empty strings")
        return
    if status == "inconclusive" and not has_reasons:
        add(
            "inconclusive_reasons",
            "status \"inconclusive\" requires at least one reason string",
        )
    if status == "complete" and has_reasons:
        add(
            "inconclusive_reasons",
            "status \"complete\" forbids inconclusive reasons",
        )


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------


def load_json_file(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise InputError(f"{path}: cannot read file ({error})") from error
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise InputError(f"{path}: invalid JSON ({error})") from error


def load_validated_manifest(path: Path, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Load and validate one manifest; returns (manifest, prefixed errors)."""
    try:
        manifest = load_json_file(path)
    except InputError as error:
        return None, [f"{label} {path}: {error}"]
    errors = validate_manifest(manifest)
    return manifest, [f"{label}: {error}" for error in errors]


def load_measurement_rows(path: Path) -> list[dict[str, Any]]:
    """Parse a JSONL measurements file into row objects (exit-2 on malformation)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise InputError(f"{path}: cannot read file ({error})") from error
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            raise InputError(f"{path}:{line_number}: blank lines are not allowed")
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise InputError(f"{path}:{line_number}: invalid JSON ({error})") from error
        if not isinstance(row, dict):
            raise InputError(f"{path}:{line_number}: expected a JSON object per line")
        for field in ("block_index", "frame_index"):
            if not is_int(row.get(field)):
                raise InputError(f"{path}:{line_number}: {field} must be an int")
            if row[field] < 0:
                raise InputError(f"{path}:{line_number}: {field} must be non-negative")
        clocks = row.get("clocks")
        if not isinstance(clocks, dict):
            raise InputError(f"{path}:{line_number}: clocks must be a JSON object")
        for name, value in clocks.items():
            if not isinstance(name, str) or not name:
                raise InputError(f"{path}:{line_number}: clock names must be non-empty strings")
            if value is not None and not is_finite_nonnegative_number(value):
                raise InputError(
                    f"{path}:{line_number}: clock {name!r} must be a non-negative number or null; "
                    "non-finite values are rejected"
                )
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def command_validate(args: argparse.Namespace) -> int:
    path: Path = args.validate
    try:
        manifest = load_json_file(path)
    except InputError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_INVALID
    errors = validate_manifest(manifest)
    if errors:
        for error in errors:
            print(f"ERROR: {path}: {error}", file=sys.stderr)
        return EXIT_INVALID
    assert isinstance(manifest, dict)
    frames = sum(
        block.get("frame_count", 0)
        for block in manifest.get("blocks", [])
        if isinstance(block, dict) and is_int(block.get("frame_count"))
    )
    print(
        f"OK {path}: manifest valid "
        f"(profile={manifest.get('profile')!r}, blocks={BLOCK_COUNT}, frames={frames}, "
        f"status={manifest.get('status')!r})"
    )
    return EXIT_OK


def command_quantiles(args: argparse.Namespace) -> int:
    clock: str = args.clock
    try:
        rows = load_measurement_rows(Path(args.quantiles))
    except InputError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_INVALID
    values: list[float] = []
    unavailable = 0
    missing = 0
    for row in rows:
        clocks = row["clocks"]
        if clock not in clocks:
            missing += 1
        elif clocks[clock] is None:
            unavailable += 1
        else:
            values.append(clocks[clock])
    if missing:
        print(
            f"ERROR: {args.quantiles}: requested clock {clock!r} is missing "
            f"from {missing} raw sample rows",
            file=sys.stderr,
        )
        return EXIT_INVALID
    result = {
        "clock": clock,
        "method": QUANTILE_METHOD,
        "unit": "ns",
        "frames": len(rows),
        "available_frames": len(values),
        "unavailable_frames": unavailable,
        "p50_ns": nearest_rank(values, 0.50) if values else None,
        "p95_ns": nearest_rank(values, 0.95) if values else None,
        "p99_ns": nearest_rank(values, 0.99) if values else None,
    }
    print(json.dumps(result, indent=2))
    return EXIT_OK


def command_compare(args: argparse.Namespace) -> int:
    manifest_a, errors_a = load_validated_manifest(Path(args.compare_a), "A")
    manifest_b, errors_b = load_validated_manifest(Path(args.compare_b), "B")
    errors = errors_a + errors_b
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_INVALID
    assert manifest_a is not None and manifest_b is not None
    if manifest_a["profile"] != manifest_b["profile"]:
        print(
            "ERROR: refusing cross-profile comparison: "
            f"A profile={manifest_a['profile']!r} vs B profile={manifest_b['profile']!r}; "
            "profiles are never compared across (ADR 0006 SS O-08)",
            file=sys.stderr,
        )
        return EXIT_CROSS_PROFILE

    # Totality: block p99 is nullable when a run is inconclusive, so either
    # side can be None. Unavailable pairs are excluded from the paired
    # statistics and rendered as n/a instead of crashing.
    blocks_a = sorted(manifest_a["blocks"], key=lambda b: b["block_index"])
    blocks_b = sorted(manifest_b["blocks"], key=lambda b: b["block_index"])
    deltas = [
        float(block_b["p99_ns"]) - float(block_a["p99_ns"])
        for block_a, block_b in zip(blocks_a, blocks_b)
        if block_a.get("p99_ns") is not None and block_b.get("p99_ns") is not None
    ]
    bootstrap = _bootstrap_params(manifest_a)
    if deltas:
        point_estimate, ci_low, ci_high = paired_bootstrap_ci(
            deltas,
            seed=bootstrap["seed"],
            resamples=bootstrap["resamples"],
            ci_level=bootstrap["ci"],
        )
    else:
        # No comparable block pair exists (every p99 unavailable on at least
        # one side); the report stays total and renders n/a statistics.
        point_estimate = ci_low = ci_high = None

    report = build_report(
        args.compare_a,
        args.compare_b,
        manifest_a,
        manifest_b,
        list(zip(blocks_a, blocks_b)),
        deltas,
        point_estimate,
        ci_low,
        ci_high,
        bootstrap,
    )
    out_path: Path | None = args.out
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"report written: {out_path}")
    print(report, end="" if report.endswith("\n") else "\n")
    return EXIT_OK


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.6g}"
    return str(value)


def _fmt_delta_percent(base: Any, delta: Any) -> str:
    if base is None or delta is None or base == 0:
        return "n/a"
    return f"{(float(delta) / float(base)) * 100.0:+.2f}%"


def _bootstrap_params(manifest: dict[str, Any]) -> dict[str, Any]:
    """Bootstrap parameters for the paired CI, taken from A's protocol block."""
    bootstrap = manifest["protocol"]["bootstrap"]
    return {
        "seed": bootstrap["seed"],
        "resamples": bootstrap["resamples"],
        "ci": bootstrap["ci"],
        "method": bootstrap["method"],
    }


def build_report(
    path_a: str,
    path_b: str,
    manifest_a: dict[str, Any],
    manifest_b: dict[str, Any],
    block_pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    deltas: list[float],
    point_estimate: float | None,
    ci_low: float | None,
    ci_high: float | None,
    bootstrap: dict[str, Any] | None = None,
) -> str:
    """Render the deterministic paired A/B markdown report.

    The report embeds no wall-clock time: two invocations over the same
    manifest pair produce byte-identical output. Unavailable (null) block
    quantiles render as ``n/a``; the paired statistics cover only the
    comparable pairs and are ``n/a`` when no pair is comparable.
    """
    params = _bootstrap_params(manifest_a) if bootstrap is None else bootstrap
    lines: list[str] = []
    lines.append("# O-08 paired benchmark comparison (A/B)")
    lines.append("")
    lines.append(
        "Deterministic report generated by `scripts/bench_analysis.py --compare` "
        "(contents depend only on the two input manifests)."
    )
    lines.append("")
    lines.append("## Inputs")
    lines.append("")
    for label, path, manifest in (("A", path_a, manifest_a), ("B", path_b, manifest_b)):
        lines.append(
            f"- {label}: `{path}` run_id=`{manifest['run_id']}` "
            f"profile=`{manifest['profile']}` status=`{manifest['status']}`"
        )
    fixture_a, fixture_b = manifest_a["fixture"], manifest_b["fixture"]
    lines.append(
        f"- Fixture: A id=`{fixture_a['id']}` (points={fixture_a['points']}, "
        f"canvas_px={fixture_a['canvas_px']}, dpi={fixture_a['dpi']}); "
        f"B id=`{fixture_b['id']}` (points={fixture_b['points']}, "
        f"canvas_px={fixture_b['canvas_px']}, dpi={fixture_b['dpi']})"
    )
    protocol_a = manifest_a["protocol"]
    lines.append(
        "- Protocol: blocks=5, min_frames_per_block="
        f"{protocol_a.get('min_frames_per_block', MIN_FRAMES_PER_BLOCK)}, "
        f"quantile_method={protocol_a.get('quantile_method', QUANTILE_METHOD)}, "
        f"trimming={protocol_a.get('trimming', TRIMMING)}"
    )
    lines.append("")

    lines.append("## Status propagation")
    lines.append("")
    reasons: list[str] = []
    for label, manifest in (("A", manifest_a), ("B", manifest_b)):
        if manifest.get("status") == "inconclusive":
            side_reasons = manifest.get("inconclusive_reasons") or [
                "(no reason recorded)",
            ]
            rendered = ", ".join(f'"{reason}"' for reason in side_reasons)
            lines.append(f"- {label}: **inconclusive** — reasons: {rendered}")
            reasons.extend(f"{label}: {reason}" for reason in side_reasons)
        else:
            lines.append(f"- {label}: complete")
    if reasons:
        lines.append(f"- Overall: **INCONCLUSIVE** ({'; '.join(reasons)})")
    else:
        lines.append("- Overall: COMPLETE")
    lines.append("")

    lines.append("## Per-block p99 (ns)")
    lines.append("")
    lines.append("Delta = B - A; positive deltas mean B is slower.")
    lines.append("")
    lines.append("| block | frames A | frames B | A p99 | B p99 | delta | delta % |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for index, (block_a, block_b) in enumerate(block_pairs):
        p99_a, p99_b = block_a.get("p99_ns"), block_b.get("p99_ns")
        delta = (
            float(p99_b) - float(p99_a)
            if p99_a is not None and p99_b is not None
            else None
        )
        lines.append(
            f"| {index} | {_fmt(block_a.get('frame_count'))} "
            f"| {_fmt(block_b.get('frame_count'))} "
            f"| {_fmt(p99_a)} | {_fmt(p99_b)} "
            f"| {_fmt(delta)} | {_fmt_delta_percent(p99_a, delta)} |"
        )
    lines.append("")

    lines.append("## Block aggregates (descriptive, ns)")
    lines.append("")
    lines.append("Computed over blocks with an available value; n/a when none.")
    lines.append("")
    lines.append("| statistic | A | B |")
    lines.append("| --- | --- | --- |")
    for field in ("p50_ns", "p95_ns", "p99_ns"):
        agg_a = _block_field_aggregates(manifest_a["blocks"], field)
        agg_b = _block_field_aggregates(manifest_b["blocks"], field)
        for name, index in (("mean of blocks", 0), ("min block", 1), ("max block", 2)):
            lines.append(f"| {field} {name} | {_fmt(agg_a[index])} | {_fmt(agg_b[index])} |")
    lines.append("")

    lines.append("## Pooled descriptive summary")
    lines.append("")
    lines.append(
        "Descriptive only; the gate statistic is the maximum block p99 "
        "(profiles are never pooled together)."
    )
    lines.append("")
    for label, manifest in (("A", manifest_a), ("B", manifest_b)):
        lines.append(f"### {label} pooled")
        lines.append("")
        lines.append("```json")
        pooled = manifest.get("pooled")
        if isinstance(pooled, dict):
            lines.append(json.dumps(pooled, indent=2, sort_keys=True))
        else:
            lines.append(json.dumps(None))
        lines.append("```")
        lines.append("")

    max_a = manifest_a.get("max_block_p99_ns")
    max_b = manifest_b.get("max_block_p99_ns")
    max_delta = None if max_a is None or max_b is None else float(max_b) - float(max_a)
    lines.append("## Max block p99 (gate statistic, ns)")
    lines.append("")
    lines.append(
        f"A={_fmt(max_a)} B={_fmt(max_b)} delta={_fmt(max_delta)} "
        f"({_fmt_delta_percent(max_a, max_delta)})"
    )
    lines.append("")

    lines.append("## Paired bootstrap over block p99 deltas")
    lines.append("")
    if point_estimate is None or ci_low is None or ci_high is None:
        lines.append(
            "n/a — no block pair has p99 available on both sides, so the "
            "paired bootstrap has no sample."
        )
    else:
        lines.append(
            f"Statistic: mean of the {len(deltas)} paired block p99 deltas; point estimate "
            f"{_fmt(point_estimate)} ns."
        )
        lines.append(
            f"95% CI (percentile method, seed={params['seed']}, "
            f"resamples={params['resamples']}, nearest-rank bounds): "
            f"[{_fmt(ci_low)}, {_fmt(ci_high)}] ns."
        )
    lines.append(
        "Interpretation: the interval is descriptive evidence only; native "
        "adoption gates remain governed by the accepted decision record."
    )
    lines.append("")
    return "\n".join(lines)


def _block_field_aggregates(
    blocks: list[dict[str, Any]], field: str
) -> tuple[float | None, float | None, float | None]:
    """Return (mean, min, max) over available numeric values of one field.

    Blocks whose value is null (inconclusive) are skipped; aggregates are
    n/a when no block carries an available value.
    """
    values = [float(block[field]) for block in blocks if block.get(field) is not None]
    if not values:
        return None, None, None
    return statistics.fmean(values), min(values), max(values)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--validate",
        type=Path,
        metavar="MANIFEST.json",
        help="validate a benchmark manifest against the schema",
    )
    modes.add_argument(
        "--quantiles",
        type=Path,
        metavar="SAMPLES.jsonl",
        help="compute nearest-rank p50/p95/p99 for one clock over raw JSONL rows",
    )
    modes.add_argument(
        "--compare",
        nargs=2,
        metavar=("A.json", "B.json"),
        help="paired A/B comparison report for two manifests of one profile",
    )
    parser.add_argument("--clock", metavar="NAME", help="clock name for --quantiles")
    parser.add_argument("--out", type=Path, metavar="REPORT.md", help="also write the report to a file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.quantiles is not None and not args.clock:
        parser.error("--quantiles requires --clock NAME")
    if args.clock is not None and args.quantiles is None:
        parser.error("--clock requires --quantiles SAMPLES.jsonl")
    if args.out is not None and args.compare is None:
        parser.error("--out requires --compare A.json B.json")
    if args.validate is not None:
        return command_validate(args)
    if args.quantiles is not None:
        return command_quantiles(args)
    assert args.compare is not None
    args.compare_a, args.compare_b = args.compare
    return command_compare(args)


if __name__ == "__main__":
    raise SystemExit(main())
