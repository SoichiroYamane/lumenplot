//! Portable offscreen renderer for the internal frame seam.
//!
//! This crate is the first concrete renderer edge. It consumes the backend-
//! neutral [`lumenplot_render_api::FramePacket`] and keeps all wgpu ownership
//! here, below the engine and render-api layers. The output is an owned RGBA8
//! image for headless consumers; no window or surface is needed for this slice.

mod shader;

use std::borrow::Cow;
use std::future::Future;
use std::marker::PhantomData;
use std::pin::pin;
use std::rc::Rc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, mpsc};
use std::thread::ThreadId;
use std::time::Duration;

use lumenplot_render_api::FramePacket;

pub use shader::ShaderProvenance;

const TARGET_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8UnormSrgb;
const UNIFORM_BYTES: usize = 32;
const BYTES_PER_VERTEX: usize = 16;
const MAX_PACKET_POINTS: usize = 1_000_000;
const MAX_PACKET_SEGMENTS: usize = 1_000_000;
const MAX_PACKET_SERIES: usize = 65_536;
const MAX_VERTEX_BYTES: usize = 128 * 1024 * 1024;
const READBACK_TIMEOUT: Duration = Duration::from_secs(10);

const VERTEX_ATTRIBUTES: [wgpu::VertexAttribute; 2] = wgpu::vertex_attr_array![
    0 => Float32x2,
    1 => Float32x2,
];
const VERTEX_LAYOUT: wgpu::VertexBufferLayout<'static> = wgpu::VertexBufferLayout {
    array_stride: BYTES_PER_VERTEX as wgpu::BufferAddress,
    step_mode: wgpu::VertexStepMode::Vertex,
    attributes: &VERTEX_ATTRIBUTES,
};

/// Failure categories at the portable renderer boundary.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
#[non_exhaustive]
pub enum RenderErrorKind {
    /// The frame contains malformed or non-finite values.
    InvalidInput,
    /// A checked renderer capacity would be exceeded.
    CapacityExceeded,
    /// No compiled backend can provide an offscreen adapter.
    AdapterUnavailable,
    /// The adapter could not create a device.
    DeviceUnavailable,
    /// The trusted static shader failed hash or validation checks.
    ShaderInvalid,
    /// The requested operation needs a surface, which this headless slice does not own.
    SurfaceUnavailable,
    /// A surface became unusable and must be recreated by a runtime owner.
    SurfaceLost,
    /// The device was lost and this renderer instance can no longer submit work.
    DeviceLost,
    /// The device or host allocation could not be satisfied.
    OutOfMemory,
    /// GPU readback did not complete successfully.
    ReadbackFailed,
    /// The renderer was used from a thread other than its owner.
    WrongThread,
    /// A validated renderer operation failed unexpectedly.
    Internal,
}

/// Sanitized error returned by the portable renderer.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RenderError {
    kind: RenderErrorKind,
    message: &'static str,
}

impl RenderError {
    const fn new(kind: RenderErrorKind, message: &'static str) -> Self {
        Self { kind, message }
    }

    /// Machine-readable failure category.
    pub const fn kind(self) -> RenderErrorKind {
        self.kind
    }

    /// Stable, sanitized description without backend payloads or input values.
    pub const fn message(self) -> &'static str {
        self.message
    }
}

impl std::fmt::Display for RenderError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.message)
    }
}

impl std::error::Error for RenderError {}

/// Owned top-left-origin RGBA8 pixels produced by the offscreen renderer.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OffscreenFrame {
    width: u32,
    height: u32,
    rgba8: Vec<u8>,
}

impl OffscreenFrame {
    /// Pixel width of the frame.
    pub const fn width(&self) -> u32 {
        self.width
    }

    /// Pixel height of the frame.
    pub const fn height(&self) -> u32 {
        self.height
    }

    /// Borrow the tightly packed top-left-origin RGBA8 pixels.
    pub fn rgba8(&self) -> &[u8] {
        &self.rgba8
    }

    /// Consume the frame and return tightly packed RGBA8 pixels.
    pub fn into_rgba8(self) -> Vec<u8> {
        self.rgba8
    }
}

