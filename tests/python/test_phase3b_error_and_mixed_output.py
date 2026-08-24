"""Phase-3B strict error fixtures and mixed-output raster-limit pins.

Covers two requirement lanes the existing backend suite does not yet pin:

- ``LP-MPL-006`` (error fixtures, ``AT-MPL-FALLBACK``): strict-common-2d
  raises an explicit unsupported result for unknown custom Artists,
  unsupported effects, and unconfigured TeX rather than silently dropping
  them (``docs/requirements/lumenplot-v1.0.md``, Matplotlib section).
- ``LP-MPL-009`` (mixed-output structural test, ``AT-EXPORT-FALLBACK``):
  supported primitives stay vector-aware in PDF/SVG while raster fallback is
  limited to the declared whole-frame PNG segment. Within the accepted
  Phase-3B slice (API 0005 §1, ADR 0015) the declared output surface is
  PNG-only: every vector target is therefore rejected explicitly before any
  write, and the only fallback representation is one whole-frame raster
  record. These pins hold the adapter to exactly that declared segment until
  the Phase-2 vector-export lanes land. The PNG-only ``filetypes`` declaration
  itself is pinned by ``TestModuleSurface.test_exports_and_identity`` in
  ``tests/python/test_phase3b_backend.py`` and is cross-referenced here rather
  than duplicated.

All fixtures exercise the public ``lumenplot_mpl.backend`` surface with a
stubbed ``lumenplot_mpl._native`` seam, exactly like
``test_phase3b_backend.py``; the real Rust seam is not required here.

Governing sources: requirements ``LP-MPL-006``/``LP-MPL-009``,
API 0005 §3/§5, ADR 0015 §4/§7/§12, API 0002 taxonomy.
"""

from __future__ import annotations

import io
import os
import struct
import tempfile
import types
import unittest
import unittest.mock

try:
    import matplotlib
except ModuleNotFoundError:  # offline cells: matplotlib evidence is a later slice
    matplotlib = None
else:
    matplotlib.use("module://matplotlib.backends.backend_agg")  # baseline only

    from matplotlib import figure  # noqa: E402
    from matplotlib.lines import Line2D  # noqa: E402

MATPLOTLIB_PRESENT = matplotlib is not None


class _BackendProxy:
    """Lazily resolve lumenplot_mpl.backend; raises if matplotlib is absent."""

    def __getattr__(self, name):
        import importlib
        return getattr(importlib.import_module("lumenplot_mpl.backend"), name)


backend_mod = _BackendProxy()  # noqa: E402


class _StubNativeModule(types.SimpleNamespace):
    """Stand-in for ``lumenplot_mpl._native`` recording the last spec."""

    last_spec: dict | None = None

    @staticmethod
    def render_frame_png(spec):  # noqa: N802 - mirrors native name
        _StubNativeModule.last_spec = spec
        return _stub_native_png(spec["width_px"], spec["height_px"])


def _stub_native_png(width: int, height: int) -> bytes:
    """A minimal deterministic PNG with correct IHDR (no raster content)."""
    header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(
        ">IIBBBBB", width, height, 8, 6, 0, 0, 0
    )
    return header + b"\x00\x00\x00\x00IEND\xaeB`\x82"


def _load_backend():
    """Import the backend lazily; requires matplotlib (absent in offline cells)."""
    import importlib
    return importlib.import_module("lumenplot_mpl.backend")


def _install_stub_native():
    # Resolve through the lazy proxy to the real module object before patching,
    # so the render path (which reads the module global) sees the stub.
    real = backend_mod if isinstance(backend_mod, types.ModuleType) else (
        __import__("lumenplot_mpl.backend", fromlist=["_native"])
    )
    return unittest.mock.patch.object(real, "_native", lambda: _StubNativeModule)


