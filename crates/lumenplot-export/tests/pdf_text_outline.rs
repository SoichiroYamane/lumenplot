//! M5-5B PDF retained-text outline emission acceptance (outline-only v1).
//!
//! Authority: the commander Q-MODE outline ruling on t_0d5a8e19 (outline is
//! the v1 mode; searchable text with font embedding/subsetting is deferred
//! post-v1) plus the bounded M5-5-B proposal. Scope: deterministic vector
//! outlines from the ONE retained `PlotLayout` (read via the public `runs()`
//! surface) in the private PDF sink; a stale retained result fails the sink
//! predicate and invalid input fails `InvalidInput` before allocation;
//! capacity preflight is extended within the existing ceilings.
//!
//! Explicitly OUT (asserted nowhere here and changed nowhere): searchable
//! text, font embedding/subsetting, annotation carriage in PDF, per-run
//! clip/style scopes, true space projections, bridge changes, public API,
//! fixtures, thresholds, checkers, requirements, and ADRs.
//!
//! Placement note: the PDF sink stays private — no bridge export, no public
//! API — so this test pulls `src/pdf.rs` and its sink-local dependencies
//! through `#[path]` includes, following the render-metal `compile_gate.rs`
//! precedent. Whatever is asserted here is the exact sink source. The
//! `#[cfg(test)]` unit modules ride along into this binary and run here too;
//! the allocation-failure forwarder below mirrors the crate root so those
//! modules resolve.
//!
//! Acceptance mapping (one test per item):
//! - (a) per-run outline path in bounds: every stored glyph origin of each of
//!   the 6 fixture runs lands as one filled vector cell inside the page, in
//!   layout order with byte-exact 6dp geometry;
//! - (b) byte-identical repeat: two encodes of one frame are identical and
//!   structurally framed;
//! - (c) stale layout predicate plus `InvalidInput` before output: bumped
//!   generations fail the sink predicate while the stamped generations plan
//!   cleanly, invalid DPI fails through the PDF entry, and forced allocation
//!   failure reports without partial output (corrupt digests are
//!   unfabricatable through the public constructors — every engine
//!   constructor validates — so the digest gate stands as defense-in-depth
//!   mirroring the raster plan gate, exactly like the PNG precedent);
//! - (d) EXPORT-006 negative pinned: with all 35 outline cells present, the
//!   file carries no raster image and no searchable-text operator.

#[path = "../src/compositor.rs"]
mod compositor;
#[path = "../src/error.rs"]
mod error;
#[path = "../src/pdf.rs"]
mod pdf;
#[path = "../src/png.rs"]
mod png;
#[path = "../src/raster.rs"]
mod raster;

/// Mirrors the crate-root allocation-failure fan-out so the included
/// `#[cfg(test)]` unit modules resolve `crate::set_allocation_failure_for_test`.
#[cfg(test)]
fn set_allocation_failure_for_test(fail: bool) {
    compositor::set_allocation_failure_for_test(fail);
    pdf::set_allocation_failure_for_test(fail);
    raster::set_allocation_failure_for_test(fail);
}

use error::ExportErrorKind;
use lumenplot_engine::bridge::{
    AxisScale, AxisScales, LineFrame, LineFrameSpec, LineStyle, LogicalRect, LogicalSize,
    PlotScene, SeriesData, SeriesTopology, SrgbRgba8, TextRole, Viewport,
};
use pdf::{PdfSpec, encode_line_frame_pdf};

const PAGE_WIDTH: f64 = 160.0;
const PAGE_HEIGHT: f64 = 140.0;
const GLYPH_WIDTH: f64 = 5.0;
const GLYPH_HEIGHT: f64 = 7.0;
const EXPECTED_SOURCES: [&str; 6] = ["0.0", "2026-01-01", "mm", "x", "measurement", "series-0"];
const EXPECTED_ORIGINS: [(f64, f64); 6] = [
    (16.0, 16.0),
    (32.0, 16.0),
    (48.0, 16.0),
    (64.0, 32.0),
    (64.0, 48.0),
    (72.0, 64.0),
];
const EXPECTED_GLYPH_COUNT: usize = 35;

