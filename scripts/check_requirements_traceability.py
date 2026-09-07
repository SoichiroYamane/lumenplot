#!/usr/bin/env python3
"""Check the canonical v1 requirements and traceability documents.

The checker intentionally reads only the canonical requirement list, registry,
and normative-closure tables.  It does not consult historical notes or any
implementation evidence outside those two documents.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Sequence


EXPECTED_TOTAL = 237
EXPECTED_NORMATIVE = 157
EXPECTED_EVIDENCE_GATES = 107
EXPECTED_STATUS_COUNTS = {
    "Implemented (bounded)": 19,
    "Not implemented": 145,
    "Not measured": 43,
    "environment required": 6,
    "Reference only": 13,
    "Not applicable": 5,
    "Planning only": 6,
}
STATUS_ORDER = tuple(EXPECTED_STATUS_COUNTS)
NORMATIVE_CLASSES = frozenset(("MUST", "MUST NOT"))

# These gates use the canonical Agg-oracle acceptance contract.
REQUIRED_AGG_GATES = frozenset(
    {
        "AT-FUNC-3D",
        "AT-FUNC-FILL",
        "AT-FUNC-BAR",
        "AT-FUNC-DRAWSTYLE",
        "AT-SEM-COMPOSITING",
        "AT-FUNC-POLAR",
        "AT-FUNC-DATE-AXIS",
        "AT-FUNC-QUIVER",
        "AT-SEM-SCALE-EXT",
        "AT-MPL-ELIGIBILITY",
        "AT-FUNC-NAN-GAP",
        "AT-MPL-PREFLIGHT-SOUNDNESS",
        "AT-MPL-UNIT-DATA",
        "AT-MPL-COLLECTIONS",
        "AT-FUNC-MAPPABLE",
    }
)

_IDENTIFIER_RE = re.compile(r"LP-[A-Z0-9]+-\d+")
_GATE_RE = re.compile(r"\bAT-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")
_REQUIREMENT_ROW_RE = re.compile(
    r"^- \*\*(?P<identifier>LP-[A-Z0-9]+-\d+)\*\*\s*\|\s*"
    r"`(?P<classification>[^`|]+)`\s*\|\s*.*?\s*\|\s*"
    r"Target:\s*.*?\s*\|\s*Release:\s*.*?\s*\|\s*"
    r"Phase:\s*.*?\s*\|\s*Evidence:\s*(?P<evidence>.*?)\s*$"
)
_REGISTRY_ROW_RE = re.compile(
    r"^\| `(?P<identifier>LP-[A-Z0-9]+-\d+)` \| "
    r"`(?P<classification>[^`|]+)` \| "
    r"(?P<target>[^|]*) \| (?P<phase>[^|]*) \| "
    r"(?P<release>[^|]*) \| (?P<evidence>[^|]*) \| "
    r"(?P<result>[^|]*) \|$"
)
_CLOSURE_ROW_RE = re.compile(
    r"^\| `(?P<identifier>LP-[A-Z0-9]+-\d+)` \| "
    r"`(?P<classification>[^`|]+)` \| "
    r"(?P<evidence>[^|]*) \| (?P<result>[^|]*) \|$"
)


@dataclass(frozen=True)
class RequirementRow:
    identifier: str
    classification: str
    evidence_gates: tuple[str, ...]
    line_number: int


@dataclass(frozen=True)
class RegistryRow:
    identifier: str
    classification: str
    evidence_gates: tuple[str, ...]
    result: str
    line_number: int


@dataclass(frozen=True)
class ClosureRow:
    identifier: str
    classification: str
    evidence_gates: tuple[str, ...]
    result: str
    line_number: int


def _gate_names(value: str) -> tuple[str, ...]:
    """Return gate names in stable order, without duplicate references."""

    return tuple(sorted(set(_GATE_RE.findall(value))))


def _duplicate_ids(rows: Sequence[object]) -> list[str]:
    counts = Counter(row.identifier for row in rows)  # type: ignore[attr-defined]
    return sorted(identifier for identifier, count in counts.items() if count > 1)


def _format_ids(identifiers: Sequence[str]) -> str:
    return ", ".join(sorted(identifiers)) or "none"


def _parse_requirements(text: str) -> tuple[list[RequirementRow], list[str]]:
    rows: list[RequirementRow] = []
    diagnostics: list[str] = []

    for line_number, line in enumerate(text.splitlines(), 1):
        # Requirement entries have one stable, machine-readable bullet shape.
        if not line.startswith("- **LP-"):
            continue
        match = _REQUIREMENT_ROW_RE.fullmatch(line)
        if match is None:
            diagnostics.append(f"requirements row malformed at line {line_number}")
            continue
        rows.append(
            RequirementRow(
                identifier=match.group("identifier"),
                classification=match.group("classification").strip(),
                evidence_gates=_gate_names(match.group("evidence")),
                line_number=line_number,
            )
        )

    return rows, diagnostics


def _section(
    lines: Sequence[str], heading: str
) -> tuple[list[tuple[int, str]], list[str]]:
    """Slice one top-level Markdown section, excluding later sections."""

    start = next((index for index, line in enumerate(lines) if line.strip() == heading), None)
    if start is None:
        return [], [f"traceability section missing: {heading}"]

    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return list(enumerate(lines[start + 1 : end], start + 2)), []


def _table_cells(line: str) -> list[str] | None:
    """Split a Markdown table row while requiring its leading pipe."""

    if not line.startswith("| "):
        return None
    parts = line.split("|")
    if len(parts) < 3 or parts[-1] != "":
        return None
    return [part.strip() for part in parts[1:-1]]


def _parse_registry_section(
    numbered_lines: Sequence[tuple[int, str]],
) -> tuple[list[RegistryRow], list[str]]:
    rows: list[RegistryRow] = []
    diagnostics: list[str] = []

    for line_number, line in numbered_lines:
        # This exact prefix excludes the header/separator and every prose line.
        if not line.startswith("| `LP-"):
            continue
        match = _REGISTRY_ROW_RE.fullmatch(line)
        if match is None:
            diagnostics.append(f"registry row malformed at line {line_number}")
            continue
        rows.append(
            RegistryRow(
                identifier=match.group("identifier"),
                classification=match.group("classification").strip(),
                evidence_gates=_gate_names(match.group("evidence")),
                result=match.group("result").strip(),
                line_number=line_number,
            )
        )

    return rows, diagnostics


def _parse_closure_section(
    numbered_lines: Sequence[tuple[int, str]],
) -> tuple[list[ClosureRow], list[str]]:
    rows: list[ClosureRow] = []
    diagnostics: list[str] = []

    for line_number, line in numbered_lines:
        if not line.startswith("| `LP-"):
            continue
        match = _CLOSURE_ROW_RE.fullmatch(line)
        if match is None:
            diagnostics.append(f"normative closure row malformed at line {line_number}")
            continue
        rows.append(
            ClosureRow(
                identifier=match.group("identifier"),
                classification=match.group("classification").strip(),
                evidence_gates=_gate_names(match.group("evidence")),
                result=match.group("result").strip(),
                line_number=line_number,
            )
        )

    return rows, diagnostics


def _parse_traceability(
    text: str,
) -> tuple[list[RegistryRow], list[ClosureRow], list[str]]:
    lines = text.splitlines()
    registry_lines, registry_section_diagnostics = _section(
        lines, "## Complete requirement registry"
    )
    closure_lines, closure_section_diagnostics = _section(
        lines, "## Normative closure: every MUST and MUST NOT"
    )
    registry_rows, registry_row_diagnostics = _parse_registry_section(registry_lines)
    closure_rows, closure_row_diagnostics = _parse_closure_section(closure_lines)
    return (
        registry_rows,
        closure_rows,
        registry_section_diagnostics
        + registry_row_diagnostics
        + closure_section_diagnostics
        + closure_row_diagnostics,
    )


def _status_category(result: str) -> str | None:
    """Classify only the anchored status at the start of the Result cell."""

    value = result.strip()
    if value.startswith("Implemented (bounded"):
        return "Implemented (bounded)"
    if value.startswith("environment required"):
        return "environment required"
    if value.startswith("Not implemented"):
        return "Not implemented"
    if value.startswith("Not measured"):
        return "Not measured"
    if value.startswith("Reference only"):
        return "Reference only"
    if value.startswith("Not applicable"):
        return "Not applicable"
    if value.startswith("Planning only"):
        return "Planning only"
    return None


def check_documents(requirements_text: str, traceability_text: str) -> list[str]:
    """Return deterministic diagnostics for two document contents."""

    requirements, requirement_diagnostics = _parse_requirements(requirements_text)
    registry, closure, traceability_diagnostics = _parse_traceability(traceability_text)
    diagnostics = requirement_diagnostics + traceability_diagnostics

    if len(requirements) != EXPECTED_TOTAL:
        diagnostics.append(
            f"requirements rows: expected {EXPECTED_TOTAL}, found {len(requirements)}"
        )
    if len(registry) != EXPECTED_TOTAL:
        diagnostics.append(f"registry rows: expected {EXPECTED_TOTAL}, found {len(registry)}")

    requirement_normative = [
        row for row in requirements if row.classification in NORMATIVE_CLASSES
    ]
    registry_normative = [
        row for row in registry if row.classification in NORMATIVE_CLASSES
    ]
    if len(requirement_normative) != EXPECTED_NORMATIVE:
        diagnostics.append(
            "normative requirements: "
            f"expected {EXPECTED_NORMATIVE}, found {len(requirement_normative)}"
        )
    if len(registry_normative) != EXPECTED_NORMATIVE:
        diagnostics.append(
            "normative registry rows: "
            f"expected {EXPECTED_NORMATIVE}, found {len(registry_normative)}"
        )

    requirement_duplicates = _duplicate_ids(requirements)
    registry_duplicates = _duplicate_ids(registry)
    if requirement_duplicates:
        diagnostics.append(
            f"duplicate requirement ID(s): {_format_ids(requirement_duplicates)}"
        )
    if registry_duplicates:
        diagnostics.append(f"duplicate registry ID(s): {_format_ids(registry_duplicates)}")

    requirement_ids = {row.identifier for row in requirements}
    registry_ids = {row.identifier for row in registry}
    missing_registry_ids = sorted(requirement_ids - registry_ids)
    orphan_registry_ids = sorted(registry_ids - requirement_ids)
    if missing_registry_ids or orphan_registry_ids:
        diagnostics.append(
            "requirement/registry ID mismatch: "
            f"missing from registry: {_format_ids(missing_registry_ids)}; "
            f"orphan in registry: {_format_ids(orphan_registry_ids)}"
        )

    # A registry row is the traceability counterpart of its requirement row.
    # Check the fields that are expected to be identical without comparing the
    # intentionally shorter Target/Phase/Release summaries.
    requirement_by_id = {row.identifier: row for row in requirements}
    registry_by_id = {row.identifier: row for row in registry}
    for identifier in sorted(requirement_ids & registry_ids):
        requirement = requirement_by_id[identifier]
        registry_row = registry_by_id[identifier]
        if requirement.classification != registry_row.classification:
            diagnostics.append(
                f"class mismatch for {identifier}: requirements "
                f"{requirement.classification}, registry {registry_row.classification}"
            )
        if requirement.evidence_gates != registry_row.evidence_gates:
            diagnostics.append(
                f"evidence gate mismatch for {identifier}: requirements "
                f"{_format_ids(requirement.evidence_gates)}, registry "
                f"{_format_ids(registry_row.evidence_gates)}"
            )

    closure_duplicates = _duplicate_ids(closure)
    if closure_duplicates:
        diagnostics.append(
            f"duplicate normative-closure ID(s): {_format_ids(closure_duplicates)}"
        )
    normative_ids = {
        row.identifier for row in requirement_normative
    }
    closure_ids = {row.identifier for row in closure}
    missing_closure_ids = sorted(normative_ids - closure_ids)
    orphan_closure_ids = sorted(closure_ids - normative_ids)
    if missing_closure_ids:
        diagnostics.append(
            f"normative closure missing ID(s): {_format_ids(missing_closure_ids)}"
        )
    if orphan_closure_ids:
        diagnostics.append(
            f"normative closure orphan ID(s): {_format_ids(orphan_closure_ids)}"
        )
    if len(closure) != EXPECTED_NORMATIVE:
        diagnostics.append(
            "normative closure rows: "
            f"expected {EXPECTED_NORMATIVE}, found {len(closure)}"
        )

    closure_by_id = {row.identifier: row for row in closure}
    for identifier in sorted(normative_ids & closure_ids):
        requirement = requirement_by_id[identifier]
        closure_row = closure_by_id[identifier]
        if closure_row.classification != requirement.classification:
            diagnostics.append(
                f"normative closure class mismatch for {identifier}: requirements "
                f"{requirement.classification}, closure {closure_row.classification}"
            )
        if closure_row.evidence_gates != requirement.evidence_gates:
            diagnostics.append(
                f"normative closure evidence mismatch for {identifier}: requirements "
                f"{_format_ids(requirement.evidence_gates)}, closure "
                f"{_format_ids(closure_row.evidence_gates)}"
            )

    evidence_gates = {
        gate for row in registry for gate in row.evidence_gates
    }
    if len(evidence_gates) != EXPECTED_EVIDENCE_GATES:
        diagnostics.append(
            "evidence gates: "
            f"expected {EXPECTED_EVIDENCE_GATES}, found {len(evidence_gates)}"
        )
    missing_agg_gates = sorted(REQUIRED_AGG_GATES - evidence_gates)
    if missing_agg_gates:
        diagnostics.append(
            f"required Agg gate(s) missing from registry: {_format_ids(missing_agg_gates)}"
        )

    status_counts: Counter[str] = Counter()
    unknown_statuses: list[str] = []
    for row in registry:
        category = _status_category(row.result)
        if category is None:
            unknown_statuses.append(f"{row.identifier}={row.result}")
        else:
            status_counts[category] += 1
    if unknown_statuses:
        diagnostics.append(
            "unknown registry status(es): " + "; ".join(sorted(unknown_statuses))
        )
    if any(status_counts[label] != EXPECTED_STATUS_COUNTS[label] for label in STATUS_ORDER):
        actual = "; ".join(
            f"{label}={status_counts[label]} (expected {EXPECTED_STATUS_COUNTS[label]})"
            for label in STATUS_ORDER
        )
        diagnostics.append(f"status partition mismatch: {actual}")

    return diagnostics


def _read_document(path: Path, label: str) -> tuple[str | None, str | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeError) as error:
        return None, f"{label} file could not be read: {error}"


def check_files(requirements_path: Path | str, traceability_path: Path | str) -> list[str]:
    """Read and check the requested files without changing either file."""

    requirements_file = Path(requirements_path)
    traceability_file = Path(traceability_path)
    requirements_text, requirements_error = _read_document(
        requirements_file, "requirements"
    )
    traceability_text, traceability_error = _read_document(
        traceability_file, "traceability"
    )
    file_errors = [
        error for error in (requirements_error, traceability_error) if error is not None
    ]
    if file_errors:
        return file_errors
    assert requirements_text is not None
    assert traceability_text is not None
    return check_documents(requirements_text, traceability_text)


def _default_paths() -> tuple[Path, Path]:
    repo_root = Path(__file__).resolve().parents[1]
    return (
        repo_root / "docs" / "requirements" / "lumenplot-v1.0.md",
        repo_root / "docs" / "requirements" / "traceability-v1.0.md",
    )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check canonical LumenPlot requirements/traceability consistency."
    )
    parser.add_argument(
        "requirements_path",
        nargs="?",
        help="requirements Markdown path (default: canonical repo document)",
    )
    parser.add_argument(
        "traceability_path",
        nargs="?",
        help="traceability Markdown path (default: canonical repo document)",
    )
    parser.add_argument(
        "--requirements",
        "--requirements-file",
        dest="requirements_option",
        help="requirements Markdown path",
    )
    parser.add_argument(
        "--traceability",
        "--traceability-file",
        dest="traceability_option",
        help="traceability Markdown path",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(argv)
    if args.requirements_option is not None and args.requirements_path is not None:
        parser.error("requirements path supplied both positionally and by option")
    if args.traceability_option is not None and args.traceability_path is not None:
        parser.error("traceability path supplied both positionally and by option")

    default_requirements, default_traceability = _default_paths()
    requirements_path = Path(
        args.requirements_option or args.requirements_path or default_requirements
    )
    traceability_path = Path(
        args.traceability_option or args.traceability_path or default_traceability
    )
    diagnostics = check_files(requirements_path, traceability_path)
    if diagnostics:
        for diagnostic in diagnostics:
            print(f"ERROR: {diagnostic}", file=sys.stderr)
        return 1

    print(
        "PASS: requirements/traceability consistent "
        f"({EXPECTED_TOTAL} requirements, {EXPECTED_TOTAL} registry rows, "
        f"{EXPECTED_NORMATIVE} normative rows, "
        f"{EXPECTED_EVIDENCE_GATES} evidence gates)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