/// Main-thread-owned portable offscreen renderer.
///
/// The renderer owns the wgpu device, queue, pipeline, uniform resource, and
/// device-loss observation. It intentionally carries a non-sendable marker so
/// concrete GPU resources cannot be moved to a worker thread by this API.
pub struct Renderer {
    device: wgpu::Device,
    queue: wgpu::Queue,
    pipeline: wgpu::RenderPipeline,
    uniform_buffer: wgpu::Buffer,
    uniform_bind_group: wgpu::BindGroup,
    owner_thread: ThreadId,
    device_lost: Arc<AtomicBool>,
    max_texture_dimension_2d: u32,
    max_buffer_size: u64,
    _main_thread_only: PhantomData<Rc<()>>,
}

impl Renderer {
    /// Creates an offscreen renderer through capability probing.
    ///
    /// No startup benchmark or runtime shader download is performed. If no
    /// compiled backend can provide a device, the explicit adapter/device
    /// error is returned instead of silently switching to a different sink.
    pub fn new() -> Result<Self, RenderError> {
        verify_line_shader_artifact()?;
        let backends = wgpu::Instance::enabled_backend_features();
        if backends.is_empty() {
            return Err(RenderError::new(
                RenderErrorKind::AdapterUnavailable,
                "no portable GPU backend is compiled",
            ));
        }

        let instance = wgpu::Instance::new(wgpu::InstanceDescriptor {
            backends,
            ..wgpu::InstanceDescriptor::new_without_display_handle()
        });
        let adapter = block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::LowPower,
            force_fallback_adapter: false,
            compatible_surface: None,
        }))
        .map_err(|_| {
            RenderError::new(
                RenderErrorKind::AdapterUnavailable,
                "portable GPU adapter is unavailable",
            )
        })?;

        let (device, queue) = block_on(adapter.request_device(&wgpu::DeviceDescriptor {
            label: Some("lumenplot-portable-offscreen-device"),
            required_features: wgpu::Features::empty(),
            required_limits: wgpu::Limits::downlevel_defaults(),
            ..Default::default()
        }))
        .map_err(|_| {
            RenderError::new(
                RenderErrorKind::DeviceUnavailable,
                "portable GPU device could not be created",
            )
        })?;

        let device_lost = Arc::new(AtomicBool::new(false));
        let device_lost_callback = Arc::clone(&device_lost);
        device.set_device_lost_callback(move |_, _| {
            device_lost_callback.store(true, Ordering::Release);
        });

        let resources = create_gpu_resources(&device)?;
        if device_lost.load(Ordering::Acquire) {
            return Err(RenderError::new(
                RenderErrorKind::DeviceLost,
                "portable GPU device was lost during initialization",
            ));
        }

        let limits = device.limits();
        Ok(Self {
            device,
            queue,
            pipeline: resources.pipeline,
            uniform_buffer: resources.uniform_buffer,
            uniform_bind_group: resources.uniform_bind_group,
            owner_thread: std::thread::current().id(),
            device_lost,
            max_texture_dimension_2d: limits.max_texture_dimension_2d,
            max_buffer_size: limits.max_buffer_size,
            _main_thread_only: PhantomData,
        })
    }

    /// Renders one validated frame to an owned tightly packed RGBA8 image.
    ///
    /// The frame is expanded into triangles in screen space. A scissor region
    /// enforces the packet plot rectangle, while the static fragment shader
    /// computes analytic edge coverage. Device loss, readback failure, and
    /// out-of-memory are returned explicitly.
    pub fn render(&mut self, frame: &FramePacket) -> Result<OffscreenFrame, RenderError> {
        self.ensure_owner()?;
        if self.device_lost.load(Ordering::Acquire) {
            return Err(RenderError::new(
                RenderErrorKind::DeviceLost,
                "portable GPU device is lost",
            ));
        }

        let prepared = prepare_frame(frame, self.max_texture_dimension_2d)?;
        if u64::try_from(prepared.vertices.len()).unwrap_or(u64::MAX) > self.max_buffer_size
            || u64::try_from(prepared.readback_bytes).unwrap_or(u64::MAX) > self.max_buffer_size
        {
            return Err(RenderError::new(
                RenderErrorKind::CapacityExceeded,
                "frame buffers exceed the device capacity",
            ));
        }

        // Error scopes keep backend resource failures explicit. The input and
        // descriptor checks above make validation failures programming/data
        // errors, not a silent fallback opportunity.
        let validation_scope = self.device.push_error_scope(wgpu::ErrorFilter::Validation);
        let oom_scope = self.device.push_error_scope(wgpu::ErrorFilter::OutOfMemory);
        let result = self.render_prepared(prepared);
        let oom_error = block_on(oom_scope.pop());
        let validation_error = block_on(validation_scope.pop());
        if is_out_of_memory(oom_error) {
            return Err(RenderError::new(
                RenderErrorKind::OutOfMemory,
                "portable GPU operation ran out of memory",
            ));
        }
        if validation_error.is_some() {
            return Err(RenderError::new(
                RenderErrorKind::Internal,
                "portable GPU operation failed validation",
            ));
        }
        result
    }

    fn ensure_owner(&self) -> Result<(), RenderError> {
        if std::thread::current().id() != self.owner_thread {
            Err(RenderError::new(
                RenderErrorKind::WrongThread,
                "portable renderer must be used on its owner thread",
            ))
        } else {
            Ok(())
        }
    }

    fn render_prepared(&mut self, prepared: PreparedFrame) -> Result<OffscreenFrame, RenderError> {
        self.queue
            .write_buffer(&self.uniform_buffer, 0, &prepared.uniform_bytes);

        let texture = self.device.create_texture(&wgpu::TextureDescriptor {
            label: Some("lumenplot-offscreen-color"),
            size: wgpu::Extent3d {
                width: prepared.width,
                height: prepared.height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: TARGET_FORMAT,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let texture_view = texture.create_view(&wgpu::TextureViewDescriptor::default());

        let vertex_buffer = if prepared.vertices.is_empty() {
            None
        } else {
            let buffer = self.device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("lumenplot-offscreen-line-vertices"),
                size: u64::try_from(prepared.vertices.len()).map_err(|_| {
                    RenderError::new(
                        RenderErrorKind::CapacityExceeded,
                        "line vertex buffer size is not representable",
                    )
                })?,
                usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::VERTEX,
                mapped_at_creation: false,
            });
            self.queue.write_buffer(&buffer, 0, &prepared.vertices);
            Some(buffer)
        };

        let readback = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("lumenplot-offscreen-readback"),
            size: u64::try_from(prepared.readback_bytes).map_err(|_| {
                RenderError::new(
                    RenderErrorKind::CapacityExceeded,
                    "readback buffer size is not representable",
                )
            })?,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });

        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("lumenplot-offscreen-encoder"),
            });
        {
            let color_attachment = Some(wgpu::RenderPassColorAttachment {
                view: &texture_view,
                depth_slice: None,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(prepared.clear_color),
                    store: wgpu::StoreOp::Store,
                },
            });
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("lumenplot-offscreen-line-pass"),
                color_attachments: &[color_attachment],
                depth_stencil_attachment: None,
                timestamp_writes: None,
                occlusion_query_set: None,
                multiview_mask: None,
            });
            pass.set_scissor_rect(
                prepared.scissor.x,
                prepared.scissor.y,
                prepared.scissor.width,
                prepared.scissor.height,
            );
            if let Some(vertex_buffer) = &vertex_buffer {
                pass.set_pipeline(&self.pipeline);
                pass.set_bind_group(0, &self.uniform_bind_group, &[]);
                pass.set_vertex_buffer(0, vertex_buffer.slice(..));
                pass.draw(0..prepared.vertex_count, 0..1);
            }
        }
        encoder.copy_texture_to_buffer(
            wgpu::TexelCopyTextureInfo {
                texture: &texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::TexelCopyBufferInfo {
                buffer: &readback,
                layout: wgpu::TexelCopyBufferLayout {
                    offset: 0,
                    bytes_per_row: Some(prepared.row_pitch),
                    rows_per_image: Some(prepared.height),
                },
            },
            wgpu::Extent3d {
                width: prepared.width,
                height: prepared.height,
                depth_or_array_layers: 1,
            },
        );
        self.queue.submit(std::iter::once(encoder.finish()));

        let (sender, receiver) = mpsc::channel();
        readback
            .slice(..)
            .map_async(wgpu::MapMode::Read, move |result| {
                let _ = sender.send(result.is_ok());
            });
        if self
            .device
            .poll(wgpu::PollType::Wait {
                submission_index: None,
                timeout: Some(READBACK_TIMEOUT),
            })
            .is_err()
        {
            return Err(RenderError::new(
                RenderErrorKind::ReadbackFailed,
                "portable GPU readback timed out",
            ));
        }
        if self.device_lost.load(Ordering::Acquire) {
            return Err(RenderError::new(
                RenderErrorKind::DeviceLost,
                "portable GPU device was lost during rendering",
            ));
        }
        if receiver
            .recv_timeout(READBACK_TIMEOUT)
            .ok()
            .filter(|completed| *completed)
            .is_none()
        {
            return Err(RenderError::new(
                RenderErrorKind::ReadbackFailed,
                "portable GPU readback failed",
            ));
        }

        let mut rgba8 = Vec::new();
        rgba8.try_reserve_exact(prepared.tight_bytes).map_err(|_| {
            RenderError::new(
                RenderErrorKind::OutOfMemory,
                "host readback allocation failed",
            )
        })?;
        rgba8.resize(prepared.tight_bytes, 0);
        {
            let mapped = readback.slice(..).get_mapped_range();
            for row in 0..prepared.height as usize {
                let source_start = row * prepared.row_pitch as usize;
                let source_end = source_start + prepared.tight_row_bytes;
                let destination_start = row * prepared.tight_row_bytes;
                rgba8[destination_start..destination_start + prepared.tight_row_bytes]
                    .copy_from_slice(&mapped[source_start..source_end]);
            }
        }
        readback.unmap();
        Ok(OffscreenFrame {
            width: prepared.width,
            height: prepared.height,
            rgba8,
        })
    }
}

