//! FBS-1 step-through-line-pipeline offscreen harness.
//!
//! Scope (commander authorization 2026-09-20 on `t_367aaa7b`, FBS-1):
//! test-only lane driving adapter-expanded step geometry (pre/post/mid,
//! including riser x-repeat) through the EXISTING entries
//! `Renderer::render` and hidden `Renderer::render_validated`. No new WGSL,
//! no manifest/shader/build edits, no `frame.rs`/`packet.rs` edits, no
//! tolerance/fixture/checker/requirement edits, no FBS-2 fill/bar/3D/
//! compositing scope.
//!
//! Step meaning stays adapter-side: `backend_support._expand_step_vertices`
//! plus `backend_preflight` expand sampled data to plain vertices before the
//! frame seam, and non-finite samples under a step drawstyle are explicit
//! `unsupported` (LP-FUNC-034/LP-MPL-020, no silent approximation). The engine
//! `Topology::MonotonicX` rejects only strict reversal, so step risers
//! (repeated-x) are admissible scene input. This harness therefore feeds
//! already-expanded finite-only polylines into the existing
//! `SceneHandle::add_series` seam and asserts they render as ordinary line
//! geometry. No renderer-owned step meaning exists or is added here.
//!
//! What runs where:
//!
//! - `step_expansion_matches_documented_adapter_semantics` and
//!   `step_risers_are_admissible_through_existing_seam` run on every host
//!   without a GPU and must pass. They prove the local expansion mirrors the
//!   documented adapter semantics (hand-derived vectors) and that riser
//!   x-repeat is accepted by the existing scene/packet seam (CPU-only,
//!   including `RenderPacketBuilder::build` plus `validate_for_owner`).
//! - `step_through_line_pipeline_covers_oracle_scales` needs a real portable
//!   adapter/device, so it is `#[ignore]`d by default: an unexecuted cell is
//!   reported as ignored (environment required), never as passed. Run it on
//!   the Lavapipe control cell or a real portable-GPU cell with
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
//! Background fill is record-only: every render exercises the existing
//! plot-background clear path (`LoadOp::Clear` from `frame.background()`)
//! via the oracle white background, but no background-pixel assertion is
//! made while tolerance stays OPEN. Polygon/`fill_between` fills, bar
//! rectangles, 3D fills, and compositing are deferred to FBS-2 pending the
//! packet-meaning architecture decision and are explicitly out of scope here.

use lumenplot_render_api::__internal::{
    DeviceGeneration, RenderPacketBuilder, SceneRevision, SrgbRgba8, Viewport, WorkGeneration,
};
use lumenplot_render_api::{FrameSpec, SceneHandle};
use lumenplot_render_wgpu::{RenderErrorKind, Renderer};

/// Semantic oracle scales for the M3 1x/1.25x/2x/3x matrix.
///
/// The base canvas is a multiple of four so the fractional 1.25x cell lands
/// on integer pixels without rounding policy drift. Duplicated locally so
/// this lane never edits the line-harness file (sibling-lane collision
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

/// Step drawstyle under test (adapter-side meaning, renderer sees plain vertices).
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum StepStyle {
    Pre,
    Post,
    Mid,
}

impl StepStyle {
    const ALL: [Self; 3] = [Self::Pre, Self::Post, Self::Mid];

    const fn label(self) -> &'static str {
        match self {
            Self::Pre => "steps-pre",
            Self::Post => "steps-post",
            Self::Mid => "steps-mid",
        }
    }
}

/// Mirrors `backend_support._expand_step_vertices` for `steps-pre`.
///
/// The `steps` alias maps to `steps-pre` adapter-side (`backend_preflight`
/// L2348-2352); the intermediate vertex holds the next y at the current x.
fn expand_steps_pre(xs: &[f64], ys: &[f64]) -> (Vec<f64>, Vec<f64>) {
    assert_eq!(xs.len(), ys.len(), "step input must be paired");
    assert!(!xs.is_empty(), "step input must be non-empty");
    let count = xs.len();
    let mut expanded_x = Vec::with_capacity(2 * count - 1);
    let mut expanded_y = Vec::with_capacity(2 * count - 1);
    for index in 0..count {
        expanded_x.push(xs[index]);
        expanded_y.push(ys[index]);
        if index == count - 1 {
            break;
        }
        expanded_x.push(xs[index]);
        expanded_y.push(ys[index + 1]);
    }
    (expanded_x, expanded_y)
}

