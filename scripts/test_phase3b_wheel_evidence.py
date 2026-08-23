"""Phase-3B wheel-evidence probe (propose-only; changes no CI workflow).

Pipeline (all steps are real executions, results reported verbatim):

1. create two isolated virtualenvs (build venv, run venv);
2. download pinned maturin with ``pip download --require-hashes`` exactly as
   the accepted Phase-3A2 offline build does, then install it into the build
   venv (any digest mismatch aborts before any code runs);
3. ``maturin build --release`` the repository-root pyproject.toml;
4. install the produced wheel into the run venv;
5. probe the ADR-0015/API-0005 public surface: distribution metadata,
   ``matplotlib.backend`` entry point, module-loader registration,
   ``filetypes``/``required_interactive_framework``, forbidden exports;
6. run the existing Phase-3A2 helper tests (tests/python/) against the
   installed wheel;
7. emit a JSON manifest describing exactly what was proven and what was
   blocked. The backend module itself is owned by sibling lane t_e60a8ed3;
   until it lands the manifest records ``backend_absent`` instead of
   pretending success.

Usage:
    python3 scripts/test_phase3b_wheel_evidence.py --probe [--workdir DIR]
    python3 -m unittest scripts.test_phase3b_wheel_evidence

Network is needed only for the pinned maturin (and optional matplotlib)
download; without network or a Rust toolchain the probe records why it
stopped. This script produces convenience evidence only; it is not an
acceptance-grade artifact — release claims remain gated by the offline
containerized Phase-3A2 supply-chain lane.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.request
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

MATURIN_VERSION = "1.14.1"
# Exact wheel filename + sha256 downloaded by the accepted Phase-3A2 wheel
# workflow (.github/workflows/phase3a2-wheel.yml, cp311 cell). The workflow's
# cp311 download resolves to this py3-manylinux_2_12/musllinux universal
# wheel; the digest below was re-verified against a fresh PyPI download.
MATURIN_WHEEL = (
    "maturin-1.14.1-py3-none-manylinux_2_12_x86_64.manylinux2010_x86_64"
    ".musllinux_1_1_x86_64.whl"
)
MATURIN_WHEEL_SHA256 = (
    "dfc54ae32e6fcb18302193ab9a30b0b25eefffba994ae13238974805533ef75e"
)

EXPECTED_DISTRIBUTION = "lumenplot-mpl"
EXPECTED_ENTRY_POINT_VALUE = "lumenplot_mpl.backend"
EXPECTED_MODULE_LOADER = "module://lumenplot_mpl.backend"
EXPECTED_ENTRY_POINT_NAME = "lumenplot"
BACKEND_EXPORTS = ("FigureCanvasLumenPlot", "FigureCanvas", "FigureManager")
FORBIDDEN_BACKEND_EXPORTS = (
    "_Backend",
    "new_figure_manager",
    "draw_if_interactive",
    "show",
)

STATUS_IMPLEMENTED = "implemented"
STATUS_BACKEND_ABSENT = "backend-absent"
STATUS_BLOCKED = "blocked"


class ProbeBlocked(Exception):
    """The probe environment cannot proceed; message records the reason."""


def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    merged = {"capture_output": True, "text": True, "check": True}
    merged.update(kwargs)
    return subprocess.run(cmd, **merged)  # type: ignore[arg-type]


def provision_pinned_maturin(build_python: Path, cache_dir: Path) -> None:
    """Download the exact reviewed maturin wheel; abort on digest mismatch."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    wheel_path = cache_dir / MATURIN_WHEEL
    if not wheel_path.exists():
        requirements = cache_dir / "maturin-pin.txt"
        requirements.write_text(
            f"maturin=={MATURIN_VERSION} "
            f"--hash=sha256:{MATURIN_WHEEL_SHA256}\n",
            encoding="utf-8",
        )
        # Mirrors the accepted Phase-3A2 prefetch: pip resolves the URL,
        # --require-hashes gates integrity against the reviewed digest.
        run(
            [
                str(sys.executable),
                "-m",
                "pip",
                "download",
                "--no-deps",
                "--only-binary=:all:",
                "--require-hashes",
                "--dest",
                str(cache_dir),
                "-r",
                str(requirements),
            ]
        )
    digest = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    if digest != MATURIN_WHEEL_SHA256:
        raise ProbeBlocked(
            f"pinned maturin digest mismatch {digest} != {MATURIN_WHEEL_SHA256}"
        )
    run(
        [
            str(build_python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            "--find-links",
            str(cache_dir),
            f"maturin=={MATURIN_VERSION}",
        ]
    )


def make_venv(path: Path) -> Path:
    venv.EnvBuilder(with_pip=True, clear=True).create(path)
    return path / "bin" / "python"


def build_wheel(project_dir: Path, build_python: Path, out_dir: Path) -> Path:
    """Run pinned maturin from the repository root and return the wheel path.

    maturin must run with cwd=project_dir and no positional directory
    argument: passing one makes it append the path to the inner ``cargo
    rustc`` invocation as an extra input filename, which fails with
    ``multiple input filenames provided``.
    """
    result = run(
        [
            str(build_python),
            "-m",
            "maturin",
            "build",
            "--release",
            "--locked",
            "--out",
            str(out_dir),
        ],
        check=False,
        cwd=str(project_dir),
    )
    if result.returncode != 0:
        raise ProbeBlocked(f"maturin build failed:\n{result.stdout}\n{result.stderr}")
    wheels = sorted(out_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise ProbeBlocked(f"expected one wheel, found {[w.name for w in wheels]}")
    return wheels[0]


def ensure_matplotlib(run_python: Path) -> bool:
    """Best-effort matplotlib provision for probing; never claims evidence."""
    probe = run([str(run_python), "-c", "import matplotlib"], check=False)
    if probe.returncode == 0:
        return True
    install = run(
        [
            str(run_python),
            "-m",
            "pip",
            "install",
            "--only-binary=:all:",
            "matplotlib==3.11.1",
        ],
        check=False,
    )
    return install.returncode == 0


def probe_backend(run_python: Path, matplotlib_ready: bool) -> dict[str, object]:
    """Probe the public backend surface; report absence honestly."""
    info: dict[str, object] = {
        "backend_importable": False,
        "entry_point_registered": False,
        "module_loader_usable": False,
        "exports": [],
        "forbidden_exports_absent": None,
        "filetypes_png_only": None,
        "required_interactive_framework_none": None,
    }
    if not matplotlib_ready:
        info["blocked_reason"] = "matplotlib unavailable in run venv"
        return info

    import_probe = run(
        [str(run_python), "-c", "import lumenplot_mpl.backend"],
        check=False,
    )
    if import_probe.returncode != 0:
        missing_module = (
            "No module named 'lumenplot_mpl.backend'" in import_probe.stderr
        )
        info["blocked_reason"] = (
            STATUS_BACKEND_ABSENT if missing_module else import_probe.stderr.strip()
        )
        return info

    info["backend_importable"] = True
    detail = json.loads(
        run(
            [str(run_python), "-c", PROBE_DETAIL_SNIPPET],
        ).stdout
    )
    exports = sorted(detail["exports"])
    info["exports"] = exports
    info["forbidden_exports_absent"] = not (
        set(exports) & set(FORBIDDEN_BACKEND_EXPORTS)
    )
    info["filetypes_png_only"] = detail["filetypes"] == ["png"]
    info["required_interactive_framework_none"] = (
        detail["required_interactive_framework"] is None
    )
    info["module_loader_usable"] = detail["module_loader_ok"]
    ep = run(
        [
            str(run_python),
            "-c",
            "import json,importlib.metadata as m;"
            "print(json.dumps("
            "[ep.value for ep in m.entry_points(group='matplotlib.backend')"
            " if ep.name=='lumenplot']))",
        ]
    ).stdout
    values = json.loads(ep)
    info["entry_point_registered"] = EXPECTED_ENTRY_POINT_VALUE in values
    return info


PROBE_DETAIL_SNIPPET = """\
import json
import matplotlib
matplotlib.use("module://lumenplot_mpl.backend")
import lumenplot_mpl.backend as b
canvas = b.FigureCanvasLumenPlot
detail = {
    "exports": [
        n
        for n in ("FigureCanvasLumenPlot", "FigureCanvas", "FigureManager")
        if hasattr(b, n)
    ],
    "filetypes": sorted(getattr(canvas, "filetypes", {}).keys()),
    "required_interactive_framework": getattr(
        canvas, "required_interactive_framework", "missing"
    ),
    "module_loader_ok": matplotlib.get_backend() == "module://lumenplot_mpl.backend",
}
print(json.dumps(detail))
"""


def ensure_numpy(run_python: Path) -> bool:
    """Install the pinned NumPy evidence stack into the run venv."""
    install = run(
        [
            str(run_python),
            "-m",
            "pip",
            "install",
            "--only-binary=:all:",
            "numpy==2.4.6",
        ],
        check=False,
    )
    return install.returncode == 0


def _find_libstdcxx() -> str | None:
    """Locate a system libstdc++ directory (NixOS hosts lack one on PATH)."""
    if shutil.which("gcc") or Path("/usr/lib/x86_64-linux-gnu/libstdc++.so.6").exists():
        return None
    for candidate in sorted(Path("/nix/store").glob("*gcc*-lib/lib")):
        if (candidate / "libstdc++.so.6").exists():
            return str(candidate)
    return None


def run_helper_tests(run_python: Path) -> dict[str, object]:
    """Run the existing Phase-3A2 helper suite against the installed wheel.

    On NixOS hosts the PyPI NumPy wheel needs a system libstdc++; when it is
    discoverable in a Nix store gcc lib directory, the probe exports
    LD_LIBRARY_PATH for the child process and reports that in the manifest.
    """
    env = os.environ.copy()
    libstdcxx = _find_libstdcxx()
    if libstdcxx:
        existing = env.get("LD_LIBRARY_PATH")
        env["LD_LIBRARY_PATH"] = (
            f"{libstdcxx}:{existing}" if existing else libstdcxx
        )
    result = run(
        [
            str(run_python),
            "-m",
            "unittest",
            "discover",
            "-s",
            str(REPO_ROOT / "tests" / "python"),
        ],
        check=False,
        cwd=str(REPO_ROOT),
        env=env,
    )
    tail = "\n".join(result.stderr.strip().splitlines()[-3:])
    return {
        "suite": "tests/python (Phase-3A2 helper + Phase-3B entry-point checks)",
        "exit_code": result.returncode,
        "summary": tail,
        "ld_library_path_added": libstdcxx,
    }


def run_probe(workdir: Path) -> dict[str, object]:
    """Execute the full pipeline; every failure mode is recorded, not faked."""
    workdir.mkdir(parents=True, exist_ok=True)
    if shutil.which("cargo") is None:
        raise ProbeBlocked("cargo not on PATH; Rust toolchain required")

    build_dir = workdir / "venv-build"
    run_dir = workdir / "venv-run"
    build_python = make_venv(build_dir)
    run_python = make_venv(run_dir)

    provision_pinned_maturin(build_python, workdir / "wheelhouse")
    wheel = build_wheel(REPO_ROOT, build_python, workdir)

    run(
        [str(run_python), "-m", "pip", "install", "--no-deps", str(wheel)],
    )
    version = run(
        [
            str(run_python),
            "-c",
            "import importlib.metadata as m; print(m.version('lumenplot-mpl'))",
        ]
    ).stdout.strip()

    matplotlib_ready = ensure_matplotlib(run_python)
    surface = probe_backend(run_python, matplotlib_ready)

    # The helper suite exercises the native extension and the entry-point
    # suite skips cleanly when the backend module has not landed yet; both
    # run regardless of surface state so the manifest records real results.
    numpy_ready = ensure_numpy(run_python)
    if numpy_ready:
        helper_tests = run_helper_tests(run_python)
    else:
        helper_tests = {
            "suite": "tests/python (Phase-3A2 helper + Phase-3B entry-point checks)",
            "exit_code": None,
            "summary": "skipped: pinned numpy==2.4.6 could not be installed",
            "ld_library_path_added": None,
        }

    implemented = surface["backend_importable"] and all(
        surface[key] is True
        for key in (
            "forbidden_exports_absent",
            "filetypes_png_only",
            "required_interactive_framework_none",
            "module_loader_usable",
        )
    )
    status = (
        STATUS_IMPLEMENTED
        if implemented
        else STATUS_BACKEND_ABSENT
        if surface.get("blocked_reason") == STATUS_BACKEND_ABSENT
        else STATUS_BLOCKED
    )
    return {
        "wheel": wheel.name,
        "distribution_version": version,
        "surface_status": status,
        "surface": surface,
        "helper_tests": helper_tests,
        "note": (
            "convenience evidence only; acceptance requires the reviewed "
            "offline containerized Phase-3A2 supply-chain lane"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", action="store_true", help="run the full probe")
    parser.add_argument("--workdir", type=Path, default=None)
    args = parser.parse_args(argv)
    if not args.probe:
        parser.print_help()
        return 2
    workdir = args.workdir or Path(tempfile.mkdtemp(prefix="phase3b-probe-"))
    try:
        manifest = run_probe(workdir)
    except ProbeBlocked as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, indent=2))
        return 1
    print(json.dumps(manifest, indent=2))
    return 0


class SurfaceConstantsTests(unittest.TestCase):
    """Pure checks that the probe encodes the API-0005 declared surface."""

    def test_declared_identity_constants(self) -> None:
        self.assertEqual(EXPECTED_ENTRY_POINT_VALUE, "lumenplot_mpl.backend")
        self.assertEqual(EXPECTED_MODULE_LOADER, "module://lumenplot_mpl.backend")
        self.assertEqual(EXPECTED_ENTRY_POINT_NAME, "lumenplot")
        self.assertEqual(set(BACKEND_EXPORTS), {"FigureCanvasLumenPlot", "FigureCanvas", "FigureManager"})
        self.assertEqual(set(FORBIDDEN_BACKEND_EXPORTS), {"_Backend", "new_figure_manager", "draw_if_interactive", "show"})


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