struct GpuResources {
    pipeline: wgpu::RenderPipeline,
    uniform_buffer: wgpu::Buffer,
    uniform_bind_group: wgpu::BindGroup,
}

fn create_gpu_resources(device: &wgpu::Device) -> Result<GpuResources, RenderError> {
    let shader_scope = device.push_error_scope(wgpu::ErrorFilter::Validation);
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("lumenplot-line-wgsl-v1"),
        source: wgpu::ShaderSource::Wgsl(Cow::Borrowed(shader::LINE_SHADER_SOURCE)),
    });
    let shader_error = block_on(shader_scope.pop());
    if shader_error.is_some() {
        return Err(RenderError::new(
            RenderErrorKind::ShaderInvalid,
            "static line shader failed validation",
        ));
    }

    let validation_scope = device.push_error_scope(wgpu::ErrorFilter::Validation);
    let oom_scope = device.push_error_scope(wgpu::ErrorFilter::OutOfMemory);
    let uniform_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
        label: Some("lumenplot-line-uniform-layout"),
        entries: &[wgpu::BindGroupLayoutEntry {
            binding: 0,
            visibility: wgpu::ShaderStages::VERTEX_FRAGMENT,
            ty: wgpu::BindingType::Buffer {
                ty: wgpu::BufferBindingType::Uniform,
                has_dynamic_offset: false,
                min_binding_size: None,
            },
            count: None,
        }],
    });
    let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("lumenplot-line-pipeline-layout"),
        bind_group_layouts: &[Some(&uniform_layout)],
        immediate_size: 0,
    });
    let uniform_buffer = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("lumenplot-line-uniforms"),
        size: UNIFORM_BYTES as wgpu::BufferAddress,
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    let uniform_bind_group = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("lumenplot-line-uniform-bind-group"),
        layout: &uniform_layout,
        entries: &[wgpu::BindGroupEntry {
            binding: 0,
            resource: wgpu::BindingResource::Buffer(wgpu::BufferBinding {
                buffer: &uniform_buffer,
                offset: 0,
                size: None,
            }),
        }],
    });
    let color_targets = [Some(wgpu::ColorTargetState {
        format: TARGET_FORMAT,
        blend: Some(wgpu::BlendState::ALPHA_BLENDING),
        write_mask: wgpu::ColorWrites::ALL,
    })];
    let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("lumenplot-line-pipeline"),
        layout: Some(&pipeline_layout),
        vertex: wgpu::VertexState {
            module: &shader,
            entry_point: Some("vs_main"),
            compilation_options: Default::default(),
            buffers: &[VERTEX_LAYOUT],
        },
        primitive: wgpu::PrimitiveState {
            topology: wgpu::PrimitiveTopology::TriangleList,
            ..Default::default()
        },
        depth_stencil: None,
        multisample: wgpu::MultisampleState::default(),
        fragment: Some(wgpu::FragmentState {
            module: &shader,
            entry_point: Some("fs_main"),
            compilation_options: Default::default(),
            targets: &color_targets,
        }),
        multiview_mask: None,
        cache: None,
    });
    let oom_error = block_on(oom_scope.pop());
    let validation_error = block_on(validation_scope.pop());
    if is_out_of_memory(oom_error) {
        return Err(RenderError::new(
            RenderErrorKind::OutOfMemory,
            "portable GPU resource allocation failed",
        ));
    }
    if validation_error.is_some() {
        return Err(RenderError::new(
            RenderErrorKind::Internal,
            "portable GPU resource validation failed",
        ));
    }
    Ok(GpuResources {
        pipeline,
        uniform_buffer,
        uniform_bind_group,
    })
}

