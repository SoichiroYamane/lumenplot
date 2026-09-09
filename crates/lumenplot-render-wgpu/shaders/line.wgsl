// Static LumenPlot portable line artifact.
//
// The host supplies screen-space geometry in pixels. The vertex stage maps it
// to top-left-origin normalized device coordinates; the fragment stage applies
// analytic coverage across the expanded triangle edge.

struct Uniforms {
    viewport_px: vec2<f32>,
    half_width_px: f32,
    _padding: f32,
    color_linear: vec4<f32>,
};

@group(0) @binding(0)
var<uniform> uniforms: Uniforms;

struct VertexInput {
    @location(0) position_px: vec2<f32>,
    @location(1) local_px: vec2<f32>,
};

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) local_px: vec2<f32>,
};

@vertex
fn vs_main(input: VertexInput) -> VertexOutput {
    var output: VertexOutput;
    let ndc = vec2<f32>(
        input.position_px.x / uniforms.viewport_px.x * 2.0 - 1.0,
        1.0 - input.position_px.y / uniforms.viewport_px.y * 2.0,
    );
    output.position = vec4<f32>(ndc, 0.0, 1.0);
    output.local_px = input.local_px;
    return output;
}

@fragment
fn fs_main(input: VertexOutput) -> @location(0) vec4<f32> {
    let aa_width_px = 0.75;
    let inner_edge = max(uniforms.half_width_px - aa_width_px, 0.0);
    let outer_edge = uniforms.half_width_px + aa_width_px;
    let coverage = 1.0 - smoothstep(inner_edge, outer_edge, abs(input.local_px.y));
    return vec4<f32>(uniforms.color_linear.rgb, uniforms.color_linear.a * coverage);
}