def _strict_canvas(figsize=(2.0, 1.0), dpi=100):
    """A strict-mode canvas on an empty figure (content added per-test)."""
    if not MATPLOTLIB_PRESENT:
        raise unittest.SkipTest("matplotlib not in this offline cell")
    fig = figure.Figure(figsize=figsize, dpi=dpi)
    canvas = _load_backend().FigureCanvasLumenPlot(fig)
    return fig, canvas


def _eligible_axes(ax):
    """Make an axes carry the fixed strict-style eligible line (ADR 0015 §5)."""
    ax.axison = False
    ax.add_line(Line2D([0.0, 10.0], [0.0, 5.0], color="red",
                       linewidth=2.0, solid_capstyle="butt",
                       solid_joinstyle="miter"))
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(0.0, 5.0)


def _hybrid_canvas_with(build, figsize=(2.0, 1.0), dpi=100):
    """Build a hybrid-mode canvas whose figure carries ``build(ax)`` content."""
    fig = figure.Figure(figsize=figsize, dpi=dpi)
    canvas = _load_backend().FigureCanvasLumenPlot(fig, mode="hybrid")
    ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
    build(ax)
    return fig, canvas


# ---------------------------------------------------------------------------
# LP-MPL-006 error fixtures: strict mode never silently drops content
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestStrictErrorFixtures(unittest.TestCase):
    """Unknown custom Artists, unsupported effects, and unconfigured TeX
    produce an explicit unsupported failure in strict-common-2d (this
    slice's strict profile); nothing is silently dropped or approximated."""

    def setUp(self):
        _StubNativeModule.last_spec = None
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)

    def _canvas_with(self, build):
        fig, canvas = _strict_canvas()
        ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
        build(ax)
        return fig, canvas

    def _assert_explicitly_unsupported(self, build, expected_type=None):
        fig, canvas = self._canvas_with(build)
        with self.assertRaises(
            backend_mod.LumenPlotUnsupportedError
        ) as ctx:
            canvas.render_png()
        # Nothing was published to the native seam and no fallback
        # diagnostics exist: the failure is the explicit result itself.
        self.assertIs(_StubNativeModule.last_spec, None)
        self.assertEqual(canvas.last_diagnostics, ())
        if expected_type is not None:
            self.assertEqual(ctx.exception.type_context, expected_type)
        return fig

    def test_stock_nonwhitelisted_artist_rejected(self):
        """A stock Patch outside the Line2D whitelist is named and refused."""
        from matplotlib.patches import Rectangle

        def build(ax):
            ax.axison = False
            ax.add_patch(Rectangle((1.0, 1.0), 2.0, 1.0))
            _eligible_axes(ax)

        self._assert_explicitly_unsupported(build, expected_type="Rectangle")

    def test_user_defined_artist_subclass_rejected(self):
        """A user-defined Line2D subclass is unknown content: the whitelist
        rejects the subclass itself rather than silently rendering it."""
        class _CustomTrace(Line2D):
            pass

        def build(ax):
            ax.axison = False
            ax.add_line(_CustomTrace([0, 10], [0, 5], color="red"))
            ax.set_xlim(0, 10)
            ax.set_ylim(0, 5)

        self._assert_explicitly_unsupported(
            build, expected_type="_CustomTrace"
        )

    def test_figure_level_unknown_artist_rejected(self):
        """Content attached directly to the figure is inspected too."""
        def build(ax):
            _eligible_axes(ax)

        fig, canvas = self._canvas_with(build)
        fig.add_artist(Line2D([0, 1], [0, 1], marker="o"))
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            canvas.render_png()
        self.assertEqual(canvas.last_diagnostics, ())
        self.assertIs(_StubNativeModule.last_spec, None)

    def test_path_effects_rejected(self):
        """Path effects on an otherwise eligible line are refused."""
        from matplotlib import patheffects

        def build(ax):
            ax.axison = False
            line = Line2D([0, 10], [0, 5], color="red",
                          solid_capstyle="butt", solid_joinstyle="miter")
            line.set_path_effects([patheffects.withStroke(
                linewidth=3.0, foreground="black")])
            ax.add_line(line)
            ax.set_xlim(0, 10)
            ax.set_ylim(0, 5)

        self._assert_explicitly_unsupported(build)

    def test_sketch_params_rejected(self):
        """Sketch (hand-drawn wiggle) parameters are refused, not drawn."""

        def build(ax):
            ax.axison = False
            line = Line2D([0, 10], [0, 5], color="red",
                          solid_capstyle="butt", solid_joinstyle="miter")
            line.set_sketch_params(scale=2.0)
            ax.add_line(line)
            ax.set_xlim(0, 10)
            ax.set_ylim(0, 5)

        self._assert_explicitly_unsupported(build)

    def test_usetex_text_fails_explicitly_never_silently_dropped(self):
        """Unconfigured TeX cannot render in this slice: the adapter has no
        TeX pathway, so TeX-bound text reaches the guarded public-render
        traversal boundary and the attempt fails explicitly instead of
        dropping the text or approximating it."""
        from matplotlib import rc_context

        def build(ax):
            ax.axison = False
            ax.add_line(Line2D([0, 10], [0, 5], color="red",
                               solid_capstyle="butt",
                               solid_joinstyle="miter"))
            ax.set_xlim(0, 10)
            ax.set_ylim(0, 5)

        fig, canvas = self._canvas_with(build)
        ax = fig.get_axes()[0]
        with rc_context({"text.usetex": True}):
            ax.set_title(r"$\int_0^\infty e^{-x}\,dx$")
            with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
                canvas.render_png()
        self.assertIs(_StubNativeModule.last_spec, None)
        self.assertEqual(canvas.last_diagnostics, ())

    def test_mathtext_text_fails_explicitly_never_silently_dropped(self):
        """Mathtext is equally outside the supported set: explicit failure."""

        def build(ax):
            ax.axison = False
            ax.add_line(Line2D([0, 10], [0, 5], color="red",
                               solid_capstyle="butt",
                               solid_joinstyle="miter"))
            ax.set_xlim(0, 10)
            ax.set_ylim(0, 5)

        fig, canvas = self._canvas_with(build)
        fig.text(0.5, 0.5, r"$\alpha+\beta$")
        with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
            canvas.render_png()
        self.assertIs(_StubNativeModule.last_spec, None)

    def test_strict_failure_via_savefig_leaves_no_output_file(self):
        """The explicit unsupported result precedes any target write, so a
        failed ``savefig`` to a path leaves no file behind."""

        def build(ax):
            ax.axison = False
            ax.add_line(Line2D([0, 1], [0, 1], marker="o"))
            ax.set_xlim(0, 10)
            ax.set_ylim(0, 5)

        fig, canvas = self._canvas_with(build)
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "out.png")
            with self.assertRaises(backend_mod.LumenPlotUnsupportedError):
                fig.savefig(target, format="png")
            self.assertFalse(os.path.exists(target))

    def test_strict_raises_before_write_for_every_negative_fixture(self):
        """Every negative fixture raises ``unsupported-capability`` before a
        single byte reaches the target: driving each one through a BytesIO
        savefig leaves the buffer empty (LP-MPL-006 / API-0002). The marker,
        dash, drawstyle, and text negatives duplicate the raise coverage in
        ``test_phase3b_backend.py``; the new part here is the empty-target
        assertion across all of them. usetex fails pre-render, so no TeX
        installation is required."""

        def build_marker(ax):
            ax.axison = False
            ax.add_line(Line2D([0, 10], [0, 5], color="red", marker="o",
                               solid_capstyle="butt",
                               solid_joinstyle="miter"))

        def build_dash(ax):
            ax.axison = False
            ax.add_line(Line2D([0, 10], [0, 5], color="red", linestyle="--"))

        def build_drawstyle(ax):
            ax.axison = False
            ax.add_line(Line2D([0, 10], [0, 5], color="red",
                               drawstyle="steps-mid",
                               solid_capstyle="butt",
                               solid_joinstyle="miter"))

        def build_text(ax):
            ax.axison = False
            ax.text(0.5, 0.5, "annotation")
            ax.add_line(Line2D([0, 10], [0, 5], color="red",
                               solid_capstyle="butt",
                               solid_joinstyle="miter"))

        class _CustomTrace(Line2D):
            pass

        def build_custom_artist(ax):
            ax.axison = False
            ax.add_line(_CustomTrace([0, 10], [0, 5], color="red"))

        def build_path_effect(ax):
            from matplotlib import patheffects

            ax.axison = False
            line = Line2D([0, 10], [0, 5], color="red",
                          solid_capstyle="butt", solid_joinstyle="miter")
            line.set_path_effects([patheffects.withStroke(
                linewidth=3.0, foreground="black")])
            ax.add_line(line)

        def build_usetex(ax):
            from matplotlib import rc_context

            ax.axison = False
            ax.add_line(Line2D([0, 10], [0, 5], color="red",
                               solid_capstyle="butt",
                               solid_joinstyle="miter"))
            with rc_context({"text.usetex": True}):
                ax.set_title(r"$\int_0^\infty e^{-x}\,dx$")

        for name, build in (
            ("marker", build_marker),
            ("dash", build_dash),
            ("drawstyle", build_drawstyle),
            ("text", build_text),
            ("custom artist", build_custom_artist),
            ("path effect", build_path_effect),
            ("usetex", build_usetex),
        ):
            with self.subTest(fixture=name):
                fig, canvas = self._canvas_with(build)
                buffer = io.BytesIO()
                with self.assertRaises(
                    backend_mod.LumenPlotUnsupportedError
                ) as ctx:
                    fig.savefig(buffer, format="png")
                self.assertEqual(ctx.exception.code, "unsupported-capability")
                self.assertEqual(buffer.getvalue(), b"")
                self.assertIs(_StubNativeModule.last_spec, None)


