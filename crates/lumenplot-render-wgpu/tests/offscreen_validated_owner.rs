//! Phase-B line-only validated-owner offscreen harness.
//!
//! Scope (commander authorization 2026-09-08): 2D line-only slice through the
//! existing validated packet entry. No fill/bar/step/3D, no new shared
//! command schema, no new public renderer signature, no new dependency.
//!
//! What runs where:
//!
//! - `manifest_metadata_is_authoritative_and_fail_closed`,
//!   `static_runtime_download_negative_guard`, and
//!   `offscreen_renderer_reports_explicit_capability_outcome` run on every
//!   host without a GPU and must pass. They prove build-time/runtime
//!   provenance linkage, the absence of a runtime shader download/compiler
//!   path, and explicit adapter/device outcomes.
//! - `validated_owner_harness_covers_oracle_scales` needs a real portable
//!   adapter/device, so it is `#[ignore]`d by default: an unexecuted cell is
//!   reported as ignored (environment required), never as passed. Run it on
//!   the Lavapipe control cell or a real portable-GPU cell with
//!   `cargo test -p lumenplot-render-wgpu --all-features -- --ignored`.
//!
//! Pixel tolerance: the numeric GPU-vs-CPU/Agg bound stays OPEN until the
//! Lavapipe control cell produces real numbers. This harness therefore
//! asserts validated-submission geometry (dimensions, byte length,
//! stale-generation rejection, repeated submission) and retained-resource
//! observations at 1x/1.25x/2x/3x, and performs no decoded-pixel comparison.
//! Any pixel threshold appearing here in the future must cite measured Lavapipe
//! numbers; fabricated bounds are not accepted.

use lumenplot_render_api::__internal::{
    DeviceGeneration, RenderPacketBuilder, SceneRevision, SrgbRgba8, Viewport, WorkGeneration,
};
use lumenplot_render_api::{FrameSpec, SceneHandle};
use lumenplot_render_wgpu::{
    RenderErrorKind, Renderer, line_shader_provenance, verify_line_shader_artifact,
};

/// Semantic oracle scales for the M3 1x/1.25x/2x/3x matrix.
///
/// The base canvas is a multiple of four so the fractional 1.25x cell lands
/// on integer pixels without rounding policy drift.
const ORACLE_SCALES: [f64; 4] = [1.0, 1.25, 2.0, 3.0];
const ORACLE_BASE_CANVAS: [u32; 2] = [160, 120];
const ORACLE_BASE_PLOT_RECT: [u32; 4] = [16, 12, 144, 108];
const ORACLE_BASE_LINE_WIDTH_PX: f64 = 1.5;
const ORACLE_DPI: f64 = 100.0;

/// Numeric pixel-tolerance status.
///
/// OPEN pending Lavapipe control-cell numbers. No pixel comparison is
/// performed while this reads OPEN; see the module docs.
const GPU_CPU_ORACLE_TOLERANCE_STATUS: &str = "OPEN: numeric GPU-vs-CPU/Agg bound pending Lavapipe control-cell measurement; no fabricated threshold";

/// Pinned manifest provenance (mirrors `shaders/manifest.toml` and the
/// `build.rs` pins). Any manifest mutation must update all three together;
/// each layer fails closed on drift.
const EXPECTED_SOURCE_REVISION: &str = "lumenplot-line-wgsl-v1";
const EXPECTED_VALIDATION: &str =
    "naga WGSL parser plus wgpu 29.0.4 checked shader at renderer initialization";
const EXPECTED_RESOURCE_LAYOUT: &str =
    "group0/binding0 uniform(viewport_px, half_width_px, color_linear)";
const EXPECTED_ARTIFACT_SHA256: &str =
    "e0c3b4d3247963a1b8a96fe91dacb2f1c6f14ee5c31ed1c91fd6bbcc5ec9cbf3";

#[test]
fn manifest_metadata_is_authoritative_and_fail_closed() {
    let manifest = include_str!("../shaders/manifest.toml");
    let pinned = [
        "schema = 1".to_string(),
        "artifact = \"line.wgsl\"".to_string(),
        format!("source_revision = \"{EXPECTED_SOURCE_REVISION}\""),
        format!("sha256 = \"{EXPECTED_ARTIFACT_SHA256}\""),
        "validator = \"naga 29.0.4\"".to_string(),
        format!("validation = \"{EXPECTED_VALIDATION}\""),
        format!("resource_layout = \"{EXPECTED_RESOURCE_LAYOUT}\""),
        "coordinate_space = \"DisplayLogical top-left\"".to_string(),
    ];
    for expected in &pinned {
        assert!(
            manifest.contains(expected),
            "shader manifest drifted from its pinned Phase-B provenance: missing {expected:?}"
        );
    }

    let provenance = line_shader_provenance();
    assert_eq!(provenance.source_revision(), EXPECTED_SOURCE_REVISION);
    assert_eq!(provenance.validation(), EXPECTED_VALIDATION);
    assert_eq!(provenance.resource_layout(), EXPECTED_RESOURCE_LAYOUT);
    assert_eq!(provenance.artifact_sha256(), EXPECTED_ARTIFACT_SHA256);

    // Runtime linkage (manifest env consumed by `src/shader.rs`) plus byte
    // digest plus WGSL parse/validation must all hold before any GPU use.
    verify_line_shader_artifact().expect("static line shader provenance must verify");
}

