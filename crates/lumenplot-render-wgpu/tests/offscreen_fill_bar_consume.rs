//! M3-FB-CONSUME-B fill-bar consumer validated-submission harness.
//!
//! Scope (commander task `t_ed6fb430`, consumer lane): the render-wgpu
//! fill/bar consumer reads ONLY the existing renderer-visible projection
//! (`RenderPacket::semantic_frame().fill_bar()`), paints fills/bars in
//! `paint_order` beneath the line family (decision D4) with each edge
//! stroked immediately after its own fill (decision D5), and reuses the
//! existing `MAX_*` cap family (decision D6). No new WGSL module, no
//! manifest/shader/build edits, no `frame.rs`/`packet.rs` signature edits,
//! no public/wire/serde API, no `ResourceTable` growth, and no
//! tolerance/fixture/checker/requirement edits.
//!
//! What runs where:
//!
//! - `fill_bar_consumer_reports_explicit_capability_outcome` and
//!   `fill_bar_fixture_contract_is_additive_and_ordered` run on every
//!   host without a GPU and must pass. They prove renderer creation keeps
//!   its explicit capability outcome with the consumer present and that
//!   the additive carriage contract the consumer relies on holds
//!   (permutation order, inline paint, empty resolves to zero).
//! - `fill_bar_validated_submission_covers_oracle_scales` needs a real
//!   portable adapter/device, so it is `#[ignore]`d by default: an
//!   unexecuted cell is reported as ignored (environment required), never
//!   as passed. Run it on the Lavapipe control cell or a real portable-GPU
//!   cell with
//!   `cargo test -p lumenplot-render-wgpu --all-features -- --ignored`.
//!
//! Pixel tolerance: the numeric GPU-vs-CPU/Agg bound stays OPEN until the
//! Lavapipe control cell produces real numbers. This harness therefore
//! asserts validated-submission geometry only (dimensions, byte length,
//! stale-generation rejection before allocation, same-size resource reuse)
//! at 1x/1.25x/2x/3x, and performs no decoded-pixel comparison. Any pixel
//! threshold appearing here in the future must cite measured Lavapipe
//! numbers; fabricated bounds are not accepted.
//!
//! Fill-carrying packets are not buildable from this crate: the
//! `FramePacket` carriage stays `pub(crate)` with no new accessor, and
//! the absolute bar-rectangle constructor is not exported through the
//! renderer-visible boundary. On-device fill submission is therefore
//! covered by the `src` ignored submit test driving directly-constructed
//! fill meaning through the shared line pipeline; the ignored test below
//! proves the consumer dispatch preserves the validated line path on a
//! real device. End-to-end fill-carrying packet submission awaits the
//! authorized producer attach lane and is explicitly out of scope here.

use lumenplot_render_api::__internal::{
    DeviceGeneration, EdgeStyle, FillPolygon, PaintKey, RenderPacketBuilder, SceneRevision,
    SemanticFillBar, SrgbRgba8, Viewport, WorkGeneration,
};
use lumenplot_render_api::{FrameSpec, SceneHandle};
use lumenplot_render_wgpu::{RenderErrorKind, Renderer};

/// Semantic oracle scales for the M3 1x/1.25x/2x/3x matrix.
///
/// The base canvas is a multiple of four so the fractional 1.25x cell lands
/// on integer pixels without rounding policy drift. Duplicated locally so
/// this lane never edits a sibling harness file (sibling-lane collision
/// avoidance); values must stay in sync with `offscreen_validated_owner.rs`.
const ORACLE_SCALES: [f64; 4] = [1.0, 1.25, 2.0, 3.0];
const ORACLE_BASE_CANVAS: [u32; 2] = [160, 120];
const ORACLE_BASE_PLOT_RECT: [u32; 4] = [16, 12, 144, 108];
const ORACLE_BASE_LINE_WIDTH_PX: f64 = 1.5;
const ORACLE_DPI: f64 = 100.0;

/// Numeric pixel-tolerance status.
///
/// OPEN pending Lavapipe control-cell numbers. No pixel comparison is
/// performed while this reads OPEN; see the module docs.
const GPU_CPU_ORACLE_TOLERANCE_STATUS: &str = "OPEN: numeric GPU-vs-CPU/Agg bound pending Lavapipe control-cell measurement; no fabricated threshold";

