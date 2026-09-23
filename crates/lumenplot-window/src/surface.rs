//! M4-PRESENT-2 private surface transport (standalone loop only).
//!
//! This module owns the real OS-surface configure/present body behind the
//! [`super::present::present_surface`] seam. The [`WindowApp`](super::WindowApp)
//! core stays backend-neutral and owns only the logical
//! [`SurfaceId`](lumenplot_runtime::SurfaceId); every concrete window/backend
//! surface object lives here and in [`WinitHost`](super::WinitHost), never in
//! the core. All items are `pub(crate)` or narrower; no new `pub` item appears
//! at the crate root.
//!
//! Behavior contract (architecture-authority M4-PRESENT-2 ruling):
//! - configure means creating the surface for the live window and applying
//!   the current window size; a later size change reconfigures before the
//!   next present (mirroring the runtime logical `resize` seam);
//! - present acquires one surface texture, clears it to the declared
//!   lifecycle color, submits, and presents exactly once per call (no retry
//!   loop, no latch);
//! - a genuinely unavailable adapter/device/surface reports
//!   [`WindowErrorKind::BackendUnavailable`](super::WindowErrorKind); real
//!   failures report [`WindowErrorKind::Internal`](super::WindowErrorKind)
//!   with a fixed sanitized message; there is never a silent offscreen
//!   fallback;
//! - validated scene pixels stay on the offscreen owner path
//!   ([`present_offscreen`](super::present::present_offscreen) plus the
//!   declared display cells); this body proves the OS configure/present loop
//!   with a lifecycle clear while the pixel-tolerance gate reads OPEN, so no
//!   pixel comparison or support/performance claim is made here.
//!
//! The portable backend is named through the renamed `surface-wgpu` edge so
//! this source never spells the backend crate name; the architecture checker
//! pins that exact edge fail-closed.

use std::future::Future;
use std::sync::Arc;

use super::{WindowError, WindowErrorKind};

/// Opaque lifecycle clear color (linear RGBA): opaque white matching the
/// declared oracle background. No scene content is encoded here.
const LIFECYCLE_CLEAR: surface_wgpu::Color = surface_wgpu::Color {
    r: 1.0,
    g: 1.0,
    b: 1.0,
    a: 1.0,
};

/// Outcome of one surface acquire/present attempt.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub(crate) enum SurfaceFrame {
    /// One texture was cleared, submitted, and presented.
    Presented,
    /// The compositor reported occlusion; the frame was skipped without a
    /// retry loop and may be re-attempted on the next redraw.
    OccludedSkipped,
    /// The bounded acquire wait expired; the frame was skipped without a
    /// retry loop and may be re-attempted on the next redraw.
    TimeoutSkipped,
}

/// Private OS-surface transport: configured surface plus its device/queue.
pub(crate) struct SurfaceTransport {
    surface: surface_wgpu::Surface<'static>,
    device: surface_wgpu::Device,
    queue: surface_wgpu::Queue,
    config: surface_wgpu::SurfaceConfiguration,
}

impl SurfaceTransport {
    /// Create and configure a surface for `window` at `width` x `height`.
    ///
    /// Requests a low-power portable adapter compatible with the new surface
    /// (Lavapipe control and the named-host cell both select their adapter
    /// through the ambient single-ICD loader route, never by forcing a
    /// fallback here) and a downlevel-defaults device, mirroring the
    /// offscreen renderer baseline. A missing adapter/device or an
    /// incompatible surface reports `BackendUnavailable`; any other failure
    /// reports `Internal`.
    pub(crate) fn create(
        window: Arc<winit::window::Window>,
        width: u32,
        height: u32,
    ) -> Result<Self, WindowError> {
        if width == 0 || height == 0 {
            return Err(WindowError::new(
                WindowErrorKind::InvalidInput,
                "window size must be nonzero",
            ));
        }
        let backends = surface_wgpu::Instance::enabled_backend_features();
        if backends.is_empty() {
            return Err(WindowError::new(
                WindowErrorKind::BackendUnavailable,
                "window backend is unavailable",
            ));
        }
        let instance = surface_wgpu::Instance::new(surface_wgpu::InstanceDescriptor {
            backends,
            ..surface_wgpu::InstanceDescriptor::new_without_display_handle()
        });
        let surface = instance.create_surface(window).map_err(|_| {
            WindowError::new(
                WindowErrorKind::BackendUnavailable,
                "window backend is unavailable",
            )
        })?;
        let adapter = block_on(
            instance.request_adapter(&surface_wgpu::RequestAdapterOptions {
                power_preference: surface_wgpu::PowerPreference::LowPower,
                force_fallback_adapter: false,
                compatible_surface: Some(&surface),
            }),
        )
        .map_err(|_| {
            WindowError::new(
                WindowErrorKind::BackendUnavailable,
                "window backend is unavailable",
            )
        })?;
        let capabilities = surface.get_capabilities(&adapter);
        let format = pick_format(&capabilities.formats).ok_or_else(|| {
            WindowError::new(
                WindowErrorKind::BackendUnavailable,
                "window backend is unavailable",
            )
        })?;
        let (device, queue) = block_on(adapter.request_device(&surface_wgpu::DeviceDescriptor {
            label: Some("lumenplot-window-surface-device"),
            required_features: surface_wgpu::Features::empty(),
            required_limits: surface_wgpu::Limits::downlevel_defaults(),
            ..Default::default()
        }))
        .map_err(|_| {
            WindowError::new(
                WindowErrorKind::BackendUnavailable,
                "window backend is unavailable",
            )
        })?;
        let config = surface_wgpu::SurfaceConfiguration {
            usage: surface_wgpu::TextureUsages::RENDER_ATTACHMENT,
            format,
            width,
            height,
            present_mode: pick_present_mode(&capabilities.present_modes),
            desired_maximum_frame_latency: 2,
            alpha_mode: surface_wgpu::CompositeAlphaMode::Auto,
            view_formats: Vec::new(),
        };
        surface.configure(&device, &config);
        Ok(Self {
            surface,
            device,
            queue,
            config,
        })
    }

