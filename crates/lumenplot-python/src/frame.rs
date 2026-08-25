//! Private whole-frame PNG rasterizer for the `render_frame_png` seam.
//!
//! This module is deliberately free of PyO3 types: `crates/lumenplot/src/lib.rs`
//! exposes the accepted private line-frame facade, and this module extends the
//! same seam family with a frame-shaped request (API-0005 Phase-3B, manager
//! decisions 2/3). The Python-facing extraction layer lives in `lib.rs` and
//! copies the caller's dictionaries into the owned intermediate representation
//! below while the GIL is held; nothing borrowed from the interpreter reaches
//! this module.
//!
//! Rendering model (frozen for this slice):
//! - the canvas starts fully transparent;
//! - `path` commands contribute coverage generated with `tiny-skia` (the same
//!   pinned rasterizer version used by `lumenplot-export`) and are composited
//!   with the exact linear-light source-over math used by the Phase-2 line
//!   exporter, so native output stays numerically consistent across seams;
//! - `image` commands composite straight-alpha RGBA directly with the same
//!   math (row 0 of the source is the top row);
//! - vertices arrive in display pixels with a lower-left origin and are
//!   flipped once into top-left device space;
//! - non-finite vertices act as pen lifts (gaps), never as errors, matching
//!   the no-reconnection gap semantics of the accepted line seam;
//! - output is deterministic: fixed iteration order, no global state, IEEE
//!   arithmetic only.

use std::io::Write;

use png::{BitDepth, ColorType, Compression, Encoder, Filter, SrgbRenderingIntent};
use tiny_skia::{
    FillRule, IntSize, LineCap, LineJoin, Mask, Path, PathBuilder, Stroke, StrokeDash, Transform,
};

/// Upper bounds mirrored from `lumenplot-export/src/raster.rs` so both native
/// seams enforce identical capacity discipline.
const MAX_DIMENSION: u32 = 16_384;
const MAX_PIXELS: usize = 16_777_216;
const MAX_OUTPUT_BYTES: usize = 67_108_864;

/// Largest path-coordinate magnitude tiny-skia 0.12 can process safely
/// (mirrors the pinned-dependency guard in `lumenplot-export/src/raster.rs`).
const TINY_SKIA_SAFE_PATH_BOUND: f32 = f32::MAX * 0.25;

/// Maximum accepted vertex count per path command (same budget as the
/// accepted line seam).
const MAX_PATH_POINTS: usize = 1_000_000;