/// Resolve one frame on the 160x140 page the outline probes assume, at 72
/// logical units per inch so logical units map 1:1 to PDF points.
fn make_text_frame() -> LineFrame {
    let canvas = LogicalSize::new(PAGE_WIDTH, PAGE_HEIGHT).expect("canvas");
    let plot = LogicalRect::new(8.0, 8.0, 56.0, 56.0).expect("plot");
    let style = LineStyle::new(SrgbRgba8::new(20, 40, 80, 255), 1.0).expect("style");
    let frame_spec = LineFrameSpec::new(
        canvas,
        plot,
        72.0,
        style,
        SrgbRgba8::new(255, 255, 255, 255),
    )
    .expect("frame spec");
    let view = Viewport::from_bounds(0.0, 10.0, 0.0, 10.0).expect("view");
    let mut scene =
        PlotScene::new(view, AxisScales::new(AxisScale::Linear, AxisScale::Linear)).expect("scene");
    let data =
        SeriesData::from_owned_xy(SeriesTopology::MonotonicX, vec![0.0, 10.0], vec![0.0, 0.0])
            .expect("series data");
    let mut transaction = scene.transaction();
    transaction.add_series(data).expect("add series");
    transaction.commit().expect("commit");
    scene
        .snapshot()
        .resolve_line_frame(&frame_spec)
        .expect("frame")
}

/// Borrow the single content stream of one encoded PDF as UTF-8.
fn content_stream(bytes: &[u8]) -> &str {
    let text = std::str::from_utf8(bytes).expect("PDF output is ASCII");
    let start = text.find("stream\n").expect("content stream") + "stream\n".len();
    let end = text[start..].find("\nendstream").expect("stream end") + start;
    &text[start..end]
}

/// (a) Every stored glyph origin of each of the 6 fixture runs lands as one
/// filled vector cell inside the page, in layout order with byte-exact
/// geometry derived independently from the public `runs()` surface.
#[test]
fn per_run_outline_cells_land_in_bounds_in_layout_order() {
    let frame = make_text_frame();
    let layout = frame.plot_layout();
    // ONE retained result shared by every sink.
    assert!(std::ptr::eq(layout, frame.plot_layout()));
    assert_eq!(layout.runs().len(), EXPECTED_SOURCES.len());
    let expected_roles = [
        TextRole::NumericTick,
        TextRole::DateTick,
        TextRole::UnitTick,
        TextRole::AxisLabel,
        TextRole::AxisTitle,
        TextRole::LegendEntry,
    ];
    for ((run, expected_source), expected_origin) in layout
        .runs()
        .iter()
        .zip(EXPECTED_SOURCES)
        .zip(EXPECTED_ORIGINS)
    {
        assert_eq!(run.source(), expected_source);
        assert_eq!(
            run.positions().len(),
            expected_source.chars().count(),
            "one stored origin per source character"
        );
        assert_eq!(
            (run.positions()[0].x(), run.positions()[0].y()),
            expected_origin
        );
    }
    for (run, expected_role) in layout.runs().iter().zip(expected_roles) {
        assert_eq!(run.role(), expected_role);
    }

    // Every stored cell sits inside the page in logical units (y-down).
    let mut glyph_count = 0usize;
    for run in layout.runs() {
        for position in run.positions() {
            assert!(position.x() >= 0.0, "cell left inside the page");
            assert!(position.y() >= 0.0, "cell top inside the page");
            assert!(
                position.x() + GLYPH_WIDTH <= PAGE_WIDTH,
                "cell right inside the page"
            );
            assert!(
                position.y() + GLYPH_HEIGHT <= PAGE_HEIGHT,
                "cell bottom inside the page"
            );
            glyph_count += 1;
        }
    }
    assert_eq!(glyph_count, EXPECTED_GLYPH_COUNT);

    let spec = PdfSpec::new(72.0).expect("PDF spec");
    let bytes = encode_line_frame_pdf(&frame, &spec).expect("PDF");
    let content = content_stream(&bytes);

    // Byte-exact expected cells in layout order (scale 1.0, PDF y-up flip).
    let mut expected = Vec::with_capacity(EXPECTED_GLYPH_COUNT);
    for run in layout.runs() {
        for position in run.positions() {
            expected.push(format!(
                "{:.6} {:.6} {:.6} {:.6} re\nf\n",
                position.x(),
                PAGE_HEIGHT - (position.y() + GLYPH_HEIGHT),
                GLYPH_WIDTH,
                GLYPH_HEIGHT,
            ));
        }
    }
    let ink_marker = "0.000000 0.000000 0.000000 rg\n";
    assert_eq!(
        content.matches(ink_marker).count(),
        1,
        "one fixed-ink text section"
    );
    let section = content
        .split(ink_marker)
        .nth(1)
        .expect("text section follows the ink setting");
    assert!(
        section.ends_with("Q\n"),
        "text section closes its graphics state"
    );
    let mut cursor = 0usize;
    for rect in &expected {
        let found = section[cursor..]
            .find(rect.as_str())
            .unwrap_or_else(|| panic!("outline cell missing in order: {rect:?}"));
        cursor += found + rect.len();
    }
    assert_eq!(
        section.matches(" re\n").count(),
        EXPECTED_GLYPH_COUNT,
        "no extra rects in the text section"
    );
}

