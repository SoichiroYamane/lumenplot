//! Private internal render boundary.
//!
//! The accepted M1 slice — the minimal synchronous, CPU-side frame seam —
//! lives in [`crate::frame`] and is re-exported below. The M2 renderer packet
//! projection remains hidden behind [`__internal`]: it is nameable only by the
//! workspace runtime/renderer owners and is not a public or persistent data
//! format.
//!
//! The internal packet boundary is intentionally not root-exported:
//!
//! ```compile_fail
//! use lumenplot_render_api::RenderPacket;
//! ```

mod frame;
mod packet;
#[allow(dead_code)]
mod resources;

pub use crate::frame::{
    FramePacket, FrameSeamError, FrameSeamErrorKind, FrameSpec, PacketPoint, PacketRevision,
    PacketSegment, PacketSeries, SceneHandle,
};

/// Hidden process-local handoff for renderer-owner integration.
///
/// This module is intentionally not re-exported at the crate root.  Its items
/// are nameable only through the doc-hidden path by workspace renderer/runtime
/// crates; they are not a public constructor, wire format, persistence format,
/// or serialization schema.
#[doc(hidden)]
pub mod __internal {
    pub use crate::frame::{
        Bounds3D, Line3DGeometry, Point3D, Projection3D, Semantic3D, SemanticFrame,
        Triangle3DGeometry, ViewFacts3D,
    };
    pub use crate::packet::{
        DeviceGeneration, LogicalResourceId, PacketValidationError, PacketValidationErrorKind,
        RenderPacket, RenderPacketBuilder, SceneRevision, WorkGeneration,
    };
    pub use crate::resources::{
        CompletionFence, ResourceCache, ResourceLease, ResourceLifecycleError,
        ResourceLifecycleErrorKind,
    };
    pub use lumenplot_engine::bridge::{
        AnnotationShape, AnnotationSpace, AnnotationTransform, RetainedAnnotation,
    };
    pub use lumenplot_engine::bridge::{
        FallbackRoute, FontFeature, FontIdentity, FontVariation, GlyphPosition, PlotLayout,
        ShapedRun, TextDirection, TextRole,
    };
    pub use lumenplot_engine::bridge::{SrgbRgba8, Viewport};
}
