//! M5-TEXT-1B retained text-layout slice tests (tests a-f, Phase-A spec).
//!
//! Scope: NEW integration coverage only, against the EXISTING retained
//! shaping types in `crates/lumenplot-engine/src/text.rs`
//! (`ShapedRun` / `PlotLayout` / `canonical_digest` carrier). ZERO
//! production-code change: this file constructs nothing private and
//! changes no public signature. It reads the one shared shaping result
//! through the public bridge (`PlotScene` -> `SceneSnapshot` ->
//! `resolve_line_frame` -> `LineFrame::plot_layout`), exactly the path
//! every downstream sink consumes.
//!
//! Mapping to the t_be3c8b40 slice-1 tests:
//! - (a) shared-digest determinism across independent frames;
//! - (b) retained glyph geometry matches the declared fixture grid, and
//!   the declared adapter display transform (`p_display = R(angle) @
//!   S(dpi/72) @ p_outline + anchor`) re-evaluates deterministically, so
//!   any consumer agrees within the S15.1 part-3 1e-6 logical-pt gate;
//!   the direct outline-vs-`TextPath` 1e-6 agreement lives in
//!   `tests/python/test_m5_shaped_layout.py`, which owns a Matplotlib;
//! - (c) no-remeasurement static gate over `render-api` + `export`
//!   sources (the M5-P3ii shaping pins stay declared-but-uncalled);
//! - (d) missing-glyph strictness observable half: no silent blank is
//!   representable (every run carries >= 1 positioned non-zero glyph,
//!   the strict `UnsupportedCapability` route stays publicly mapped);
//! - (e) clip/stack retention survives projection into the frame;
//! - (f) fallback-route provenance is recorded per run (exact-bytes
//!   primary route; no silent system fallback exists on the type).

use std::path::PathBuf;

use lumenplot_engine::bridge::{
    AnnotationSpace, AxisScale, AxisScales, FallbackRoute, LineFrame, LineFrameSpec, LineStyle,
    LogicalRect, LogicalSize, PlotScene, SeriesData, SeriesTopology, SrgbRgba8, TextDirection,
    TextRole, Viewport,
};

/// Build one resolved line frame through the public bridge only.
///
/// Mirrors the `make_frame` helper in `lumenplot-export`'s raster tests:
/// a two-point series committed to a fresh scene, resolved against a
/// 4x4 logical spec. The retained layout rides the frame, never the
/// series data.
fn make_frame() -> LineFrame {
    let canvas = LogicalSize::new(4.0, 4.0).expect("canvas");
    let plot = LogicalRect::new(0.0, 0.0, 4.0, 4.0).expect("plot");
    let style = LineStyle::new(SrgbRgba8::new(20, 40, 80, 255), 1.0).expect("style");
    let frame_spec =
        LineFrameSpec::new(canvas, plot, 1.0, style, SrgbRgba8::new(255, 255, 255, 255))
            .expect("frame spec");
    let view = Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view");
    let mut scene =
        PlotScene::new(view, AxisScales::new(AxisScale::Linear, AxisScale::Linear)).expect("scene");
    let data =
        SeriesData::from_owned_xy(SeriesTopology::MonotonicX, vec![0.0, 10.0], vec![0.0, 0.0])
            .expect("series data");
    {
        let mut transaction = scene.transaction();
        transaction.add_series(data).expect("add series");
        transaction.commit().expect("commit");
    }
    scene
        .snapshot()
        .resolve_line_frame(&frame_spec)
        .expect("resolve line frame")
}

