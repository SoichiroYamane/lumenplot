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

RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$"
)


class InputError(Exception):
    """Raised when an input file cannot be read or parsed."""


def is_number(value: Any) -> bool:
    """Return True for real JSON numbers (bool excluded)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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
    ordered = sorted(values)
    scaled = round(quantile * len(ordered), 9)
    rank = min(max(math.ceil(scaled), 1), len(ordered))
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

    for field in REQUIRED_TOP_LEVEL:
        if field not in manifest:
            add(field, "required field is missing")

    version = manifest.get("schema_version")
    if version is not None and (not is_int(version) or version != SCHEMA_VERSION):
        add("schema_version", f"expected int {SCHEMA_VERSION}, got {version!r}")

    run_id = manifest.get("run_id")
    if run_id is not None and not is_uuid4(run_id):
        add("run_id", f"expected a uuid4 string, got {run_id!r}")

    generated_at = manifest.get("generated_at_utc")
    if generated_at is not None and not is_rfc3339_utc(generated_at):
        add("generated_at_utc", f"expected an RFC3339 UTC timestamp, got {generated_at!r}")

    profile = manifest.get("profile")
    if profile is not None and profile not in PROFILES:
        add("profile", f"expected one of {list(PROFILES)}, got {profile!r}")

    _validate_fixture(manifest.get("fixture"), add)
    _validate_environment(manifest.get("environment"), add)
    _validate_protocol(manifest.get("protocol"), add)
    _validate_clocks(manifest.get("clocks"), add)
    min_frames = _protocol_min_frames(manifest.get("protocol"))
    _validate_blocks(manifest.get("blocks"), min_frames, add)

    pooled = manifest.get("pooled")
    if pooled is not None and not isinstance(pooled, dict):
        add("pooled", "expected a JSON object of descriptive statistics")

    max_block_p99 = manifest.get("max_block_p99_ns")
    if max_block_p99 is not None and (
        not is_number(max_block_p99) or max_block_p99 < 0
    ):
        add("max_block_p99_ns", "expected a non-negative number or null")

    _validate_status(manifest.get("status"), manifest.get("inconclusive_reasons"), add)
    return errors


def _validate_fixture(fixture: Any, add: Any) -> None:
    if fixture is None or not isinstance(fixture, dict):
        if fixture is not None:
            add("fixture", "expected a JSON object")
        return
    if "id" in fixture and not is_nonempty_str(fixture["id"]):
        add("fixture.id", "expected a non-empty string")
    points = fixture.get("points")
    if points is not None and (not is_int(points) or points <= 0):
        add("fixture.points", "expected a positive int")
    canvas = fixture.get("canvas_px")
    if canvas is not None:
        if not isinstance(canvas, list) or len(canvas) != 2 or not all(
            is_int(side) and side > 0 for side in canvas
        ):
            add("fixture.canvas_px", "expected [width, height] positive ints")
    dpi = fixture.get("dpi")
    if dpi is not None and (not is_number(dpi) or dpi <= 0):
        add("fixture.dpi", "expected a positive number")


def _validate_environment(environment: Any, add: Any) -> None:
    if environment is None or not isinstance(environment, dict):
        if environment is not None:
            add("environment", "expected a JSON object")
        return
    for field in ENV_STRING_FIELDS:
        if field in environment and not is_nonempty_str(environment[field]):
            add(f"environment.{field}", "expected a non-empty string")
    scale = environment.get("display_scale")
    if scale is not None and (not is_number(scale) or scale <= 0):
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
        if field in gpu and not is_nonempty_str(gpu[field]):
            add(f"environment.gpu.{field}", "expected a non-empty string")


def _validate_protocol(protocol: Any, add: Any) -> None:
    if protocol is None or not isinstance(protocol, dict):
        if protocol is not None:
            add("protocol", "expected a JSON object")
        return
    blocks = protocol.get("blocks")
    if blocks is not None and (not is_int(blocks) or blocks != BLOCK_COUNT):
        add("protocol.blocks", f"expected int {BLOCK_COUNT}, got {blocks!r}")
    min_frames = protocol.get("min_frames_per_block")
    if min_frames is not None and (
        not is_int(min_frames) or min_frames != MIN_FRAMES_PER_BLOCK
    ):
        add(
            "protocol.min_frames_per_block",
            f"expected int {MIN_FRAMES_PER_BLOCK}, got {min_frames!r}",
        )
    if protocol.get("quantile_method") not in (None, QUANTILE_METHOD):
        add(
            "protocol.quantile_method",
            f"expected \"{QUANTILE_METHOD}\", got {protocol['quantile_method']!r}",
        )
    if protocol.get("trimming") not in (None, TRIMMING):
        add("protocol.trimming", f"expected \"{TRIMMING}\", got {protocol['trimming']!r}")
    bootstrap = protocol.get("bootstrap")
    if bootstrap is None:
        return
    if not isinstance(bootstrap, dict):
        add("protocol.bootstrap", "expected a JSON object")
        return
    resamples = bootstrap.get("resamples")
    if resamples is not None and (not is_int(resamples) or resamples != BOOTSTRAP_RESAMPLES):
        add(
            "protocol.bootstrap.resamples",
            f"expected int {BOOTSTRAP_RESAMPLES}, got {resamples!r}",
        )
    ci = bootstrap.get("ci")
    if ci is not None and (not is_number(ci) or ci != BOOTSTRAP_CI):
        add("protocol.bootstrap.ci", f"expected {BOOTSTRAP_CI}, got {ci!r}")
    seed = bootstrap.get("seed")
    if seed is not None and (not is_int(seed) or seed != BOOTSTRAP_SEED):
        add("protocol.bootstrap.seed", f"expected int {BOOTSTRAP_SEED}, got {seed!r}")
    if bootstrap.get("method") not in (None, BOOTSTRAP_METHOD):
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
    if clocks is None or not isinstance(clocks, list):
        if clocks is not None:
            add("clocks", "expected a non-empty JSON array")
        return
    if not clocks:
        add("clocks", "expected at least one clock entry")
    seen_names: set[str] = set()
    for index, clock in enumerate(clocks):
        path = f"clocks[{index}]"
        if not isinstance(clock, dict):
            add(path, "expected a JSON object")
            continue
        name = clock.get("name")
        if name is not None:
            if not is_nonempty_str(name):
                add(f"{path}.name", "expected a non-empty string")
            elif name in seen_names:
                add(f"{path}.name", f"duplicate clock name {name!r}")
            else:
                seen_names.add(name)
        domain = clock.get("domain")
        if domain is not None and domain not in CLOCK_DOMAINS:
            add(f"{path}.domain", f"expected one of {list(CLOCK_DOMAINS)}, got {domain!r}")
        if clock.get("unit") not in (None, "ns"):
            add(f"{path}.unit", f"expected \"ns\", got {clock['unit']!r}")
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


def _validate_blocks(blocks: Any, min_frames: int, add: Any) -> None:
    if blocks is None or not isinstance(blocks, list):
        if blocks is not None:
            add("blocks", f"expected a JSON array of {BLOCK_COUNT} blocks")
        return
    if len(blocks) != BLOCK_COUNT:
        add("blocks", f"expected exactly {BLOCK_COUNT} blocks, got {len(blocks)}")
    indexes: list[int] = []
    for index, block in enumerate(blocks):
        path = f"blocks[{index}]"
        if not isinstance(block, dict):
            add(path, "expected a JSON object")
            continue
        block_index = block.get("block_index")
        if block_index is not None:
            if not is_int(block_index):
                add(f"{path}.block_index", "expected an int")
            else:
                indexes.append(block_index)
        pid = block.get("pid")
        if pid is not None and (not is_int(pid) or pid <= 0):
            add(f"{path}.pid", "expected a positive int")
        started_at = block.get("started_at_utc")
        if started_at is not None and not is_rfc3339_utc(started_at):
            add(f"{path}.started_at_utc", f"expected an RFC3339 UTC timestamp, got {started_at!r}")
        frame_count = block.get("frame_count")
        if frame_count is not None and (not is_int(frame_count) or frame_count < min_frames):
            add(f"{path}.frame_count", f"expected int >= {min_frames}, got {frame_count!r}")
        quantiles: list[float] = []
        for field in ("p50_ns", "p95_ns", "p99_ns"):
            value = block.get(field)
            if value is None:
                continue
            if not is_number(value) or value < 0:
                add(f"{path}.{field}", "expected a non-negative number")
            else:
                quantiles.append(value)
        if len(quantiles) == 3 and not (
            quantiles[0] <= quantiles[1] <= quantiles[2]
        ):
            add(path, "expected p50_ns <= p95_ns <= p99_ns")
        raw_path = block.get("raw_samples_path")
        if raw_path is not None and not is_nonempty_str(raw_path):
            add(f"{path}.raw_samples_path", "expected a non-empty string")
    if indexes and sorted(indexes) != list(range(BLOCK_COUNT)):
        add(
            "blocks[].block_index",
            f"expected block_index 0..{BLOCK_COUNT - 1} exactly once each, got {sorted(indexes)}",
        )


def _validate_status(status: Any, reasons: Any, add: Any) -> None:
    if status is not None and status not in STATUSES:
        add("status", f"expected one of {list(STATUSES)}, got {status!r}")
    if reasons is not None:
        if not isinstance(reasons, list) or not all(is_nonempty_str(r) for r in reasons):
            add("inconclusive_reasons", "expected an array of non-empty strings")
    if status == "inconclusive":
        if isinstance(reasons, list) and not reasons:
            add(
                "inconclusive_reasons",
                "status \"inconclusive\" requires at least one reason string",
            )
    if status == "complete":
        if isinstance(reasons, list) and reasons:
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
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise InputError(f"{path}:{line_number}: invalid JSON ({error})") from error
        if not isinstance(row, dict):
            raise InputError(f"{path}:{line_number}: expected a JSON object per line")
        for field in ("block_index", "frame_index"):
            if not is_int(row.get(field)):
                raise InputError(f"{path}:{line_number}: {field} must be an int")
        clocks = row.get("clocks")
        if not isinstance(clocks, dict):
            raise InputError(f"{path}:{line_number}: clocks must be a JSON object")
        for name, value in clocks.items():
            if not isinstance(name, str) or not name:
                raise InputError(f"{path}:{line_number}: clock names must be non-empty strings")
            if value is not None and not is_number(value):
                raise InputError(
                    f"{path}:{line_number}: clock {name!r} must be a number or null"
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
    for row in rows:
        clocks = row["clocks"]
        if clock not in clocks or clocks[clock] is None:
            unavailable += 1
        else:
            values.append(clocks[clock])
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

    deltas = [
        float(block_b["p99_ns"]) - float(block_a["p99_ns"])
        for block_a, block_b in zip(
            sorted(manifest_a["blocks"], key=lambda b: b["block_index"]),
            sorted(manifest_b["blocks"], key=lambda b: b["block_index"]),
        )
    ]
    bootstrap = manifest_a["protocol"]["bootstrap"]
    point_estimate, ci_low, ci_high = paired_bootstrap_ci(
        deltas,
        seed=bootstrap["seed"],
        resamples=bootstrap["resamples"],
        ci_level=bootstrap["ci"],
    )

    report = build_report(
        args.compare_a, args.compare_b, manifest_a, manifest_b,
        deltas, point_estimate, ci_low, ci_high,
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


def _block_by_index(manifest: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {block["block_index"]: block for block in manifest["blocks"]}


def build_report(
    path_a: str,
    path_b: str,
    manifest_a: dict[str, Any],
    manifest_b: dict[str, Any],
    deltas: list[float],
    point_estimate: float,
    ci_low: float,
    ci_high: float,
) -> str:
    """Render the deterministic paired A/B markdown report.

    The report embeds no wall-clock time: two invocations over the same
    manifest pair produce byte-identical output.
    """
    bootstrap = manifest_a["protocol"]["bootstrap"]
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
    lines.append(
        "- Protocol: blocks=5, min_frames_per_block="
        f"{manifest_a['protocol']['min_frames_per_block']}, "
        f"quantile_method={manifest_a['protocol']['quantile_method']}, "
        f"trimming={manifest_a['protocol']['trimming']}"
    )
    lines.append("")

    lines.append("## Status propagation")
    lines.append("")
    reasons: list[str] = []
    for label, manifest in (("A", manifest_a), ("B", manifest_b)):
        if manifest["status"] == "inconclusive":
            lines.append(f"- {label}: **inconclusive** — reasons: {manifest['inconclusive_reasons']}")
            reasons.extend(f"{label}: {reason}" for reason in manifest["inconclusive_reasons"])
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
    blocks_a = _block_by_index(manifest_a)
    blocks_b = _block_by_index(manifest_b)
    for index, delta in enumerate(deltas):
        block_a, block_b = blocks_a[index], blocks_b[index]
        lines.append(
            f"| {index} | {block_a['frame_count']} | {block_b['frame_count']} "
            f"| {_fmt(block_a['p99_ns'])} | {_fmt(block_b['p99_ns'])} "
            f"| {_fmt(delta)} | {_fmt_delta_percent(block_a['p99_ns'], delta)} |"
        )
    lines.append("")

    lines.append("## Block aggregates (descriptive, ns)")
    lines.append("")
    lines.append("| statistic | A | B |")
    lines.append("| --- | --- | --- |")
    for field in ("p50_ns", "p95_ns", "p99_ns"):
        agg_a = (
            statistics.fmean([float(block[field]) for block in manifest_a["blocks"]]),
            min(float(block[field]) for block in manifest_a["blocks"]),
            max(float(block[field]) for block in manifest_a["blocks"]),
        )
        agg_b = (
            statistics.fmean([float(block[field]) for block in manifest_b["blocks"]]),
            min(float(block[field]) for block in manifest_b["blocks"]),
            max(float(block[field]) for block in manifest_b["blocks"]),
        )
        lines.append(
            f"| {field} mean of blocks | {_fmt(agg_a[0])} | {_fmt(agg_b[0])} |"
        )
        lines.append(f"| {field} min block | {_fmt(agg_a[1])} | {_fmt(agg_b[1])} |")
        lines.append(f"| {field} max block | {_fmt(agg_a[2])} | {_fmt(agg_b[2])} |")
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
        lines.append(json.dumps(manifest["pooled"], indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")

    max_a = manifest_a["max_block_p99_ns"]
    max_b = manifest_b["max_block_p99_ns"]
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
    lines.append(
        f"Statistic: mean of the 5 paired block p99 deltas; point estimate "
        f"{_fmt(point_estimate)} ns."
    )
    lines.append(
        f"95% CI (percentile method, seed={bootstrap['seed']}, "
        f"resamples={bootstrap['resamples']}, nearest-rank bounds): "
        f"[{_fmt(ci_low)}, {_fmt(ci_high)}] ns."
    )
    lines.append(
        "Interpretation: the interval is descriptive evidence only; native "
        "adoption gates remain governed by the accepted decision record."
    )
    lines.append("")
    return "\n".join(lines)


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