/// (b) Two encodes of one frame are byte-identical and structurally framed.
#[test]
fn outline_pdf_is_byte_identical_across_repeats() {
    let frame = make_text_frame();
    let spec = PdfSpec::new(72.0).expect("PDF spec");
    let first = encode_line_frame_pdf(&frame, &spec).expect("PDF");
    let second = encode_line_frame_pdf(&frame, &spec).expect("PDF");
    assert!(!first.is_empty(), "encoding must produce bytes");
    assert_eq!(first, second, "encoding must be deterministic");
    assert!(first.starts_with(b"%PDF-1.4\n%LumenPlot\n"));
    assert!(first.ends_with(b"%%EOF\n"));
    let text = std::str::from_utf8(&first).expect("PDF output is ASCII");
    assert!(text.contains("/MediaBox [0 0 160.000000 140.000000]"));
    assert!(text.contains("/LPLogicalUnitsPerInch (72.000000)"));
    assert!(text.contains("/LPOutputDpi (72.000000)"));
    assert!(text.contains("/LPFormat (private-line-text-outline-v1)"));
}

/// (c) Bumped generations fail the sink predicate while the stamped
/// generations plan cleanly; invalid input fails before output and forced
/// allocation failure reports without partial output.
#[test]
fn stale_generations_fail_the_sink_predicate_and_invalid_input_fails_before_output() {
    let frame = make_text_frame();
    let layout = frame.plot_layout();
    assert!(layout.validate());
    assert!(layout.validate_for_generation(layout.font_revision(), layout.layout_revision()));
    assert!(!layout.validate_for_generation(
        layout.font_revision().saturating_add(1),
        layout.layout_revision()
    ));
    assert!(!layout.validate_for_generation(
        layout.font_revision(),
        layout.layout_revision().saturating_add(1)
    ));
    // The stamped generations plan cleanly through the PDF entry.
    let spec = PdfSpec::new(72.0).expect("PDF spec");
    encode_line_frame_pdf(&frame, &spec).expect("stamped layout encodes");

    // Invalid DPI is rejected before any output.
    for dpi in [0.0, -1.0, f64::NAN, f64::INFINITY] {
        assert_eq!(
            PdfSpec::new(dpi).expect_err("invalid DPI").kind(),
            ExportErrorKind::InvalidInput
        );
    }

    // Forced allocation failure reports without partial output.
    pdf::set_allocation_failure_for_test(true);
    let result = encode_line_frame_pdf(&frame, &spec);
    pdf::set_allocation_failure_for_test(false);
    assert_eq!(
        result.expect_err("allocation failure").kind(),
        ExportErrorKind::AllocationFailed
    );
}

/// (d) EXPORT-006 negative: with all 35 outline cells present, the file
/// carries no raster image and no searchable-text operator.
#[test]
fn export_006_no_raster_screenshot_no_searchable_text_with_outlines_present() {
    let frame = make_text_frame();
    let spec = PdfSpec::new(72.0).expect("PDF spec");
    let bytes = encode_line_frame_pdf(&frame, &spec).expect("PDF");
    let text = std::str::from_utf8(&bytes).expect("PDF output is ASCII");

    // Non-vacuous: background + plot clip + all 35 outline cells are present
    // as vector rects, and the fixed text ink is set.
    assert_eq!(
        text.matches(" re\n").count(),
        EXPECTED_GLYPH_COUNT + 2,
        "background, plot clip, and every outline cell"
    );
    assert_eq!(
        text.matches("\nf\n").count(),
        EXPECTED_GLYPH_COUNT + 1,
        "background and every outline cell filled"
    );
    assert!(text.contains("0.000000 0.000000 0.000000 rg\n"));

    // No raster image carriage anywhere in the file.
    for marker in ["/Subtype", "/Image", "/XObject", "FlateDecode", "DCTDecode"] {
        assert!(
            !text.contains(marker),
            "raster marker must be absent: {marker}"
        );
    }
    assert!(
        !bytes.windows(2).any(|window| window == b"BI"),
        "no inline-image operator"
    );

    // No searchable-text operators or font resources in the content stream.
    let content = content_stream(&bytes);
    let tokens: Vec<&str> = content.split_whitespace().collect();
    for operator in ["Tj", "TJ", "BT", "ET"] {
        assert!(
            !tokens.contains(&operator),
            "text operator must be absent: {operator}"
        );
    }
    for marker in ["/Font", "/ToUnicode", "ActualText"] {
        assert!(
            !content.contains(marker),
            "font carriage must be absent: {marker}"
        );
    }
}