#[test]
fn fill_bar_consumer_reports_explicit_capability_outcome() {
    // Portable, GPU-independent: creation either succeeds (a real adapter is
    // present) or fails with an explicit capability kind. The consumer lane
    // changes no creation contract: no silent fallback, no panic, no
    // invented frame.
    match Renderer::new() {
        Ok(_) => {}
        Err(error) => {
            assert!(
                matches!(
                    error.kind(),
                    RenderErrorKind::AdapterUnavailable
                        | RenderErrorKind::DeviceUnavailable
                        | RenderErrorKind::DeviceLost
                        | RenderErrorKind::OutOfMemory
                        | RenderErrorKind::ShaderInvalid
                        | RenderErrorKind::Internal
                ),
                "renderer creation must report an explicit capability outcome, got {:?}: {}",
                error.kind(),
                error.message()
            );
            assert!(
                !error.message().is_empty(),
                "explicit renderer errors carry a sanitized message"
            );
        }
    }
}

#[test]
fn fill_bar_fixture_contract_is_additive_and_ordered() {
    // The additive carriage contract the consumer relies on: one open
    // fill ring with inline paint plus an edge, ordered beneath the lines
    // by an exact permutation, with empty meaning resolving to zero.
    let band = FillPolygon::new(
        vec![
            lumenplot_render_api::PacketPoint::new(20.0, 20.0),
            lumenplot_render_api::PacketPoint::new(60.0, 20.0),
            lumenplot_render_api::PacketPoint::new(40.0, 60.0),
        ],
        SrgbRgba8::new(31, 119, 180, 128),
        Some(EdgeStyle::new(SrgbRgba8::new(31, 119, 180, 255), 1.0).expect("edge")),
    )
    .expect("band");
    assert_eq!(band.points().len(), 3);
    assert!(band.fill() == SrgbRgba8::new(31, 119, 180, 128));
    let edge = band.edge().expect("band edge");
    assert!(edge.color() == SrgbRgba8::new(31, 119, 180, 255));
    assert_eq!(edge.width_px(), 1.0);

    let second = FillPolygon::new(
        vec![
            lumenplot_render_api::PacketPoint::new(80.0, 20.0),
            lumenplot_render_api::PacketPoint::new(120.0, 20.0),
            lumenplot_render_api::PacketPoint::new(100.0, 60.0),
        ],
        SrgbRgba8::new(44, 160, 44, 255),
        None,
    )
    .expect("second");
    let semantic = SemanticFillBar::new(
        vec![band, second],
        Vec::new(),
        vec![PaintKey::fill(1), PaintKey::fill(0)],
    )
    .expect("permutation");
    assert_eq!(semantic.fills().len(), 2);
    assert!(semantic.bars().is_empty());
    assert_eq!(
        semantic.paint_order(),
        &[PaintKey::fill(1), PaintKey::fill(0)]
    );

    let empty = SemanticFillBar::new(Vec::new(), Vec::new(), Vec::new()).expect("empty");
    assert!(empty.fills().is_empty());
    assert!(empty.bars().is_empty());
    assert!(empty.paint_order().is_empty());
}