/// Mirrors `backend_support._expand_step_vertices` for `steps-post`.
///
/// The intermediate vertex holds the current y at the next x.
fn expand_steps_post(xs: &[f64], ys: &[f64]) -> (Vec<f64>, Vec<f64>) {
    assert_eq!(xs.len(), ys.len(), "step input must be paired");
    assert!(!xs.is_empty(), "step input must be non-empty");
    let count = xs.len();
    let mut expanded_x = Vec::with_capacity(2 * count - 1);
    let mut expanded_y = Vec::with_capacity(2 * count - 1);
    for index in 0..count {
        expanded_x.push(xs[index]);
        expanded_y.push(ys[index]);
        if index == count - 1 {
            break;
        }
        expanded_x.push(xs[index + 1]);
        expanded_y.push(ys[index]);
    }
    (expanded_x, expanded_y)
}

/// Mirrors `backend_support._expand_step_vertices` for `steps-mid`.
///
/// Risers sit on interval midpoints; each midpoint appears twice (once per
/// adjacent y), producing the characteristic x-repeat.
fn expand_steps_mid(xs: &[f64], ys: &[f64]) -> (Vec<f64>, Vec<f64>) {
    assert_eq!(xs.len(), ys.len(), "step input must be paired");
    assert!(!xs.is_empty(), "step input must be non-empty");
    let count = xs.len();
    let mut expanded_x = Vec::with_capacity(2 * count);
    let mut expanded_y = Vec::with_capacity(2 * count);
    expanded_x.push(xs[0]);
    expanded_y.push(ys[0]);
    for index in 0..count - 1 {
        let midpoint = (xs[index] + xs[index + 1]) / 2.0;
        expanded_x.push(midpoint);
        expanded_y.push(ys[index]);
        expanded_x.push(midpoint);
        expanded_y.push(ys[index + 1]);
    }
    expanded_x.push(xs[count - 1]);
    expanded_y.push(ys[count - 1]);
    (expanded_x, expanded_y)
}

fn expand_step(style: StepStyle, xs: &[f64], ys: &[f64]) -> (Vec<f64>, Vec<f64>) {
    match style {
        StepStyle::Pre => expand_steps_pre(xs, ys),
        StepStyle::Post => expand_steps_post(xs, ys),
        StepStyle::Mid => expand_steps_mid(xs, ys),
    }
}

fn has_riser_x_repeat(xs: &[f64]) -> bool {
    xs.windows(2).any(|pair| pair[0] == pair[1])
}

fn assert_finite_pair(xs: &[f64], ys: &[f64], context: &str) {
    assert_eq!(
        xs.len(),
        ys.len(),
        "finite check needs paired input ({context})"
    );
    assert!(
        xs.iter().chain(ys.iter()).all(|value| value.is_finite()),
        "step fixtures stay finite-only per LP-FUNC-034 refusal rule ({context})"
    );
}

/// Hand-derived oracle for the documented adapter semantics.
///
/// Base samples `xs = [0.0, 0.5, 1.0]`, `ys = [0.2, 0.6, 0.4]` expand to:
/// - pre:  `[(0.0,0.2),(0.0,0.6),(0.5,0.6),(0.5,0.4),(1.0,0.4)]`
/// - post: `[(0.0,0.2),(0.5,0.2),(0.5,0.6),(1.0,0.6),(1.0,0.4)]`
/// - mid:  `[(0.0,0.2),(0.25,0.2),(0.25,0.6),(0.75,0.6),(0.75,0.4),(1.0,0.4)]`
#[test]
fn step_expansion_matches_documented_adapter_semantics() {
    let xs = [0.0, 0.5, 1.0];
    let ys = [0.2, 0.6, 0.4];

    let (pre_x, pre_y) = expand_steps_pre(&xs, &ys);
    assert_eq!(pre_x, vec![0.0, 0.0, 0.5, 0.5, 1.0]);
    assert_eq!(pre_y, vec![0.2, 0.6, 0.6, 0.4, 0.4]);

    let (post_x, post_y) = expand_steps_post(&xs, &ys);
    assert_eq!(post_x, vec![0.0, 0.5, 0.5, 1.0, 1.0]);
    assert_eq!(post_y, vec![0.2, 0.2, 0.6, 0.6, 0.4]);

    let (mid_x, mid_y) = expand_steps_mid(&xs, &ys);
    assert_eq!(mid_x, vec![0.0, 0.25, 0.25, 0.75, 0.75, 1.0]);
    assert_eq!(mid_y, vec![0.2, 0.2, 0.6, 0.6, 0.4, 0.4]);

    // Length contract mirrors the adapter: pre/post produce 2n-1 vertices,
    // mid produces 2n vertices for n >= 1 (here n = 3).
    assert_eq!(pre_x.len(), 2 * xs.len() - 1);
    assert_eq!(post_x.len(), 2 * xs.len() - 1);
    assert_eq!(mid_x.len(), 2 * xs.len());

    // Every style carries at least one riser x-repeat; that repeat is the
    // coverage this lane exists to prove admissible downstream.
    for (label, expanded) in [
        ("steps-pre", pre_x.as_slice()),
        ("steps-post", post_x.as_slice()),
        ("steps-mid", mid_x.as_slice()),
    ] {
        assert!(
            has_riser_x_repeat(expanded),
            "{label} expansion must carry a riser x-repeat"
        );
    }

    // Non-decreasing x (risers allowed, reversals forbidden) matches the
    // `Topology::MonotonicX` admission rule: only strict reversal rejects.
    for (label, expanded) in [
        ("steps-pre", pre_x.as_slice()),
        ("steps-post", post_x.as_slice()),
        ("steps-mid", mid_x.as_slice()),
    ] {
        for pair in expanded.windows(2) {
            assert!(
                pair[1] >= pair[0],
                "{label} expansion must stay non-decreasing in x"
            );
        }
    }
}