/// Verifies the checked-in shader bytes and provenance without touching a GPU.
pub fn verify_line_shader_artifact() -> Result<(), RenderError> {
    if !shader::verify_artifact() {
        return Err(RenderError::new(
            RenderErrorKind::ShaderInvalid,
            "static line shader provenance does not match its bytes",
        ));
    }
    let Ok(module) = wgpu::naga::front::wgsl::parse_str(shader::LINE_SHADER_SOURCE) else {
        return Err(RenderError::new(
            RenderErrorKind::ShaderInvalid,
            "static line shader failed WGSL parsing",
        ));
    };
    if wgpu::naga::valid::Validator::new(
        wgpu::naga::valid::ValidationFlags::all(),
        wgpu::naga::valid::Capabilities::all(),
    )
    .validate(&module)
    .is_err()
    {
        return Err(RenderError::new(
            RenderErrorKind::ShaderInvalid,
            "static line shader failed WGSL validation",
        ));
    }
    Ok(())
}

/// Returns provenance for the trusted static line artifact.
pub const fn line_shader_provenance() -> ShaderProvenance {
    shader::provenance()
}

struct PreparedFrame {
    width: u32,
    height: u32,
    row_pitch: u32,
    tight_row_bytes: usize,
    tight_bytes: usize,
    readback_bytes: usize,
    vertices: Vec<u8>,
    vertex_count: u32,
    uniform_bytes: [u8; UNIFORM_BYTES],
    clear_color: wgpu::Color,
    scissor: Scissor,
}

