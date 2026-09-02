//! Private internal render boundary.
//!
//! The accepted M1 slice — the minimal synchronous, CPU-side frame seam —
//! lives in [`crate::frame`] and is re-exported below. The M2 renderer packet
//! projection remains private to this crate and is not a public or persistent
//! data format.
//!
//! The internal packet boundary is intentionally not root-exported:
//!
//! ```compile_fail
//! use lumenplot_render_api::RenderPacket;
//! ```

mod frame;
mod packet;

pub use crate::frame::{
    FramePacket, FrameSeamError, FrameSeamErrorKind, FrameSpec, PacketPoint, PacketRevision,
    PacketSegment, PacketSeries, SceneHandle,
};
