// AT-REVIEW-A11Y contrast fixture (LP-UX-031; API-0004 baselines 4.5:1
// normal text / 3:1 large text / 3:1 non-text and focus indicators).
//
// Reads the provisional M5-C defaults in `lumenplot_engine::bridge` without
// touching export encoder semantics: textures, rasters, and encoders are not
// exercised here. Ratios use the WCAG relative-luminance definition and are
// compared UNROUNDED against the baselines. The proposed values are
// explicitly NON-FROZEN (freeze deferred to release review) and carry no
// legal WCAG conformance claim.

use lumenplot_engine::bridge::{DEFAULT_SERIES_CUES, DEFAULT_SERIES_PALETTE, SrgbRgba8};

fn srgb_channel_to_linear(channel: u8) -> f64 {
    let c = f64::from(channel) / 255.0;
    if c <= 0.03928 {
        c / 12.92
    } else {
        ((c + 0.055) / 1.055).powf(2.4)
    }
}

fn relative_luminance(color: SrgbRgba8) -> f64 {
    0.2126 * srgb_channel_to_linear(color.r())
        + 0.7152 * srgb_channel_to_linear(color.g())
        + 0.0722 * srgb_channel_to_linear(color.b())
}

/// Unrounded WCAG contrast ratio of two opaque colors.
fn contrast_ratio(foreground: SrgbRgba8, background: SrgbRgba8) -> f64 {
    assert!(
        foreground.a() == 255,
        "fixture only defines ratios for opaque foregrounds"
    );
    assert!(
        background.a() == 255,
        "fixture only defines ratios for opaque backgrounds"
    );
    let lighter = relative_luminance(foreground).max(relative_luminance(background));
    let darker = relative_luminance(foreground).min(relative_luminance(background));
    (lighter + 0.05) / (darker + 0.05)
}

#[test]
fn at_review_a11y_contrast_defaults_meet_baselines() {
    let background = SrgbRgba8::DEFAULT_BACKGROUND;
    let text = SrgbRgba8::DEFAULT_TEXT_INK;
    let focus = SrgbRgba8::DEFAULT_FOCUS_RING;

    // Defaults are opaque; transparent black canonicalizes to zero rgb in
    // `SrgbRgba8::new`, so opaque values keep the ratio well-defined.
    assert!(background.a() == 255, "background must be opaque");
    assert!(text.a() == 255, "text ink must be opaque");
    assert!(focus.a() == 255, "focus ring must be opaque");

    // 4.5:1 normal-text baseline on the default pair, compared unrounded.
    let text_ratio = contrast_ratio(text, background);
    assert!(
        text_ratio >= 4.5,
        "normal-text baseline 4.5:1 not met on defaults"
    );

    // 3:1 large-text baseline on the same default pair, compared unrounded.
    assert!(
        text_ratio >= 3.0,
        "large-text baseline 3:1 not met on defaults"
    );

    // 3:1 focus-indicator baseline, compared unrounded.
    let focus_ratio = contrast_ratio(focus, background);
    assert!(
        focus_ratio >= 3.0,
        "focus-indicator baseline 3:1 not met on defaults"
    );

    // 3:1 non-text baseline for every provisional series color, unrounded.
    assert!(
        !DEFAULT_SERIES_PALETTE.is_empty(),
        "series palette must not be empty"
    );
    for series in DEFAULT_SERIES_PALETTE.iter() {
        assert!(series.a() == 255, "series entry must be opaque");
        assert!(
            *series != background,
            "series entry must differ from the background"
        );
        let ratio = contrast_ratio(*series, background);
        assert!(
            ratio >= 3.0,
            "non-text baseline 3:1 not met for a series entry"
        );
    }

    // Series entries are pairwise distinct colors.
    for (i, a) in DEFAULT_SERIES_PALETTE.iter().enumerate() {
        for b in DEFAULT_SERIES_PALETTE.iter().skip(i + 1) {
            assert!(a != b, "series palette entries must be pairwise distinct");
        }
    }
}

#[test]
fn at_review_a11y_every_series_has_distinct_non_color_cue() {
    // One cue per palette entry, index-aligned.
    assert_eq!(
        DEFAULT_SERIES_CUES.len(),
        DEFAULT_SERIES_PALETTE.len(),
        "cue table must stay index-aligned with the palette"
    );

    // Every semantic (series) distinction carries a non-color cue: all cues
    // are pairwise distinct, so no two series share the same cue.
    for (i, a) in DEFAULT_SERIES_CUES.iter().enumerate() {
        for b in DEFAULT_SERIES_CUES.iter().skip(i + 1) {
            assert_ne!(
                a, b,
                "series cues must be pairwise distinct (non-color cue per distinction)"
            );
        }
    }
}
