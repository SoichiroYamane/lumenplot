//! Window-driven validated offscreen frame through the M1 cadence seam.
//!
//! M4-PRESENT-1 slice (commander Option-A ruling 2026-09-20): the core stays
//! backend-neutral and headless-safe. [`present_offscreen`] drives the
//! existing runtime owner path (`begin_submission` plus the hidden
//! `submit_frame`) with the caller-supplied [`FramePacket`], consuming the
//! pending occlusion/timeout note exactly once per frame (no latch,
//! mirroring [`WindowApp::request_frame`]). [`present_surface`] stays an
//! explicit surface-transport stub: the real `Surface` configure/present body
//! is M4-PRESENT-2, so this slice returns a sanitized unavailable error whose
//! meaning delegates to the existing `present_unsupported` outcome.
//!
//! All items are `pub(crate)` or narrower; no new `pub` item appears at the
//! crate root. No new runtime/renderer signature is introduced. Pixel buffers
//! are never invented: without an attached renderer the owner path reports an
//! explicit unavailable error, and on success this slice reports the outcome
//! with no pixel return (`None` reserved for the M4-PRESENT-2 transport).

use lumenplot_render_api::FramePacket;
use lumenplot_render_wgpu::OffscreenFrame;
use lumenplot_runtime::{
    RuntimeErrorKind, SceneRevision, SkipReason, SubmissionOutcome, SurfaceCondition,
};

use super::{WindowApp, WindowError, WindowErrorKind, map_runtime_error};

/// Observable outcome of one window-driven validated offscreen attempt.
///
/// Maps the runtime [`SubmissionOutcome`] plus the render-owner
/// unavailable meaning one-to-one; no new success is invented.
#[cfg_attr(not(test), allow(dead_code))]
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub(crate) enum PresentOutcome {
    /// The owner accepted the validated submission for the active surface.
    Presented,
    /// The attempt was skipped (occlusion, timeout, suspension) without a
    /// busy retry loop.
    Skipped(SkipReason),
    /// Stale work was dropped without publication.
    StaleDropped,
    /// The surface present transport is unsupported in this slice.
    SurfaceUnavailable,
}

impl PresentOutcome {
    fn from_submission(outcome: SubmissionOutcome) -> Self {
        match outcome {
            SubmissionOutcome::Ready | SubmissionOutcome::Reconfigured => Self::Presented,
            SubmissionOutcome::Skipped(reason) => Self::Skipped(reason),
            SubmissionOutcome::StaleDropped => Self::StaleDropped,
            // `SubmissionOutcome` is non-exhaustive: an unknown future outcome
            // is conservatively reported as dropped without publication, never
            // as an accepted present.
            _ => Self::StaleDropped,
        }
    }
}

/// Drive one validated offscreen frame through the M1 cadence seam.
///
/// Consumes the pending occlusion/timeout note exactly once per call, then
/// issues a fresh owner token from the core monotonic revision and submits
/// `frame` through the hidden owner path. The pixel return stays `None` in
/// this slice: the owner path retains its validated pixels and this seam
/// reports only the outcome, never invented bytes. A missing backend surfaces
/// an explicit unavailable error.
#[cfg_attr(not(test), allow(dead_code))]
pub(crate) fn present_offscreen(
    app: &mut WindowApp,
    frame: &FramePacket,
) -> Result<(PresentOutcome, Option<OffscreenFrame>), WindowError> {
    app.ensure_open()?;
    let revision = SceneRevision::new(app.next_revision);
    let token = app
        .session
        .begin_submission(revision)
        .map_err(map_runtime_error)?;
    let condition = app.pending_condition;
    app.pending_condition = SurfaceCondition::Ready;
    match app
        .session
        .submit_frame(app.surface, frame.clone(), token, condition)
    {
        Ok(outcome) => {
            app.next_revision = app.next_revision.saturating_add(1).max(1);
            Ok((PresentOutcome::from_submission(outcome), None))
        }
        Err(error) if error.kind() == RuntimeErrorKind::UnsupportedCapability => {
            app.next_revision = app.next_revision.saturating_add(1).max(1);
            Ok((PresentOutcome::SurfaceUnavailable, None))
        }
        Err(error) => Err(map_runtime_error(error)),
    }
}

/// Explicit surface-present stub for this slice.
///
/// Always returns a sanitized unavailable error headlessly. The meaning
/// delegates to the existing render-owner `present_unsupported` outcome
/// (surface transport unsupported, never a silent offscreen fallback); the
/// real surface configure/present body belongs to M4-PRESENT-2.
#[cfg_attr(not(test), allow(dead_code))]
pub(crate) fn present_surface(_app: &WindowApp) -> WindowError {
    WindowError::new(
        WindowErrorKind::BackendUnavailable,
        "window surface present is unavailable",
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{CadenceEvent, EventApplied, WindowSize};

    const TEST_SIZE: WindowSize = match WindowSize::new(160, 120) {
        Ok(size) => size,
        Err(_) => panic!("test window size is invalid"),
    };

    fn oracle_frame() -> FramePacket {
        use lumenplot_render_api::__internal::{SrgbRgba8, Viewport};
        use lumenplot_render_api::{FrameSpec, SceneHandle};
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
            [160, 120],
            [16, 12, 144, 108],
            100.0,
            SrgbRgba8::new(31, 119, 180, 255),
            1.5,
            SrgbRgba8::new(255, 255, 255, 255),
        )
        .expect("oracle spec must be valid");
        scene
            .resolve_frame(&spec)
            .expect("oracle seam resolution must succeed")
    }

    #[test]
    fn present_maps_ready_and_reconfigured_to_presented() {
        assert_eq!(
            PresentOutcome::from_submission(SubmissionOutcome::Ready),
            PresentOutcome::Presented
        );
        assert_eq!(
            PresentOutcome::from_submission(SubmissionOutcome::Reconfigured),
            PresentOutcome::Presented
        );
        assert_eq!(
            PresentOutcome::from_submission(SubmissionOutcome::StaleDropped),
            PresentOutcome::StaleDropped
        );
    }

    #[test]
    fn present_offscreen_without_backend_is_explicit() {
        let mut app = WindowApp::new(TEST_SIZE).expect("core opens headlessly");
        let frame = oracle_frame();
        let error = present_offscreen(&mut app, &frame)
            .expect_err("state-only session must not validate a submission");
        assert_eq!(error.kind(), WindowErrorKind::BackendUnavailable);
    }

    #[test]
    fn present_offscreen_skips_occlusion_without_latching() {
        let mut app = WindowApp::new(TEST_SIZE).expect("core opens headlessly");
        let frame = oracle_frame();
        assert_eq!(
            app.handle_event(CadenceEvent::Occluded(true)),
            Ok(EventApplied::ConditionRecorded)
        );
        let (outcome, pixels) =
            present_offscreen(&mut app, &frame).expect("occluded attempt must resolve");
        assert_eq!(
            outcome,
            PresentOutcome::Skipped(SkipReason::Occluded),
            "occlusion must skip without a retry loop"
        );
        assert!(pixels.is_none(), "this slice never invents pixels");
        let next = present_offscreen(&mut app, &frame).expect_err("next frame needs a backend");
        assert_eq!(next.kind(), WindowErrorKind::BackendUnavailable);
    }

    #[test]
    fn present_surface_is_always_unavailable() {
        let app = WindowApp::new(TEST_SIZE).expect("core opens headlessly");
        let error = present_surface(&app);
        assert_eq!(error.kind(), WindowErrorKind::BackendUnavailable);
    }
}