/// Step risers are admissible through the existing scene/packet seam.
///
/// CPU-only: each expanded step polyline (finite-only, with x-repeat) must
/// be accepted by `SceneHandle::add_series`, resolve to a frame, and build
/// plus revalidate as an owner packet without a GPU.
#[test]
fn step_risers_are_admissible_through_existing_seam() {
    let base_x = [0.0, 0.25, 0.5, 0.75, 1.0];
    let base_y = [0.1, 0.3, 0.5, 0.7, 0.9];
    for style in StepStyle::ALL {
        let (xs, ys) = expand_step(style, &base_x, &base_y);
        assert_finite_pair(&xs, &ys, style.label());
        assert!(
            has_riser_x_repeat(&xs),
            "{} fixture must carry a riser x-repeat",
            style.label()
        );
        let viewport =
            Viewport::from_bounds(0.0, 1.0, 0.0, 1.0).expect("step viewport must be valid");
        let mut scene = SceneHandle::new(viewport).expect("step scene must build");
        scene
            .add_series(xs.clone(), ys.clone())
            .unwrap_or_else(|_| {
                panic!(
                    "{} risers must be accepted (repeat-x, no reversal)",
                    style.label()
                )
            });
        let spec = FrameSpec::new(
            ORACLE_BASE_CANVAS,
            ORACLE_BASE_PLOT_RECT,
            ORACLE_DPI,
            SrgbRgba8::new(31, 119, 180, 255),
            ORACLE_BASE_LINE_WIDTH_PX,
            SrgbRgba8::new(255, 255, 255, 255),
        )
        .expect("step spec must be valid");
        let frame = scene
            .resolve_frame(&spec)
            .unwrap_or_else(|_| panic!("{} seam resolution must succeed", style.label()));
        let work = WorkGeneration::initial();
        let device = DeviceGeneration::initial();
        let packet = RenderPacketBuilder::new(work, device)
            .build(frame, work, device)
            .unwrap_or_else(|_| panic!("{} validated packet build must succeed", style.label()));
        packet
            .validate_for_owner(SceneRevision::initial(), work, device)
            .unwrap_or_else(|_| panic!("{} owner revalidation must succeed", style.label()));
    }
}

