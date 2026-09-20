//! M5-ANNOT Slices 1-5 PNG evidence through the public export bridge.
//!
//! Scope: ordinary-export behavior of the annotation mirror fallback.
//! Live Plot State cannot be staged through the public bridge
//! (annotation transactions stay `pub(crate)` by Slice-1 non-goal, kept by
//! Slices 2-5), so the empty-live-map branch is pinned here at the
//! encoded-PNG level:
//!
//! - (a) encoding is deterministic: two encodes of one frame are
//!   byte-identical;
//! - (b) the empty-page corner stays background: no hover, focus,
//!   selection, or drag chrome lands in an ordinary export;
//! - (c) retained annotation ink lands: the fixture rectangle outline
//!   strokes a covered pixel, the fixture text box fills its interior
//!   pixel, and the fixture line and arrow shafts stroke their pixels, so
//!   the sink path the live mirror feeds is proven to carry all four
//!   Slice-3 annotation inks into the export;
//! - (d) the line-shaft probe rides an `AxesLogical` entry, so the ink the
//!   Slice-4 mirror newly admits in that space is proven to land through
//!   the same sink path;
//! - (e) the arrow-shaft probe rides a `FigureLogical` entry and the
//!   rectangle-edge probe rides a `DisplayLogical` entry, so the ink the
//!   Slice-5 mirror newly admits in those spaces is proven to land through
//!   the same sink path.
//!
//! Pixel expectations reuse the mask probes pinned by the in-tree
//! `rasterize_annotations` unit tests on the same 160x140 page, except the
//! arrow probe: the mask probe (24, 16) sits under retained glyph cells at
//! the composed-PNG level, so the PNG arrow probe moves along the same
//! shaft to (12, 10), clear of every other ink source.

use std::io::Cursor;

use lumenplot_engine::bridge::{
    AnnotationSpace, AxisScale, AxisScales, LineFrame, LineFrameSpec, LineStyle, LogicalRect,
    LogicalSize, PlotScene, SeriesData, SeriesTopology, SrgbRgba8, Viewport,
};
use lumenplot_export::bridge::{PngSpec, encode_line_frame_png};

const BACKGROUND: [u8; 4] = [255, 255, 255, 255];

/// Resolve one frame on the 160x140 page the mask probes assume.
fn make_page_frame() -> LineFrame {
    let canvas = LogicalSize::new(160.0, 140.0).expect("canvas");
    let plot = LogicalRect::new(8.0, 8.0, 56.0, 56.0).expect("plot");
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
    let mut transaction = scene.transaction();
    transaction.add_series(data).expect("add series");
    transaction.commit().expect("commit");
    scene
        .snapshot()
        .resolve_line_frame(&frame_spec)
        .expect("frame")
}

/// Decode one encoded PNG into raw RGBA8 pixels.
fn decode_rgba8(bytes: &[u8]) -> (u32, u32, Vec<u8>) {
    let decoder = png::Decoder::new(Cursor::new(bytes));
    let mut reader = decoder.read_info().expect("PNG info");
    let mut pixels = vec![0u8; reader.output_buffer_size().expect("PNG buffer size")];
    let info = reader.next_frame(&mut pixels).expect("PNG frame");
    assert_eq!(info.color_type, png::ColorType::Rgba);
    assert_eq!(info.bit_depth, png::BitDepth::Eight);
    (info.width, info.height, pixels)
}

fn pixel_at(pixels: &[u8], width: u32, x: u32, y: u32) -> [u8; 4] {
    let offset = (u64::from(y) * u64::from(width) + u64::from(x)) as usize * 4;
    [
        pixels[offset],
        pixels[offset + 1],
        pixels[offset + 2],
        pixels[offset + 3],
    ]
}