#[derive(Clone, Copy, Debug)]
struct Scissor {
    x: u32,
    y: u32,
    width: u32,
    height: u32,
}

fn prepare_frame(
    frame: &FramePacket,
    max_texture_dimension_2d: u32,
) -> Result<PreparedFrame, RenderError> {
    let [width, height] = frame.canvas_px();
    if width == 0
        || height == 0
        || width > max_texture_dimension_2d
        || height > max_texture_dimension_2d
    {
        return Err(RenderError::new(
            RenderErrorKind::CapacityExceeded,
            "frame dimensions exceed the portable device capacity",
        ));
    }
    let tight_row_bytes = usize::try_from(width)
        .ok()
        .and_then(|value| value.checked_mul(4))
        .ok_or_else(|| {
            RenderError::new(
                RenderErrorKind::CapacityExceeded,
                "frame row size exceeds a supported capacity",
            )
        })?;
    let tight_bytes = tight_row_bytes
        .checked_mul(usize::try_from(height).unwrap_or(usize::MAX))
        .ok_or_else(|| {
            RenderError::new(
                RenderErrorKind::CapacityExceeded,
                "frame pixel count exceeds a supported capacity",
            )
        })?;
    if tight_bytes == 0 || tight_bytes > 4 * 16_777_216 {
        return Err(RenderError::new(
            RenderErrorKind::CapacityExceeded,
            "frame pixel count exceeds a supported capacity",
        ));
    }
    let row_pitch = aligned_row_pitch(tight_row_bytes)?;
    let readback_bytes = row_pitch
        .checked_mul(height)
        .and_then(|value| usize::try_from(value).ok())
        .ok_or_else(|| {
            RenderError::new(
                RenderErrorKind::CapacityExceeded,
                "frame readback size exceeds a supported capacity",
            )
        })?;

    let canvas = frame.canvas_logical();
    if !canvas.width().is_finite()
        || !canvas.height().is_finite()
        || canvas.width() != f64::from(width)
        || canvas.height() != f64::from(height)
    {
        return Err(RenderError::new(
            RenderErrorKind::InvalidInput,
            "frame canvas geometry is invalid",
        ));
    }
    let plot_rect = frame.plot_rect();
    let scissor = scissor_from_rect(
        [
            plot_rect.x_min(),
            plot_rect.y_min(),
            plot_rect.x_max(),
            plot_rect.y_max(),
        ],
        width,
        height,
    )?;
    if !frame.dots_per_inch().is_finite() || frame.dots_per_inch() <= 0.0 {
        return Err(RenderError::new(
            RenderErrorKind::InvalidInput,
            "frame dots-per-inch is invalid",
        ));
    }
    if !frame.logical_units_per_inch().is_finite() || frame.logical_units_per_inch() <= 0.0 {
        return Err(RenderError::new(
            RenderErrorKind::InvalidInput,
            "frame logical scale is invalid",
        ));
    }
    let line_width = frame.line_width_px();
    if !line_width.is_finite() || line_width <= 0.0 || line_width > 16_384.0 {
        return Err(RenderError::new(
            RenderErrorKind::InvalidInput,
            "frame line width is invalid",
        ));
    }
    if frame.series().len() > MAX_PACKET_SERIES {
        return Err(RenderError::new(
            RenderErrorKind::CapacityExceeded,
            "frame series count exceeds a supported capacity",
        ));
    }

    let mut point_count = 0usize;
    let mut segment_count = 0usize;
    let mut line_count = 0usize;
    for series in frame.series() {
        for segment in series.segments() {
            if segment.points().is_empty() {
                return Err(RenderError::new(
                    RenderErrorKind::InvalidInput,
                    "frame contains an empty line segment",
                ));
            }
            segment_count = segment_count.checked_add(1).ok_or_else(|| {
                RenderError::new(
                    RenderErrorKind::CapacityExceeded,
                    "frame segment count exceeds a supported capacity",
                )
            })?;
            if segment_count > MAX_PACKET_SEGMENTS {
                return Err(RenderError::new(
                    RenderErrorKind::CapacityExceeded,
                    "frame segment count exceeds a supported capacity",
                ));
            }
            point_count = point_count
                .checked_add(segment.points().len())
                .ok_or_else(|| {
                    RenderError::new(
                        RenderErrorKind::CapacityExceeded,
                        "frame point count exceeds a supported capacity",
                    )
                })?;
            if point_count > MAX_PACKET_POINTS {
                return Err(RenderError::new(
                    RenderErrorKind::CapacityExceeded,
                    "frame point count exceeds a supported capacity",
                ));
            }
            line_count = line_count
                .checked_add(segment.points().len().saturating_sub(1))
                .ok_or_else(|| {
                    RenderError::new(
                        RenderErrorKind::CapacityExceeded,
                        "frame line count exceeds a supported capacity",
                    )
                })?;
            for point in segment.points() {
                if !point.x().is_finite()
                    || !point.y().is_finite()
                    || point.x() < 0.0
                    || point.y() < 0.0
                    || point.x() > f64::from(width)
                    || point.y() > f64::from(height)
                {
                    return Err(RenderError::new(
                        RenderErrorKind::InvalidInput,
                        "frame point geometry is invalid",
                    ));
                }
            }
        }
    }
    let vertex_count_upper = line_count.checked_mul(6).ok_or_else(|| {
        RenderError::new(
            RenderErrorKind::CapacityExceeded,
            "frame vertex count exceeds a supported capacity",
        )
    })?;
    let vertex_bytes_upper = vertex_count_upper
        .checked_mul(BYTES_PER_VERTEX)
        .ok_or_else(|| {
            RenderError::new(
                RenderErrorKind::CapacityExceeded,
                "frame vertex storage exceeds a supported capacity",
            )
        })?;
    if vertex_bytes_upper > MAX_VERTEX_BYTES {
        return Err(RenderError::new(
            RenderErrorKind::CapacityExceeded,
            "frame vertex storage exceeds a supported capacity",
        ));
    }
    let mut vertices = Vec::new();
    vertices
        .try_reserve_exact(vertex_bytes_upper)
        .map_err(|_| {
            RenderError::new(
                RenderErrorKind::OutOfMemory,
                "host line vertex allocation failed",
            )
        })?;
    let half_width = line_width * 0.5;
    for series in frame.series() {
        for segment in series.segments() {
            for pair in segment.points().windows(2) {
                append_segment_quad(&mut vertices, pair[0], pair[1], half_width)?;
            }
        }
    }
    let vertex_count = vertices.len() / BYTES_PER_VERTEX;
    let vertex_count = u32::try_from(vertex_count).map_err(|_| {
        RenderError::new(
            RenderErrorKind::CapacityExceeded,
            "frame vertex count is not representable",
        )
    })?;

    let background = frame.background();
    let clear_color = linear_color([
        background.r(),
        background.g(),
        background.b(),
        background.a(),
    ]);
    let line_color = frame.line_color();
    let uniform_bytes = uniform_bytes(
        [f64::from(width), f64::from(height)],
        half_width,
        [
            line_color.r(),
            line_color.g(),
            line_color.b(),
            line_color.a(),
        ],
    )?;
    Ok(PreparedFrame {
        width,
        height,
        row_pitch,
        tight_row_bytes,
        tight_bytes,
        readback_bytes,
        vertices,
        vertex_count,
        uniform_bytes,
        clear_color,
        scissor,
    })
}