#[test]
#[ignore = "environment required: portable GPU adapter/device needed (Lavapipe control or real GPU cell); numeric pixel tolerance stays OPEN until Lavapipe numbers land"]
fn step_through_line_pipeline_covers_oracle_scales() {
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
        for style in StepStyle::ALL {
            let (scene, spec) = step_fixture(scale, style);
            let expected_canvas = oracle_canvas(scale);
            let work = WorkGeneration::initial();
            let device = DeviceGeneration::initial();
            let frame = scene.resolve_frame(&spec).unwrap_or_else(|_| {
                panic!("{} seam resolution must succeed at {scale}x", style.label())
            });

            // The renderer instance rejects a packet whose expected device
            // generation differs from its owner binding before target/buffer
            // allocation or visible publication.
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
                "instance-generation rejection must happen before retained allocation ({} at {scale}x)",
                style.label()
            );

            let builder = RenderPacketBuilder::new(work, device);
            let packet = builder
                .build(frame.clone(), work, device)
                .unwrap_or_else(|_| {
                    panic!(
                        "{} validated packet build must succeed at {scale}x",
                        style.label()
                    )
                });

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
                let error = rejected.expect_err(&format!(
                    "{label} generation must be rejected ({} at {scale}x)",
                    style.label()
                ));
                assert_eq!(
                    error.kind(),
                    RenderErrorKind::InvalidInput,
                    "{label} generation must map to InvalidInput"
                );
                assert_eq!(
                    renderer.resource_observations(),
                    observations_before_rejection,
                    "{label} rejection must not allocate or publish ({} at {scale}x)",
                    style.label()
                );
            }

            let frame_out = renderer
                .render_validated(&packet, SceneRevision::initial(), work, device)
                .unwrap_or_else(|_| {
                    panic!(
                        "{} validated step render must succeed at {scale}x",
                        style.label()
                    )
                });
            let warmed_allocations = renderer.resource_observations();
            assert!(warmed_allocations.target_allocations() > 0);
            assert!(warmed_allocations.vertex_buffer_allocations() > 0);
            assert!(warmed_allocations.readback_buffer_allocations() > 0);
            assert_eq!(
                frame_out.width(),
                expected_canvas[0],
                "{} width at {scale}x",
                style.label()
            );
            assert_eq!(
                frame_out.height(),
                expected_canvas[1],
                "{} height at {scale}x",
                style.label()
            );
            assert_eq!(
                frame_out.rgba8().len(),
                expected_canvas[0] as usize * expected_canvas[1] as usize * 4,
                "{} frame must be tightly packed RGBA8 at {scale}x",
                style.label()
            );

            // Same-size repeated submission must reuse the retained target,
            // vertex storage, and readback buffer. This is an app-level create
            // observation, not a driver allocation or performance claim.
            let repeated = renderer
                .render_validated(&packet, SceneRevision::initial(), work, device)
                .unwrap_or_else(|_| {
                    panic!(
                        "{} repeated validated render must succeed at {scale}x",
                        style.label()
                    )
                });
            assert_eq!(repeated.width(), frame_out.width());
            assert_eq!(repeated.height(), frame_out.height());
            assert_eq!(repeated.rgba8().len(), frame_out.rgba8().len());
            assert_eq!(
                renderer.resource_observations(),
                warmed_allocations,
                "same-size warm render must not recreate retained resources ({} at {scale}x)",
                style.label()
            );

            // Legacy public entry consumes the same step geometry as ordinary
            // line input. Dims/byte-length only; no pixel comparison while
            // tolerance stays OPEN. The background clear path (white oracle
            // background via `LoadOp::Clear`) is exercised record-only here.
            let legacy = renderer.render(&frame).unwrap_or_else(|_| {
                panic!("{} legacy render must succeed at {scale}x", style.label())
            });
            assert_eq!(
                legacy.width(),
                expected_canvas[0],
                "{} legacy width at {scale}x",
                style.label()
            );
            assert_eq!(
                legacy.height(),
                expected_canvas[1],
                "{} legacy height at {scale}x",
                style.label()
            );
            assert_eq!(
                legacy.rgba8().len(),
                expected_canvas[0] as usize * expected_canvas[1] as usize * 4,
                "{} legacy frame must be tightly packed RGBA8 at {scale}x",
                style.label()
            );
        }
    }
}

/// Builds the deterministic step oracle scene and spec for `scale`/`style`.
///
/// Canvas and plot rectangle scale geometrically from the base fixture; line
/// width and DPI stay fixed so each cell differs only in frame size. Base
/// samples stay in `[0, 1]` with finite values only (non-finite + step is
/// refused adapter-side); the expanded polyline carries riser x-repeat and
/// stays inside the canvas by construction. Background stays the oracle
/// white so the existing clear-path fill is exercised record-only.
fn step_fixture(scale: f64, style: StepStyle) -> (SceneHandle, FrameSpec) {
    let canvas = oracle_canvas(scale);
    let rect = oracle_plot_rect(scale);
    let viewport = Viewport::from_bounds(0.0, 1.0, 0.0, 1.0).expect("step viewport must be valid");
    let mut scene = SceneHandle::new(viewport).expect("step scene must build");
    let base_x = [0.0, 0.25, 0.5, 0.75, 1.0];
    let base_y = [0.1, 0.3, 0.5, 0.7, 0.9];
    let (xs, ys) = expand_step(style, &base_x, &base_y);
    debug_assert!(has_riser_x_repeat(&xs), "step fixture must carry risers");
    scene
        .add_series(xs, ys)
        .unwrap_or_else(|_| panic!("{} series must be accepted", style.label()));
    let spec = FrameSpec::new(
        canvas,
        rect,
        ORACLE_DPI,
        SrgbRgba8::new(31, 119, 180, 255),
        ORACLE_BASE_LINE_WIDTH_PX,
        SrgbRgba8::new(255, 255, 255, 255),
    )
    .expect("step spec must be valid");
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