#[test]
fn static_runtime_download_negative_guard() {
    // Runtime sources must never fetch, download, or compile shaders from
    // the network or the filesystem: the only shader bytes are the
    // compile-time `include_str!` artifact validated above. (`build.rs` is
    // intentionally out of scope here; build-time file reads are its job.)
    let lib = include_str!("../src/lib.rs");
    let shader = include_str!("../src/shader.rs");
    for (name, source) in [("src/lib.rs", lib), ("src/shader.rs", shader)] {
        for forbidden in [
            "reqwest",
            "ureq",
            "hyper::",
            "curl::",
            "http://",
            "https://",
            "std::net::",
            "tokio::",
            "std::process::",
            "std::fs::",
        ] {
            assert!(
                !source.contains(forbidden),
                "runtime shader download/compiler path is forbidden in {name}: found {forbidden:?}"
            );
        }
    }
    assert!(
        shader.contains("include_str!"),
        "the static WGSL artifact must be compiled in via include_str!, never loaded at runtime"
    );
}

#[test]
fn offscreen_renderer_reports_explicit_capability_outcome() {
    // Portable, GPU-independent: creation either succeeds (a real adapter is
    // present) or fails with an explicit capability kind. No silent
    // fallback, no panic, no invented frame.
    match Renderer::new() {
        Ok(_) => {}
        Err(error) => {
            assert!(
                matches!(
                    error.kind(),
                    RenderErrorKind::AdapterUnavailable
                        | RenderErrorKind::DeviceUnavailable
                        | RenderErrorKind::DeviceLost
                        | RenderErrorKind::OutOfMemory
                        | RenderErrorKind::ShaderInvalid
                        | RenderErrorKind::Internal
                ),
                "renderer creation must report an explicit capability outcome, got {:?}: {}",
                error.kind(),
                error.message()
            );
            assert!(
                !error.message().is_empty(),
                "explicit renderer errors carry a sanitized message"
            );
        }
    }
}