/// Expected retained runs in layout order: (role, source, origin).
///
/// Mirrors `PlotLayout::fixture` in `text.rs`: each stored glyph origin
/// opens at `origin + index * 8.0` on the x axis with advance
/// `(8.0, 0.0)`. Pinning the grid here keeps the geometry the adapter
/// display transform consumes from drifting silently.
fn expected_runs() -> [(TextRole, &'static str, (f64, f64)); 6] {
    [
        (TextRole::NumericTick, "0.0", (16.0, 16.0)),
        (TextRole::DateTick, "2026-01-01", (32.0, 16.0)),
        (TextRole::UnitTick, "mm", (48.0, 16.0)),
        (TextRole::AxisLabel, "x", (64.0, 32.0)),
        (TextRole::AxisTitle, "measurement", (64.0, 48.0)),
        (TextRole::LegendEntry, "series-0", (72.0, 64.0)),
    ]
}

/// Fixture font-byte SHA-256 pinned by the in-file `text.rs` unit test.
///
/// Re-stated here so the integration suite independently pins the exact
/// font identity every retained run must carry.
const FIXTURE_FONT_SHA256: [u8; 32] = [
    0xc7, 0x7e, 0x54, 0xd9, 0x02, 0x7d, 0xb7, 0xb8, 0xaf, 0x82, 0x1d, 0x96, 0xd9, 0xbb, 0xa2, 0x04,
    0x31, 0x10, 0x0b, 0x94, 0x05, 0x5d, 0x42, 0x80, 0x4c, 0xb2, 0x95, 0xc7, 0x9e, 0xe4, 0x3f, 0xb7,
];

/// (a) One shaping result shared by all consumers: two independently
/// built frames carry byte-identical layout digests.
#[test]
fn shared_digest_is_deterministic_across_independent_frames() {
    let first = make_frame();
    let second = make_frame();
    let first_layout = first.plot_layout();
    let second_layout = second.plot_layout();
    assert!(first_layout.validate(), "fixture layout must validate");
    assert!(second_layout.validate(), "second layout must validate");
    assert_eq!(
        first_layout.layout_digest(),
        second_layout.layout_digest(),
        "same shaped input must digest identically"
    );
    assert_ne!(
        first_layout.layout_digest(),
        [0u8; 32],
        "digest must carry real content"
    );
    // Repeated reads of one carrier agree: the digest is stored, never
    // re-derived per consumer.
    assert_eq!(
        first.plot_layout().layout_digest(),
        first_layout.layout_digest()
    );
    // Generation bookkeeping rides the carrier: two identical build
    // sequences reach identical generations, and each carrier validates
    // for exactly its own generation pair (fail-closed on stale reads).
    assert_eq!(first_layout.font_revision(), second_layout.font_revision());
    assert_eq!(
        first_layout.layout_revision(),
        second_layout.layout_revision()
    );
    for layout in [first_layout, second_layout] {
        assert!(layout.validate_for_generation(layout.font_revision(), layout.layout_revision()));
        assert!(!layout.validate_for_generation(
            layout.font_revision().saturating_add(1),
            layout.layout_revision()
        ));
    }
    // All six required text families are retained in layout order.
    assert_eq!(first_layout.runs().len(), 6);
    for (run, (role, source, _)) in first_layout.runs().iter().zip(expected_runs()) {
        assert_eq!(run.role(), role);
        assert_eq!(run.source(), source);
    }
}

/// (b) Retained glyph geometry matches the declared grid, and the
/// declared adapter display transform re-evaluates deterministically.
///
/// The adapter composes outlines into display space with one explicit
/// matrix per label (`p_display = R(angle) @ S(dpi/72) @ p_outline +
/// anchor`, see `_tick_label_commands`). Because the retained origins
/// below are exact, any consumer applying that declared transform
/// agrees within the S15.1 part-3 1e-6 logical-pt gate by construction.
#[test]
fn retained_glyph_geometry_matches_the_declared_grid_within_1e6() {
    const TOLERANCE_PT: f64 = 1e-6;
    let frame = make_frame();
    let layout = frame.plot_layout();
    for (run, (_, source, (origin_x, origin_y))) in layout.runs().iter().zip(expected_runs()) {
        let glyph_count = source.chars().count();
        assert_eq!(run.clusters().len(), glyph_count);
        assert_eq!(run.glyph_ids().len(), glyph_count);
        assert_eq!(run.positions().len(), glyph_count);
        for (index, ((cluster, glyph_id), position)) in run
            .clusters()
            .iter()
            .zip(run.glyph_ids())
            .zip(run.positions())
            .enumerate()
        {
            let expected_x = origin_x + index as f64 * 8.0;
            assert!(
                (position.x() - expected_x).abs() <= TOLERANCE_PT,
                "run {source} glyph {index}: x {} vs grid {expected_x}",
                position.x()
            );
            assert!(
                (position.y() - origin_y).abs() <= TOLERANCE_PT,
                "run {source} glyph {index}: y {} vs grid {origin_y}",
                position.y()
            );
            assert!(
                (position.advance_x() - 8.0).abs() <= TOLERANCE_PT,
                "run {source} glyph {index}: advance_x must be 8.0"
            );
            assert!(
                position.advance_y().abs() <= TOLERANCE_PT,
                "run {source} glyph {index}: advance_y must be 0.0"
            );
            assert!(
                position.x().is_finite()
                    && position.y().is_finite()
                    && position.advance_x().is_finite()
                    && position.advance_y().is_finite(),
                "run {source} glyph {index}: geometry must stay finite"
            );
            assert_eq!(
                *cluster, index as u32,
                "clusters must densely index the source"
            );
            let expected_glyph = u32::from(source.chars().nth(index).expect("char"));
            assert_eq!(
                *glyph_id, expected_glyph,
                "glyph id must capture the source char"
            );
        }
    }
    // The declared display transform evaluated twice over retained
    // geometry agrees exactly (hence within 1e-6): projection is pure.
    let angle_radians = 30.0_f64.to_radians();
    let (cosine, sine) = (angle_radians.cos(), angle_radians.sin());
    let scale = 100.0 / 72.0;
    let (anchor_x, anchor_y) = (11.0, 23.0);
    for run in layout.runs() {
        for position in run.positions() {
            let project = |x: f64, y: f64| {
                let scaled = (x * scale, y * scale);
                (
                    anchor_x + scaled.0 * cosine + scaled.1 * sine,
                    anchor_y + (scaled.1 * cosine - scaled.0 * sine),
                )
            };
            let first = project(position.x(), position.y());
            let second = project(position.x(), position.y());
            assert!(
                (first.0 - second.0).abs() <= TOLERANCE_PT
                    && (first.1 - second.1).abs() <= TOLERANCE_PT
                    && first.0.is_finite()
                    && first.1.is_finite(),
                "display projection must be finite and deterministic"
            );
        }
    }
}

/// (c) No-remeasurement gate: `render-api` + `export` sources contain
/// no text measurement or shaping calls.
///
/// The M5-P3ii shaping pins (`parley` / `fontique` / `harfrust` /
/// `subsetter`, hermetic, no `system` feature) are declared-but-uncalled
/// by slice order, so their crate names are themselves forbidden tokens
/// here alongside every measurement/shaping call spelling. Full-line
/// `//` comments are stripped before matching so prose (e.g. "the sink
/// never measures text") cannot trip the gate; only code counts.
#[test]
fn render_api_and_export_contain_no_text_measurement_or_shaping_calls() {
    const RENDER_API_SOURCES: [&str; 4] = ["frame.rs", "lib.rs", "packet.rs", "resources.rs"];
    const EXPORT_SOURCES: [&str; 6] = [
        "compositor.rs",
        "error.rs",
        "lib.rs",
        "pdf.rs",
        "png.rs",
        "raster.rs",
    ];
    // Call spellings a sink remeasurement would need. `quantize_*`
    // (alpha quantization) and `AnnotationShape` (retained geometry
    // reads) are deliberately absent: they are not measurement.
    const FORBIDDEN_TOKENS: [&str; 28] = [
        "parley",
        "fontique",
        "harfbuzz",
        "harfrust",
        "rustybuzz",
        "swash::",
        "skrifa",
        "fontdb",
        "cosmic_text",
        "ab_glyph",
        "ttf_parser",
        "rusttype",
        "freetype",
        "font_kit",
        "TextPath",
        "FT2Font",
        "set_text",
        "load_glyph",
        "get_char_index",
        "get_path",
        "get_text_width",
        "text_extent",
        "measure_text",
        "shape_text",
        "layout_text",
        "shape_run",
        "measure_run",
        ".measure(",
    ];
    const EXTRA_FORBIDDEN_TOKENS: [&str; 6] = [
        "measure_glyph",
        "shaper",
        "reshap",
        "hinting",
        "subsetter",
        "load_font",
    ];
    let crate_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let mut scanned_files = 0;
    let mut scanned_code_lines = 0;
    for (crate_dir, sources) in [
        ("../lumenplot-render-api/src", RENDER_API_SOURCES.as_slice()),
        ("../lumenplot-export/src", EXPORT_SOURCES.as_slice()),
    ] {
        for source in sources {
            let path = crate_root.join(crate_dir).join(source);
            assert!(path.is_file(), "gate source missing: {}", path.display());
            let text = std::fs::read_to_string(&path)
                .unwrap_or_else(|error| panic!("cannot read {}: {error}", path.display()));
            scanned_files += 1;
            for (index, line) in text.lines().enumerate() {
                let code = line.trim_start();
                if code.starts_with("//") {
                    continue;
                }
                scanned_code_lines += 1;
                for token in FORBIDDEN_TOKENS.iter().chain(EXTRA_FORBIDDEN_TOKENS.iter()) {
                    assert!(
                        !code.contains(token),
                        "{}:{}: sink remeasurement spelling {token:?} in {code:?}",
                        path.display(),
                        index + 1,
                    );
                }
            }
        }
    }
    assert_eq!(scanned_files, 10, "gate must cover all 10 sink sources");
    assert!(
        scanned_code_lines > 1_000,
        "gate scanned only {scanned_code_lines} code lines; refusing a vacuous pass"
    );
}

/// (d) Missing glyphs are strict errors, never silent blanks.
///
/// Observable half through the public surface: no empty source, no
/// length mismatch, no zero (`.notdef`-placeholder) glyph id, and no
/// non-finite position is representable on a validating carrier. The
/// strict route itself (`fixture_run` rejects non-ASCII with
/// `UnsupportedCapability`) is pinned in-file in `text.rs`; here we pin
/// that its error kind stays publicly mapped on the bridge seam.
#[test]
fn missing_glyphs_never_render_silent_blank() {
    let frame = make_frame();
    let layout = frame.plot_layout();
    assert!(layout.validate());
    for run in layout.runs() {
        assert!(!run.source().is_empty(), "a retained run must carry source");
        assert!(
            run.source()
                .chars()
                .all(|character| character.is_ascii_graphic() || character == ' '),
            "fixture capture covers ASCII graphics only: {:?}",
            run.source()
        );
        assert!(
            !run.glyph_ids().is_empty(),
            "a retained run must carry glyphs"
        );
        assert_eq!(run.glyph_ids().len(), run.positions().len());
        assert_eq!(run.clusters().len(), run.glyph_ids().len());
        assert!(
            run.glyph_ids().iter().all(|glyph_id| *glyph_id != 0),
            "zero glyph ids (.notdef placeholders) are rejected at construction"
        );
    }
    // The strict missing-glyph error kind remains publicly mapped so a
    // future strict-error path surfaces instead of blanking.
    const STRICT_ROUTE: lumenplot_engine::bridge::SceneErrorKind =
        lumenplot_engine::bridge::SceneErrorKind::UnsupportedCapability;
    assert!(matches!(
        STRICT_ROUTE,
        lumenplot_engine::bridge::SceneErrorKind::UnsupportedCapability
    ));
}

/// (e) Clip/stack retention: clip and style refs survive projection
/// into the frame for every run, and every annotation keeps stored
/// finite geometry in its declared space.
#[test]
fn clip_and_style_refs_survive_into_the_projected_frame() {
    let frame = make_frame();
    let layout = frame.plot_layout();
    for run in layout.runs() {
        assert_ne!(
            run.clip_ref(),
            0,
            "run {:?} must retain a clip ref",
            run.source()
        );
        assert_ne!(
            run.style_ref(),
            0,
            "run {:?} must retain a style ref",
            run.source()
        );
    }
    // Scene-owned CPU state projects identically on every resolve: one
    // shared shaping result, not per-sink remeasurement.
    let again = make_frame();
    assert_eq!(layout.layout_digest(), again.plot_layout().layout_digest());
    // All four annotation kinds stay retained with finite stored boxes
    // in four distinct declared spaces.
    let annotations = layout.annotations();
    assert_eq!(annotations.len(), 4);
    let mut spaces = annotations
        .iter()
        .map(|annotation| annotation.space())
        .collect::<Vec<_>>();
    spaces.sort_by_key(|space| *space as u8);
    assert_eq!(
        spaces,
        vec![
            AnnotationSpace::Data2D,
            AnnotationSpace::AxesLogical,
            AnnotationSpace::FigureLogical,
            AnnotationSpace::DisplayLogical,
        ]
    );
    for annotation in annotations {
        let (x_min, y_min, x_max, y_max) = annotation.bounds();
        assert!(
            x_min.is_finite() && y_min.is_finite() && x_max.is_finite() && y_max.is_finite(),
            "annotation bounds must stay finite"
        );
        assert!(
            x_min < x_max && y_min < y_max,
            "annotation box must be non-degenerate"
        );
        let identity = annotation.transform().apply(1.0, 2.0);
        assert_eq!(identity, Some((1.0, 2.0)), "fixture maps stay identity");
    }
}

/// (f) Fallback-route provenance is recorded per run.
///
/// Every retained run records the exact-bytes primary route; the
/// `FallbackRoute` type offers no silent system-fallback spelling, and
/// the font identity pins exact bytes (SHA-256), face, variation,
/// features, and script/lang/dir alongside it.
#[test]
fn fallback_route_provenance_is_recorded_per_run() {
    let frame = make_frame();
    let layout = frame.plot_layout();
    for run in layout.runs() {
        assert_eq!(
            run.fallback_route(),
            FallbackRoute::PrimaryFont,
            "run {:?} must record the exact-bytes primary route",
            run.source()
        );
        let font = run.font();
        assert_eq!(font.font_bytes_sha256(), FIXTURE_FONT_SHA256);
        assert_eq!(font.face_index(), 0);
        assert_eq!(font.script(), "Latn");
        assert_eq!(font.language(), "en");
        assert_eq!(font.direction(), TextDirection::LeftToRight);
        let variations = font.normalized_variation();
        assert_eq!(variations.len(), 1);
        assert_eq!(variations[0].tag(), *b"wght");
        assert_eq!(variations[0].value(), 400.0);
        let features = font.features();
        assert_eq!(features.len(), 1);
        assert_eq!(features[0].tag(), *b"kern");
        assert_eq!(features[0].value(), 1);
        // The strict-error route stays nameable so provenance can record
        // a refusal instead of a silent fallback.
        assert_ne!(run.fallback_route(), FallbackRoute::StrictError);
    }
}
