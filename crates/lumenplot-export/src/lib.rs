//! Private semantic-frame-to-output-sink boundary.
//!
//! M2 EXIT-1 wiring decision (explicit not-to-wire, recorded here so the skip
//! is never silent): the PNG path consumes the engine-resolved `LineFrame`,
//! not the render-api `SemanticFrame` or `RenderPacket` types. Rationale:
//! ADR 0004 requires export to consume the shared semantic/layout frame and
//! never reverse-engineer GPU buffers from a packet, so depending on the
//! packet type would invert renderer ownership; the crate DAG fixes the
//! export edge to the engine only and the static architecture checker fails
//! closed on any render-api edge including dev-dependencies, so naming those
//! types here needs an architecture-authority decision first; the shared
//! meaning is already wired at the engine seam because the render-api frame
//! candidate is projected from the same engine line frame with equal retained
//! layout (digest equality across independent consumers is pinned by
//! `independent_consumers_read_one_validated_semantic_frame` in
//! lumenplot-render-api). Wiring export to the packet type would add a
//! forbidden edge without changing the consumed meaning.
mod compositor;
mod error;
mod pdf;
mod png;
mod raster;

#[cfg(test)]
pub(crate) fn set_allocation_failure_for_test(fail: bool) {
    compositor::set_allocation_failure_for_test(fail);
    pdf::set_allocation_failure_for_test(fail);
    raster::set_allocation_failure_for_test(fail);
}

#[doc(hidden)]
pub mod bridge {
    pub use crate::error::{ExportError, ExportErrorKind};
    pub use crate::png::{PngSpec, encode_line_frame_png};
}