#[test]
#[ignore = "environment required: portable GPU adapter/device needed (Lavapipe control or real GPU cell); numeric pixel tolerance stays OPEN until Lavapipe numbers land"]
fn validated_owner_harness_covers_oracle_scales() {
    assert_eq!(
        GPU_CPU_ORACLE_TOLERANCE_STATUS.as_bytes()[0],
        b'O',
        "tolerance gate must stay visibly OPEN (no numeric bound claimed)"
    );
    let mut renderer = Renderer::new().expect(
        "environment required: portable GPU adapter/device unavailable on this host \
         (Lavapipe control or real GPU cell); this is not a renderer failure",
    );
    renderer.bind_device_generation(DeviceGeneration::initial());

    for scale in ORACLE_SCALES {
        let (scene, spec) = oracle_fixture(scale);
        let expected_canvas = oracle_canvas(scale);
        let work = WorkGeneration::initial();
        let device = DeviceGeneration::initial();
        let frame = scene
            .resolve_frame(&spec)
            .expect("oracle seam resolution must succeed");

        // The renderer instance rejects a packet whose expected device
        // generation differs from its owner binding before target/buffer
        // allocation or visible publication.
        let stale_device = DeviceGeneration::new(1);
        let stale_packet = RenderPacketBuilder::new(work, stale_device)
            .build(frame.clone(), work, stale_device)
            .expect("stale packet construction must succeed before owner rejection");
        let observations_before_rejection = renderer.resource_observations();
        let stale_error = renderer
            .render_validated(&stale_packet, SceneRevision::initial(), work, stale_device)
            .expect_err("renderer instance must reject stale device generation");
        assert_eq!(stale_error.kind(), RenderErrorKind::InvalidInput);
        assert_eq!(
            renderer.resource_observations(),
            observations_before_rejection,
            "instance-generation rejection must happen before retained allocation"
        );

        let builder = RenderPacketBuilder::new(work, device);
        let packet = builder
            .build(frame, work, device)
            .expect("oracle validated packet build must succeed");

        // Caller-supplied stale scene/work values remain rejected by the
        // packet boundary without touching retained backend resources.
        for (label, scene_rev, work_gen, device_gen) in [
            ("stale scene", SceneRevision::new(u64::MAX), work, device),
            (
                "stale work",
                SceneRevision::initial(),
                WorkGeneration::new(u64::MAX),
                device,
            ),
        ] {
            let observations_before_rejection = renderer.resource_observations();
            let rejected = renderer.render_validated(&packet, scene_rev, work_gen, device_gen);
            let error = rejected.expect_err(&format!("{label} generation must be rejected"));
            assert_eq!(
                error.kind(),
                RenderErrorKind::InvalidInput,
                "{label} generation must map to InvalidInput"
            );
            assert_eq!(
                renderer.resource_observations(),
                observations_before_rejection,
                "{label} rejection must not allocate or publish"
            );
        }

        let frame = renderer
            .render_validated(&packet, SceneRevision::initial(), work, device)
            .expect("validated oracle render must succeed where a device exists");
        let warmed_allocations = renderer.resource_observations();
        assert!(warmed_allocations.target_allocations() > 0);
        assert!(warmed_allocations.vertex_buffer_allocations() > 0);
        assert!(warmed_allocations.readback_buffer_allocations() > 0);
        assert_eq!(
            frame.width(),
            expected_canvas[0],
            "oracle width at {scale}x"
        );
        assert_eq!(
            frame.height(),
            expected_canvas[1],
            "oracle height at {scale}x"
        );
        assert_eq!(
            frame.rgba8().len(),
            expected_canvas[0] as usize * expected_canvas[1] as usize * 4,
            "oracle frame must be tightly packed RGBA8 at {scale}x"
        );

        // Same-size repeated submission must reuse the retained target,
        // vertex storage, and readback buffer. This is an app-level create
        // observation, not a driver allocation or performance claim.
        let repeated = renderer
            .render_validated(&packet, SceneRevision::initial(), work, device)
            .expect("repeated validated render must succeed");
        assert_eq!(repeated.width(), frame.width());
        assert_eq!(repeated.height(), frame.height());
        assert_eq!(repeated.rgba8().len(), frame.rgba8().len());
        assert_eq!(
            renderer.resource_observations(),
            warmed_allocations,
            "same-size warm render must not recreate retained resources"
        );
    }
}

/// Builds the deterministic monotone-in-x oracle scene and spec for `scale`.
///
/// Canvas and plot rectangle scale geometrically from the base fixture; line
/// width and DPI stay fixed so each cell differs only in frame size. All
/// vertices stay inside the canvas by construction.
fn oracle_fixture(scale: f64) -> (SceneHandle, FrameSpec) {
    let canvas = oracle_canvas(scale);
    let rect = oracle_plot_rect(scale);
    let viewport =
        Viewport::from_bounds(0.0, 1.0, 0.0, 1.0).expect("oracle viewport must be valid");
    let mut scene = SceneHandle::new(viewport).expect("oracle scene must build");
    let points = 64usize;
    let mut xs = Vec::with_capacity(points);
    let mut ys = Vec::with_capacity(points);
    for index in 0..points {
        let t = index as f64 / (points - 1) as f64;
        xs.push(t);
        ys.push(0.1 + 0.8 * t);
    }
    scene
        .add_series(xs, ys)
        .expect("oracle series must be accepted");
    let spec = FrameSpec::new(
        canvas,
        rect,
        ORACLE_DPI,
        SrgbRgba8::new(31, 119, 180, 255),
        ORACLE_BASE_LINE_WIDTH_PX,
        SrgbRgba8::new(255, 255, 255, 255),
    )
    .expect("oracle spec must be valid");
    (scene, spec)
}

fn oracle_canvas(scale: f64) -> [u32; 2] {
    [
        scaled_pixel(ORACLE_BASE_CANVAS[0], scale),
        scaled_pixel(ORACLE_BASE_CANVAS[1], scale),
    ]
}

fn oracle_plot_rect(scale: f64) -> [u32; 4] {
    [
        scaled_pixel(ORACLE_BASE_PLOT_RECT[0], scale),
        scaled_pixel(ORACLE_BASE_PLOT_RECT[1], scale),
        scaled_pixel(ORACLE_BASE_PLOT_RECT[2], scale),
        scaled_pixel(ORACLE_BASE_PLOT_RECT[3], scale),
    ]
}

fn scaled_pixel(base: u32, scale: f64) -> u32 {
    (f64::from(base) * scale).round() as u32
}
