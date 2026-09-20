//! M4-PRESENT-1 display-cell integration slice (environment-required).
//!
//! Declared cells (commander Phase-B authorization plus Option-A ruling):
//! (1) Lavapipe control first, (2) named host cell Linux/Wayland Radeon 780M
//! (`synix`). Every test here is `#[ignore]`: an unexecuted cell is reported
//! as ignored/environment-required, never as passed. No present claim is made
//! without a passing named cell. Real OS `Surface` present stays M4-PRESENT-2;
//! this slice asserts validated-submission geometry plus retained-resource
//! observations through the existing owner seams, with no decoded-pixel
//! comparison while the tolerance gate reads OPEN.

use lumenplot_render_api::__internal::{SrgbRgba8, Viewport};
use lumenplot_render_api::{FrameSpec, SceneHandle};
use lumenplot_render_wgpu::Renderer;
use lumenplot_runtime::{
    EngineSession, LoopMode, SceneRevision, SubmissionOutcome, SurfaceCondition,
};

/// Declared control cell: portable Lavapipe baseline (first).
const CELL_LAVAPIPE_CONTROL: &str = "Lavapipe control (portable baseline, first)";
/// Declared host cell: Linux/Wayland Radeon 780M (`synix`).
const CELL_NAMED_HOST: &str = "Linux/Wayland Radeon 780M (synix)";

/// Semantic oracle scales for the 1x/1.25x/2x/3x matrix.
const ORACLE_SCALES: [f64; 4] = [1.0, 1.25, 2.0, 3.0];
const ORACLE_BASE_CANVAS: [u32; 2] = [160, 120];
const ORACLE_BASE_PLOT_RECT: [u32; 4] = [16, 12, 144, 108];
const ORACLE_BASE_LINE_WIDTH_PX: f64 = 1.5;
const ORACLE_DPI: f64 = 100.0;

/// Numeric pixel-tolerance status.
///
/// OPEN pending Lavapipe control-cell numbers. No pixel comparison is
/// performed while this reads OPEN.
const GPU_CPU_ORACLE_TOLERANCE_STATUS: &str = "OPEN: numeric GPU-vs-CPU/Agg bound pending Lavapipe control-cell measurement; no fabricated threshold";

