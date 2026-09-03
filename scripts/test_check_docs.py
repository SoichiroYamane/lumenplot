#!/usr/bin/env python3
"""Tests for the repository-local Markdown link checker."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.check_docs import check_tree


class MarkdownLinkCheckTests(unittest.TestCase):
    def test_repository_links_and_anchors_are_valid(self) -> None:
        self.assertEqual(check_tree(Path(__file__).resolve().parents[1]), [])

    def test_missing_file_and_anchor_are_reported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lumenplot-docs-") as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "# Root\n\n[missing](missing.md)\n[anchor](README.md#absent)\n",
                encoding="utf-8",
            )
            diagnostics = check_tree(root)
            self.assertEqual(len(diagnostics), 2)
            self.assertIn("missing link target", diagnostics[0])
            self.assertIn("missing anchor", diagnostics[1])

    def test_repository_escape_is_reported(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lumenplot-docs-") as directory:
            root = Path(directory)
            (root / "README.md").write_text(
                "# Root\n\n[outside](../outside.md)\n", encoding="utf-8"
            )
            diagnostics = check_tree(root)
            self.assertEqual(len(diagnostics), 1)
            self.assertIn("escapes repository", diagnostics[0])


if __name__ == "__main__":
    unittest.main()
