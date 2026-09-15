//! M2-EXIT2-A Phase B owner-to-renderer integration harness.
//!
//! Scope (commander authorization 2026-09-15, Phase B follow-up comment):
//! env-gated integration over EXISTING seams only —
//! `EngineSession::with_renderer` + `begin_submission` / `submit` /
//! `submit_frame` (runtime `src/lib.rs`, `submit_frame` at L1148,
//! `#[doc(hidden)]`) driving the hidden M2 handoff
//! `Renderer::render_validated` (render-wgpu `src/lib.rs` L433,
//! `#[doc(hidden)]`). No new public API, no new signature, no renderer
//! injection seam (option (b) explicitly denied), no pixel comparison
//! (numeric GPU-vs-CPU/Agg tolerance stays OPEN), no upload rewiring
//! (`render` keeps consuming `packet.frame()`).
//!
//! What runs where:
//!
//! - `owner_submit_frame_without_backend_is_explicit` runs on every host
//!   without a GPU and must pass. It proves the owner prepare path reaches
//!   an explicit `BackendUnavailable` outcome on a state-only session
//!   instead of silently falling back or inventing a frame.
//! - The three `#[ignore]`d tests need a real portable adapter/device, so an
//!   unexecuted cell is reported as ignored (environment required), never
//!   as passed. Run them on the Lavapipe control cell or a real portable-GPU
//!   cell with `cargo test -p lumenplot-runtime -- --ignored`.
//!
//! Oracle scales mirror the render-wgpu validated-owner harness
//! (`offscreen_validated_owner.rs`): the 1x/1.25x/2x/3x matrix over a base
//! canvas that is a multiple of four so the fractional 1.25x cell lands on
//! integer pixels without rounding policy drift.

use lumenplot_render_api::__internal::{SrgbRgba8, Viewport};
use lumenplot_render_api::{FrameSpec, SceneHandle};
use lumenplot_render_wgpu::Renderer;
use lumenplot_runtime::{
    EngineSession, LoopMode, RuntimeErrorKind, SceneRevision, SubmissionOutcome, SurfaceCondition,
};

/// Semantic oracle scales for the M3 1x/1.25x/2x/3x matrix.
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

/// State-only owner path is explicit without a backend: prepare runs on the
/// CPU packet, then the missing renderer surfaces `BackendUnavailable`
/// instead of a silent fallback or an invented frame.
#[test]
fn owner_submit_frame_without_backend_is_explicit() {
    let mut session = EngineSession::new(LoopMode::NativeOwned);
    session
        .run_native_loop()
        .expect("native loop entry must succeed");
    let surface = session
        .create_surface(ORACLE_BASE_CANVAS)
        .expect("surface must be created");
    let (_, spec) = oracle_fixture(1.0);
    let scene = fresh_scene();
    let frame = scene
        .resolve_frame(&spec)
        .expect("oracle seam resolution must succeed");
    let token = session
        .begin_submission(SceneRevision::new(1))
        .expect("submission token must issue");
    let error = session
        .submit_frame(surface, frame, token, SurfaceCondition::Ready)
        .expect_err("state-only session must not validate a submission");
    assert_eq!(
        error.kind(),
        RuntimeErrorKind::BackendUnavailable,
        "missing portable backend must be an explicit outcome"
    );
}

/// Owner-to-renderer validated submission across the oracle scales.
///
/// Each cell drives `with_renderer` + loop entry + surface + begin/submit +
/// `submit_frame`, asserting the accepted `Ready` geometry and that a second
/// validated submission on a fresh token also succeeds (lease acquire +
/// all-or-nothing commit accounting advances without error). A stale older
/// token issued before a newer scene revision must drop without publication.
#[test]
#[ignore = "environment required: portable GPU adapter/device needed (Lavapipe control or real GPU cell); numeric pixel tolerance stays OPEN until Lavapipe numbers land"]
fn owner_to_renderer_validated_submission_covers_oracle_scales() {
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

        // A second validated submission on a fresh token for the same scene
        // revision exercises a second lease acquire + commit cycle.
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

        // An older scene token issued before a newer watermark must drop
        // without publication.
        let stale = session
            .begin_submission(SceneRevision::new(revision))
            .expect("stale-candidate token must issue");
        let _ = session
            .begin_submission(SceneRevision::new(revision + 100))
            .expect("newer watermark must issue");
        let dropped = session
            .submit_frame(surface, fresh_frame(*scale), stale, SurfaceCondition::Ready)
            .expect("stale submission must resolve to an outcome, not an error");
        assert_eq!(
            dropped,
            SubmissionOutcome::StaleDropped,
            "older scene token must drop without publication at {scale}x"
        );
    }
}