/// Error taxonomy for the frame seam. Callers map `Validation` to Python
/// `ValueError`; every other variant becomes a `RuntimeError` family
/// exception (`out-of-memory/resource`, `internal/internal`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum FrameError {
    /// Structural or numeric spec violation raised before any allocation.
    Validation(&'static str),
    /// An allocation refused by the checked-reserve discipline.
    OutOfMemory,
    /// Unreachable-by-contract internal failure (encoding, stroking).
    Internal(&'static str),
}

/// Matplotlib path codes accepted by the seam.
const CODE_STOP: i64 = 0;
const CODE_MOVETO: i64 = 1;
const CODE_LINETO: i64 = 2;
const CODE_CURVE3: i64 = 3;
const CODE_CURVE4: i64 = 4;
const CODE_CLOSEPOLY: i64 = 79;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum CapSelector {
    Butt,
    Round,
    Projecting,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum JoinSelector {
    Miter,
    Round,
    Bevel,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum FillRuleSelector {
    NonZero,
    EvenOdd,
}

/// One validated `kind: "path"` command in device-independent form.
#[derive(Clone, Debug)]
pub(crate) struct PathCommand {
    vertices: Vec<[f64; 2]>,
    codes: Option<Vec<i64>>,
    transform: [f64; 6],
    stroke_rgba: Option<[u8; 4]>,
    fill_rgba: Option<[u8; 4]>,
    line_width_pt: f64,
    cap: CapSelector,
    join: JoinSelector,
    dash_offset_pt: f64,
    dashes: Option<Vec<f64>>,
    fill_rule: FillRuleSelector,
    antialias: bool,
    clip_rect: Option<[f64; 4]>,
}

#[allow(clippy::too_many_arguments)]
impl PathCommand {
    /// Validates and stores one path command. All failures are `Validation`.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn new(
        vertices: Vec<[f64; 2]>,
        codes: Option<Vec<i64>>,
        transform: [f64; 6],
        stroke_rgba: Option<[u8; 4]>,
        fill_rgba: Option<[u8; 4]>,
        line_width_pt: f64,
        cap: CapSelector,
        join: JoinSelector,
        dash_offset_pt: f64,
        dashes: Option<Vec<f64>>,
        fill_rule: FillRuleSelector,
        antialias: bool,
        clip_rect: Option<[f64; 4]>,
    ) -> Result<Self, FrameError> {
        if vertices.len() > MAX_PATH_POINTS {
            return Err(FrameError::Validation("path has too many vertices"));
        }
        if let Some(codes) = &codes {
            if codes.len() != vertices.len() {
                return Err(FrameError::Validation(
                    "codes length must equal vertices length",
                ));
            }
            if codes.iter().any(|code| {
                !matches!(
                    *code,
                    CODE_STOP
                        | CODE_MOVETO
                        | CODE_LINETO
                        | CODE_CURVE3
                        | CODE_CURVE4
                        | CODE_CLOSEPOLY
                )
            }) {
                return Err(FrameError::Validation("path code is not recognized"));
            }
        }
        if !transform.iter().all(|value| f64::is_finite(*value)) {
            return Err(FrameError::Validation(
                "transform coefficients must be finite",
            ));
        }
        if !line_width_pt.is_finite() || line_width_pt < 0.0 {
            return Err(FrameError::Validation("line_width_pt must be >= 0"));
        }
        if !dash_offset_pt.is_finite() || dash_offset_pt < 0.0 {
            return Err(FrameError::Validation("dash_offset_pt must be >= 0"));
        }
        if let Some(dashes) = &dashes {
            if dashes.len() % 2 != 0 {
                return Err(FrameError::Validation("dashes must have even length"));
            }
            if dashes
                .iter()
                .any(|value| !f64::is_finite(*value) || *value < 0.0)
            {
                return Err(FrameError::Validation("dashes must be finite and >= 0"));
            }
        }
        if let Some(clip) = clip_rect
            && (!clip.iter().all(|value| f64::is_finite(*value))
                || !clip[2].is_finite()
                || clip[2] <= 0.0
                || !clip[3].is_finite()
                || clip[3] <= 0.0)
        {
            return Err(FrameError::Validation(
                "clip_rect must be finite with positive width and height",
            ));
        }
        if stroke_rgba.is_none() && fill_rgba.is_none() {
            return Err(FrameError::Validation(
                "path command needs stroke_rgba or fill_rgba",
            ));
        }
        Ok(Self {
            vertices,
            codes,
            transform,
            stroke_rgba: stroke_rgba.map(canonical_rgba),
            fill_rgba: fill_rgba.map(canonical_rgba),
            line_width_pt,
            cap,
            join,
            dash_offset_pt,
            dashes,
            fill_rule,
            antialias,
            clip_rect,
        })
    }
}

/// One validated `kind: "image"` command: straight-alpha RGBA, row 0 = top,
/// anchored at the lower-left display-space corner `(x, y)` covering
/// `width x height` display pixels.
#[derive(Clone, Debug)]
pub(crate) struct ImageCommand {
    x: f64,
    y: f64,
    width: u32,
    height: u32,
    rgba: Vec<u8>,
    clip_rect: Option<[f64; 4]>,
}

impl ImageCommand {
    pub(crate) fn new(
        x: f64,
        y: f64,
        width: u32,
        height: u32,
        rgba: Vec<u8>,
        clip_rect: Option<[f64; 4]>,
    ) -> Result<Self, FrameError> {
        if !x.is_finite() || !y.is_finite() {
            return Err(FrameError::Validation("image anchor must be finite"));
        }
        let expected = usize::try_from(width)
            .ok()
            .and_then(|width| {
                usize::try_from(height)
                    .ok()
                    .and_then(|height| width.checked_mul(height))
            })
            .and_then(|pixels| pixels.checked_mul(4))
            .ok_or(FrameError::Validation("image dimensions are too large"))?;
        if rgba.len() != expected {
            return Err(FrameError::Validation(
                "rgba length must equal width * height * 4",
            ));
        }
        if let Some(clip) = clip_rect
            && (!clip.iter().all(|value| f64::is_finite(*value))
                || !clip[2].is_finite()
                || clip[2] <= 0.0
                || !clip[3].is_finite()
                || clip[3] <= 0.0)
        {
            return Err(FrameError::Validation(
                "clip_rect must be finite with positive width and height",
            ));
        }
        Ok(Self {
            x,
            y,
            width,
            height,
            rgba,
            clip_rect,
        })
    }
}

/// One discriminated frame command.
#[derive(Clone, Debug)]
pub(crate) enum Command {
    Path(PathCommand),
    Image(ImageCommand),
}

/// Validated whole-frame specification (owned IR; no interpreter borrows).
#[derive(Clone, Debug)]
pub(crate) struct FrameSpec {
    width_px: u32,
    height_px: u32,
    output_dpi: f64,
    commands: Vec<Command>,
}

impl FrameSpec {
    pub(crate) fn new(width_px: u32, height_px: u32, output_dpi: f64) -> Result<Self, FrameError> {
        if width_px == 0 || height_px == 0 {
            return Err(FrameError::Validation("dimensions must be positive"));
        }
        if width_px > MAX_DIMENSION || height_px > MAX_DIMENSION {
            return Err(FrameError::Validation(
                "dimensions exceed the supported maximum",
            ));
        }
        let pixel_count = usize::try_from(width_px)
            .ok()
            .and_then(|width| {
                usize::try_from(height_px)
                    .ok()
                    .and_then(|height| width.checked_mul(height))
            })
            .ok_or(FrameError::Validation(
                "dimensions exceed the supported maximum",
            ))?;
        if pixel_count > MAX_PIXELS {
            return Err(FrameError::Validation(
                "pixel count exceeds the supported maximum",
            ));
        }
        if !output_dpi.is_finite() || output_dpi <= 0.0 {
            return Err(FrameError::Validation("output_dpi must be finite and > 0"));
        }
        Ok(Self {
            width_px,
            height_px,
            output_dpi,
            commands: Vec::new(),
        })
    }

    pub(crate) fn push_command(&mut self, command: Command) -> Result<(), FrameError> {
        if self.commands.len() == usize::MAX / 8 {
            return Err(FrameError::Validation("too many commands"));
        }
        self.commands.push(command);
        Ok(())
    }

    /// Pre-reserves capacity for the expected command count. Refusal is an
    /// interpreter-level allocation failure surfaced as a RuntimeError.
    pub(crate) fn reserve_commands(&mut self, count: usize) -> Result<(), FrameError> {
        self.commands
            .try_reserve_exact(count)
            .map_err(|_| FrameError::OutOfMemory)
    }

    fn scale(&self) -> f64 {
        // Points to device pixels; validated positive and finite upstream.
        self.output_dpi / 72.0
    }
}

/// Linear-light premultiplied pixel accumulator, byte-for-byte the same
/// numeric model as `lumenplot-export/src/compositor.rs`.
#[derive(Clone, Copy)]
struct LinearPixel {
    premultiplied: [f64; 3],
    alpha: f64,
}

fn clamp_unit(value: f64) -> f64 {
    if value.is_finite() {
        value.clamp(0.0, 1.0)
    } else {
        0.0
    }
}

fn decode_srgb_channel(encoded: u8) -> f64 {
    let channel = f64::from(encoded) / 255.0;
    if channel <= 0.04045 {
        channel / 12.92
    } else {
        ((channel + 0.055) / 1.055).powf(2.4)
    }
}

fn encode_srgb_channel(linear: f64) -> f64 {
    let linear = clamp_unit(linear);
    if linear <= 0.0031308 {
        12.92 * linear
    } else {
        1.055 * linear.powf(1.0 / 2.4) - 0.055
    }
}

fn quantize_round_half_even(value: f64) -> u8 {
    let value = clamp_unit(value) * 255.0;
    let lower = value.floor();
    let fraction = value - lower;
    let rounded = if fraction < 0.5 {
        lower
    } else if fraction > 0.5 {
        lower + 1.0
    } else if (lower as u64).is_multiple_of(2) {
        lower
    } else {
        lower + 1.0
    };
    rounded.clamp(0.0, 255.0) as u8
}

fn linear_pixel_from_rgba(color: [u8; 4]) -> LinearPixel {
    let alpha = f64::from(color[3]) / 255.0;
    let rgb = [
        decode_srgb_channel(color[0]),
        decode_srgb_channel(color[1]),
        decode_srgb_channel(color[2]),
    ];
    LinearPixel {
        premultiplied: [rgb[0] * alpha, rgb[1] * alpha, rgb[2] * alpha],
        alpha,
    }
}

fn source_over(source: LinearPixel, destination: LinearPixel) -> LinearPixel {
    let source_alpha = clamp_unit(source.alpha);
    let destination_alpha = clamp_unit(destination.alpha);
    let inverse_source_alpha = 1.0 - source_alpha;
    let alpha = clamp_unit(source_alpha + destination_alpha * inverse_source_alpha);
    let mut premultiplied = [0.0; 3];
    for (index, channel) in premultiplied.iter_mut().enumerate() {
        *channel = clamp_unit(
            source.premultiplied[index] + destination.premultiplied[index] * inverse_source_alpha,
        );
    }
    LinearPixel {
        premultiplied,
        alpha,
    }
}

fn to_rgba8(pixels: &[LinearPixel]) -> Vec<u8> {
    let mut rgba = Vec::new();
    // Byte count is bounded by the plan check, so reservation cannot fail
    // spuriously; fall back to push amortization on refusal anyway.
    if rgba.try_reserve_exact(pixels.len() * 4).is_err() {
        return Vec::new();
    }
    for pixel in pixels {
        let alpha = clamp_unit(pixel.alpha);
        let alpha_u8 = quantize_round_half_even(alpha);
        if alpha_u8 == 0 {
            rgba.extend_from_slice(&[0, 0, 0, 0]);
            continue;
        }
        let red = encode_srgb_channel(clamp_unit(pixel.premultiplied[0] / alpha));
        let green = encode_srgb_channel(clamp_unit(pixel.premultiplied[1] / alpha));
        let blue = encode_srgb_channel(clamp_unit(pixel.premultiplied[2] / alpha));
        rgba.extend_from_slice(&[
            quantize_round_half_even(red),
            quantize_round_half_even(green),
            quantize_round_half_even(blue),
            alpha_u8,
        ]);
    }
    rgba
}

fn canonical_rgba(mut color: [u8; 4]) -> [u8; 4] {
    if color[3] == 0 {
        color[0] = 0;
        color[1] = 0;
        color[2] = 0;
    }
    color
}

/// Device-space clip rectangle in top-left pixel coordinates
/// `(left, top, right, bottom)`, exclusive on right/bottom edges.
struct DeviceClip {
    left: u32,
    top: u32,
    right: u32,
    bottom: u32,
}

impl DeviceClip {
    fn from_display(rect: [f64; 4], width: u32, height: u32) -> Self {
        // Display space (lower-left origin) -> device space (top-left rows).
        let left = rect[0].max(0.0);
        let top = (f64::from(height) - (rect[1] + rect[3])).max(0.0);
        let right = (rect[0] + rect[2]).min(f64::from(width)).max(left);
        let bottom = (top + rect[3]).min(f64::from(height));
        DeviceClip {
            left: clamp_to_u32(left.floor()),
            top: clamp_to_u32(top.floor()),
            right: clamp_to_u32(right.ceil()),
            bottom: clamp_to_u32(bottom.ceil()),
        }
    }

    fn contains(&self, x: u32, y: u32) -> bool {
        x >= self.left && x < self.right && y >= self.top && y < self.bottom
    }
}

fn clamp_to_u32(value: f64) -> u32 {
    if value.is_finite() && value > 0.0 {
        value.min(f64::from(u32::MAX)) as u32
    } else {
        0
    }
}

fn apply_clip_to_mask(mask: &mut Mask, clip: &DeviceClip, width: u32, height: u32) {
    let data = mask.data_mut();
    for y in 0..height {
        let row_visible = y >= clip.top && y < clip.bottom;
        let row_start = usize::try_from(y)
            .ok()
            .and_then(|y| usize::try_from(width).ok().map(|width| y * width));
        let Some(row_start) = row_start else { continue };
        if row_visible {
            for x in 0..width {
                if !(x >= clip.left && x < clip.right) {
                    data[row_start + x as usize] = 0;
                }
            }
        } else {
            data[row_start..row_start + width as usize].fill(0);
        }
    }
}

/// Builds the device-space tiny-skia path for one path command, applying the
/// affine transform and the display-to-device y-flip in f64, dropping
/// non-finite or unrepresentable points as pen lifts.
fn build_device_path(command: &PathCommand, height_px: u32) -> Option<Path> {
    // Fold the flip into the affine once: y_device = H - y_display.
    let [a, b, c, d, e, f] = command.transform;
    let sa = a;
    let sb = -b;
    let sc = c;
    let sd = -d;
    let se = e;
    let sf = f64::from(height_px) - f;
    let group: Vec<(i64, &[[f64; 2]])> = Vec::new();
    let codes: Vec<i64> = command.codes.clone().unwrap_or_else(|| {
        let mut implicit = Vec::with_capacity(command.vertices.len());
        if !command.vertices.is_empty() {
            implicit.push(CODE_MOVETO);
        }
        implicit.resize(command.vertices.len(), CODE_LINETO);
        implicit
    });

    let mut builder = PathBuilder::new();
    let mut current: Option<[f32; 2]> = None;
    let mut subpath_start: Option<[f32; 2]> = None;

    let map_point = |point: &[f64; 2]| -> Option<[f32; 2]> {
        let x = sa * point[0] + sc * point[1] + se;
        let y = sb * point[0] + sd * point[1] + sf;
        if !x.is_finite() || !y.is_finite() {
            return None;
        }
        let (x, y) = (x as f32, y as f32);
        if !x.is_finite()
            || !y.is_finite()
            || x.abs() > TINY_SKIA_SAFE_PATH_BOUND
            || y.abs() > TINY_SKIA_SAFE_PATH_BOUND
        {
            return None;
        }
        Some([x, y])
    };

    // Codes run PARALLEL to vertices (one code per vertex, Matplotlib
    // convention): a CURVE3 group is the code repeated on two consecutive
    // vertices, a CURVE4 group on three. Iterating index-wise keeps every
    // vertex attached to its own code.
    let mut index = 0usize;
    while index < codes.len() {
        let code = codes[index];
        if code == CODE_STOP {
            break;
        }
        match code {
            CODE_MOVETO | CODE_LINETO => {
                if index >= command.vertices.len() {
                    break;
                }
                match map_point(&command.vertices[index]) {
                    Some(point) => {
                        if code == CODE_MOVETO || current.is_none() {
                            // A MOVETO, or a LINETO with no live pen (path
                            // start or after a dropped group), begins a new
                            // subpath instead of connecting from a stale
                            // point.
                            builder.move_to(point[0], point[1]);
                        } else {
                            builder.line_to(point[0], point[1]);
                        }
                        if code == CODE_MOVETO || current.is_none() {
                            subpath_start = Some(point);
                        }
                        current = Some(point);
                    }
                    None => {
                        // Non-finite geometry lifts the pen.
                        current = None;
                        subpath_start = None;
                    }
                }
                index += 1;
            }
            CODE_CURVE3 => {
                if index + 1 >= command.vertices.len() {
                    break;
                }
                let control = map_point(&command.vertices[index]);
                let end = map_point(&command.vertices[index + 1]);
                match (current, control, end) {
                    (Some(_), Some(control), Some(end)) => {
                        builder.quad_to(control[0], control[1], end[0], end[1]);
                        current = Some(end);
                    }
                    (_, control, end) => {
                        // A non-finite member breaks the whole curve group and
                        // lifts the pen; the finite end (if any) becomes the
                        // anchor. The builder pen is MOVED there so the next
                        // segment can never draw back into the dropped group.
                        let anchor = end.or(control);
                        match anchor {
                            Some(point) => {
                                builder.move_to(point[0], point[1]);
                                current = Some(point);
                            }
                            None => current = None,
                        }
                        subpath_start = None;
                    }
                }
                index += 2;
            }
            CODE_CURVE4 => {
                if index + 2 >= command.vertices.len() {
                    break;
                }
                let control1 = map_point(&command.vertices[index]);
                let control2 = map_point(&command.vertices[index + 1]);
                let end = map_point(&command.vertices[index + 2]);
                match (current, control1, control2, end) {
                    (Some(_), Some(control1), Some(control2), Some(end)) => {
                        builder.cubic_to(
                            control1[0],
                            control1[1],
                            control2[0],
                            control2[1],
                            end[0],
                            end[1],
                        );
                        current = Some(end);
                    }
                    (_, _, _, end) => {
                        // Same pen resync as CURVE3: move to the surviving
                        // anchor instead of leaving a stale pen behind.
                        match end.or(control2) {
                            Some(point) => {
                                builder.move_to(point[0], point[1]);
                                current = Some(point);
                            }
                            None => current = None,
                        }
                        subpath_start = None;
                    }
                }
                index += 3;
            }
            CODE_CLOSEPOLY => {
                // The CLOSEPOLY vertex is a positional dummy; only the code
                // closes the subpath.
                if let Some(start) = subpath_start {
                    builder.close();
                    current = Some(start);
                }
                index += 1;
            }
            _ => unreachable!("validated code set"),
        }
    }
    drop(group);

    builder.finish()
}

fn stroke_selection(command: &PathCommand, scale: f64) -> Result<Option<Stroke>, FrameError> {
    let command_stroke_rgba = command.stroke_rgba;
    if command_stroke_rgba.is_none() {
        return Ok(None);
    };
    let width = command.line_width_pt * scale;
    if !width.is_finite() || width < 0.0 || width > f64::from(f32::MAX) {
        return Err(FrameError::Internal("stroke width is unrepresentable"));
    }
    // A zero-width stroke has no area; Matplotlib renders lw=0 as nothing,
    // so skip instead of asking the stroker for a rejected hairline.
    if width == 0.0 {
        return Ok(None);
    }
    let mut stroke = Stroke {
        width: width as f32,
        miter_limit: 4.0,
        line_cap: match command.cap {
            CapSelector::Butt => LineCap::Butt,
            CapSelector::Round => LineCap::Round,
            CapSelector::Projecting => LineCap::Square,
        },
        line_join: match command.join {
            JoinSelector::Miter => LineJoin::Miter,
            JoinSelector::Round => LineJoin::Round,
            JoinSelector::Bevel => LineJoin::Bevel,
        },
        dash: None,
    };
    if let Some(dashes) = &command.dashes {
        let total: f64 = dashes.iter().sum();
        if total.is_finite() && total > 0.0 {
            let array: Vec<f32> = dashes.iter().map(|value| (*value * scale) as f32).collect();
            let offset = (command.dash_offset_pt * scale) as f32;
            let dash = StrokeDash::new(array, offset)
                .ok_or(FrameError::Internal("dash pattern is unrepresentable"))?;
            stroke.dash = Some(dash);
        }
        // An all-zero or degenerate pattern means "solid"; nothing to set.
    }
    Ok(Some(stroke))
}

fn coverage_mask(width: u32, height: u32, pixel_count: usize) -> Result<Mask, FrameError> {
    let size = IntSize::from_wh(width, height).ok_or(FrameError::Internal("mask size rejected"))?;
    let mut data = Vec::new();
    if data.try_reserve_exact(pixel_count).is_err() {
        return Err(FrameError::OutOfMemory);
    }
    data.resize(pixel_count, 0u8);
    Mask::from_vec(data, size).ok_or(FrameError::OutOfMemory)
}

fn composite_coverage(pixels: &mut [LinearPixel], mask: &Mask, color: [u8; 4]) {
    let source_rgb = [
        decode_srgb_channel(color[0]),
        decode_srgb_channel(color[1]),
        decode_srgb_channel(color[2]),
    ];
    let style_alpha = f64::from(color[3]) / 255.0;
    if style_alpha == 0.0 {
        return;
    }
    for (index, destination) in pixels.iter_mut().enumerate() {
        let coverage = f64::from(mask.data()[index]) / 255.0;
        if coverage == 0.0 {
            continue;
        }
        let alpha = clamp_unit(style_alpha * coverage);
        if alpha == 0.0 {
            continue;
        }
        let source = LinearPixel {
            premultiplied: [
                source_rgb[0] * alpha,
                source_rgb[1] * alpha,
                source_rgb[2] * alpha,
            ],
            alpha,
        };
        *destination = source_over(source, *destination);
    }
}

fn composite_image(
    pixels: &mut [LinearPixel],
    command: &ImageCommand,
    width: u32,
    height: u32,
    clip: Option<&DeviceClip>,
) {
    let image_width = usize::try_from(command.width).expect("validated dimension");
    let source_row_bytes = image_width * 4;
    // Device-space top-left corner of the image placement.
    let origin_x = command.x;
    let origin_y = f64::from(height) - command.y - f64::from(command.height);
    for local_row in 0..command.height {
        let device_y_f = origin_y + f64::from(local_row);
        if device_y_f < 0.0 || device_y_f >= f64::from(height) {
            continue;
        }
        let device_y = device_y_f as u32;
        for local_column in 0..command.width {
            let device_x_f = origin_x + f64::from(local_column);
            if device_x_f < 0.0 || device_x_f >= f64::from(width) {
                continue;
            }
            let device_x = device_x_f as u32;
            if let Some(clip) = clip
                && !clip.contains(device_x, device_y)
            {
                continue;
            }
            let source_index = local_row as usize * source_row_bytes + local_column as usize * 4;
            let color = [
                command.rgba[source_index],
                command.rgba[source_index + 1],
                command.rgba[source_index + 2],
                command.rgba[source_index + 3],
            ];
            if color[3] == 0 {
                continue;
            }
            let destination_index = device_y as usize * width as usize + device_x as usize;
            pixels[destination_index] =
                source_over(linear_pixel_from_rgba(color), pixels[destination_index]);
        }
    }
}

/// Renders the frame to straight-alpha RGBA8 (top-left row order), the exact
/// pre-encoding representation the PNG container wraps.
pub(crate) fn rasterize(spec: &FrameSpec) -> Result<Vec<u8>, FrameError> {
    let width = spec.width_px;
    let height = spec.height_px;
    let pixel_count = usize::try_from(width)
        .ok()
        .and_then(|width| {
            usize::try_from(height)
                .ok()
                .and_then(|height| width.checked_mul(height))
        })
        .ok_or(FrameError::Internal("pixel count overflowed"))?;

    let mut pixels = Vec::new();
    if pixels.try_reserve_exact(pixel_count).is_err() {
        return Err(FrameError::OutOfMemory);
    }
    pixels.resize(
        pixel_count,
        LinearPixel {
            premultiplied: [0.0; 3],
            alpha: 0.0,
        },
    );
    let scale = spec.scale();

    for command in &spec.commands {
        match command {
            Command::Path(path) => {
                let Some(path_geometry) = build_device_path(path, height) else {
                    continue;
                };
                let clip = path
                    .clip_rect
                    .map(|rect| DeviceClip::from_display(rect, width, height));
                if let Some(fill_rgba) = path.fill_rgba {
                    let fill_rule = match path.fill_rule {
                        FillRuleSelector::NonZero => FillRule::Winding,
                        FillRuleSelector::EvenOdd => FillRule::EvenOdd,
                    };
                    let mut mask = coverage_mask(width, height, pixel_count)?;
                    mask.fill_path(
                        &path_geometry,
                        fill_rule,
                        path.antialias,
                        Transform::identity(),
                    );
                    if let Some(clip) = &clip {
                        apply_clip_to_mask(&mut mask, clip, width, height);
                    }
                    composite_coverage(&mut pixels, &mask, fill_rgba);
                }
                let stroke = stroke_selection(path, scale)?;
                if let Some(stroke) = stroke {
                    let stroked = path_geometry
                        .stroke(&stroke, 1.0)
                        .ok_or(FrameError::Internal("stroking failed"))?;
                    let bounds = stroked.bounds();
                    let representable =
                        [bounds.left(), bounds.top(), bounds.right(), bounds.bottom()]
                            .iter()
                            .all(|side| {
                                side.is_finite()
                                    && *side >= -TINY_SKIA_SAFE_PATH_BOUND
                                    && *side <= TINY_SKIA_SAFE_PATH_BOUND
                            });
                    if !representable {
                        return Err(FrameError::Internal("stroked path is unrepresentable"));
                    }
                    let mut mask = coverage_mask(width, height, pixel_count)?;
                    mask.fill_path(
                        &stroked,
                        FillRule::Winding,
                        path.antialias,
                        Transform::identity(),
                    );
                    if let Some(clip) = &clip {
                        apply_clip_to_mask(&mut mask, clip, width, height);
                    }
                    let stroke_rgba = path.stroke_rgba.unwrap_or([0, 0, 0, 255]);
                    composite_coverage(&mut pixels, &mask, stroke_rgba);
                }
            }
            Command::Image(image) => {
                let clip = image
                    .clip_rect
                    .map(|rect| DeviceClip::from_display(rect, width, height));
                composite_image(&mut pixels, image, width, height, clip.as_ref());
            }
        }
    }

    Ok(to_rgba8(&pixels))
}

struct CappedWriter {
    bytes: Vec<u8>,
    limit: usize,
}

impl CappedWriter {
    fn new(output_estimate: usize) -> Result<Self, FrameError> {
        if output_estimate > MAX_OUTPUT_BYTES {
            return Err(FrameError::Validation(
                "output exceeds the supported maximum",
            ));
        }
        let initial_capacity = output_estimate.min(1_048_576);
        let mut bytes = Vec::new();
        if bytes.try_reserve(initial_capacity).is_err() {
            return Err(FrameError::OutOfMemory);
        }
        Ok(Self {
            bytes,
            limit: MAX_OUTPUT_BYTES,
        })
    }
}

impl Write for CappedWriter {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        let remaining = self.limit.saturating_sub(self.bytes.len());
        if bytes.len() > remaining {
            return Err(std::io::Error::other("PNG output capacity exceeded"));
        }
        if self.bytes.try_reserve(bytes.len()).is_err() {
            return Err(std::io::Error::other("PNG output allocation failed"));
        }
        self.bytes.extend_from_slice(bytes);
        Ok(bytes.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

/// Encodes straight-alpha RGBA8 into the same PNG container shape used by the
/// accepted line seam: RGBA8, sRGB perceptual intent, DEFLATE-compressed IDAT
/// per ADR 0018 as amended, no filters, no ancillary chunks.
pub(crate) fn encode_png(rgba: &[u8], width: u32, height: u32) -> Result<Vec<u8>, FrameError> {
    let expected = usize::try_from(width)
        .ok()
        .and_then(|width| {
            usize::try_from(height)
                .ok()
                .and_then(|height| width.checked_mul(height))
        })
        .and_then(|pixels| pixels.checked_mul(4))
        .ok_or(FrameError::Internal("pixel count overflowed"))?;
    if expected != rgba.len() {
        return Err(FrameError::Internal("RGBA buffer length mismatch"));
    }
    let rows_with_filter = expected
        .checked_add(usize::try_from(height).unwrap_or(usize::MAX))
        .ok_or(FrameError::Internal("output estimate overflowed"))?;
    let stored_blocks = rows_with_filter
        .checked_add(65_534)
        .and_then(|value| value.checked_div(65_535))
        .and_then(|value| value.checked_mul(5))
        .ok_or(FrameError::Internal("output estimate overflowed"))?;
    let output_estimate = rows_with_filter
        .checked_add(stored_blocks)
        .and_then(|value| value.checked_add(1_024))
        .ok_or(FrameError::Internal("output estimate overflowed"))?;
    let mut sink = CappedWriter::new(output_estimate)?;
    {
        let mut encoder = Encoder::new(&mut sink, width, height);
        encoder.set_color(ColorType::Rgba);
        encoder.set_depth(BitDepth::Eight);
        encoder.set_source_srgb(SrgbRenderingIntent::Perceptual);
        // ADR-0018: IDAT payloads use DEFLATE (Balanced). Measured on the
        // quickstart fixture (576x432): 995,916 bytes uncompressed ->
        // 2,445 bytes compressed (~407x smaller), versus a 4,367-byte Agg
        // reference for the same figure.
        encoder.set_compression(Compression::Balanced);
        encoder.set_filter(Filter::NoFilter);
        let mut writer = encoder
            .write_header()
            .map_err(|_| FrameError::Internal("PNG encoding failed"))?;
        writer
            .write_image_data(rgba)
            .map_err(|_| FrameError::Internal("PNG encoding failed"))?;
        writer
            .finish()
            .map_err(|_| FrameError::Internal("PNG encoding failed"))?;
    }
    Ok(sink.bytes)
}

/// Full seam entry point: rasterize then encode.
pub(crate) fn render_frame_png(spec: &FrameSpec) -> Result<Vec<u8>, FrameError> {
    let rgba = rasterize(spec)?;
    encode_png(&rgba, spec.width_px, spec.height_px)
}

#[cfg(test)]
mod tests {
    use std::panic::{AssertUnwindSafe, catch_unwind};

    use super::*;

    const IDENTITY: [f64; 6] = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0];

    fn png_dimensions(bytes: &[u8]) -> (u32, u32) {
        assert_eq!(&bytes[..8], b"\x89PNG\r\n\x1a\n", "PNG signature");
        let length = u32::from_be_bytes(bytes[8..12].try_into().expect("length"));
        assert_eq!(&bytes[12..16], b"IHDR", "first chunk is IHDR");
        assert_eq!(length, 13);
        let width = u32::from_be_bytes(bytes[16..20].try_into().expect("width"));
        let height = u32::from_be_bytes(bytes[20..24].try_into().expect("height"));
        (width, height)
    }

    fn frame(width: u32, height: u32) -> FrameSpec {
        FrameSpec::new(width, height, 72.0).expect("frame")
    }

    fn filled_square(x: f64, y: f64, size: f64, rgba: [u8; 4]) -> PathCommand {
        PathCommand::new(
            vec![
                [x, y],
                [x + size, y],
                [x + size, y + size],
                [x, y + size],
                [x, y],
            ],
            None,
            IDENTITY,
            None,
            Some(rgba),
            0.0,
            CapSelector::Butt,
            JoinSelector::Miter,
            0.0,
            None,
            FillRuleSelector::NonZero,
            true,
            None,
        )
        .expect("path command")
    }

    #[test]
    fn empty_commands_render_a_transparent_sized_png() {
        let bytes = render_frame_png(&frame(8, 6)).expect("render");
        assert_eq!(png_dimensions(&bytes), (8, 6));
        // Decode-free check of the raw RGBA payload is not possible from the
        // container alone, so rasterize() is asserted directly instead.
        let rgba = rasterize(&frame(8, 6)).expect("rasterize");
        assert_eq!(rgba.len(), 8 * 6 * 4);
        assert!(rgba.iter().all(|byte| *byte == 0));
    }

    #[test]
    fn width_height_and_dpi_validation_rejects_bad_specs() {
        assert_eq!(
            FrameSpec::new(0, 4, 72.0).err(),
            Some(FrameError::Validation("dimensions must be positive"))
        );
        assert!(FrameSpec::new(16_385, 1, 72.0).is_err());
        // 16385 x 16385 would exceed the pixel budget even though each
        // dimension is at the limit.
        assert!(FrameSpec::new(16_385, 16_385, 72.0).is_err());
        assert_eq!(
            FrameSpec::new(2, 2, 0.0).err(),
            Some(FrameError::Validation("output_dpi must be finite and > 0"))
        );
        assert_eq!(
            FrameSpec::new(2, 2, f64::NAN).err(),
            Some(FrameError::Validation("output_dpi must be finite and > 0"))
        );
    }

    #[test]
    fn path_command_requires_paint_and_finite_geometry() {
        let bare = || {
            PathCommand::new(
                Vec::new(),
                None,
                IDENTITY,
                None,
                None,
                0.0,
                CapSelector::Butt,
                JoinSelector::Miter,
                0.0,
                None,
                FillRuleSelector::NonZero,
                true,
                None,
            )
        };
        assert_eq!(
            bare().err(),
            Some(FrameError::Validation(
                "path command needs stroke_rgba or fill_rgba"
            ))
        );

        let non_finite = |transform: [f64; 6]| {
            PathCommand::new(
                vec![[0.0, 0.0]],
                None,
                transform,
                Some([0, 0, 0, 255]),
                None,
                1.0,
                CapSelector::Butt,
                JoinSelector::Miter,
                0.0,
                None,
                FillRuleSelector::NonZero,
                true,
                None,
            )
        };
        assert!(non_finite([1.0, 0.0, 0.0, 1.0, f64::NAN, 0.0]).is_err());
        assert!(non_finite([1.0, 0.0, 0.0, f64::INFINITY, 0.0, 0.0]).is_err());

        let bad_width = PathCommand::new(
            Vec::new(),
            None,
            IDENTITY,
            Some([0, 0, 0, 255]),
            None,
            -1.0,
            CapSelector::Butt,
            JoinSelector::Miter,
            0.0,
            None,
            FillRuleSelector::NonZero,
            true,
            None,
        );
        assert_eq!(
            bad_width.err(),
            Some(FrameError::Validation("line_width_pt must be >= 0"))
        );
    }

    #[test]
    fn codes_accept_the_documented_set_with_closepoly_dummy() {
        // CLOSEPOLY's vertex is a positional dummy; any finite value works.
        let command = PathCommand::new(
            vec![[0.0, 0.0], [2.0, 0.0], [99.0, 99.0]],
            Some(vec![CODE_MOVETO, CODE_LINETO, CODE_CLOSEPOLY]),
            IDENTITY,
            Some([255, 0, 0, 255]),
            None,
            1.0,
            CapSelector::Butt,
            JoinSelector::Miter,
            0.0,
            None,
            FillRuleSelector::NonZero,
            true,
            None,
        );
        assert!(command.is_ok());

        let unknown = PathCommand::new(
            vec![[0.0, 0.0]],
            Some(vec![7]),
            IDENTITY,
            Some([255, 0, 0, 255]),
            None,
            1.0,
            CapSelector::Butt,
            JoinSelector::Miter,
            0.0,
            None,
            FillRuleSelector::NonZero,
            true,
            None,
        );
        assert_eq!(
            unknown.err(),
            Some(FrameError::Validation("path code is not recognized"))
        );

        let mismatched = PathCommand::new(
            vec![[0.0, 0.0], [1.0, 1.0]],
            Some(vec![CODE_MOVETO]),
            IDENTITY,
            Some([255, 0, 0, 255]),
            None,
            1.0,
            CapSelector::Butt,
            JoinSelector::Miter,
            0.0,
            None,
            FillRuleSelector::NonZero,
            true,
            None,
        );
        assert_eq!(
            mismatched.err(),
            Some(FrameError::Validation(
                "codes length must equal vertices length"
            ))
        );
    }

    #[test]
    fn non_finite_vertices_break_curve_groups_without_reconnection() {
        // A CURVE4 whose control point is NaN must not be drawn at all; its
        // finite end point lifts the pen so the following LINETO starts from
        // the end point instead of drawing back into the dropped group.
        let command = PathCommand::new(
            vec![
                [0.0, 1.0],
                [f64::NAN, 0.0],
                [0.0, 0.0],
                [4.0, 0.0],
                [6.0, 6.0],
            ],
            Some(vec![
                CODE_MOVETO,
                CODE_CURVE4,
                CODE_CURVE4,
                CODE_CURVE4,
                CODE_LINETO,
            ]),
            IDENTITY,
            Some([0, 0, 255, 255]),
            None,
            1.0,
            CapSelector::Butt,
            JoinSelector::Miter,
            0.0,
            None,
            FillRuleSelector::NonZero,
            true,
            None,
        )
        .expect("path");
        let mut spec = frame(8, 8);
        spec.push_command(Command::Path(command)).expect("push");
        let rgba = rasterize(&spec).expect("rasterize");

        let alpha_at = |x: usize, y: usize| rgba[(y * 8 + x) * 4 + 3];
        // Device row 7 is display y=0, where the broken curve would have
        // terminated at (4,0); everything left of x=3 must stay transparent.
        for x in 0..3 {
            assert_eq!(alpha_at(x, 7), 0, "broken curve painted at ({x},7)");
        }
        // The surviving LINETO runs from display (4,0) to (6,6), i.e. device
        // (4,7) to (6,1); its midpoint neighbourhood must be painted.
        let midpoint_painted = (4..=6).any(|x| alpha_at(x, 4) > 0);
        assert!(midpoint_painted, "trailing finite LINETO must paint");
    }

    #[test]
    fn images_place_top_row_at_lower_left_anchor() {
        // 2x1 image: source row 0 is TOP of the image. Anchored at (0, 0)
        // with height 1 it occupies device rows 7 only (display row 0).
        let red = [255u8, 0, 0, 255];
        let green = [0u8, 255, 0, 255];
        let rgba = [
            red[0], red[1], red[2], red[3], green[0], green[1], green[2], green[3],
        ];
        let image = ImageCommand::new(0.0, 0.0, 2, 1, rgba.to_vec(), None).expect("image");
        let mut spec = frame(2, 2);
        spec.push_command(Command::Image(image)).expect("push");
        let rendered = rasterize(&spec).expect("rasterize");
        assert_eq!(rendered.len(), 16);
        // Device rows: row 0 = display y=1 (empty), row 1 = display y=0.
        assert_eq!(&rendered[0..8], [0u8; 8].as_slice());
        assert_eq!(rendered[8], 255);
        assert!(rendered[9] == 0 && rendered[10] == 0);
        assert_eq!(rendered[11], 255);
        assert_eq!(rendered[12], 0);
        assert_eq!(rendered[13], 255);
        assert!(rendered[14] == 0);
        assert_eq!(rendered[15], 255);

        // Same image anchored at display y=1 occupies device row 0 instead.
        let image = ImageCommand::new(0.0, 1.0, 2, 1, vec![255, 0, 0, 255, 0, 255, 0, 255], None)
            .expect("image");
        let mut spec = frame(2, 2);
        spec.push_command(Command::Image(image)).expect("push");
        let rendered = rasterize(&spec).expect("rasterize");
        assert_ne!(&rendered[0..8], [0u8; 8].as_slice());
        assert_eq!(&rendered[8..16], [0u8; 8].as_slice());
    }

    #[test]
    fn same_spec_renders_identical_bytes() {
        let build = || {
            let mut spec = frame(12, 12);
            spec.push_command(Command::Path(filled_square(
                1.0,
                1.0,
                6.0,
                [10, 200, 90, 220],
            )))
            .expect("push");
            spec.push_command(Command::Image(
                ImageCommand::new(
                    4.0,
                    4.0,
                    2,
                    2,
                    vec![
                        255, 128, 0, 255, 0, 255, 128, 255, 9, 9, 9, 200, 250, 250, 250, 130,
                    ],
                    None,
                )
                .expect("image"),
            ))
            .expect("push");
            spec
        };
        let first = render_frame_png(&build()).expect("first render");
        let second = render_frame_png(&build()).expect("second render");
        assert_eq!(first, second);
    }

    #[test]
    fn rasterizer_panics_are_contained_by_the_seam_boundary() {
        struct PanicsOnDrop;
        impl Drop for PanicsOnDrop {
            fn drop(&mut self) {
                if !std::thread::panicking() {
                    panic!("drop panic");
                }
            }
        }
        // The guard is created and dropped INSIDE the closure, mirroring the
        // seam contract: a panic anywhere in the rasterizer (including a
        // panic during unwinding of scoped state) is caught by the boundary,
        // never propagated across PyO3.
        let outcome = catch_unwind(AssertUnwindSafe(|| {
            let _guard = PanicsOnDrop;
            panic!("raster failure");
        }));
        assert!(
            outcome.is_err(),
            "panic must surface as Err, not unwind out"
        );
        // The boundary can be reused after a contained panic.
        let recovered = catch_unwind(AssertUnwindSafe(|| 7));
        assert_eq!(recovered.expect("recovered"), 7);
    }
}
