#!/usr/bin/env python3
"""Fail-closed checks for repository-local Markdown links and anchors."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import urllib.parse

_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\n]+)\)")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_EXTERNAL_PREFIXES = ("http:", "https:", "mailto:", "data:")


def _heading_slug(value: str) -> str:
    value = re.sub(r"[`*_~]", "", value).strip().lower()
    # Keep ASCII hyphens (GitHub keeps the hyphen in identifiers such as
    # ``O-04``) while dropping punctuation such as an em dash.
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    return re.sub(r"\s+", "-", value)


def _split_target(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and ">" in raw:
        return raw[1 : raw.index(">")]
    return raw.split(None, 1)[0]


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def check_tree(root: Path) -> list[str]:
    """Return deterministic diagnostics for broken local Markdown links."""

    root = root.resolve()
    markdown_files = sorted(path for path in root.rglob("*.md") if path.is_file())
    headings: dict[Path, set[str]] = {}
    for source in markdown_files:
        headings[source] = {
            _heading_slug(match.group(1))
            for line in source.read_text(encoding="utf-8").splitlines()
            if (match := _HEADING.match(line))
        }

    diagnostics: list[str] = []
    for source in markdown_files:
        text = source.read_text(encoding="utf-8")
        for match in _LINK.finditer(text):
            target = urllib.parse.unquote(_split_target(match.group(1)))
            if not target or target.startswith("#") or target.startswith(_EXTERNAL_PREFIXES):
                continue
            path_part, _, anchor = target.partition("#")
            resolved = (source.parent / path_part).resolve() if path_part else source
            if not _is_inside(resolved, root):
                diagnostics.append(
                    f"{source.relative_to(root)}: link escapes repository: {target}"
                )
                continue
            if not resolved.exists():
                diagnostics.append(
                    f"{source.relative_to(root)}: missing link target: {target}"
                )
                continue
            if anchor and anchor.lower() not in {
                heading.lower() for heading in headings.get(resolved, set())
            }:
                diagnostics.append(
                    f"{source.relative_to(root)}: missing anchor: {target}"
                )
    return diagnostics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: the parent of scripts/)",
    )
    args = parser.parse_args(argv)
    diagnostics = check_tree(args.root)
    if diagnostics:
        for diagnostic in diagnostics:
            print(f"[FAIL] {diagnostic}")
        print(f"Markdown link check failed: {len(diagnostics)} issue(s)")
        return 1
    count = sum(1 for _ in args.root.resolve().rglob("*.md"))
    print(f"[PASS] Markdown local links and anchors — {count} Markdown files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
