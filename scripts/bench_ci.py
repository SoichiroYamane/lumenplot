#!/usr/bin/env python3
"""Fail-closed validation for one emitted O-08 benchmark run.

The benchmark binary owns measurement and manifest emission.  The CI lane owns
only evidence admission: it validates the manifest with the existing
``bench_analysis`` contract, then checks that every referenced raw JSONL file
is present, safe to upload, well-formed, and agrees with its block metadata.
No result is synthesized when a required file or observation is missing.

Exit codes: 0 valid evidence, 2 invalid or incomplete evidence.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path, PurePosixPath
from typing import Any

if __package__:
    from . import bench_analysis
else:  # pragma: no cover - exercised by the workflow's direct invocation.
    import bench_analysis


EXIT_OK = 0
EXIT_INVALID = 2
MANIFEST_NAME = "manifest.json"
REQUIRED_SAMPLE_KEYS = frozenset({"block_index", "frame_index", "clocks"})


def _is_regular_file(path: Path) -> bool:
    """Return true only for a non-symlink regular file."""
    return path.is_file() and not path.is_symlink()


def _is_finite_nonnegative_number(value: Any) -> bool:
    """Reject Python's non-standard JSON NaN/Infinity values as evidence."""
    return (
        bench_analysis.is_number(value)
        and (not isinstance(value, float) or math.isfinite(value))
        and value >= 0
    )


def _nonfinite_number_errors(value: Any, path: str = "manifest") -> list[str]:
    """Find NaN/Infinity accepted by Python's permissive JSON decoder."""
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


def _safe_sample_path(raw_path: Any, block_index: int) -> tuple[str | None, str | None]:
    """Check the emitted raw-sample name before it reaches artifact upload."""
    expected = f"samples-{block_index}.jsonl"
    if not isinstance(raw_path, str) or not raw_path:
        return None, "raw_samples_path must be a non-empty string"

    # The workflow uploads a flat, exact allowlist.  Reject absolute paths,
    # traversal, platform-ambiguous separators, and alternate names rather
    # than relying on a glob to decide what evidence is trusted.
    parsed = PurePosixPath(raw_path)
    if (
        parsed.is_absolute()
        or "\\" in raw_path
        or parsed.name != raw_path
        or raw_path != expected
    ):
        return None, f"raw_samples_path must be exactly {expected!r}, got {raw_path!r}"
    return raw_path, None


def _validate_sample(
    path: Path,
    block: dict[str, Any],
    clock_names: set[str],
    unavailable_clocks: set[str],
    scheduler_name: str | None,
    status: Any,
) -> tuple[list[dict[str, Any]] | None, list[str]]:
    """Validate one raw JSONL file and its relationship to one manifest block."""
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return None, [f"{path}: cannot read raw samples ({error})"]

    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            errors.append(f"{path}:{line_number}: blank lines are not allowed")

    try:
        rows = bench_analysis.load_measurement_rows(path)
    except bench_analysis.InputError as error:
        return None, [str(error)]

    block_index = block.get("block_index")
    frame_count = block.get("frame_count")
    if isinstance(frame_count, int) and not isinstance(frame_count, bool):
        if len(rows) != frame_count:
            errors.append(
                f"{path}: expected {frame_count} rows for block {block_index}, got {len(rows)}"
            )

    if not isinstance(block_index, int) or isinstance(block_index, bool):
        return rows, errors

    for position, row in enumerate(rows):
        if set(row) != REQUIRED_SAMPLE_KEYS:
            errors.append(
                f"{path}:{position + 1}: expected exactly the per-frame keys "
                f"{sorted(REQUIRED_SAMPLE_KEYS)}, got {sorted(row)}"
            )
        if row.get("block_index") != block_index:
            errors.append(
                f"{path}:{position + 1}: block_index must be {block_index}, "
                f"got {row.get('block_index')!r}"
            )
        if row.get("frame_index") != position:
            errors.append(
                f"{path}:{position + 1}: frame_index must be {position}, "
                f"got {row.get('frame_index')!r}"
            )

        clocks = row.get("clocks")
        if not isinstance(clocks, dict):
            # load_measurement_rows already reports this, but do not inspect a
            # malformed value as though it were a clock map.
            continue
        if set(clocks) != clock_names:
            errors.append(
                f"{path}:{position + 1}: clock names must match the manifest "
                f"exactly, expected {sorted(clock_names)}, got {sorted(clocks)}"
            )
        for name, value in clocks.items():
            if value is not None and not _is_finite_nonnegative_number(value):
                errors.append(
                    f"{path}:{position + 1}: clock {name!r} must be a non-negative number or null"
                )
            if name in unavailable_clocks and value is not None:
                errors.append(
                    f"{path}:{position + 1}: unavailable clock {name!r} must be null"
                )

    if scheduler_name is not None and isinstance(frame_count, int) and not isinstance(
        frame_count, bool
    ):
        values = [
            row["clocks"][scheduler_name]
            for row in rows
            if isinstance(row.get("clocks"), dict)
            and bench_analysis.is_number(row["clocks"].get(scheduler_name))
            and row["clocks"].get(scheduler_name) >= 0
        ]
        for field, quantile in (
            ("p50_ns", 0.50),
            ("p95_ns", 0.95),
            ("p99_ns", 0.99),
        ):
            reported = block.get(field)
            if reported is not None and values:
                expected = bench_analysis.nearest_rank(values, quantile)
                if reported != expected:
                    errors.append(
                        f"{path}: block {block_index} {field}={reported!r} "
                        f"does not match raw {scheduler_name} nearest-rank value {expected!r}"
                    )
        if status == "complete" and len(values) != len(rows):
            errors.append(
                f"{path}: complete block {block_index} has "
                f"{len(rows) - len(values)} unavailable scheduler observations"
            )

    return rows, errors


