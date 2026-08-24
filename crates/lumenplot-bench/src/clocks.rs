//! Clock-domain observation for the O-08 benchmark protocol (decision D2).
//!
//! Four clock domains exist per the shared contract:
//!
//! 1. **scheduler** — CPU-monotonic wall span from event acceptance to the
//!    presentation call returning. Every scheduler-originated span name
//!    carries the mandatory `event_accept_to_` prefix.
//! 2. **gpu** — GPU-timestamp domain with its own time base. It is never
//!    merged into scheduler nanoseconds. This harness currently drives the
//!    accepted private PNG facade, which exposes no GPU timestamp queries,
//!    so this domain reports `available: false`.
//! 3. **queue** — completion/readback observations taken on the CPU
//!    monotonic clock with the `queue_` prefix. The facade surface exposes
//!    no distinct queue-completion or readback observation point, so this
//!    domain reports `available: false` instead of aliasing the scheduler
//!    domain under a second name.
//! 4. **scanout** — scanout markers when the platform exposes them;
//!    otherwise null. A `present()` return value is explicitly *not* a
//!    scanout observation.
//!
//! Missing instrumentation therefore yields null values and an
//! `inconclusive` status downstream; substituting zeros is forbidden by the
//! protocol. Cross-domain derived values must carry a `derived_` prefix and
//! stay excluded from gate statistics; none are emitted today.

use std::time::Instant;

/// Scheduler-domain span: accept the frame event until the present call
/// returns (the facade render call completing on the CPU).
pub(crate) const SCHEDULER_SPAN: &str = "event_accept_to_present_return";
/// GPU-timestamp-domain span (own time base; unavailable on this surface).
pub(crate) const GPU_SPAN: &str = "gpu_frame_timestamp_span";
/// Queue-domain span (CPU-monotonic completion/readback observation).
pub(crate) const QUEUE_SPAN: &str = "queue_completion_readback";
/// Scanout-domain marker (only when the platform exposes scanout feedback).
pub(crate) const SCANOUT_MARKER: &str = "scanout_present_marker";

/// Manifest description of one clock domain.
pub(crate) struct ClockDescriptor {
    pub(crate) name: &'static str,
    pub(crate) domain: &'static str,
    pub(crate) unit: &'static str,
    pub(crate) available: bool,
}

/// One frame's clock observations. Absent instrumentation is `None`, which
/// serializes as JSON `null` (never zero).
pub(crate) struct FrameClocks {
    pub(crate) scheduler_ns: Option<u64>,
}

/// Process-local clock board anchoring every CPU-monotonic observation.
pub(crate) struct ClockBoard {
    scheduler_available: bool,
}

impl ClockBoard {
    /// Detect the observable clock domains for this process.
    ///
    /// The CPU monotonic clock (`Instant`) is always available, so the
    /// scheduler domain activates. GPU timestamps, queue completion, and
    /// scanout markers require instrumentation the current facade surface
    /// does not expose and stay unavailable until that changes.
    pub(crate) fn detect() -> Self {
        Self {
            scheduler_available: true,
        }
    }

    /// Run one frame body and observe the scheduler-domain span around it.
    ///
    /// The returned nanosecond value measures acceptance (immediately before
    /// the frame body starts) through the present call returning; the frame
    /// result is handed back untouched so callers can keep work observable.
    pub(crate) fn observe_frame<F, T>(&self, frame: F) -> (FrameClocks, T)
    where
        F: FnOnce() -> T,
    {
        let accept = Instant::now();
        let produced = frame();
        let present_return = Instant::now();
        let elapsed = present_return.duration_since(accept);
        let scheduler_ns = self
            .scheduler_available
            .then(|| u64::try_from(elapsed.as_nanos()).unwrap_or(u64::MAX));
        (FrameClocks { scheduler_ns }, produced)
    }

    /// Manifest `clocks[]` inventory in the fixed D1 order.
    pub(crate) fn descriptors(&self) -> [ClockDescriptor; 4] {
        [
            ClockDescriptor {
                name: SCHEDULER_SPAN,
                domain: "scheduler",
                unit: "ns",
                available: self.scheduler_available,
            },
            ClockDescriptor {
                name: GPU_SPAN,
                domain: "gpu",
                unit: "ns",
                available: false,
            },
            ClockDescriptor {
                name: QUEUE_SPAN,
                domain: "queue",
                unit: "ns",
                available: false,
            },
            ClockDescriptor {
                name: SCANOUT_MARKER,
                domain: "scanout",
                unit: "ns",
                available: false,
            },
        ]
    }
}
