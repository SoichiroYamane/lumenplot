use std::mem::size_of;

use tiny_skia::Mask;

use crate::error::ExportError;
use crate::raster::RasterPlan;

#[derive(Clone, Copy)]
pub(crate) struct LinearPixel {
    premultiplied: [f64; 3],
    alpha: f64,
}

#[cfg(test)]
thread_local! {
    static FORCE_ALLOCATION_FAILURE: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

#[cfg(test)]
pub(crate) fn set_allocation_failure_for_test(fail: bool) {
    FORCE_ALLOCATION_FAILURE.with(|value| value.set(fail));
}

fn allocation_is_forced_to_fail() -> bool {
    #[cfg(test)]
    {
        FORCE_ALLOCATION_FAILURE.with(std::cell::Cell::get)
    }
    #[cfg(not(test))]
    {
        false
    }
}

pub(crate) fn pixel_storage_bytes(pixel_count: usize) -> Option<usize> {
    pixel_count.checked_mul(size_of::<LinearPixel>())
}

pub(crate) fn rgba_storage_bytes(pixel_count: usize) -> Option<usize> {
    pixel_count.checked_mul(4)
}

pub(crate) fn new_pixels(
    pixel_count: usize,
    background: [u8; 4],
) -> Result<Vec<LinearPixel>, ExportError> {
    if allocation_is_forced_to_fail() {
        return Err(ExportError::allocation_failed());
    }
    let mut pixels = Vec::new();
    pixels
        .try_reserve_exact(pixel_count)
        .map_err(|_| ExportError::allocation_failed())?;
    pixels.resize(pixel_count, linear_pixel_from_rgba(background));
    Ok(pixels)
}

pub(crate) fn composite_mask(
    pixels: &mut [LinearPixel],
    mask: &Mask,
    plan: &RasterPlan,
    color: [u8; 4],
    width: u32,
    height: u32,
) -> Result<(), ExportError> {
    if pixels.len() != plan.pixel_count() || mask.data().len() != pixels.len() {
        return Err(ExportError::internal());
    }
    let source_rgb = [
        decode_srgb_channel(color[0]),
        decode_srgb_channel(color[1]),
        decode_srgb_channel(color[2]),
    ];
    let style_alpha = f64::from(color[3]) / 255.0;
    if !style_alpha.is_finite() || !source_rgb.iter().all(|channel| channel.is_finite()) {
        return Err(ExportError::invalid_input());
    }

    let width = usize::try_from(width).map_err(|_| ExportError::capacity_exceeded())?;
    let height = usize::try_from(height).map_err(|_| ExportError::capacity_exceeded())?;
    for y in 0..height {
        let row = y
            .checked_mul(width)
            .ok_or_else(ExportError::capacity_exceeded)?;
        for x in 0..width {
            let index = row
                .checked_add(x)
                .ok_or_else(ExportError::capacity_exceeded)?;
            let mask_alpha = f64::from(mask.data()[index]) / 255.0;
            let clip_alpha = f64::from(plan.clip_a8(x, y)) / 255.0;
            let alpha = clamp_unit(style_alpha * mask_alpha * clip_alpha);
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
            pixels[index] = source_over(source, pixels[index]);
        }
    }
    Ok(())
}

pub(crate) fn to_rgba8(pixels: &[LinearPixel]) -> Result<Vec<u8>, ExportError> {
    if allocation_is_forced_to_fail() {
        return Err(ExportError::allocation_failed());
    }
    let byte_count = rgba_storage_bytes(pixels.len()).ok_or_else(ExportError::capacity_exceeded)?;
    let mut rgba = Vec::new();
    rgba.try_reserve_exact(byte_count)
        .map_err(|_| ExportError::allocation_failed())?;
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
    Ok(rgba)
}

pub(crate) fn linear_pixel_from_rgba(color: [u8; 4]) -> LinearPixel {
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

pub(crate) fn source_over(source: LinearPixel, destination: LinearPixel) -> LinearPixel {
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

pub(crate) fn decode_srgb_channel(encoded: u8) -> f64 {
    let channel = f64::from(encoded) / 255.0;
    if channel <= 0.04045 {
        channel / 12.92
    } else {
        ((channel + 0.055) / 1.055).powf(2.4)
    }
}

pub(crate) fn encode_srgb_channel(linear: f64) -> f64 {
    let linear = clamp_unit(linear);
    if linear <= 0.0031308 {
        12.92 * linear
    } else {
        1.055 * linear.powf(1.0 / 2.4) - 0.055
    }
}

pub(crate) fn quantize_round_half_even(value: f64) -> u8 {
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

fn clamp_unit(value: f64) -> f64 {
    if value.is_finite() {
        value.clamp(0.0, 1.0)
    } else {
        0.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn transfer_functions_use_the_contract_thresholds() {
        let low = decode_srgb_channel(10);
        assert!((low - (f64::from(10_u8) / 255.0 / 12.92)).abs() < 1e-15);
        let high = decode_srgb_channel(11);
        let expected = ((f64::from(11_u8) / 255.0 + 0.055) / 1.055).powf(2.4);
        assert!((high - expected).abs() < 1e-15);
        assert_eq!(encode_srgb_channel(0.0), 0.0);
        assert!((encode_srgb_channel(0.0031308) - 12.92 * 0.0031308).abs() < 1e-15);
    }

    #[test]
    fn round_half_even_is_explicit() {
        assert_eq!(quantize_round_half_even(0.5 / 255.0), 0);
        assert_eq!(quantize_round_half_even(1.5 / 255.0), 2);
        assert_eq!(quantize_round_half_even(2.5 / 255.0), 2);
        assert_eq!(quantize_round_half_even(3.5 / 255.0), 4);
    }

    #[test]
    fn source_over_keeps_transparent_rgb_premultiplied() {
        let transparent = LinearPixel {
            premultiplied: [0.0, 0.0, 0.0],
            alpha: 0.0,
        };
        let source = LinearPixel {
            premultiplied: [0.25, 0.0, 0.0],
            alpha: 0.5,
        };
        let result = source_over(source, transparent);
        assert_eq!(result.alpha, 0.5);
        assert!((result.premultiplied[0] - 0.25).abs() < 1e-15);
    }

    #[test]
    fn source_over_matches_an_independent_f64_oracle() {
        let source_rgb = [0.2_f64, 0.5, 0.9];
        let source_alpha = 0.35_f64;
        let destination_rgb = [0.8_f64, 0.1, 0.4];
        let destination_alpha = 0.6_f64;
        let source = LinearPixel {
            premultiplied: [
                source_rgb[0] * source_alpha,
                source_rgb[1] * source_alpha,
                source_rgb[2] * source_alpha,
            ],
            alpha: source_alpha,
        };
        let destination = LinearPixel {
            premultiplied: [
                destination_rgb[0] * destination_alpha,
                destination_rgb[1] * destination_alpha,
                destination_rgb[2] * destination_alpha,
            ],
            alpha: destination_alpha,
        };
        let expected_alpha = source_alpha + destination_alpha * (1.0 - source_alpha);
        let expected_premultiplied = [
            source_rgb[0] * source_alpha
                + destination_rgb[0] * destination_alpha * (1.0 - source_alpha),
            source_rgb[1] * source_alpha
                + destination_rgb[1] * destination_alpha * (1.0 - source_alpha),
            source_rgb[2] * source_alpha
                + destination_rgb[2] * destination_alpha * (1.0 - source_alpha),
        ];
        let actual = source_over(source, destination);
        assert!((actual.alpha - expected_alpha).abs() < 1e-15);
        for (actual, expected) in actual.premultiplied.iter().zip(expected_premultiplied) {
            assert!((*actual - expected).abs() < 1e-15);
        }
    }

    #[test]
    fn quantized_transparent_pixels_have_zero_rgb() {
        let pixels = [LinearPixel {
            premultiplied: [0.8, 0.2, 0.1],
            alpha: 0.0,
        }];
        assert_eq!(to_rgba8(&pixels).expect("RGBA"), vec![0, 0, 0, 0]);
    }
}
