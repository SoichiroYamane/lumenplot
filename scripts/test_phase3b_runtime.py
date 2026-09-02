"""Runtime probe for an installed Phase-3B backend package.

The probe is intentionally separate from the source-tree contract suites.  It
must be run from a fresh virtual environment after installing the wheel under
test, so importing ``lumenplot_mpl.backend`` cannot accidentally resolve the
checkout's ``python/`` directory.  It reports a compact, path-free JSON record
and exits non-zero for any failed assertion.
"""

from __future__ import annotations

import argparse
from io import BytesIO
import importlib
from importlib.metadata import entry_points, version
import json
from pathlib import Path
import sys
import tempfile
import unittest


DISTRIBUTION = "lumenplot-mpl"
ENTRY_POINT_GROUP = "matplotlib.backend"
ENTRY_POINT_NAME = "lumenplot"
ENTRY_POINT_VALUE = "lumenplot_mpl.backend"
MODULE_LOADER = "module://lumenplot_mpl.backend"
EXPECTED_MATPLOTLIB = "3.11.1"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class ProbeFailure(RuntimeError):
    """A redaction-safe runtime assertion failure."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProbeFailure(message)


def _png_dimensions(data: bytes) -> tuple[int, int]:
    _require(data.startswith(PNG_SIGNATURE), "native output is not a PNG")
    _require(len(data) >= 24, "native PNG is shorter than its IHDR")
    length = int.from_bytes(data[8:12], "big")
    _require(data[12:16] == b"IHDR", "native PNG has no IHDR first chunk")
    _require(length == 13, "native PNG IHDR length is not 13")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _ensure_wheel_module(backend: object) -> None:
    """Reject a source-tree import while keeping paths out of diagnostics."""
    module_file = getattr(backend, "__file__", None)
    _require(isinstance(module_file, str), "backend module has no file location")
    resolved = Path(module_file).resolve()
    source_package = Path(__file__).resolve().parents[1] / "python" / "lumenplot_mpl"
    try:
        resolved.relative_to(source_package)
    except ValueError:
        return
    raise ProbeFailure("backend resolved from the source checkout")


def _line_figure(figure_type: object, line_type: object):
    figure = figure_type(figsize=(2.0, 1.0), dpi=100)
    canvas = _BACKEND.FigureCanvasLumenPlot(figure)
    axes = figure.add_axes([0.1, 0.1, 0.8, 0.8])
    axes.set_axis_off()
    axes.add_line(
        line_type(
            [0.0, 10.0],
            [0.0, 5.0],
            color="red",
            linewidth=2.0,
            solid_capstyle="butt",
            solid_joinstyle="miter",
        )
    )
    axes.set_xlim(0.0, 10.0)
    axes.set_ylim(0.0, 5.0)
    return figure, canvas


def _hybrid_figure(figure_type: object, line_type: object):
    figure = figure_type(figsize=(2.0, 1.0), dpi=100)
    canvas = _BACKEND.FigureCanvasLumenPlot(figure, mode="hybrid")
    axes = figure.add_axes([0.1, 0.1, 0.8, 0.8])
    axes.set_axis_off()
    axes.add_line(
        line_type(
            [0.0, 10.0],
            [0.0, 5.0],
            color="red",
            linewidth=2.0,
            linestyle="--",
            solid_capstyle="butt",
            solid_joinstyle="miter",
        )
    )
    axes.set_xlim(0.0, 10.0)
    axes.set_ylim(0.0, 5.0)
    return figure, canvas


def run_probe(expected_version: str | None = None) -> dict[str, object]:
    """Exercise the public backend from an installed distribution."""
    global _BACKEND

    import matplotlib

    _require(matplotlib.__version__ == EXPECTED_MATPLOTLIB, "unexpected Matplotlib version")
    matplotlib.use(MODULE_LOADER, force=True)
    _BACKEND = importlib.import_module(ENTRY_POINT_VALUE)
    _ensure_wheel_module(_BACKEND)

    installed_version = version(DISTRIBUTION)
    if expected_version is not None:
        _require(
            installed_version == expected_version,
            "installed distribution version differs from Cargo metadata",
        )

    matches = [
        point
        for point in entry_points(group=ENTRY_POINT_GROUP)
        if point.name == ENTRY_POINT_NAME
    ]
    _require(len(matches) == 1, "installed backend entry point is not unique")
    point = matches[0]
    _require(point.value == ENTRY_POINT_VALUE, "backend entry point value is incorrect")
    _require(point.load() is _BACKEND, "backend entry point does not resolve to the module")
    _require(
        matplotlib.get_backend().lower() == MODULE_LOADER,
        "module loader did not select the declared backend",
    )

    # Check the name-based Matplotlib loader in the same clean process after
    # the module-based route has been proven.
    matplotlib.use(ENTRY_POINT_NAME, force=True)
    loader_backend = matplotlib.get_backend().lower()
    _require(
        loader_backend in (ENTRY_POINT_NAME, MODULE_LOADER),
        "entry-point backend selection did not resolve",
    )

    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D

    figure, canvas = _line_figure(Figure, Line2D)
    output = BytesIO()
    _require(figure.savefig(output, format="png") is None, "savefig changed its return contract")
    _require(_png_dimensions(output.getvalue()) == (200, 100), "native savefig dimensions are incorrect")
    native = canvas.render_png()
    _require(_png_dimensions(native.png_bytes) == (200, 100), "native helper dimensions are incorrect")
    _require(native.diagnostics == (), "eligible native output published diagnostics")

    strict_figure, strict_canvas = _hybrid_figure(Figure, Line2D)
    strict_target = BytesIO()
    try:
        strict_canvas = _BACKEND.FigureCanvasLumenPlot(strict_figure, mode="strict")
        strict_canvas.render_png(strict_target)
    except _BACKEND.LumenPlotUnsupportedError as error:
        _require(error.code == "unsupported-capability", "strict failure token changed")
    else:
        raise ProbeFailure("strict unsupported content did not fail")
    _require(strict_target.getvalue() == b"", "strict failure wrote output bytes")

    hybrid_figure, hybrid_canvas = _hybrid_figure(Figure, Line2D)
    fallback = hybrid_canvas.render_png()
    _require(len(fallback.diagnostics) == 1, "hybrid output did not publish one diagnostic")
    diagnostic = fallback.diagnostics[0]
    _require(diagnostic.kind == "unsupported-capability", "hybrid diagnostic token changed")
    _require(diagnostic.scope == "whole-frame", "hybrid diagnostic scope changed")
    _require(diagnostic.representation == "raster", "hybrid diagnostic representation changed")
    _require(diagnostic.output_format == "png", "hybrid diagnostic format changed")
    _require(diagnostic.fallback_type == "matplotlib-agg", "hybrid fallback type changed")
    _require(_png_dimensions(fallback.png_bytes) == (200, 100), "hybrid PNG dimensions are incorrect")
    _require(hybrid_figure.canvas is hybrid_canvas, "hybrid fallback did not restore the canvas")

    return {
        "backend_module": ENTRY_POINT_VALUE,
        "distribution": DISTRIBUTION,
        "distribution_version": installed_version,
        "entry_point": {
            "group": ENTRY_POINT_GROUP,
            "name": ENTRY_POINT_NAME,
            "resolved": True,
            "value": ENTRY_POINT_VALUE,
        },
        "hybrid_fallback": {
            "diagnostics": len(fallback.diagnostics),
            "fallback_type": diagnostic.fallback_type,
            "format": diagnostic.output_format,
            "representation": diagnostic.representation,
            "scope": diagnostic.scope,
        },
        "matplotlib": EXPECTED_MATPLOTLIB,
        "module_loader": True,
        "native_png": {"diagnostics": 0, "height": 100, "width": 200},
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "status": "pass",
        "strict_unsupported": {
            "code": "unsupported-capability",
            "target_unchanged": True,
        },
    }


def _contains_forbidden_text(value: object) -> bool:
    """Return whether an evidence value contains a private path or secret."""
    if isinstance(value, str):
        lowered = value.lower()
        return any(
            token in lowered
            for token in ("/home/", "/tmp/", "github_token", "secret")
        )
    if isinstance(value, dict):
        return any(
            _contains_forbidden_text(key) or _contains_forbidden_text(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden_text(item) for item in value)
    return False


def verify_evidence(paths: list[Path]) -> dict[str, object]:
    """Validate the four CI-local records emitted by the runtime cells."""
    expected_names = [
        "phase3b-runtime-cp311.json",
        "phase3b-runtime-cp312.json",
        "phase3b-runtime-cp313.json",
        "phase3b-runtime-cp314.json",
    ]
    _require(
        [path.name for path in paths] == expected_names,
        "runtime evidence files are not the ordered CPython 3.11-3.14 set",
    )
    cells: list[str] = []
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise ProbeFailure("runtime evidence record is unreadable") from None
        _require(isinstance(record, dict), "runtime evidence record is not an object")
        _require(record.get("status") == "pass", "runtime evidence cell did not pass")
        _require(record.get("matplotlib") == EXPECTED_MATPLOTLIB, "runtime evidence Matplotlib version changed")
        _require(record.get("distribution") == DISTRIBUTION, "runtime evidence distribution changed")
        _require(record.get("backend_module") == ENTRY_POINT_VALUE, "runtime evidence backend identity changed")
        _require(record.get("module_loader") is True, "runtime evidence module-loader check is missing")
        entry_point = record.get("entry_point")
        _require(isinstance(entry_point, dict), "runtime evidence entry-point record is missing")
        _require(entry_point.get("group") == ENTRY_POINT_GROUP, "runtime evidence entry-point group changed")
        _require(entry_point.get("name") == ENTRY_POINT_NAME, "runtime evidence entry-point name changed")
        _require(entry_point.get("value") == ENTRY_POINT_VALUE, "runtime evidence entry-point value changed")
        _require(entry_point.get("resolved") is True, "runtime evidence entry point did not resolve")
        _require(not _contains_forbidden_text(record), "runtime evidence contains private path or secret text")
        cell = record.get("python")
        _require(isinstance(cell, str), "runtime evidence Python cell is missing")
        cells.append(cell)
    _require(cells == ["3.11", "3.12", "3.13", "3.14"], "runtime evidence Python cells are not ordered")
    return {"cells": cells, "matplotlib": EXPECTED_MATPLOTLIB, "status": "pass"}


class RuntimeEvidenceVerifierTests(unittest.TestCase):
    """Keep the CI-local four-cell validator fail-closed."""

    @staticmethod
    def _record(cell: str) -> dict[str, object]:
        return {
            "backend_module": ENTRY_POINT_VALUE,
            "distribution": DISTRIBUTION,
            "distribution_version": "0.1.0",
            "entry_point": {
                "group": ENTRY_POINT_GROUP,
                "name": ENTRY_POINT_NAME,
                "resolved": True,
                "value": ENTRY_POINT_VALUE,
            },
            "matplotlib": EXPECTED_MATPLOTLIB,
            "module_loader": True,
            "python": cell,
            "status": "pass",
        }

    def test_ordered_four_cell_records_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = []
            for tag, cell in zip(
                ("cp311", "cp312", "cp313", "cp314"),
                ("3.11", "3.12", "3.13", "3.14"),
            ):
                path = root / f"phase3b-runtime-{tag}.json"
                path.write_text(
                    json.dumps(self._record(cell)), encoding="utf-8"
                )
                paths.append(path)
            self.assertEqual(verify_evidence(paths)["status"], "pass")

    def test_private_path_in_record_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = []
            for tag, cell in zip(
                ("cp311", "cp312", "cp313", "cp314"),
                ("3.11", "3.12", "3.13", "3.14"),
            ):
                record = self._record(cell)
                if tag == "cp313":
                    record["private_path"] = "/tmp/runner-secret"
                path = root / f"phase3b-runtime-{tag}.json"
                path.write_text(
                    json.dumps(record), encoding="utf-8"
                )
                paths.append(path)
            with self.assertRaises(ProbeFailure):
                verify_evidence(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", default=None)
    parser.add_argument("--verify-evidence", nargs="+", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        if args.verify_evidence is not None:
            result = verify_evidence(args.verify_evidence)
        else:
            result = run_probe(expected_version=args.expected_version)
    except ProbeFailure as error:
        print(json.dumps({"reason": str(error), "status": "failed"}, sort_keys=True))
        return 1
    except Exception:
        # Keep CI evidence path-free even for an unexpected dependency/runtime
        # exception; the detailed process log remains the ordinary test gate.
        print(json.dumps({"reason": "unexpected runtime probe failure", "status": "failed"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