    /// Configured surface format (reported once at configure as evidence;
    /// never compared while the tolerance gate reads OPEN).
    pub(crate) const fn format(&self) -> surface_wgpu::TextureFormat {
        self.config.format
    }

    /// Reconfigure the surface for `width` x `height` when it differs.
    ///
    /// A same-size call is a no-op so warmed presents never recreate their
    /// target; this is the physical analogue of the runtime logical `resize`
    /// seam. Zero sizes are rejected observably (a minimized window maps to
    /// a skip in the caller, never to a reconfigure here).
    pub(crate) fn ensure_size(&mut self, width: u32, height: u32) -> Result<(), WindowError> {
        if width == 0 || height == 0 {
            return Err(WindowError::new(
                WindowErrorKind::InvalidInput,
                "window size must be nonzero",
            ));
        }
        if self.config.width == width && self.config.height == height {
            return Ok(());
        }
        self.config.width = width;
        self.config.height = height;
        self.surface.configure(&self.device, &self.config);
        Ok(())
    }

    /// Reconfigure without changing the size (surface loss/outdated path).
    fn reconfigure(&self) {
        self.surface.configure(&self.device, &self.config);
    }

    /// Clear one surface texture to the lifecycle color and present it.
    ///
    /// Exactly one acquire is attempted per call. Loss/outdated reconfigures
    /// once and retries once; occlusion and timeout report a skip; any other
    /// failure reports `Internal`. No offscreen fallback is ever taken.
    pub(crate) fn present_clear(&mut self) -> Result<SurfaceFrame, WindowError> {
        match self.surface.get_current_texture() {
            surface_wgpu::CurrentSurfaceTexture::Success(texture)
            | surface_wgpu::CurrentSurfaceTexture::Suboptimal(texture) => {
                self.draw_and_present(texture);
                Ok(SurfaceFrame::Presented)
            }
            surface_wgpu::CurrentSurfaceTexture::Outdated
            | surface_wgpu::CurrentSurfaceTexture::Lost => {
                self.reconfigure();
                match self.surface.get_current_texture() {
                    surface_wgpu::CurrentSurfaceTexture::Success(texture)
                    | surface_wgpu::CurrentSurfaceTexture::Suboptimal(texture) => {
                        self.draw_and_present(texture);
                        Ok(SurfaceFrame::Presented)
                    }
                    surface_wgpu::CurrentSurfaceTexture::Occluded => {
                        Ok(SurfaceFrame::OccludedSkipped)
                    }
                    surface_wgpu::CurrentSurfaceTexture::Timeout => {
                        Ok(SurfaceFrame::TimeoutSkipped)
                    }
                    surface_wgpu::CurrentSurfaceTexture::Outdated
                    | surface_wgpu::CurrentSurfaceTexture::Lost
                    | surface_wgpu::CurrentSurfaceTexture::Validation => Err(WindowError::new(
                        WindowErrorKind::Internal,
                        "window operation failed",
                    )),
                }
            }
            surface_wgpu::CurrentSurfaceTexture::Occluded => Ok(SurfaceFrame::OccludedSkipped),
            surface_wgpu::CurrentSurfaceTexture::Timeout => Ok(SurfaceFrame::TimeoutSkipped),
            surface_wgpu::CurrentSurfaceTexture::Validation => Err(WindowError::new(
                WindowErrorKind::Internal,
                "window operation failed",
            )),
        }
    }