/// (a) Double encode is byte-identical; (b) the far corner stays
/// background; (c) the fixture rectangle outline inks its edge pixel, the
/// fixture text box fills its interior pixel, and the fixture line and
/// arrow shafts ink their pixels.
#[test]
fn annotation_mirror_fallback_exports_deterministically_with_ink_and_clean_corner() {
    let frame = make_page_frame();
    // Empty live map: the fallback carries the fixture four.
    assert_eq!(frame.plot_layout().annotations().len(), 4);
    let spec = PngSpec::new(1.0).expect("spec");
    let first = encode_line_frame_png(&frame, &spec).expect("PNG");
    let second = encode_line_frame_png(&frame, &spec).expect("PNG");
    assert!(!first.is_empty(), "encoding must produce bytes");
    assert_eq!(first, second, "encoding must be deterministic");

    let (width, height, pixels) = decode_rgba8(&first);
    assert_eq!((width, height), (160, 140));
    // Far corner: clear of series ink, text cells, and every fixture
    // annotation box or shaft, so it must stay background.
    assert_eq!(pixel_at(&pixels, width, 159, 139), BACKGROUND);
    // Fixture rectangle top edge at logical (120, 100): outline ink lands.
    // The edge entry lives in the DisplayLogical space Slice-5 newly
    // mirrors, so this probe pins Slice-5 ink through the same sink path.
    assert_eq!(
        frame.plot_layout().annotations()[3].space(),
        AnnotationSpace::DisplayLogical,
        "rectangle-edge probe must ride the DisplayLogical entry"
    );
    assert_ne!(
        pixel_at(&pixels, width, 120, 100),
        BACKGROUND,
        "rectangle outline must ink its edge pixel"
    );
    // Fixture text box interior at logical (10, 20): the Data2D text box
    // (-2, 16)-(22, 24) fills through the existing fixture ink path, clear
    // of the series run (display y 56) and retained glyph cells (x >= 16).
    assert_ne!(
        pixel_at(&pixels, width, 10, 20),
        BACKGROUND,
        "text box must ink its interior pixel"
    );
    // Fixture line shaft from (0, 0) to (64, 32): the mask probe pixel
    // (8, 4) rides the shaft center, clear of the series run, glyph cells
    // (y >= 16), text fill, and rectangle ink. The shaft entry lives in
    // the AxesLogical space Slice-4 newly mirrors, so this probe pins
    // Slice-4 ink through the same sink path.
    assert_eq!(
        frame.plot_layout().annotations()[1].space(),
        AnnotationSpace::AxesLogical,
        "line-shaft probe must ride the AxesLogical entry"
    );
    assert_ne!(
        pixel_at(&pixels, width, 8, 4),
        BACKGROUND,
        "line shaft must ink its crossing pixel"
    );
    // Fixture arrow shaft from (8, 8) to (40, 24): (12, 10) rides the same
    // shaft, clear of the line shaft (y 6 there), glyph cells, text fill,
    // series run, and rectangle ink. The shaft entry lives in the
    // FigureLogical space Slice-5 newly mirrors, so this probe pins
    // Slice-5 ink through the same sink path.
    assert_eq!(
        frame.plot_layout().annotations()[2].space(),
        AnnotationSpace::FigureLogical,
        "arrow-shaft probe must ride the FigureLogical entry"
    );
    assert_ne!(
        pixel_at(&pixels, width, 12, 10),
        BACKGROUND,
        "arrow shaft must ink its crossing pixel"
    );
    // Rectangle interior carries fill from no pass (outline only): the
    // center stays free of annotation ink. The horizontal series runs at
    // display y 56, so (120, 110) is clear of every ink source.
    assert_eq!(pixel_at(&pixels, width, 120, 110), BACKGROUND);
}

/// Small page: every fixture annotation falls outside the 4x4 canvas, so
/// the annotation pass is a no-op and the top-left corner stays
/// background while encoding stays deterministic.
#[test]
fn small_page_corner_stays_background() {
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
    let mut transaction = scene.transaction();
    transaction.add_series(data).expect("add series");
    transaction.commit().expect("commit");
    let frame = scene
        .snapshot()
        .resolve_line_frame(&frame_spec)
        .expect("frame");
    let spec = PngSpec::new(1.0).expect("spec");
    let first = encode_line_frame_png(&frame, &spec).expect("PNG");
    let second = encode_line_frame_png(&frame, &spec).expect("PNG");
    assert_eq!(first, second, "encoding must be deterministic");
    let (width, height, pixels) = decode_rgba8(&first);
    assert_eq!((width, height), (4, 4));
    assert_eq!(pixel_at(&pixels, width, 0, 0), BACKGROUND);
}