fn aligned_row_pitch(tight_row_bytes: usize) -> Result<u32, RenderError> {
    let alignment = usize::try_from(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT).unwrap_or(usize::MAX);
    let aligned = tight_row_bytes
        .checked_add(alignment - 1)
        .map(|value| value / alignment)
        .and_then(|value| value.checked_mul(alignment))
        .ok_or_else(|| {
            RenderError::new(
                RenderErrorKind::CapacityExceeded,
                "frame row pitch exceeds a supported capacity",
            )
        })?;
    u32::try_from(aligned).map_err(|_| {
        RenderError::new(
            RenderErrorKind::CapacityExceeded,
            "frame row pitch is not representable",
        )
    })
}

fn scissor_from_rect(rect: [f64; 4], width: u32, height: u32) -> Result<Scissor, RenderError> {
    let values = rect;
    if !values.iter().all(|value| value.is_finite()) {
        return Err(RenderError::new(
            RenderErrorKind::InvalidInput,
            "frame plot rectangle is invalid",
        ));
    }
    let x = checked_floor_coordinate(rect[0], width)?;
    let y = checked_floor_coordinate(rect[1], height)?;
    let x_max = checked_ceil_coordinate(rect[2], width)?;
    let y_max = checked_ceil_coordinate(rect[3], height)?;
    if x >= x_max || y >= y_max {
        return Err(RenderError::new(
            RenderErrorKind::InvalidInput,
            "frame plot rectangle is empty",
        ));
    }
    Ok(Scissor {
        x,
        y,
        width: x_max - x,
        height: y_max - y,
    })
}