# ---------------------------------------------------------------------------
# LP-MPL-009 mixed-output structural pins: PNG-only surface, whole-frame
# raster fallback only, no subtree/segment fallback surface
# ---------------------------------------------------------------------------


@unittest.skipUnless(MATPLOTLIB_PRESENT, "matplotlib not in this offline cell")
class TestMixedOutputRasterLimit(unittest.TestCase):
    """Within the accepted Phase-3B surface the only output format is PNG;
    every vector target is refused explicitly before any byte is written,
    and the only fallback representation is one structured whole-frame
    raster diagnostic. No subtree/segment fallback surface exists."""

    def setUp(self):
        _StubNativeModule.last_spec = None
        patcher = _install_stub_native()
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fig, self.canvas = _strict_canvas()
        ax = self.fig.add_axes([0.1, 0.1, 0.8, 0.8])
        _eligible_axes(ax)

    def test_vector_formats_rejected_before_any_write(self):
        """PDF/SVG/PS/EPS targets fail explicitly with an empty target."""
        for fmt in ("pdf", "svg", "ps", "eps"):
            with self.subTest(fmt=fmt):
                buffer = io.BytesIO()
                with self.assertRaises(
                    backend_mod.LumenPlotUnsupportedError
                ) as ctx:
                    self.fig.savefig(buffer, format=fmt)
                self.assertEqual(ctx.exception.code, "unsupported-capability")
                self.assertEqual(buffer.getvalue(), b"")

    def test_vector_suffix_targets_rejected_without_creating_files(self):
        """Suffix-derived format detection refuses vector paths pre-write."""
        for suffix in (".pdf", ".svg", ".eps"):
            with self.subTest(suffix=suffix):
                with tempfile.TemporaryDirectory() as tmpdir:
                    target = os.path.join(tmpdir, "mixed-output" + suffix)
                    with self.assertRaises(
                        backend_mod.LumenPlotUnsupportedError
                    ):
                        self.fig.savefig(target)
                    self.assertEqual(os.listdir(tmpdir), [])

    def test_extensionless_target_defaults_to_declared_png(self):
        """An extensionless path follows the base-class convention and
        produces the single declared output: a PNG file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "mixed-output")
            self.assertIsNone(self.fig.savefig(target))
            produced = sorted(os.listdir(tmpdir))
            self.assertEqual(produced, ["mixed-output.png"])
            with open(os.path.join(tmpdir, "mixed-output.png"), "rb") as fh:
                data = fh.read()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")

    def test_hybrid_fallback_is_one_whole_frame_raster_record(self):
        """Hybrid degradation publishes exactly one structured record whose
        scope is the whole frame and whose representation is raster PNG --
        never a subtree or per-primitive substitution. The card-named hybrid
        counterparts of the strict negatives (unknown custom Artist, path
        effects) each succeed via whole-frame Agg with exactly that record;
        generation is the canvas counter spent once for the attempt."""
        from matplotlib import patheffects

        class _CustomTrace(Line2D):
            pass

        def build_custom_artist(ax):
            ax.axison = False
            ax.add_line(_CustomTrace([0, 10], [0, 5], color="red"))
            ax.set_xlim(0, 10)
            ax.set_ylim(0, 5)

        def build_path_effect(ax):
            ax.axison = False
            line = Line2D([0, 10], [0, 5], color="red",
                          solid_capstyle="butt", solid_joinstyle="miter")
            line.set_path_effects([patheffects.withStroke(
                linewidth=3.0, foreground="black")])
            ax.add_line(line)
            ax.set_xlim(0, 10)
            ax.set_ylim(0, 5)

        for name, build in (
            ("custom artist", build_custom_artist),
            ("path effect", build_path_effect),
        ):
            with self.subTest(fixture=name):
                fig, canvas = _hybrid_canvas_with(build)
                before_generation = canvas._generation
                result = canvas.render_png()
                self.assertEqual(
                    canvas._generation, before_generation + 1
                )
                self.assertEqual(len(result.diagnostics), 1)
                diagnostic = result.diagnostics[0]
                self.assertIsInstance(
                    diagnostic,
                    backend_mod.LumenPlotFallbackDiagnostic,
                )
                self.assertEqual(
                    diagnostic.kind, "unsupported-capability"
                )
                self.assertEqual(diagnostic.scope, "whole-frame")
                self.assertEqual(diagnostic.representation, "raster")
                self.assertEqual(diagnostic.output_format, "png")
                self.assertEqual(
                    diagnostic.fallback_type, "matplotlib-agg"
                )
                self.assertIsInstance(diagnostic.generation, int)
                self.assertGreaterEqual(diagnostic.generation, 1)
                self.assertEqual(
                    diagnostic.generation, canvas._generation
                )
                self.assertEqual(
                    canvas.last_diagnostics, result.diagnostics
                )
                del fig

    def test_no_subtree_or_segment_fallback_surface_exists(self):
        """Structural pin: the declared diagnostic envelope carries exactly
        the LP-MPL-008 fields with raster/whole-frame/png defaults, and the
        module exposes no subtree or region fallback API at all."""
        import inspect

        import lumenplot_mpl.backend as real_backend

        module_dict = vars(real_backend)
        for forbidden in (
            "draw_artist_subtree",
            "render_subtree",
            "render_region",
            "fallback_region",
            "subtree_fallback",
            "partial_fallback",
        ):
            self.assertNotIn(forbidden, module_dict)

        signature = inspect.signature(
            real_backend.LumenPlotFallbackDiagnostic.__init__
        )
        self.assertEqual(
            set(signature.parameters),
            {
                "self",
                "kind",
                "type",
                "generation",
                "output_format",
                "scope",
                "representation",
                "fallback_type",
            },
        )
        self.assertEqual(
            signature.parameters["representation"].default, "raster"
        )
        self.assertEqual(signature.parameters["scope"].default, "whole-frame")
        self.assertEqual(signature.parameters["output_format"].default, "png")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