/// Stale scene/work/device triple rejection at the owner edge.
///
/// A pre-loss token carried across `handle_device_loss` +
/// `recover_device` (which advances both work and device generations) must
/// drop without publication once the session is running again.
#[test]
#[ignore = "environment required: portable GPU adapter/device needed (Lavapipe control or real GPU cell)"]
fn owner_stale_triple_is_rejected_without_publication() {
    let renderer = Renderer::new().expect(
        "environment required: portable GPU adapter/device unavailable on this host \
         (Lavapipe control or real GPU cell); this is not a renderer failure",
    );
    let mut session = EngineSession::with_renderer(LoopMode::NativeOwned, renderer);
    session
        .run_native_loop()
        .expect("native loop entry must succeed");
    let surface = session
        .create_surface(ORACLE_BASE_CANVAS)
        .expect("surface must be created");
    let pre_loss = session
        .begin_submission(SceneRevision::new(1))
        .expect("pre-loss token must issue");

    session
        .handle_device_loss()
        .expect("device loss must transition");
    session
        .recover_device()
        .expect("backend recovery must rebuild where a device exists");

    let dropped = session
        .submit_frame(surface, fresh_frame(1.0), pre_loss, SurfaceCondition::Ready)
        .expect("cross-generation submission must resolve to an outcome, not an error");
    assert_eq!(
        dropped,
        SubmissionOutcome::StaleDropped,
        "pre-loss work/device generations must drop without publication after recovery"
    );
}

/// Device-loss recovery rebuilds the validated path and resumes submission.
///
/// After `handle_device_loss`, submission reports `DeviceLost`; after
/// `recover_device` (which re-prepares the retained CPU frame and
/// revalidates it into the replacement renderer), the next validated
/// submission is accepted as `Reconfigured` because recovery marks surfaces
/// `ReconfigurePending`.
#[test]
#[ignore = "environment required: portable GPU adapter/device needed (Lavapipe control or real GPU cell)"]
fn owner_device_loss_rebuilds_and_resumes_validated_submission() {
    let renderer = Renderer::new().expect(
        "environment required: portable GPU adapter/device unavailable on this host \
         (Lavapipe control or real GPU cell); this is not a renderer failure",
    );
    let mut session = EngineSession::with_renderer(LoopMode::NativeOwned, renderer);
    session
        .run_native_loop()
        .expect("native loop entry must succeed");
    let surface = session
        .create_surface(ORACLE_BASE_CANVAS)
        .expect("surface must be created");
    let (scene, spec) = oracle_fixture(1.0);
    let frame = scene
        .resolve_frame(&spec)
        .expect("oracle seam resolution must succeed");
    let first = session
        .begin_submission(SceneRevision::new(1))
        .expect("first token must issue");
    assert_eq!(
        session
            .submit_frame(surface, frame, first, SurfaceCondition::Ready)
            .expect("initial validated submission must succeed"),
        SubmissionOutcome::Ready,
        "initial validated submission must be Ready"
    );

    session
        .handle_device_loss()
        .expect("device loss must transition");
    let during_loss = session.begin_submission(SceneRevision::new(2));
    assert!(
        during_loss.is_err(),
        "no token may issue while device recovery is pending"
    );

    session
        .recover_device()
        .expect("backend recovery must rebuild where a device exists");
    let after = session
        .begin_submission(SceneRevision::new(2))
        .expect("post-recovery token must issue");
    let resumed = session
        .submit_frame(surface, fresh_frame(1.0), after, SurfaceCondition::Ready)
        .expect("post-recovery validated submission must succeed");
    assert_eq!(
        resumed,
        SubmissionOutcome::Reconfigured,
        "post-recovery submission must apply the pending reconfigure"
    );
}

/// Builds the deterministic monotone-in-x oracle scene and spec for `scale`.
///
/// Canvas and plot rectangle scale geometrically from the base fixture; line
/// width and DPI stay fixed so each cell differs only in frame size. All
/// vertices stay inside the canvas by construction.
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

fn fresh_scene() -> SceneHandle {
    let viewport =
        Viewport::from_bounds(0.0, 1.0, 0.0, 1.0).expect("oracle viewport must be valid");
    let mut scene = SceneHandle::new(viewport).expect("oracle scene must build");
    fill_oracle_series(&mut scene);
    scene
}

fn fresh_frame(scale: f64) -> lumenplot_render_api::FramePacket {
    let (scene, spec) = oracle_fixture(scale);
    scene
        .resolve_frame(&spec)
        .expect("oracle seam resolution must succeed")
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
