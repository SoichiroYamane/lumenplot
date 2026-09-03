#!/usr/bin/env python3
"""Contract tests for the contributor verification shell script."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
VERIFY = ROOT / "scripts" / "verify.sh"


class VerifyScriptTests(unittest.TestCase):
    def run_verify(
        self,
        *arguments: str,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(VERIFY), *arguments],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_script_is_executable(self) -> None:
        mode = VERIFY.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR, "verify.sh must be executable by its owner")

    def test_shell_syntax_is_valid(self) -> None:
        shell = shutil.which("sh")
        self.assertIsNotNone(shell, "a POSIX shell is required for the syntax check")
        result = subprocess.run(
            [shell, "-n", str(VERIFY)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_help_lists_supported_options_without_running_gates(self) -> None:
        result = self.run_verify("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("Usage:", result.stdout)
        for option in ("--help", "--skip-install", "--skip-nix"):
            self.assertIn(option, result.stdout)
        self.assertNotIn("cargo", result.stdout)

    def test_unknown_option_fails_closed(self) -> None:
        result = self.run_verify("--not-a-supported-option")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown option", result.stderr)

    def test_skip_flags_are_accepted_without_install_or_nix(self) -> None:
        with tempfile.TemporaryDirectory(prefix="lumenplot-verify-contract-") as directory:
            fake_bin = Path(directory) / "bin"
            fake_bin.mkdir()
            log_path = Path(directory) / "commands.log"
            self._write_fake_command(
                fake_bin,
                "python3",
                """\
printf 'python3 %s\\n' "$*" >> "$VERIFY_FAKE_LOG"
if [ "${1-}" = "-m" ] && [ "${2-}" = "pip" ]; then
    printf '%s\\n' 'unexpected package installation' >&2
    exit 97
fi
exit 0
""",
            )
            self._write_fake_command(
                fake_bin,
                "cargo",
                """\
printf 'cargo %s\\n' "$*" >> "$VERIFY_FAKE_LOG"
exit 0
""",
            )
            self._write_fake_command(
                fake_bin,
                "git",
                """\
printf 'git %s\\n' "$*" >> "$VERIFY_FAKE_LOG"
exit 0
""",
            )
            self._write_fake_command(
                fake_bin,
                "nix",
                """\
printf '%s\\n' 'unexpected nix invocation' >&2
exit 98
""",
            )

            environment = os.environ.copy()
            environment["PATH"] = os.pathsep.join(
                (str(fake_bin), environment.get("PATH", ""))
            )
            environment["VERIFY_FAKE_LOG"] = str(log_path)
            result = self.run_verify(
                "--skip-install",
                "--skip-nix",
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            commands = log_path.read_text(encoding="utf-8")
            self.assertNotIn("-m pip install --editable .", commands)
            self.assertNotIn("unexpected nix invocation", commands)
            self.assertIn("cargo fmt --all -- --check", commands)
            self.assertIn("python3 scripts/check_requirements_traceability.py", commands)
            self.assertIn("python3 -m unittest scripts.test_check_requirements_traceability", commands)
            self.assertIn("python3 scripts/check_docs.py", commands)
            self.assertNotIn("verify_traceability_coverage.py", commands)
            self.assertIn("git diff --check", commands)

    @staticmethod
    def _write_fake_command(directory: Path, name: str, body: str) -> None:
        command = directory / name
        command.write_text(f"#!/bin/sh\nset -eu\n{body}", encoding="utf-8")
        command.chmod(0o755)


if __name__ == "__main__":
    unittest.main()