fn checked_floor_coordinate(value: f64, limit: u32) -> Result<u32, RenderError> {
    let value = value.floor();
    if value < 0.0 || value > f64::from(limit) {
        return Err(RenderError::new(
            RenderErrorKind::InvalidInput,
            "frame plot rectangle is outside the canvas",
        ));
    }
    u32::try_from(value as u64).map_err(|_| {
        RenderError::new(
            RenderErrorKind::InvalidInput,
            "frame plot rectangle coordinate is not representable",
        )
    })
}

fn checked_ceil_coordinate(value: f64, limit: u32) -> Result<u32, RenderError> {
    let value = value.ceil();
    if value < 0.0 || value > f64::from(limit) {
        return Err(RenderError::new(
            RenderErrorKind::InvalidInput,
            "frame plot rectangle is outside the canvas",
        ));
    }
    u32::try_from(value as u64).map_err(|_| {
        RenderError::new(
            RenderErrorKind::InvalidInput,
            "frame plot rectangle coordinate is not representable",
        )
    })
}

fn append_segment_quad(
    vertices: &mut Vec<u8>,
    start: lumenplot_render_api::PacketPoint,
    end: lumenplot_render_api::PacketPoint,
    half_width: f64,
) -> Result<(), RenderError> {
    let dx = end.x() - start.x();
    let dy = end.y() - start.y();
    let length = dx.hypot(dy);
    if !length.is_finite() || length < 0.0 {
        return Err(RenderError::new(
            RenderErrorKind::InvalidInput,
            "line segment length is invalid",
        ));
    }
    if length == 0.0 {
        return Ok(());
    }
    let nx = -dy / length;
    let ny = dx / length;
    let left_start = [start.x() + nx * half_width, start.y() + ny * half_width];
    let right_start = [start.x() - nx * half_width, start.y() - ny * half_width];
    let left_end = [end.x() + nx * half_width, end.y() + ny * half_width];
    let right_end = [end.x() - nx * half_width, end.y() - ny * half_width];
    let local_left_start = [0.0, half_width];
    let local_right_start = [0.0, -half_width];
    let local_left_end = [length, half_width];
    let local_right_end = [length, -half_width];
    for (position, local) in [
        (left_start, local_left_start),
        (right_start, local_right_start),
        (right_end, local_right_end),
        (left_start, local_left_start),
        (right_end, local_right_end),
        (left_end, local_left_end),
    ] {
        append_vertex(vertices, position, local)?;
    }
    Ok(())
}

fn append_vertex(
    vertices: &mut Vec<u8>,
    position: [f64; 2],
    local: [f64; 2],
) -> Result<(), RenderError> {
    for value in position.into_iter().chain(local) {
        let value = checked_f32(value)?;
        vertices.extend_from_slice(&value.to_le_bytes());
    }
    Ok(())
}

