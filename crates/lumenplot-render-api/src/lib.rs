//! Private internal render boundary.
//!
//! The accepted M1 slice — the minimal synchronous, CPU-side frame seam —
//! lives in [`crate::frame`] and is re-exported below. Packet construction
//! beyond the line-frame path stays deferred to later phases.

mod frame;

pub use crate::frame::{
    FramePacket, FrameSeamError, FrameSeamErrorKind, FrameSpec, PacketPoint, PacketRevision,
    PacketSegment, PacketSeries, SceneHandle,
};