fn oracle_fixture(scale: f64) -> (SceneHandle, FrameSpec) {
    let canvas = oracle_canvas(scale);
    let rect = oracle_plot_rect(scale);
    let viewport =
        Viewport::from_bounds(0.0, 1.0, 0.0, 1.0).expect("oracle viewport must be valid");
    let mut scene = SceneHandle::new(viewport).expect("oracle scene must build");
    fill_oracle_series(&mut scene);
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

fn fill_oracle_series(scene: &mut SceneHandle) {
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
}

fn scaled_pixel(base: u32, scale: f64) -> u32 {
    (f64::from(base) * scale).round() as u32
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

/// Owner-to-renderer validated submission across the oracle scales.
///
/// Each cell drives `with_renderer` plus loop entry plus surface plus
/// begin/submit plus the hidden `submit_frame`, asserting the accepted
/// `Ready` geometry and that a second validated submission on a fresh token
/// also succeeds. A stale older token issued before a newer scene revision
/// must drop without publication.
#[test]
#[ignore = "environment required: portable GPU adapter/device needed (Lavapipe control or real GPU cell); numeric pixel tolerance stays OPEN until Lavapipe numbers land"]
fn present_display_validated_submission_covers_oracle_scales() {
    println!("declared cells: {CELL_LAVAPIPE_CONTROL} | {CELL_NAMED_HOST}");
    assert_eq!(
        GPU_CPU_ORACLE_TOLERANCE_STATUS.as_bytes()[0],
        b'O',
        "tolerance gate must stay visibly OPEN (no numeric bound claimed)"
    );
    for (index, scale) in ORACLE_SCALES.iter().enumerate() {
        let revision = index as u64 + 1;
        let renderer = Renderer::new().expect(
            "environment required: portable GPU adapter/device unavailable on this host \
             (Lavapipe control or real GPU cell); this is not a renderer failure",
        );
        let mut session = EngineSession::with_renderer(LoopMode::NativeOwned, renderer);
        session
            .run_native_loop()
            .expect("native loop entry must succeed");
        let canvas = oracle_canvas(*scale);
        let surface = session
            .create_surface(canvas)
            .expect("surface must be created");
        let (scene, spec) = oracle_fixture(*scale);
        let frame = scene
            .resolve_frame(&spec)
            .expect("oracle seam resolution must succeed");

        let token = session
            .begin_submission(SceneRevision::new(revision))
            .expect("submission token must issue");
        let outcome = session
            .submit_frame(surface, frame.clone(), token, SurfaceCondition::Ready)
            .expect("validated owner submission must succeed where a device exists");
        assert_eq!(
            outcome,
            SubmissionOutcome::Ready,
            "fresh validated submission must be Ready at {scale}x"
        );

        let second = session
            .begin_submission(SceneRevision::new(revision))
            .expect("second token must issue");
        let repeated = session
            .submit_frame(surface, frame, second, SurfaceCondition::Ready)
            .expect("repeated validated submission must succeed");
        assert_eq!(
            repeated,
            SubmissionOutcome::Ready,
            "repeated validated submission must stay Ready at {scale}x"
        );

        let stale = session
            .begin_submission(SceneRevision::new(revision))
            .expect("stale-candidate token must issue");
        let _ = session
            .begin_submission(SceneRevision::new(revision + 100))
            .expect("newer watermark must issue");
        let (fresh_scene, fresh_spec) = oracle_fixture(*scale);
        let fresh = fresh_scene
            .resolve_frame(&fresh_spec)
            .expect("oracle seam resolution must succeed");
        let dropped = session
            .submit_frame(surface, fresh, stale, SurfaceCondition::Ready)
            .expect("stale submission must resolve to an outcome, not an error");
        assert_eq!(
            dropped,
            SubmissionOutcome::StaleDropped,
            "older scene token must drop without publication at {scale}x"
        );
    }
}

/// Offscreen geometry plus retained-resource observations (no pixel compare).
///
/// Renders each oracle scale directly, asserting frame dimensions and byte
/// length plus that a same-size warmed render does not recreate its retained
/// target. Real OS surface present stays M4-PRESENT-2: in this slice the
/// passing headless outcome remains an explicit unavailable error (covered by
/// the crate-internal present stub units), never a silent fallback.
#[test]
#[ignore = "environment required: portable GPU adapter/device needed (Lavapipe control or real GPU cell)"]
fn present_display_offscreen_geometry_and_retained_resources() {
    println!("declared cells: {CELL_LAVAPIPE_CONTROL} | {CELL_NAMED_HOST}");
    assert_eq!(
        GPU_CPU_ORACLE_TOLERANCE_STATUS.as_bytes()[0],
        b'O',
        "tolerance gate must stay visibly OPEN (no numeric bound claimed)"
    );
    let mut renderer = Renderer::new().expect(
        "environment required: portable GPU adapter/device unavailable on this host \
         (Lavapipe control or real GPU cell); this is not a renderer failure",
    );
    for scale in ORACLE_SCALES {
        let (scene, spec) = oracle_fixture(scale);
        let frame = scene
            .resolve_frame(&spec)
            .expect("oracle seam resolution must succeed");
        let rendered = renderer
            .render(&frame)
            .expect("offscreen render must succeed where a device exists");
        let canvas = oracle_canvas(scale);
        assert_eq!(
            [rendered.width(), rendered.height()],
            canvas,
            "offscreen dims must match the oracle canvas at {scale}x"
        );
        assert_eq!(
            rendered.rgba8().len(),
            usize::try_from(canvas[0]).expect("width must fit")
                * usize::try_from(canvas[1]).expect("height must fit")
                * 4,
            "offscreen byte length must be tightly packed RGBA8 at {scale}x"
        );
        let before = renderer.resource_observations();
        let warmed = renderer.render(&frame).expect("warmed render must succeed");
        assert_eq!(
            [warmed.width(), warmed.height()],
            canvas,
            "warmed render must keep dims at {scale}x"
        );
        let after = renderer.resource_observations();
        assert_eq!(
            after.target_allocations(),
            before.target_allocations(),
            "same-size warmed render must not recreate its target at {scale}x"
        );
    }
}
