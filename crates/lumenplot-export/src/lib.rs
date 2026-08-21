mod compositor;
mod error;
mod png;
mod raster;

#[cfg(test)]
pub(crate) fn set_allocation_failure_for_test(fail: bool) {
    compositor::set_allocation_failure_for_test(fail);
    raster::set_allocation_failure_for_test(fail);
}

#[doc(hidden)]
pub mod bridge {
    pub use crate::error::{ExportError, ExportErrorKind};
    pub use crate::png::{PngSpec, encode_line_frame_png};
}