def validate_run(output_dir: Path, expected_profile: str) -> list[str]:
    """Return all admission errors for one benchmark output directory."""
    errors: list[str] = []
    if expected_profile not in bench_analysis.PROFILES:
        errors.append(
            f"profile: expected one of {list(bench_analysis.PROFILES)}, got {expected_profile!r}"
        )
    if output_dir.is_symlink() or not output_dir.is_dir():
        return [*errors, f"{output_dir}: benchmark output directory is missing or not a directory"]

    try:
        entries = list(output_dir.iterdir())
    except OSError as error:
        return [*errors, f"{output_dir}: cannot inspect output directory ({error})"]

    manifest_path = output_dir / MANIFEST_NAME
    manifest: Any = None
    if not _is_regular_file(manifest_path):
        errors.append(f"{manifest_path}: required manifest is missing or not a regular file")
    else:
        try:
            manifest = bench_analysis.load_json_file(manifest_path)
        except bench_analysis.InputError as error:
            errors.append(str(error))
        else:
            errors.extend(
                f"manifest: {error}" for error in bench_analysis.validate_manifest(manifest)
            )
            errors.extend(_nonfinite_number_errors(manifest))
            if isinstance(manifest, dict) and manifest.get("profile") != expected_profile:
                errors.append(
                    "manifest.profile: does not match the selected CI profile "
                    f"{expected_profile!r}; got {manifest.get('profile')!r}"
                )

    if not isinstance(manifest, dict):
        for entry in entries:
            errors.append(f"{entry}: unexpected artifact candidate without a valid manifest")
        return errors

    blocks = manifest.get("blocks")
    clocks = manifest.get("clocks")
    status = manifest.get("status")
    if not isinstance(blocks, list) or not isinstance(clocks, list):
        # The authoritative validator has already reported the malformed
        # containers.  Do not risk indexing them while trying to validate raw
        # files; the run is already rejected.
        for entry in entries:
            if entry.name != MANIFEST_NAME:
                errors.append(f"{entry}: unexpected artifact candidate")
        return errors

    clock_names = {
        clock["name"]
        for clock in clocks
        if isinstance(clock, dict) and isinstance(clock.get("name"), str)
    }
    scheduler_names = [
        clock["name"]
        for clock in clocks
        if isinstance(clock, dict)
        and clock.get("domain") == "scheduler"
        and isinstance(clock.get("name"), str)
    ]
    scheduler_name = scheduler_names[0] if scheduler_names else None
    if scheduler_name is None:
        errors.append("clocks: at least one scheduler-domain clock is required for CI evidence")

    unavailable_clocks = {
        clock["name"]
        for clock in clocks
        if isinstance(clock, dict)
        and clock.get("available") is False
        and isinstance(clock.get("name"), str)
    }
    if unavailable_clocks and status == "complete":
        errors.append(
            "status: complete is not allowed while manifest clocks are unavailable; "
            "record inconclusive instead"
        )

    sample_names: set[str] = set()
    blocks_with_paths: list[tuple[dict[str, Any], str]] = []
    for position, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        block_index = block.get("block_index")
        if not isinstance(block_index, int) or isinstance(block_index, bool):
            continue
        raw_path, path_error = _safe_sample_path(block.get("raw_samples_path"), block_index)
        if path_error is not None:
            errors.append(f"blocks[{position}]: {path_error}")
            continue
        assert raw_path is not None
        if raw_path in sample_names:
            errors.append(f"blocks[{position}].raw_samples_path: duplicate path {raw_path!r}")
        sample_names.add(raw_path)
        blocks_with_paths.append((block, raw_path))

    expected_names = {MANIFEST_NAME, *sample_names}
    for entry in entries:
        if entry.name not in expected_names:
            errors.append(f"{entry}: unexpected file in benchmark output; refusing upload")
        elif entry.is_symlink():
            errors.append(f"{entry}: symlinks are not accepted as evidence")

    output_root = output_dir.resolve()
    rows_by_block: dict[int, list[dict[str, Any]]] = {}
    for block, raw_path in blocks_with_paths:
        path = output_dir / raw_path
        if not _is_regular_file(path):
            errors.append(f"{path}: referenced raw sample file is missing or not a regular file")
            continue
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(output_root)
        except (OSError, ValueError) as error:
            errors.append(f"{path}: referenced raw sample path escapes output directory ({error})")
            continue
        rows, sample_errors = _validate_sample(
            path,
            block,
            clock_names,
            unavailable_clocks,
            scheduler_name,
            status,
        )
        errors.extend(sample_errors)
        if rows is not None and isinstance(block.get("block_index"), int):
            rows_by_block[block["block_index"]] = rows

    # Validate the descriptive pooled values emitted by the current runner when
    # present. ``pooled: null`` remains valid for an inconclusive future cell;
    # the authoritative manifest validator handles that nullable boundary.
    pooled = manifest.get("pooled")
    if isinstance(pooled, dict) and rows_by_block and scheduler_name is not None:
        total_rows = sum(len(rows) for rows in rows_by_block.values())
        pooled_count = pooled.get("frame_count")
        if pooled_count != total_rows:
            errors.append(
                "pooled.frame_count: must equal the total retained raw sample count "
                f"({total_rows}), got {pooled_count!r}"
            )
        values = [
            row["clocks"][scheduler_name]
            for rows in rows_by_block.values()
            for row in rows
            if isinstance(row.get("clocks"), dict)
            and bench_analysis.is_number(row["clocks"].get(scheduler_name))
            and row["clocks"].get(scheduler_name) >= 0
        ]
        if values:
            for field, quantile in (
                ("p50_ns", 0.50),
                ("p95_ns", 0.95),
                ("p99_ns", 0.99),
            ):
                reported = pooled.get(field)
                expected = bench_analysis.nearest_rank(values, quantile)
                if reported != expected:
                    errors.append(
                        f"pooled.{field}: {reported!r} does not match raw "
                        f"{scheduler_name} nearest-rank value {expected!r}"
                    )

    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--validate-run",
        type=Path,
        required=True,
        metavar="DIR",
        help="validate one lumenplot-bench output directory",
    )
    parser.add_argument(
        "--profile",
        required=True,
        metavar="PROFILE",
        help="profile selected by the CI matrix",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    errors = validate_run(args.validate_run, args.profile)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_INVALID

    manifest = bench_analysis.load_json_file(args.validate_run / MANIFEST_NAME)
    assert isinstance(manifest, dict)
    frames = sum(block["frame_count"] for block in manifest["blocks"])
    print(
        f"OK {args.validate_run}: benchmark evidence valid "
        f"(profile={manifest['profile']!r}, blocks={len(manifest['blocks'])}, frames={frames}, "
        f"status={manifest['status']!r})"
    )
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