#[test]
#[ignore = "environment required: portable GPU adapter/device needed (Lavapipe control or real GPU cell); numeric pixel tolerance stays OPEN until Lavapipe numbers land"]
fn fill_bar_validated_submission_covers_oracle_scales() {
    assert_eq!(
        GPU_CPU_ORACLE_TOLERANCE_STATUS.as_bytes()[0],
        b'O',
        "tolerance gate must stay visibly OPEN (no numeric bound claimed)"
    );
    let mut renderer = Renderer::new().expect(
        "environment required: portable GPU adapter/device unavailable on this host \
         (Lavapipe control or real GPU cell); this is not a renderer failure",
    );
    renderer.bind_device_generation(DeviceGeneration::initial());

    for scale in ORACLE_SCALES {
        let (scene, spec) = oracle_fixture(scale);
        let expected_canvas = oracle_canvas(scale);
        let work = WorkGeneration::initial();
        let device = DeviceGeneration::initial();
        let frame = scene
            .resolve_frame(&spec)
            .expect("oracle seam resolution must succeed");

        // The renderer instance rejects a packet whose expected device
        // generation differs from its owner binding before target/buffer
        // allocation or visible publication. The consumer dispatch runs
        // after this gate, so fill/bar meaning can never bypass it.
        let stale_device = DeviceGeneration::new(1);
        let stale_packet = RenderPacketBuilder::new(work, stale_device)
            .build(frame.clone(), work, stale_device)
            .expect("stale packet construction must succeed before owner rejection");
        let observations_before_rejection = renderer.resource_observations();
        let stale_error = renderer
            .render_validated(&stale_packet, SceneRevision::initial(), work, stale_device)
            .expect_err("renderer instance must reject stale device generation");
        assert_eq!(stale_error.kind(), RenderErrorKind::InvalidInput);
        assert_eq!(
            renderer.resource_observations(),
            observations_before_rejection,
            "instance-generation rejection must happen before retained allocation"
        );

        let builder = RenderPacketBuilder::new(work, device);
        let packet = builder
            .build(frame, work, device)
            .expect("oracle validated packet build must succeed");

        // Caller-supplied stale scene/work values remain rejected by the
        // packet boundary without touching retained backend resources.
        for (label, scene_rev, work_gen, device_gen) in [
            ("stale scene", SceneRevision::new(u64::MAX), work, device),
            (
                "stale work",
                SceneRevision::initial(),
                WorkGeneration::new(u64::MAX),
                device,
            ),
        ] {
            let observations_before_rejection = renderer.resource_observations();
            let rejected = renderer.render_validated(&packet, scene_rev, work_gen, device_gen);
            let error = rejected.expect_err(&format!("{label} generation must be rejected"));
            assert_eq!(
                error.kind(),
                RenderErrorKind::InvalidInput,
                "{label} generation must map to InvalidInput"
            );
            assert_eq!(
                renderer.resource_observations(),
                observations_before_rejection,
                "{label} rejection must not allocate or publish"
            );
        }

        let frame = renderer
            .render_validated(&packet, SceneRevision::initial(), work, device)
            .expect("validated oracle render must succeed where a device exists");
        let warmed_allocations = renderer.resource_observations();
        assert!(warmed_allocations.target_allocations() > 0);
        assert!(warmed_allocations.vertex_buffer_allocations() > 0);
        assert!(warmed_allocations.readback_buffer_allocations() > 0);
        assert_eq!(
            frame.width(),
            expected_canvas[0],
            "oracle width at {scale}x"
        );
        assert_eq!(
            frame.height(),
            expected_canvas[1],
            "oracle height at {scale}x"
        );
        assert_eq!(
            frame.rgba8().len(),
            expected_canvas[0] as usize * expected_canvas[1] as usize * 4,
            "oracle frame must be tightly packed RGBA8 at {scale}x"
        );

        // Same-size repeated submission must reuse the retained target,
        // vertex storage, and readback buffer. This is an app-level create
        // observation, not a driver allocation or performance claim.
        let repeated = renderer
            .render_validated(&packet, SceneRevision::initial(), work, device)
            .expect("repeated validated render must succeed");
        assert_eq!(repeated.width(), frame.width());
        assert_eq!(repeated.height(), frame.height());
        assert_eq!(repeated.rgba8().len(), frame.rgba8().len());
        assert_eq!(
            renderer.resource_observations(),
            warmed_allocations,
            "same-size warm render must not recreate retained resources"
        );
    }
}

/// Builds the deterministic monotone-in-x oracle scene and spec for `scale`.
///
/// Duplicated locally so this lane never edits a sibling harness file;
/// values must stay in sync with `offscreen_validated_owner.rs`.
fn oracle_fixture(scale: f64) -> (SceneHandle, FrameSpec) {
    let canvas = oracle_canvas(scale);
    let rect = oracle_plot_rect(scale);
    let viewport =
        Viewport::from_bounds(0.0, 1.0, 0.0, 1.0).expect("oracle viewport must be valid");
    let mut scene = SceneHandle::new(viewport).expect("oracle scene must build");
    let points = 64usize;
    let mut xs = Vec::with_capacity(points);
    let mut ys = Vec::with_capacity(points);
    for index in 0..points {
        let t = index as f64 / (points - 1) as f64;
        xs.push(t);
        ys.push(0.1 + 0.8 * t);
    }
    scene
        .add_series(xs, ys)
        .expect("oracle series must be accepted");
    let spec = FrameSpec::new(
        canvas,
        rect,
        ORACLE_DPI,
        SrgbRgba8::new(31, 119, 180, 255),
        ORACLE_BASE_LINE_WIDTH_PX,
        SrgbRgba8::new(255, 255, 255, 255),
    )
    .expect("oracle spec must be valid");
    (scene, spec)
}

fn oracle_canvas(scale: f64) -> [u32; 2] {
    [
        scaled_pixel(ORACLE_BASE_CANVAS[0], scale),
        scaled_pixel(ORACLE_BASE_CANVAS[1], scale),
    ]
}

fn oracle_plot_rect(scale: f64) -> [u32; 4] {
    [
        scaled_pixel(ORACLE_BASE_PLOT_RECT[0], scale),
        scaled_pixel(ORACLE_BASE_PLOT_RECT[1], scale),
        scaled_pixel(ORACLE_BASE_PLOT_RECT[2], scale),
        scaled_pixel(ORACLE_BASE_PLOT_RECT[3], scale),
    ]
}

fn scaled_pixel(base: u32, scale: f64) -> u32 {
    (f64::from(base) * scale).round() as u32
}