    /// Record one lifecycle clear into `texture`, submit, and present.
    fn draw_and_present(&mut self, texture: surface_wgpu::SurfaceTexture) {
        let view = texture
            .texture
            .create_view(&surface_wgpu::TextureViewDescriptor::default());
        let mut encoder =
            self.device
                .create_command_encoder(&surface_wgpu::CommandEncoderDescriptor {
                    label: Some("lumenplot-window-surface-clear"),
                });
        {
            let _pass = encoder.begin_render_pass(&surface_wgpu::RenderPassDescriptor {
                label: Some("lumenplot-window-surface-clear-pass"),
                color_attachments: &[Some(surface_wgpu::RenderPassColorAttachment {
                    view: &view,
                    depth_slice: None,
                    resolve_target: None,
                    ops: surface_wgpu::Operations {
                        load: surface_wgpu::LoadOp::Clear(LIFECYCLE_CLEAR),
                        store: surface_wgpu::StoreOp::Store,
                    },
                })],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
        }
        self.queue.submit(std::iter::once(encoder.finish()));
        texture.present();
    }
}

/// Prefer a deterministic 8-bit sRGB surface format.
///
/// Rgba8UnormSrgb first (matches the offscreen oracle byte order), then
/// Bgra8UnormSrgb, then whatever the adapter offers first. `None` means the
/// surface is incompatible with this adapter.
pub(crate) fn pick_format(
    formats: &[surface_wgpu::TextureFormat],
) -> Option<surface_wgpu::TextureFormat> {
    if formats.contains(&surface_wgpu::TextureFormat::Rgba8UnormSrgb) {
        return Some(surface_wgpu::TextureFormat::Rgba8UnormSrgb);
    }
    if formats.contains(&surface_wgpu::TextureFormat::Bgra8UnormSrgb) {
        return Some(surface_wgpu::TextureFormat::Bgra8UnormSrgb);
    }
    formats.first().copied()
}

/// Prefer vsync (`Fifo`, always available on a conformant surface) and take
/// whatever the surface offers first otherwise. Never invents tearing
/// behavior for the standalone loop.
pub(crate) fn pick_present_mode(modes: &[surface_wgpu::PresentMode]) -> surface_wgpu::PresentMode {
    if modes.contains(&surface_wgpu::PresentMode::Fifo) {
        return surface_wgpu::PresentMode::Fifo;
    }
    modes
        .first()
        .copied()
        .unwrap_or(surface_wgpu::PresentMode::Fifo)
}

/// Block on a backend future without adding an executor dependency.
///
/// Mirrors the offscreen renderer baseline: spin on a no-op waker with a
/// yield. Only used for the bounded adapter/device requests during surface
/// creation, never in the per-frame path.
fn block_on<F: Future>(future: F) -> F::Output {
    let mut future = std::pin::pin!(future);
    let waker = std::task::Waker::noop();
    let mut context = std::task::Context::from_waker(waker);
    loop {
        match future.as_mut().poll(&mut context) {
            std::task::Poll::Ready(value) => return value,
            std::task::Poll::Pending => std::thread::yield_now(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn format_prefers_oracle_byte_order_then_first() {
        assert_eq!(
            pick_format(&[
                surface_wgpu::TextureFormat::Bgra8UnormSrgb,
                surface_wgpu::TextureFormat::Rgba8UnormSrgb,
            ]),
            Some(surface_wgpu::TextureFormat::Rgba8UnormSrgb)
        );
        assert_eq!(
            pick_format(&[surface_wgpu::TextureFormat::Bgra8UnormSrgb]),
            Some(surface_wgpu::TextureFormat::Bgra8UnormSrgb)
        );
        assert_eq!(
            pick_format(&[surface_wgpu::TextureFormat::Rgba8Unorm]),
            Some(surface_wgpu::TextureFormat::Rgba8Unorm)
        );
        assert_eq!(pick_format(&[]), None);
    }

    #[test]
    fn present_mode_prefers_vsync_then_first() {
        assert_eq!(
            pick_present_mode(&[
                surface_wgpu::PresentMode::Immediate,
                surface_wgpu::PresentMode::Fifo,
            ]),
            surface_wgpu::PresentMode::Fifo
        );
        assert_eq!(
            pick_present_mode(&[surface_wgpu::PresentMode::Immediate]),
            surface_wgpu::PresentMode::Immediate
        );
        assert_eq!(pick_present_mode(&[]), surface_wgpu::PresentMode::Fifo);
    }
}