fn checked_f32(value: f64) -> Result<f32, RenderError> {
    if !value.is_finite() || value.abs() > f64::from(f32::MAX) {
        Err(RenderError::new(
            RenderErrorKind::InvalidInput,
            "line vertex value is not representable",
        ))
    } else {
        Ok(value as f32)
    }
}

fn uniform_bytes(
    viewport: [f64; 2],
    half_width: f64,
    color: [u8; 4],
) -> Result<[u8; UNIFORM_BYTES], RenderError> {
    let values = [
        checked_f32(viewport[0])?,
        checked_f32(viewport[1])?,
        checked_f32(half_width)?,
        0.0,
        srgb_channel_to_linear(color[0]),
        srgb_channel_to_linear(color[1]),
        srgb_channel_to_linear(color[2]),
        f32::from(color[3]) / 255.0,
    ];
    let mut bytes = [0u8; UNIFORM_BYTES];
    for (index, value) in values.into_iter().enumerate() {
        bytes[index * 4..index * 4 + 4].copy_from_slice(&value.to_le_bytes());
    }
    Ok(bytes)
}

fn linear_color(color: [u8; 4]) -> wgpu::Color {
    wgpu::Color {
        r: f64::from(srgb_channel_to_linear(color[0])),
        g: f64::from(srgb_channel_to_linear(color[1])),
        b: f64::from(srgb_channel_to_linear(color[2])),
        a: f64::from(color[3]) / 255.0,
    }
}

fn srgb_channel_to_linear(channel: u8) -> f32 {
    let encoded = f64::from(channel) / 255.0;
    let linear = if encoded <= 0.04045 {
        encoded / 12.92
    } else {
        ((encoded + 0.055) / 1.055).powf(2.4)
    };
    linear as f32
}

fn is_out_of_memory(error: Option<wgpu::Error>) -> bool {
    matches!(error, Some(wgpu::Error::OutOfMemory { .. }))
}

fn block_on<F: Future>(future: F) -> F::Output {
    let mut future = pin!(future);
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
    fn row_pitch_is_copy_aligned_and_tightly_bounded() {
        assert_eq!(aligned_row_pitch(4).expect("row pitch"), 256);
        assert_eq!(aligned_row_pitch(256).expect("row pitch"), 256);
        assert_eq!(aligned_row_pitch(257).expect("row pitch"), 512);
    }

    #[test]
    fn srgb_conversion_has_expected_endpoints() {
        assert_eq!(srgb_channel_to_linear(0), 0.0);
        assert_eq!(srgb_channel_to_linear(255), 1.0);
        let midpoint = srgb_channel_to_linear(128);
        assert!(midpoint > 0.2 && midpoint < 0.22);
    }

    #[test]
    fn horizontal_segment_expands_to_two_triangles() {
        let mut bytes = Vec::new();
        append_segment_quad(
            &mut bytes,
            lumenplot_render_api::PacketPoint::new(10.0, 20.0),
            lumenplot_render_api::PacketPoint::new(30.0, 20.0),
            2.0,
        )
        .expect("quad");
        assert_eq!(bytes.len(), 6 * BYTES_PER_VERTEX);
        assert_eq!(bytes.len() % BYTES_PER_VERTEX, 0);
    }

    #[test]
    fn degenerate_segment_publishes_no_vertices() {
        let mut bytes = Vec::new();
        append_segment_quad(
            &mut bytes,
            lumenplot_render_api::PacketPoint::new(10.0, 20.0),
            lumenplot_render_api::PacketPoint::new(10.0, 20.0),
            2.0,
        )
        .expect("degenerate segment");
        assert!(bytes.is_empty());
    }

    #[test]
    fn invalid_scissor_geometry_is_rejected() {
        let error = scissor_from_rect([-1.0, 0.0, 4.0, 4.0], 4, 4).expect_err("negative clip");
        assert_eq!(error.kind(), RenderErrorKind::InvalidInput);
    }

    #[test]
    fn static_shader_provenance_is_verified_before_gpu_use() {
        verify_line_shader_artifact().expect("shader provenance");
        assert_eq!(
            line_shader_provenance().artifact_sha256(),
            "e0c3b4d3247963a1b8a96fe91dacb2f1c6f14ee5c31ed1c91fd6bbcc5ec9cbf3"
        );
    }
}
