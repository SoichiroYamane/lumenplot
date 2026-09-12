//! Agg-compatible coverage for bounded, simple Line2D strokes.
//!
//! Matplotlib's pinned Agg oracle converts stroked polygon vertices to 24.8
//! fixed-point coordinates and integrates signed edge area per pixel. Tiny-skia
//! uses a 4x4 coverage grid, which is intentionally faster but leaves visible
//! 1/16 coverage steps on oblique stroke fringes. This module implements the
//! same fixed-point area model for isolated, undashed butt- or
//! projecting-capped segments in the adapter-only `agg_srgb` path.
//! Unsupported geometry falls through to the existing tiny-skia rasterizer;
//! native/export linear-light rendering is never routed here.

use tiny_skia::Mask;

use super::{
    CODE_CLOSEPOLY, CODE_CURVE3, CODE_CURVE4, CODE_LINETO, CODE_MOVETO, CODE_STOP, CapSelector,
    FrameError, JoinSelector, PathCommand, coverage_mask,
};

const SUBPIXEL_SHIFT: u32 = 8;
const SUBPIXEL_SCALE: i64 = 1 << SUBPIXEL_SHIFT;
const SUBPIXEL_MASK: i64 = SUBPIXEL_SCALE - 1;
const COVERAGE_SHIFT: u32 = SUBPIXEL_SHIFT * 2 + 1 - 8;
const MAX_CELLS: usize = 1_000_000;
const AUTO_SNAP_VERTEX_LIMIT: usize = 1_024;
const AXIS_ALIGNMENT_EPSILON: f64 = 1.0e-4;
/// Agg's default miter limit (`agg::line_miter_join`). Interior joins whose
/// miter would extend past this revert to a bevel in Agg; the joined-oblique
/// route keeps the explicit tiny-skia fallback there instead of emitting a
/// spike. `PathCommand` carries no miter-limit field, so the Agg default is
/// the only contract-faithful threshold.
const MITER_LIMIT: f64 = 4.0;
/// Largest stroke-quad coordinate magnitude (device px) admitted to the
/// exact single-segment route (see `stroke_polygon`).
const MAX_STROKE_COORD: f64 = 1e9;

#[derive(Clone, Copy, Debug, PartialEq)]
struct Point {
    x: f64,
    y: f64,
}

#[derive(Clone, Copy, Debug)]
struct Segment {
    start: Point,
    end: Point,
}

#[derive(Clone, Copy, Debug)]
struct SubpixelPoint {
    x: i64,
    y: i64,
}

#[derive(Clone, Copy, Debug)]
struct Polygon {
    points: [SubpixelPoint; 4],
}

#[derive(Clone, Copy, Debug, Default)]
struct Cell {
    x: i64,
    y: i64,
    cover: i64,
    area: i64,
}

struct CellRasterizer {
    cells: Vec<Cell>,
    current: Cell,
    has_current: bool,
}

impl CellRasterizer {
    fn new(capacity: usize) -> Result<Self, FrameError> {
        let mut cells = Vec::new();
        cells
            .try_reserve_exact(capacity)
            .map_err(|_| FrameError::OutOfMemory)?;
        Ok(Self {
            cells,
            current: Cell::default(),
            has_current: false,
        })
    }

    fn flush_current(&mut self) -> Result<(), FrameError> {
        if self.has_current && (self.current.cover != 0 || self.current.area != 0) {
            if self.cells.len() == self.cells.capacity() {
                self.cells
                    .try_reserve(1)
                    .map_err(|_| FrameError::OutOfMemory)?;
            }
            self.cells.push(self.current);
        }
        Ok(())
    }

    fn set_current(&mut self, x: i64, y: i64) -> Result<(), FrameError> {
        if !self.has_current || self.current.x != x || self.current.y != y {
            self.flush_current()?;
            self.current = Cell {
                x,
                y,
                cover: 0,
                area: 0,
            };
            self.has_current = true;
        }
        Ok(())
    }

    fn render_scanline_edge(
        &mut self,
        row: i64,
        x1: i64,
        mut y1: i64,
        x2: i64,
        y2: i64,
    ) -> Result<(), FrameError> {
        let mut cell_x1 = x1 >> SUBPIXEL_SHIFT;
        let cell_x2 = x2 >> SUBPIXEL_SHIFT;
        let fractional_x1 = x1 & SUBPIXEL_MASK;
        let fractional_x2 = x2 & SUBPIXEL_MASK;

        if y1 == y2 {
            self.set_current(cell_x2, row)?;
            return Ok(());
        }
        if cell_x1 == cell_x2 {
            let delta = y2 - y1;
            self.current.cover += delta;
            self.current.area += (fractional_x1 + fractional_x2) * delta;
            return Ok(());
        }

        let mut product = (SUBPIXEL_SCALE - fractional_x1) * (y2 - y1);
        let mut first = SUBPIXEL_SCALE;
        let mut increment = 1;
        let mut dx = x2 - x1;
        if dx < 0 {
            product = fractional_x1 * (y2 - y1);
            first = 0;
            increment = -1;
            dx = -dx;
        }

        let mut delta = product / dx;
        let mut remainder_accumulator = product % dx;
        if remainder_accumulator < 0 {
            delta -= 1;
            remainder_accumulator += dx;
        }
        self.current.cover += delta;
        self.current.area += (fractional_x1 + first) * delta;

        cell_x1 += increment;
        self.set_current(cell_x1, row)?;
        y1 += delta;

        if cell_x1 != cell_x2 {
            product = SUBPIXEL_SCALE * (y2 - y1 + delta);
            let mut lift = product / dx;
            let mut remainder = product % dx;
            if remainder < 0 {
                lift -= 1;
                remainder += dx;
            }
            remainder_accumulator -= dx;

            while cell_x1 != cell_x2 {
                delta = lift;
                remainder_accumulator += remainder;
                if remainder_accumulator >= 0 {
                    remainder_accumulator -= dx;
                    delta += 1;
                }
                self.current.cover += delta;
                self.current.area += SUBPIXEL_SCALE * delta;
                y1 += delta;
                cell_x1 += increment;
                self.set_current(cell_x1, row)?;
            }
        }

        delta = y2 - y1;
        self.current.cover += delta;
        self.current.area += (fractional_x2 + SUBPIXEL_SCALE - first) * delta;
        Ok(())
    }

    fn add_edge(&mut self, start: SubpixelPoint, end: SubpixelPoint) -> Result<(), FrameError> {
        let dx = end.x - start.x;
        let mut dy = end.y - start.y;
        let cell_x = start.x >> SUBPIXEL_SHIFT;
        let mut row = start.y >> SUBPIXEL_SHIFT;
        let end_row = end.y >> SUBPIXEL_SHIFT;
        let fractional_y = start.y & SUBPIXEL_MASK;
        let end_fractional_y = end.y & SUBPIXEL_MASK;

        self.set_current(cell_x, row)?;
        if row == end_row {
            return self.render_scanline_edge(row, start.x, fractional_y, end.x, end_fractional_y);
        }

        let mut increment = 1;
        if dx == 0 {
            let doubled_fractional_x = (start.x - (cell_x << SUBPIXEL_SHIFT)) << 1;
            let mut first = SUBPIXEL_SCALE;
            if dy < 0 {
                first = 0;
                increment = -1;
            }

            let mut delta = first - fractional_y;
            self.current.cover += delta;
            self.current.area += doubled_fractional_x * delta;
            row += increment;
            self.set_current(cell_x, row)?;

            delta = first + first - SUBPIXEL_SCALE;
            let area = doubled_fractional_x * delta;
            while row != end_row {
                self.current.cover = delta;
                self.current.area = area;
                row += increment;
                self.set_current(cell_x, row)?;
            }

            delta = end_fractional_y - SUBPIXEL_SCALE + first;
            self.current.cover += delta;
            self.current.area += doubled_fractional_x * delta;
            return Ok(());
        }

        let mut product = (SUBPIXEL_SCALE - fractional_y) * dx;
        let mut first = SUBPIXEL_SCALE;
        if dy < 0 {
            product = fractional_y * dx;
            first = 0;
            increment = -1;
            dy = -dy;
        }

        let mut delta = product / dy;
        let mut remainder_accumulator = product % dy;
        if remainder_accumulator < 0 {
            delta -= 1;
            remainder_accumulator += dy;
        }

        let mut x_from = start.x + delta;
        self.render_scanline_edge(row, start.x, fractional_y, x_from, first)?;
        row += increment;
        self.set_current(x_from >> SUBPIXEL_SHIFT, row)?;

        if row != end_row {
            product = SUBPIXEL_SCALE * dx;
            let mut lift = product / dy;
            let mut remainder = product % dy;
            if remainder < 0 {
                lift -= 1;
                remainder += dy;
            }
            remainder_accumulator -= dy;

            while row != end_row {
                delta = lift;
                remainder_accumulator += remainder;
                if remainder_accumulator >= 0 {
                    remainder_accumulator -= dy;
                    delta += 1;
                }
                let x_to = x_from + delta;
                self.render_scanline_edge(row, x_from, SUBPIXEL_SCALE - first, x_to, first)?;
                x_from = x_to;
                row += increment;
                self.set_current(x_from >> SUBPIXEL_SHIFT, row)?;
            }
        }

        self.render_scanline_edge(row, x_from, SUBPIXEL_SCALE - first, end.x, end_fractional_y)
    }

    fn add_polygon(&mut self, polygon: Polygon) -> Result<(), FrameError> {
        for index in 0..polygon.points.len() {
            let next = (index + 1) % polygon.points.len();
            self.add_edge(polygon.points[index], polygon.points[next])?;
        }
        Ok(())
    }

    fn add_contour(&mut self, points: &[SubpixelPoint]) -> Result<(), FrameError> {
        if points.len() < 3 {
            return Ok(());
        }
        for index in 0..points.len() {
            let next = (index + 1) % points.len();
            self.add_edge(points[index], points[next])?;
        }
        Ok(())
    }

    fn write_mask(mut self, mask: &mut Mask, width: u32, height: u32) -> Result<(), FrameError> {
        self.flush_current()?;
        self.cells.sort_unstable_by_key(|cell| (cell.y, cell.x));

        let mut index = 0usize;
        while index < self.cells.len() {
            let row = self.cells[index].y;
            let row_start = index;
            while index < self.cells.len() && self.cells[index].y == row {
                index += 1;
            }
            if row < 0 || row >= i64::from(height) {
                continue;
            }
            self.write_row(mask, width, row as u32, row_start, index);
        }
        Ok(())
    }

    fn write_row(&self, mask: &mut Mask, width: u32, row: u32, mut index: usize, row_end: usize) {
        let mut cover = 0i64;
        while index < row_end {
            let mut x = self.cells[index].x;
            let mut area = 0i64;
            while index < row_end && self.cells[index].x == x {
                cover += self.cells[index].cover;
                area += self.cells[index].area;
                index += 1;
            }

            if area != 0 {
                let alpha = coverage_alpha((cover << (SUBPIXEL_SHIFT + 1)) - area);
                write_cell(mask, width, row, x, alpha);
                x += 1;
            }

            if index < row_end && self.cells[index].x > x {
                let alpha = coverage_alpha(cover << (SUBPIXEL_SHIFT + 1));
                write_span(mask, width, row, x, self.cells[index].x, alpha);
            }
        }
    }
}

pub(super) fn try_rasterize(
    command: &PathCommand,
    width: u32,
    height: u32,
    pixel_count: usize,
    scale: f64,
) -> Result<Option<Mask>, FrameError> {
    if !command.antialias
        || !matches!(command.cap, CapSelector::Butt | CapSelector::Projecting)
        || !matches!(command.join, JoinSelector::Miter)
        || command
            .dashes
            .as_ref()
            .is_some_and(|dashes| !dashes.is_empty())
        || !command.stroke_rgba.is_some_and(|rgba| rgba[3] == u8::MAX)
    {
        return Ok(None);
    }

    let stroke_width = command.line_width_pt * scale;
    if !stroke_width.is_finite() || stroke_width <= 0.0 {
        return Ok(None);
    }
    // Closed axis-aligned rect-stroke rings (bars) carry both fill and
    // stroke: the fill branch composites separately, so the stroke mask is
    // the ring only. Try the ring first; the line path below preserves the
    // F1 fill-absent contract.
    if let Some(ring) = extract_rect_ring(command, height)? {
        return rasterize_rect_ring(ring, command, width, height, pixel_count, scale);
    }
    if let Some(chain) = extract_rectilinear_chain(command, height)? {
        return rasterize_rectilinear_chain(chain, command, width, height, pixel_count, scale);
    }
    if let Some(chain) = extract_oblique_chain(command, height)? {
        return rasterize_oblique_chain(chain, command, width, height, pixel_count, scale);
    }
    if let Some(loop_points) = extract_closed_curve_loop(command, height)? {
        return rasterize_closed_curve_loop(
            loop_points,
            command,
            width,
            height,
            pixel_count,
            scale,
        );
    }
    if command.fill_rgba.is_some() {
        return Ok(None);
    }
    let mut segments = match extract_segments(command, height)? {
        Some(segments) if !segments.is_empty() => segments,
        _ => return Ok(None),
    };

    if command.vertices.len() <= AUTO_SNAP_VERTEX_LIMIT
        && segments.iter().all(|segment| {
            (segment.start.x - segment.end.x).abs() < AXIS_ALIGNMENT_EPSILON
                || (segment.start.y - segment.end.y).abs() < AXIS_ALIGNMENT_EPSILON
        })
    {
        let snap_offset = if (stroke_width.round() as i64) % 2 == 0 {
            0.0
        } else {
            0.5
        };
        for segment in &mut segments {
            segment.start.x = (segment.start.x + 0.5).floor() + snap_offset;
            segment.start.y = (segment.start.y + 0.5).floor() + snap_offset;
            segment.end.x = (segment.end.x + 0.5).floor() + snap_offset;
            segment.end.y = (segment.end.y + 0.5).floor() + snap_offset;
        }
    }

    if matches!(command.cap, CapSelector::Projecting) {
        // Agg generates projecting caps during stroking, after snapping:
        // extend each snapped segment by half the stroke width along its
        // direction so the quad covers the cap rectangles (axes spines
        // meet the axes corners exactly this way).
        let extension = stroke_width * 0.5;
        if !extension.is_finite() || extension < 0.0 {
            return Ok(None);
        }
        for segment in &mut segments {
            let dx = segment.end.x - segment.start.x;
            let dy = segment.end.y - segment.start.y;
            let length = dx.hypot(dy);
            if !length.is_finite() || length <= 0.0 {
                return Ok(None);
            }
            segment.start.x -= dx / length * extension;
            segment.start.y -= dy / length * extension;
            segment.end.x += dx / length * extension;
            segment.end.y += dy / length * extension;
        }
    }

    let mut polygons = Vec::new();
    polygons
        .try_reserve_exact(segments.len())
        .map_err(|_| FrameError::OutOfMemory)?;
    for segment in segments {
        let Some(polygon) = stroke_polygon(segment, stroke_width) else {
            return Ok(None);
        };
        polygons.push(polygon);
    }

    let Some(cell_capacity) = cell_capacity_bound(&polygons) else {
        return Ok(None);
    };
    let mut rasterizer = CellRasterizer::new(cell_capacity)?;
    for polygon in polygons {
        rasterizer.add_polygon(polygon)?;
    }
    let mut mask = coverage_mask(width, height, pixel_count)?;
    rasterizer.write_mask(&mut mask, width, height)?;
    Ok(Some(mask))
}

pub(super) fn try_rasterize_triangle_fill(
    command: &PathCommand,
    width: u32,
    height: u32,
    pixel_count: usize,
) -> Result<Option<Mask>, FrameError> {
    if !command.triangle_agg || command.vertices.len() < 3 {
        return Ok(None);
    }
    let mut points = [SubpixelPoint { x: 0, y: 0 }; 3];
    for (index, vertex) in command.vertices.iter().take(3).enumerate() {
        let Some(point) = map_device_point(command.transform, *vertex, height) else {
            return Ok(None);
        };
        points[index] = to_subpixel(point);
    }
    let polygon = Polygon {
        points: [points[0], points[1], points[2], points[0]],
    };
    let Some(cell_capacity) = cell_capacity_bound(&[polygon]) else {
        return Ok(None);
    };
    let mut rasterizer = CellRasterizer::new(cell_capacity)?;
    rasterizer.add_polygon(polygon)?;
    let mut mask = coverage_mask(width, height, pixel_count)?;
    rasterizer.write_mask(&mut mask, width, height)?;
    if !command.antialias {
        for value in mask.data_mut() {
            *value = u8::from(*value != 0) * u8::MAX;
        }
    }
    Ok(Some(mask))
}

fn extract_degenerate_rect_segment(
    command: &PathCommand,
    height: u32,
) -> Result<Option<Segment>, FrameError> {
    let Some(codes) = command.codes.as_ref() else {
        return Ok(None);
    };
    if command.vertices.len() != 5
        || codes.len() != 5
        || codes[0] != CODE_MOVETO
        || codes[1] != CODE_LINETO
        || codes[2] != CODE_LINETO
        || codes[3] != CODE_LINETO
        || codes[4] != CODE_CLOSEPOLY
    {
        return Ok(None);
    }
    let mut corners = [Point { x: 0.0, y: 0.0 }; 4];
    for (index, corner) in corners.iter_mut().enumerate() {
        let Some(point) = map_device_point(command.transform, command.vertices[index], height)
        else {
            return Ok(None);
        };
        *corner = point;
    }
    for index in 0..4 {
        let start = corners[index];
        let end = corners[(index + 1) % 4];
        let dx = (start.x - end.x).abs();
        let dy = (start.y - end.y).abs();
        if dx >= AXIS_ALIGNMENT_EPSILON && dy >= AXIS_ALIGNMENT_EPSILON {
            return Ok(None);
        }
    }
    let min_x = corners
        .iter()
        .map(|point| point.x)
        .fold(f64::INFINITY, f64::min);
    let max_x = corners
        .iter()
        .map(|point| point.x)
        .fold(f64::NEG_INFINITY, f64::max);
    let min_y = corners
        .iter()
        .map(|point| point.y)
        .fold(f64::INFINITY, f64::min);
    let max_y = corners
        .iter()
        .map(|point| point.y)
        .fold(f64::NEG_INFINITY, f64::max);
    if !min_x.is_finite() || !max_x.is_finite() || !min_y.is_finite() || !max_y.is_finite() {
        return Ok(None);
    }
    let zero_width = max_x - min_x <= AXIS_ALIGNMENT_EPSILON;
    let zero_height = max_y - min_y <= AXIS_ALIGNMENT_EPSILON;
    if zero_width == zero_height {
        return Ok(None);
    }
    for point in corners {
        let on_x = (point.x - min_x).abs() < AXIS_ALIGNMENT_EPSILON
            || (point.x - max_x).abs() < AXIS_ALIGNMENT_EPSILON;
        let on_y = (point.y - min_y).abs() < AXIS_ALIGNMENT_EPSILON
            || (point.y - max_y).abs() < AXIS_ALIGNMENT_EPSILON;
        if !on_x || !on_y {
            return Ok(None);
        }
    }
    let segment = if zero_height {
        Segment {
            start: Point { x: min_x, y: min_y },
            end: Point { x: max_x, y: min_y },
        }
    } else {
        Segment {
            start: Point { x: min_x, y: min_y },
            end: Point { x: min_x, y: max_y },
        }
    };
    Ok(Some(segment))
}

fn extract_segments(
    command: &PathCommand,
    height: u32,
) -> Result<Option<Vec<Segment>>, FrameError> {
    if let Some(segment) = extract_degenerate_rect_segment(command, height)? {
        let mut segments = Vec::new();
        segments
            .try_reserve_exact(1)
            .map_err(|_| FrameError::OutOfMemory)?;
        segments.push(segment);
        return Ok(Some(segments));
    }
    let capacity = command.vertices.len().saturating_add(1) / 2;
    let mut segments = Vec::new();
    segments
        .try_reserve_exact(capacity)
        .map_err(|_| FrameError::OutOfMemory)?;
    let mut first = None;
    let mut second = None;

    for (index, vertex) in command.vertices.iter().enumerate() {
        let code = command.codes.as_ref().map_or(
            if index == 0 { CODE_MOVETO } else { CODE_LINETO },
            |codes| codes[index],
        );
        if code == CODE_STOP {
            finish_subpath(&mut first, &mut second, &mut segments);
            break;
        }
        if code != CODE_MOVETO && code != CODE_LINETO {
            return Ok(None);
        }

        let point = map_device_point(command.transform, *vertex, height);
        if code == CODE_MOVETO {
            finish_subpath(&mut first, &mut second, &mut segments);
            first = point;
            continue;
        }
        let Some(point) = point else {
            finish_subpath(&mut first, &mut second, &mut segments);
            continue;
        };
        match (first, second) {
            (None, _) => first = Some(point),
            (Some(_), None) => second = Some(point),
            (Some(_), Some(_)) => return Ok(None),
        }
    }
    finish_subpath(&mut first, &mut second, &mut segments);
    Ok(Some(segments))
}

fn finish_subpath(
    first: &mut Option<Point>,
    second: &mut Option<Point>,
    segments: &mut Vec<Segment>,
) {
    if let (Some(start), Some(end)) = (*first, *second)
        && start != end
    {
        segments.push(Segment { start, end });
    }
    *first = None;
    *second = None;
}

/// Closed axis-aligned rect-stroke ring (bar outline) in device space.
#[derive(Clone, Copy, Debug)]
struct RectRing {
    corners: [Point; 4],
}

/// Detects the bar-rectangle loop: exactly five vertices with explicit
/// codes `[MOVETO, LINETO, LINETO, LINETO, CLOSEPOLY]` whose four corners
/// form an axis-aligned non-degenerate rectangle in device space.
///
/// Anything else (open lines, curves, non-rectangular polygons, degenerate
/// zero-area bars) returns `Ok(None)` so the caller falls through to the
/// existing line or tiny-skia paths. Zero-area bars stay skipped at
/// emission (phase-3 scope) and never reach the ring integrator.
fn extract_rect_ring(command: &PathCommand, height: u32) -> Result<Option<RectRing>, FrameError> {
    let Some(codes) = command.codes.as_ref() else {
        return Ok(None);
    };
    if command.vertices.len() != 5
        || codes.len() != 5
        || codes[0] != CODE_MOVETO
        || codes[1] != CODE_LINETO
        || codes[2] != CODE_LINETO
        || codes[3] != CODE_LINETO
        || codes[4] != CODE_CLOSEPOLY
    {
        return Ok(None);
    }
    let mut corners = [Point { x: 0.0, y: 0.0 }; 4];
    for (index, corner) in corners.iter_mut().enumerate() {
        let Some(point) = map_device_point(command.transform, command.vertices[index], height)
        else {
            return Ok(None);
        };
        *corner = point;
    }
    // Every edge (including the implicit close p3->p0) must be
    // axis-aligned. This also rejects bow-tie orderings whose diagonals
    // would be oblique.
    for index in 0..4 {
        let start = corners[index];
        let end = corners[(index + 1) % 4];
        let dx = (start.x - end.x).abs();
        let dy = (start.y - end.y).abs();
        if dx >= AXIS_ALIGNMENT_EPSILON && dy >= AXIS_ALIGNMENT_EPSILON {
            return Ok(None);
        }
    }
    let min_x = corners
        .iter()
        .map(|point| point.x)
        .fold(f64::INFINITY, f64::min);
    let max_x = corners
        .iter()
        .map(|point| point.x)
        .fold(f64::NEG_INFINITY, f64::max);
    let min_y = corners
        .iter()
        .map(|point| point.y)
        .fold(f64::INFINITY, f64::min);
    let max_y = corners
        .iter()
        .map(|point| point.y)
        .fold(f64::NEG_INFINITY, f64::max);
    if !min_x.is_finite() || !max_x.is_finite() || !min_y.is_finite() || !max_y.is_finite() {
        return Ok(None);
    }
    if max_x - min_x <= AXIS_ALIGNMENT_EPSILON || max_y - min_y <= AXIS_ALIGNMENT_EPSILON {
        // Degenerate (zero-area) bar: no ring area. The adapter skips
        // these at emission; stay ineligible so the fallback (paint
        // nothing) is preserved.
        return Ok(None);
    }
    // All four corners must sit on the bounding-box corners: this proves a
    // true rectangle rather than a degenerate axis-aligned quadrilateral
    // (e.g. a doubled-back line).
    let mut seen = [false; 4];
    for point in corners {
        let x_min = (point.x - min_x).abs() < AXIS_ALIGNMENT_EPSILON;
        let x_max = (point.x - max_x).abs() < AXIS_ALIGNMENT_EPSILON;
        let y_min = (point.y - min_y).abs() < AXIS_ALIGNMENT_EPSILON;
        let y_max = (point.y - max_y).abs() < AXIS_ALIGNMENT_EPSILON;
        let slot = match (x_min, x_max, y_min, y_max) {
            (true, false, true, false) => 0,
            (false, true, true, false) => 1,
            (false, true, false, true) => 2,
            (true, false, false, true) => 3,
            _ => return Ok(None),
        };
        if seen[slot] {
            return Ok(None);
        }
        seen[slot] = true;
    }
    Ok(Some(RectRing { corners }))
}

/// Open rectilinear stroke chain (step polyline) in device space.
///
/// Detects stroke-only open polylines with three or more finite vertices,
/// a single `MOVETO`-then-`LINETO` subpath (implicit `codes=None` or explicit
/// codes), every segment axis-aligned and non-degenerate, and no
/// 180-degree reversal. Anything else (single segments, oblique geometry,
/// curves, close codes, gaps, fills) returns `Ok(None)` so the caller falls
/// through to the existing F1 single-segment or tiny-skia paths.
fn extract_rectilinear_chain(
    command: &PathCommand,
    height: u32,
) -> Result<Option<Vec<Point>>, FrameError> {
    if command.fill_rgba.is_some() {
        return Ok(None);
    }
    // The joined outline below emits butt caps implicitly; projecting
    // chains stay on the single-segment route, which extends caps
    // explicitly.
    if !matches!(command.cap, CapSelector::Butt) {
        return Ok(None);
    }
    if command.vertices.len() < 3 || command.vertices.len() > AUTO_SNAP_VERTEX_LIMIT {
        return Ok(None);
    }
    if let Some(codes) = command.codes.as_ref() {
        if codes.len() != command.vertices.len() || codes[0] != CODE_MOVETO {
            return Ok(None);
        }
        for code in codes.iter().skip(1) {
            if *code != CODE_LINETO {
                return Ok(None);
            }
        }
    }
    let mut points = Vec::new();
    points
        .try_reserve_exact(command.vertices.len())
        .map_err(|_| FrameError::OutOfMemory)?;
    for vertex in &command.vertices {
        let Some(point) = map_device_point(command.transform, *vertex, height) else {
            return Ok(None);
        };
        points.push(point);
    }
    let mut previous_direction: Option<(f64, f64)> = None;
    for window in points.windows(2) {
        let dx = window[1].x - window[0].x;
        let dy = window[1].y - window[0].y;
        if !dx.is_finite() || !dy.is_finite() {
            return Ok(None);
        }
        if dx.abs() < AXIS_ALIGNMENT_EPSILON && dy.abs() < AXIS_ALIGNMENT_EPSILON {
            return Ok(None);
        }
        if dx.abs() >= AXIS_ALIGNMENT_EPSILON && dy.abs() >= AXIS_ALIGNMENT_EPSILON {
            return Ok(None);
        }
        let length = dx.hypot(dy);
        if !length.is_finite() || length <= AXIS_ALIGNMENT_EPSILON {
            return Ok(None);
        }
        let direction = (dx / length, dy / length);
        if let Some(previous) = previous_direction {
            let dot = previous.0 * direction.0 + previous.1 * direction.1;
            let cross = previous.0 * direction.1 - previous.1 * direction.0;
            if cross.abs() < 1.0e-9 {
                if dot < -0.5 {
                    return Ok(None);
                }
            } else if (cross.abs() - 1.0).abs() > 1.0e-6 {
                return Ok(None);
            }
        }
        previous_direction = Some(direction);
    }
    Ok(Some(points))
}

fn contour_capacity_bound(points: &[SubpixelPoint]) -> Option<usize> {
    if points.len() < 3 {
        return None;
    }
    let mut capacity = 0usize;
    for index in 0..points.len() {
        let start = points[index];
        let end = points[(index + 1) % points.len()];
        let x_cells = usize::try_from(
            (end.x - start.x)
                .unsigned_abs()
                .div_ceil(SUBPIXEL_SCALE as u64),
        )
        .ok()?;
        let y_cells = usize::try_from(
            (end.y - start.y)
                .unsigned_abs()
                .div_ceil(SUBPIXEL_SCALE as u64),
        )
        .ok()?;
        capacity = capacity
            .checked_add(x_cells)?
            .checked_add(y_cells)?
            .checked_add(8)?;
        if capacity > MAX_CELLS {
            return None;
        }
    }
    Some(capacity.max(1))
}

/// Rasterizes an open rectilinear chain as one JOINED miter outline.
///
/// Vertices are snapped with the existing rectilinear rule before stroking
/// (Agg `PathSnapper` behavior for rectilinear paths). The outline follows
/// Agg `vcgen_stroke` emission order for open paths (cap1, outline1, cap2,
/// outline2): start cap L0->R0, right side forward, end cap Rn->Ln, left
/// side backward, close L1->L0. This counter-clockwise (device-space)
/// winding must be preserved exactly: the shared cell integrator floors
/// `(cover << 9) - area`, so the opposite winding rounds fractional joint
/// cells one LSB lower (pinned Agg steps oracle: CW leaves 42 fringe
/// mismatches, CCW converges to 0 with byte-identical runs and caps).
/// The single contour is fed to the shared cell accumulator;
/// per-segment quads are never used (overlaps would double-darken the
/// joins under nonzero winding).
fn rasterize_rectilinear_chain(
    chain: Vec<Point>,
    command: &PathCommand,
    width: u32,
    height: u32,
    pixel_count: usize,
    scale: f64,
) -> Result<Option<Mask>, FrameError> {
    let stroke_width = command.line_width_pt * scale;
    if !stroke_width.is_finite() || stroke_width <= 0.0 {
        return Ok(None);
    }
    if chain.len() < 3 || chain.len() > AUTO_SNAP_VERTEX_LIMIT {
        return Ok(None);
    }
    let snap_offset = rect_snap_value(stroke_width);
    let mut snapped = Vec::new();
    snapped
        .try_reserve_exact(chain.len())
        .map_err(|_| FrameError::OutOfMemory)?;
    for point in chain {
        let x = (point.x + 0.5).floor() + snap_offset;
        let y = (point.y + 0.5).floor() + snap_offset;
        if !x.is_finite() || !y.is_finite() {
            return Ok(None);
        }
        snapped.push(Point { x, y });
    }
    let half = stroke_width * 0.5;
    if !half.is_finite() || half <= 0.0 {
        return Ok(None);
    }
    let segments = snapped.len() - 1;
    let mut normals: Vec<(f64, f64)> = Vec::new();
    normals
        .try_reserve_exact(segments)
        .map_err(|_| FrameError::OutOfMemory)?;
    for window in snapped.windows(2) {
        let dx = window[1].x - window[0].x;
        let dy = window[1].y - window[0].y;
        let length = dx.hypot(dy);
        if !length.is_finite() || length <= AXIS_ALIGNMENT_EPSILON {
            return Ok(None);
        }
        let ux = dx / length;
        let uy = dy / length;
        normals.push((-uy * half, ux * half));
    }
    let mut left: Vec<Point> = Vec::new();
    let mut right: Vec<Point> = Vec::new();
    left.try_reserve_exact(snapped.len())
        .map_err(|_| FrameError::OutOfMemory)?;
    right
        .try_reserve_exact(snapped.len())
        .map_err(|_| FrameError::OutOfMemory)?;
    left.push(Point {
        x: snapped[0].x + normals[0].0,
        y: snapped[0].y + normals[0].1,
    });
    right.push(Point {
        x: snapped[0].x - normals[0].0,
        y: snapped[0].y - normals[0].1,
    });
    for index in 1..snapped.len() - 1 {
        let (in_x, in_y) = normals[index - 1];
        let (out_x, out_y) = normals[index];
        let straight = (in_x - out_x).abs() < 1.0e-9 && (in_y - out_y).abs() < 1.0e-9;
        if straight {
            left.push(Point {
                x: snapped[index].x + in_x,
                y: snapped[index].y + in_y,
            });
            right.push(Point {
                x: snapped[index].x - in_x,
                y: snapped[index].y - in_y,
            });
        } else {
            left.push(Point {
                x: snapped[index].x + in_x + out_x,
                y: snapped[index].y + in_y + out_y,
            });
            right.push(Point {
                x: snapped[index].x - in_x - out_x,
                y: snapped[index].y - in_y - out_y,
            });
        }
    }
    let last = snapped.len() - 1;
    left.push(Point {
        x: snapped[last].x + normals[segments - 1].0,
        y: snapped[last].y + normals[segments - 1].1,
    });
    right.push(Point {
        x: snapped[last].x - normals[segments - 1].0,
        y: snapped[last].y - normals[segments - 1].1,
    });
    if left
        .iter()
        .chain(right.iter())
        .any(|point| !point.x.is_finite() || !point.y.is_finite())
    {
        return Ok(None);
    }
    let mut contour: Vec<SubpixelPoint> = Vec::new();
    contour
        .try_reserve_exact(left.len() + right.len())
        .map_err(|_| FrameError::OutOfMemory)?;
    contour.push(to_subpixel(left[0]));
    for point in &right {
        contour.push(to_subpixel(*point));
    }
    for point in left[1..].iter().rev() {
        contour.push(to_subpixel(*point));
    }
    let Some(cell_capacity) = contour_capacity_bound(&contour) else {
        return Ok(None);
    };
    let mut rasterizer = CellRasterizer::new(cell_capacity)?;
    rasterizer.add_contour(&contour)?;
    let mut mask = coverage_mask(width, height, pixel_count)?;
    rasterizer.write_mask(&mut mask, width, height)?;
    Ok(Some(mask))
}

/// Open joined-oblique stroke chain in device space.
///
/// Detects stroke-only open polylines with three or more finite vertices, a
/// single `MOVETO`-then-`LINETO` subpath (implicit `codes=None` or explicit
/// codes), every segment finite and non-degenerate, at least one oblique
/// segment, and every interior turn inside Agg's default miter limit.
/// Anything else (shorter chains, all-axis-aligned chains, curves, close or
/// stop codes, gaps, fills, degenerate turns, over-limit miters) returns
/// `Ok(None)` so the caller falls through to the existing rectilinear,
/// single-segment, or tiny-skia paths.
fn extract_oblique_chain(
    command: &PathCommand,
    height: u32,
) -> Result<Option<Vec<Point>>, FrameError> {
    if command.fill_rgba.is_some() {
        return Ok(None);
    }
    // Same butt-only scope as the rectilinear chain: projecting caps are
    // extended explicitly on the single-segment route below.
    if !matches!(command.cap, CapSelector::Butt) {
        return Ok(None);
    }
    if command.vertices.len() < 3 || command.vertices.len() > AUTO_SNAP_VERTEX_LIMIT {
        return Ok(None);
    }
    if let Some(codes) = command.codes.as_ref() {
        if codes.len() != command.vertices.len() || codes[0] != CODE_MOVETO {
            return Ok(None);
        }
        for code in codes.iter().skip(1) {
            if *code != CODE_LINETO {
                return Ok(None);
            }
        }
    }
    let mut points = Vec::new();
    points
        .try_reserve_exact(command.vertices.len())
        .map_err(|_| FrameError::OutOfMemory)?;
    for vertex in &command.vertices {
        let Some(point) = map_device_point(command.transform, *vertex, height) else {
            return Ok(None);
        };
        if !point.x.is_finite() || !point.y.is_finite() {
            return Ok(None);
        }
        points.push(point);
    }
    // The miter ratio at an interior turn is `1 / cos(theta / 2)` where
    // `theta` is the tangent turn angle; Agg's default limit reverts past
    // `MITER_LIMIT`, i.e. `cos(theta) <= 2 / MITER_LIMIT^2 - 1`. Gate the
    // tangent turn there so `1 + dot` in the rasterizer stays above 0.125
    // and no spike is ever emitted.
    let miter_dot_floor = 2.0 / (MITER_LIMIT * MITER_LIMIT) - 1.0;
    let mut has_oblique = false;
    let mut previous: Option<(f64, f64)> = None;
    for window in points.windows(2) {
        let dx = window[1].x - window[0].x;
        let dy = window[1].y - window[0].y;
        if !dx.is_finite() || !dy.is_finite() {
            return Ok(None);
        }
        let length = dx.hypot(dy);
        if !length.is_finite() || length <= AXIS_ALIGNMENT_EPSILON {
            return Ok(None);
        }
        has_oblique = has_oblique
            || (dx.abs() >= AXIS_ALIGNMENT_EPSILON && dy.abs() >= AXIS_ALIGNMENT_EPSILON);
        let direction = (dx / length, dy / length);
        if let Some(previous) = previous {
            let dot = previous.0 * direction.0 + previous.1 * direction.1;
            if !dot.is_finite() || dot <= miter_dot_floor {
                return Ok(None);
            }
        }
        previous = Some(direction);
    }
    if !has_oblique {
        return Ok(None);
    }
    Ok(Some(points))
}

/// Rasterizes an open oblique chain as one JOINED miter outline.
///
/// Agg never snaps oblique paths, so vertices are stroked unsnapped (unlike
/// the rectilinear route). Each interior join uses the exact offset-line
/// intersection `half * (n1 + n2) / (1 + dot)` where `n1`, `n2` are the unit
/// side normals (Agg `line_miter_join` geometry): it reduces to `in + out`
/// for 90-degree turns and to the segment normal for straight runs, so it
/// coincides with the rectilinear precedent on that precedent's domain. The
/// contour follows the same Agg `vcgen_stroke` emission order (start cap,
/// right side forward, end cap, left side backward), and the single contour
/// is fed to the shared cell accumulator so joins never double-darken.
fn rasterize_oblique_chain(
    chain: Vec<Point>,
    command: &PathCommand,
    width: u32,
    height: u32,
    pixel_count: usize,
    scale: f64,
) -> Result<Option<Mask>, FrameError> {
    let stroke_width = command.line_width_pt * scale;
    if !stroke_width.is_finite() || stroke_width <= 0.0 {
        return Ok(None);
    }
    if chain.len() < 3 || chain.len() > AUTO_SNAP_VERTEX_LIMIT {
        return Ok(None);
    }
    let half = stroke_width * 0.5;
    if !half.is_finite() || half <= 0.0 {
        return Ok(None);
    }
    let one_plus_dot_floor = 2.0 / (MITER_LIMIT * MITER_LIMIT);
    let segments = chain.len() - 1;
    let mut normals: Vec<(f64, f64)> = Vec::new();
    normals
        .try_reserve_exact(segments)
        .map_err(|_| FrameError::OutOfMemory)?;
    for window in chain.windows(2) {
        let dx = window[1].x - window[0].x;
        let dy = window[1].y - window[0].y;
        let length = dx.hypot(dy);
        if !length.is_finite() || length <= AXIS_ALIGNMENT_EPSILON {
            return Ok(None);
        }
        let ux = dx / length;
        let uy = dy / length;
        normals.push((-uy * half, ux * half));
    }
    let mut left: Vec<Point> = Vec::new();
    let mut right: Vec<Point> = Vec::new();
    left.try_reserve_exact(chain.len())
        .map_err(|_| FrameError::OutOfMemory)?;
    right
        .try_reserve_exact(chain.len())
        .map_err(|_| FrameError::OutOfMemory)?;
    left.push(Point {
        x: chain[0].x + normals[0].0,
        y: chain[0].y + normals[0].1,
    });
    right.push(Point {
        x: chain[0].x - normals[0].0,
        y: chain[0].y - normals[0].1,
    });
    for index in 1..chain.len() - 1 {
        let (in_x, in_y) = normals[index - 1];
        let (out_x, out_y) = normals[index];
        // Exact miter on both sides: the outer intersection and the inner
        // corner are `p +/- half * (n1 + n2) / (1 + dot)`. The extractor
        // gates `1 + dot` above `one_plus_dot_floor`; re-check before the
        // division so a spike can never reach the accumulator.
        let dot = (in_x * out_x + in_y * out_y) / (half * half);
        let one_plus_dot = 1.0 + dot;
        if !one_plus_dot.is_finite() || one_plus_dot < one_plus_dot_floor {
            return Ok(None);
        }
        let miter_x = (in_x + out_x) / one_plus_dot;
        let miter_y = (in_y + out_y) / one_plus_dot;
        if !miter_x.is_finite() || !miter_y.is_finite() {
            return Ok(None);
        }
        left.push(Point {
            x: chain[index].x + miter_x,
            y: chain[index].y + miter_y,
        });
        right.push(Point {
            x: chain[index].x - miter_x,
            y: chain[index].y - miter_y,
        });
    }
    let last = chain.len() - 1;
    left.push(Point {
        x: chain[last].x + normals[segments - 1].0,
        y: chain[last].y + normals[segments - 1].1,
    });
    right.push(Point {
        x: chain[last].x - normals[segments - 1].0,
        y: chain[last].y - normals[segments - 1].1,
    });
    if left
        .iter()
        .chain(right.iter())
        .any(|point| !point.x.is_finite() || !point.y.is_finite())
    {
        return Ok(None);
    }
    let mut contour: Vec<SubpixelPoint> = Vec::new();
    contour
        .try_reserve_exact(left.len() + right.len())
        .map_err(|_| FrameError::OutOfMemory)?;
    contour.push(to_subpixel(left[0]));
    for point in &right {
        contour.push(to_subpixel(*point));
    }
    for point in left[1..].iter().rev() {
        contour.push(to_subpixel(*point));
    }
    let Some(cell_capacity) = contour_capacity_bound(&contour) else {
        return Ok(None);
    };
    let mut rasterizer = CellRasterizer::new(cell_capacity)?;
    rasterizer.add_contour(&contour)?;
    let mut mask = coverage_mask(width, height, pixel_count)?;
    rasterizer.write_mask(&mut mask, width, height)?;
    Ok(Some(mask))
}

/// Squared distance tolerance of the Agg recursive curve subdivision
/// replicated by the closed-curve stroke route: Matplotlib strokes curves
/// through `agg::conv_curve` with default settings (`curve3_div` /
/// `curve4_div`, approximation scale 1.0, angle tolerance 0.0), so the
/// distance test is `d^2 <= (0.5/1.0)^2 * chord^2` with a pure
/// distance stop (the angle/cusp branches are dead at zero tolerance).
/// Subdividing any finer (e.g. a fixed 1/4096 px flatness) converges to
/// the true parallel curve, which Agg's coarse polygon visibly leaves by
/// up to ~0.15 px at small corner radii (legend frame: 3 segments per
/// corner instead of hundreds).
const AGG_DIV_DISTANCE_TOL_SQ: f64 = 0.25;
/// Collinearity epsilon of `agg_curves.cpp` (`curve_collinearity_epsilon`).
const AGG_DIV_COLLINEARITY_EPS: f64 = 1e-30;
/// Recursion cap of `agg_curves.cpp` (`curve_recursion_limit = 32`); a
/// path that is still not flat falls back to the tiny-skia path instead
/// of subdividing without bound.
const AGG_DIV_MAX_DEPTH: u32 = 32;
/// Maximum flattened loop vertices admitted to the closed-curve route.
const CLOSED_CURVE_POINT_LIMIT: usize = 65_536;

fn midpoint(first: Point, second: Point) -> Point {
    Point {
        x: (first.x + second.x) * 0.5,
        y: (first.y + second.y) * 0.5,
    }
}

/// Squared distance matching Agg's `calc_sq_distance` (`agg_math.h`).
fn agg_sq_distance(first: Point, second: Point) -> f64 {
    let dx = second.x - first.x;
    let dy = second.y - first.y;
    dx * dx + dy * dy
}

/// Fail-closed finiteness gate: Agg propagates non-finite coordinates
/// into its subdivision comparisons (which then never terminate flat),
/// while this route refuses them and falls through to tiny-skia.
fn agg_curve_inputs_finite(points: &[Point]) -> bool {
    points
        .iter()
        .all(|point| point.x.is_finite() && point.y.is_finite())
}

/// Appends the Agg-subdivided quadratic `start -> control -> end` to
/// `out` (which already ends at `start`), replicating
/// `curve3_div::recursive_bezier` at approximation scale 1.0 with the
/// angle test disabled: the chord midpoint replaces the curve once the
/// control deviation is within a quarter pixel of the chord, and a
/// collinear control that projects onto the chord contributes no vertex
/// at all. The wrapper pushes `end` (Agg's `bezier()` endpoint) after
/// the interior points. Returns false (fall back) on non-finite input,
/// depth exhaustion past Agg's own recursion cap, or the vertex cap.
fn push_agg_quad(
    start: Point,
    control: Point,
    end: Point,
    out: &mut Vec<Point>,
    depth: u32,
) -> bool {
    if !agg_curve_inputs_finite(&[start, control, end]) {
        return false;
    }
    if !agg_quad_recursive(start, control, end, out, depth) {
        return false;
    }
    if out.len() >= CLOSED_CURVE_POINT_LIMIT {
        return false;
    }
    out.push(end);
    true
}

fn agg_quad_recursive(
    start: Point,
    control: Point,
    end: Point,
    out: &mut Vec<Point>,
    depth: u32,
) -> bool {
    if depth > AGG_DIV_MAX_DEPTH || out.len() >= CLOSED_CURVE_POINT_LIMIT {
        // Past Agg's recursion cap Agg silently drops the remaining
        // interior points; this route refuses instead so an adversarial
        // curve can never hang or over-allocate the cell rasterizer.
        return depth <= AGG_DIV_MAX_DEPTH;
    }
    let middle_start = midpoint(start, control);
    let middle_end = midpoint(control, end);
    let middle = midpoint(middle_start, middle_end);
    let dx = end.x - start.x;
    let dy = end.y - start.y;
    let deviation = ((control.x - end.x) * dy - (control.y - end.y) * dx).abs();
    if deviation > AGG_DIV_COLLINEARITY_EPS {
        if deviation * deviation <= AGG_DIV_DISTANCE_TOL_SQ * (dx * dx + dy * dy) {
            if out.len() >= CLOSED_CURVE_POINT_LIMIT {
                return false;
            }
            out.push(middle);
            return true;
        }
    } else {
        let chord_squared = dx * dx + dy * dy;
        if chord_squared == 0.0 {
            if agg_sq_distance(start, control) < AGG_DIV_DISTANCE_TOL_SQ {
                if out.len() >= CLOSED_CURVE_POINT_LIMIT {
                    return false;
                }
                out.push(control);
                return true;
            }
        } else {
            let projection =
                ((control.x - start.x) * dx + (control.y - start.y) * dy) / chord_squared;
            if projection > 0.0 && projection < 1.0 {
                return true;
            }
            let off_chord = if projection <= 0.0 {
                agg_sq_distance(control, start)
            } else if projection >= 1.0 {
                agg_sq_distance(control, end)
            } else {
                agg_sq_distance(
                    control,
                    Point {
                        x: start.x + projection * dx,
                        y: start.y + projection * dy,
                    },
                )
            };
            if off_chord < AGG_DIV_DISTANCE_TOL_SQ {
                if out.len() >= CLOSED_CURVE_POINT_LIMIT {
                    return false;
                }
                out.push(control);
                return true;
            }
        }
    }
    agg_quad_recursive(start, middle_start, middle, out, depth + 1)
        && agg_quad_recursive(middle, middle_end, end, out, depth + 1)
}

/// Appends the Agg-subdivided cubic to `out` with the same contract as
/// [`push_agg_quad`], replicating `curve4_div::recursive_bezier` with
/// the angle/cusp tests disabled (both tolerances are zero in the
/// Matplotlib stroke pipeline).
fn push_agg_cubic(
    start: Point,
    control1: Point,
    control2: Point,
    end: Point,
    out: &mut Vec<Point>,
    depth: u32,
) -> bool {
    if !agg_curve_inputs_finite(&[start, control1, control2, end]) {
        return false;
    }
    if !agg_cubic_recursive(start, control1, control2, end, out, depth) {
        return false;
    }
    if out.len() >= CLOSED_CURVE_POINT_LIMIT {
        return false;
    }
    out.push(end);
    true
}

fn agg_cubic_recursive(
    start: Point,
    control1: Point,
    control2: Point,
    end: Point,
    out: &mut Vec<Point>,
    depth: u32,
) -> bool {
    if depth > AGG_DIV_MAX_DEPTH || out.len() >= CLOSED_CURVE_POINT_LIMIT {
        return depth <= AGG_DIV_MAX_DEPTH;
    }
    let m01 = midpoint(start, control1);
    let m12 = midpoint(control1, control2);
    let m23 = midpoint(control2, end);
    let m012 = midpoint(m01, m12);
    let m123 = midpoint(m12, m23);
    let middle = midpoint(m012, m123);
    let dx = end.x - start.x;
    let dy = end.y - start.y;
    let chord_squared = dx * dx + dy * dy;
    let d2 = ((control1.x - end.x) * dy - (control1.y - end.y) * dx).abs();
    let d3 = ((control2.x - end.x) * dy - (control2.y - end.y) * dx).abs();
    let significant2 = d2 > AGG_DIV_COLLINEARITY_EPS;
    let significant3 = d3 > AGG_DIV_COLLINEARITY_EPS;
    // Stopping points match `curve4_div` case-for-case: the worse
    // control point for the fully collinear case 0, the control
    // midpoint `m12` (Agg's `x23`) for cases 1-3.
    let stop_point = match (significant2, significant3) {
        (false, false) => {
            if chord_squared == 0.0 {
                let off2 = agg_sq_distance(start, control1);
                let off3 = agg_sq_distance(end, control2);
                if off2 > off3 {
                    if off2 < AGG_DIV_DISTANCE_TOL_SQ {
                        Some(control1)
                    } else {
                        None
                    }
                } else if off3 < AGG_DIV_DISTANCE_TOL_SQ {
                    Some(control2)
                } else {
                    None
                }
            } else {
                let reciprocal = 1.0 / chord_squared;
                let projected2 =
                    ((control1.x - start.x) * dx + (control1.y - start.y) * dy) * reciprocal;
                let projected3 =
                    ((control2.x - start.x) * dx + (control2.y - start.y) * dy) * reciprocal;
                if projected2 > 0.0 && projected2 < 1.0 && projected3 > 0.0 && projected3 < 1.0 {
                    return true;
                }
                let off2 = if projected2 <= 0.0 {
                    agg_sq_distance(control1, start)
                } else if projected2 >= 1.0 {
                    agg_sq_distance(control1, end)
                } else {
                    agg_sq_distance(
                        control1,
                        Point {
                            x: start.x + projected2 * dx,
                            y: start.y + projected2 * dy,
                        },
                    )
                };
                let off3 = if projected3 <= 0.0 {
                    agg_sq_distance(control2, start)
                } else if projected3 >= 1.0 {
                    agg_sq_distance(control2, end)
                } else {
                    agg_sq_distance(
                        control2,
                        Point {
                            x: start.x + projected3 * dx,
                            y: start.y + projected3 * dy,
                        },
                    )
                };
                if off2 > off3 {
                    if off2 < AGG_DIV_DISTANCE_TOL_SQ {
                        Some(control1)
                    } else {
                        None
                    }
                } else if off3 < AGG_DIV_DISTANCE_TOL_SQ {
                    Some(control2)
                } else {
                    None
                }
            }
        }
        (false, true) => {
            if d3 * d3 <= AGG_DIV_DISTANCE_TOL_SQ * chord_squared {
                Some(m12)
            } else {
                None
            }
        }
        (true, false) => {
            if d2 * d2 <= AGG_DIV_DISTANCE_TOL_SQ * chord_squared {
                Some(m12)
            } else {
                None
            }
        }
        (true, true) => {
            if (d2 + d3) * (d2 + d3) <= AGG_DIV_DISTANCE_TOL_SQ * chord_squared {
                Some(m12)
            } else {
                None
            }
        }
    };
    if let Some(point) = stop_point {
        if out.len() >= CLOSED_CURVE_POINT_LIMIT {
            return false;
        }
        out.push(point);
        return true;
    }
    // Cases 1/2 subdivide unless stopped above; the regular case 3 and
    // the collinear case fall through here when the curve is too bent.
    // (The distance test above already covers cases 1-3: with a single
    // significant control the other deviation is ~0, so `d2 + d3` is
    // that control's deviation.)
    agg_cubic_recursive(start, m01, m012, middle, out, depth + 1)
        && agg_cubic_recursive(middle, m123, m23, end, out, depth + 1)
}

/// Closed curve-bearing stroke loop in device space.
///
/// Detects closed loops with at least one CURVE3/CURVE4 group: a single
/// `MOVETO`-led subpath ending in `CLOSEPOLY` (no `STOP`), every group
/// complete with finite vertices, miter join, butt or projecting caps
/// (caps are moot on closed loops), no dashes, opaque, antialiased.
/// Straight-only closed loops keep their existing rect-ring and
/// single-segment routes, so a curve group is required; anything else
/// returns `Ok(None)` and the caller falls through to tiny-skia.
fn extract_closed_curve_loop(
    command: &PathCommand,
    height: u32,
) -> Result<Option<Vec<Point>>, FrameError> {
    let Some(codes) = command.codes.as_ref() else {
        return Ok(None);
    };
    if codes.len() != command.vertices.len() || codes.len() < 2 {
        return Ok(None);
    }
    if codes[0] != CODE_MOVETO || codes[codes.len() - 1] != CODE_CLOSEPOLY {
        return Ok(None);
    }
    let Some(start) = map_device_point(command.transform, command.vertices[0], height) else {
        return Ok(None);
    };
    let mut loop_points = Vec::new();
    loop_points
        .try_reserve_exact(codes.len())
        .map_err(|_| FrameError::OutOfMemory)?;
    loop_points.push(start);
    let mut pen = start;
    let mut saw_curve = false;
    let mut index = 1usize;
    while index < codes.len() - 1 {
        if codes[index] == CODE_LINETO {
            let Some(point) = map_device_point(command.transform, command.vertices[index], height)
            else {
                return Ok(None);
            };
            loop_points.push(point);
            pen = point;
            index += 1;
        } else if codes[index] == CODE_CURVE3 {
            if index + 1 >= codes.len() - 1 {
                return Ok(None);
            }
            let (Some(control), Some(end)) = (
                map_device_point(command.transform, command.vertices[index], height),
                map_device_point(command.transform, command.vertices[index + 1], height),
            ) else {
                return Ok(None);
            };
            if !push_agg_quad(pen, control, end, &mut loop_points, 0) {
                return Ok(None);
            }
            pen = end;
            saw_curve = true;
            index += 2;
        } else if codes[index] == CODE_CURVE4 {
            if index + 2 >= codes.len() - 1 {
                return Ok(None);
            }
            let (Some(control1), Some(control2), Some(end)) = (
                map_device_point(command.transform, command.vertices[index], height),
                map_device_point(command.transform, command.vertices[index + 1], height),
                map_device_point(command.transform, command.vertices[index + 2], height),
            ) else {
                return Ok(None);
            };
            if !push_agg_cubic(pen, control1, control2, end, &mut loop_points, 0) {
                return Ok(None);
            }
            pen = end;
            saw_curve = true;
            index += 3;
        } else {
            return Ok(None);
        }
        if loop_points.len() > CLOSED_CURVE_POINT_LIMIT {
            return Ok(None);
        }
    }
    if !saw_curve {
        return Ok(None);
    }
    // The CLOSEPOLY vertex is a positional dummy; drop exact-duplicate
    // consecutive points (shared group boundaries are already exact), and
    // a trailing point that repeats the loop start (closed paths end
    // where they begin) so the cyclic miter never sees a zero-length
    // edge.
    loop_points.dedup();
    if loop_points.len() >= 2 && loop_points[0] == loop_points[loop_points.len() - 1] {
        loop_points.pop();
    }
    if loop_points.len() < 3 {
        return Ok(None);
    }
    Ok(Some(loop_points))
}

/// Rasterizes a closed curve loop as one JOINED miter outline.
///
/// Both the outer and the inner offset contours use the exact offset-line
/// intersection `half * (n1 + n2) / (1 + dot)` at every vertex, cyclically
/// (Agg `line_miter_join` geometry, same formula as the oblique route;
/// turns past Agg's default miter limit fall back instead of spiking).
/// The contours are fed to the shared cell accumulator with opposite
/// winding so the interior hole cancels under the nonzero rule, exactly
/// like Agg's closed-stroke outline fill.
fn rasterize_closed_curve_loop(
    loop_points: Vec<Point>,
    command: &PathCommand,
    width: u32,
    height: u32,
    pixel_count: usize,
    scale: f64,
) -> Result<Option<Mask>, FrameError> {
    let stroke_width = command.line_width_pt * scale;
    if !stroke_width.is_finite() || stroke_width <= 0.0 {
        return Ok(None);
    }
    if loop_points.len() < 3 || loop_points.len() > CLOSED_CURVE_POINT_LIMIT {
        return Ok(None);
    }
    let half = stroke_width * 0.5;
    if !half.is_finite() || half <= 0.0 {
        return Ok(None);
    }
    let one_plus_dot_floor = 2.0 / (MITER_LIMIT * MITER_LIMIT);
    // Signed area orients the loop: device space is y-down, so a negative
    // area is clockwise with the interior on the right of travel.
    let mut area2 = 0.0f64;
    for index in 0..loop_points.len() {
        let current = loop_points[index];
        let next = loop_points[(index + 1) % loop_points.len()];
        area2 += current.x * next.y - next.x * current.y;
    }
    if !area2.is_finite() || area2 == 0.0 {
        return Ok(None);
    }
    // `side` selects the exterior: left of travel for CCW loops, right
    // for CW loops.
    let side = if area2 < 0.0 { -1.0 } else { 1.0 };
    let count = loop_points.len();
    let mut outer: Vec<Point> = Vec::new();
    let mut inner: Vec<Point> = Vec::new();
    outer
        .try_reserve_exact(count)
        .map_err(|_| FrameError::OutOfMemory)?;
    inner
        .try_reserve_exact(count)
        .map_err(|_| FrameError::OutOfMemory)?;
    for index in 0..count {
        let previous = loop_points[(index + count - 1) % count];
        let current = loop_points[index];
        let next = loop_points[(index + 1) % count];
        let in_dx = current.x - previous.x;
        let in_dy = current.y - previous.y;
        let out_dx = next.x - current.x;
        let out_dy = next.y - current.y;
        let in_length = in_dx.hypot(in_dy);
        let out_length = out_dx.hypot(out_dy);
        if !in_length.is_finite()
            || !out_length.is_finite()
            || in_length <= AXIS_ALIGNMENT_EPSILON
            || out_length <= AXIS_ALIGNMENT_EPSILON
        {
            return Ok(None);
        }
        let in_normal = (-in_dy / in_length * half, in_dx / in_length * half);
        let out_normal = (-out_dy / out_length * half, out_dx / out_length * half);
        let dot = (in_normal.0 * out_normal.0 + in_normal.1 * out_normal.1) / (half * half);
        let one_plus_dot = 1.0 + dot;
        if !one_plus_dot.is_finite() || one_plus_dot < one_plus_dot_floor {
            return Ok(None);
        }
        let miter_x = (in_normal.0 + out_normal.0) / one_plus_dot;
        let miter_y = (in_normal.1 + out_normal.1) / one_plus_dot;
        if !miter_x.is_finite() || !miter_y.is_finite() {
            return Ok(None);
        }
        outer.push(Point {
            x: current.x + side * miter_x,
            y: current.y + side * miter_y,
        });
        inner.push(Point {
            x: current.x - side * miter_x,
            y: current.y - side * miter_y,
        });
    }
    let mut outer_cells: Vec<SubpixelPoint> = Vec::new();
    let mut inner_cells: Vec<SubpixelPoint> = Vec::new();
    outer_cells
        .try_reserve_exact(count)
        .map_err(|_| FrameError::OutOfMemory)?;
    inner_cells
        .try_reserve_exact(count)
        .map_err(|_| FrameError::OutOfMemory)?;
    for point in &outer {
        if !point.x.is_finite() || !point.y.is_finite() {
            return Ok(None);
        }
        outer_cells.push(to_subpixel(*point));
    }
    for point in &inner {
        if !point.x.is_finite() || !point.y.is_finite() {
            return Ok(None);
        }
        inner_cells.push(to_subpixel(*point));
    }
    // The interior hole cancels under the nonzero rule: traverse the
    // inner contour in the opposite direction to the outer one.
    inner_cells.reverse();
    let Some(outer_capacity) = contour_capacity_bound(&outer_cells) else {
        return Ok(None);
    };
    let Some(inner_capacity) = contour_capacity_bound(&inner_cells) else {
        return Ok(None);
    };
    let Some(cell_capacity) = outer_capacity.checked_add(inner_capacity) else {
        return Ok(None);
    };
    if cell_capacity > MAX_CELLS {
        return Ok(None);
    }
    let mut rasterizer = CellRasterizer::new(cell_capacity)?;
    rasterizer.add_contour(&outer_cells)?;
    rasterizer.add_contour(&inner_cells)?;
    let mut mask = coverage_mask(width, height, pixel_count)?;
    rasterizer.write_mask(&mut mask, width, height)?;
    Ok(Some(mask))
}

fn rect_snap_value(stroke_width: f64) -> f64 {
    // Mirrors the frame-seam PathSnapper offset: odd rounded device widths
    // center on half pixels, even widths on integer pixels. `rem_euclid`
    // keeps the 1.5/2.5 ties on the Agg side (1.5 -> even -> 0.0).
    if stroke_width.round().rem_euclid(2.0) == 1.0 {
        0.5
    } else {
        0.0
    }
}

/// Rasterizes a closed rect-stroke ring with the Agg-compatible 24.8
/// fixed-point cell integrator: the stroked outline of an axis-aligned
/// rectangle is the outer expanded rect minus the inner shrunk rect. Agg's
/// `miter_join_revert` uses a bevel at a 90-degree corner when the rounded
/// device linewidth is below `sqrt(2)`; those four outer corner triangles are
/// subtracted in that case. Both contours are fed to the same cell accumulator
/// with opposite winding so the hole cancels; a degenerate inner (stroke wider
/// than the rect) rasterizes as the filled outer only.
fn rasterize_rect_ring(
    ring: RectRing,
    command: &PathCommand,
    width: u32,
    height: u32,
    pixel_count: usize,
    scale: f64,
) -> Result<Option<Mask>, FrameError> {
    let stroke_width = command.line_width_pt * scale;
    if !stroke_width.is_finite() || stroke_width <= 0.0 {
        return Ok(None);
    }
    if command.vertices.len() > AUTO_SNAP_VERTEX_LIMIT {
        return Ok(None);
    }
    let mut corners = ring.corners;
    // Agg auto-snaps rectilinear paths in device space before stroking;
    // the ring is axis-aligned by construction, so always snap (matches
    // the frame-seam fallback when `rectilinear_snap` is set).
    let snap_offset = rect_snap_value(stroke_width);
    for corner in &mut corners {
        corner.x = (corner.x + 0.5).floor() + snap_offset;
        corner.y = (corner.y + 0.5).floor() + snap_offset;
    }
    let min_x = corners
        .iter()
        .map(|point| point.x)
        .fold(f64::INFINITY, f64::min);
    let max_x = corners
        .iter()
        .map(|point| point.x)
        .fold(f64::NEG_INFINITY, f64::max);
    let min_y = corners
        .iter()
        .map(|point| point.y)
        .fold(f64::INFINITY, f64::min);
    let max_y = corners
        .iter()
        .map(|point| point.y)
        .fold(f64::NEG_INFINITY, f64::max);
    let half = stroke_width * 0.5;
    let outer = [min_x - half, min_y - half, max_x + half, max_y + half];
    let inner = [min_x + half, min_y + half, max_x - half, max_y - half];
    if outer.iter().any(|value| !value.is_finite()) || inner.iter().any(|value| !value.is_finite())
    {
        return Ok(None);
    }
    let outer_points = [
        Point {
            x: outer[0],
            y: outer[1],
        },
        Point {
            x: outer[2],
            y: outer[1],
        },
        Point {
            x: outer[2],
            y: outer[3],
        },
        Point {
            x: outer[0],
            y: outer[3],
        },
    ];
    if outer_points
        .iter()
        .any(|point| !point.x.is_finite() || !point.y.is_finite())
    {
        return Ok(None);
    }
    let has_hole = inner[0] < inner[2] && inner[1] < inner[3];
    let bevel_join = stroke_width < 2.0_f64.sqrt();
    let mut polygons = Vec::new();
    polygons
        .try_reserve_exact(if bevel_join {
            if has_hole { 6 } else { 5 }
        } else if has_hole {
            2
        } else {
            1
        })
        .map_err(|_| FrameError::OutOfMemory)?;
    polygons.push(Polygon {
        points: outer_points.map(to_subpixel),
    });
    let bevel_cutouts = [
        [
            Point {
                x: outer[0],
                y: outer[1],
            },
            Point {
                x: min_x,
                y: min_y - half,
            },
            Point {
                x: min_x - half,
                y: min_y,
            },
        ],
        [
            Point {
                x: outer[2],
                y: outer[1],
            },
            Point {
                x: max_x + half,
                y: min_y,
            },
            Point {
                x: max_x,
                y: min_y - half,
            },
        ],
        [
            Point {
                x: outer[2],
                y: outer[3],
            },
            Point {
                x: max_x,
                y: max_y + half,
            },
            Point {
                x: max_x + half,
                y: max_y,
            },
        ],
        [
            Point {
                x: outer[0],
                y: outer[3],
            },
            Point {
                x: min_x - half,
                y: max_y,
            },
            Point {
                x: min_x,
                y: max_y + half,
            },
        ],
    ];
    if bevel_join {
        for [corner, first, second] in bevel_cutouts {
            polygons.push(Polygon {
                // Reverse the outer winding to subtract the square corner and
                // leave Agg's bevel-style rectilinear join.
                points: [
                    to_subpixel(corner),
                    to_subpixel(second),
                    to_subpixel(first),
                    to_subpixel(corner),
                ],
            });
        }
    }
    if has_hole {
        // Opposite winding so the nonzero accumulator cancels the hole.
        let inner_points = [
            Point {
                x: inner[0],
                y: inner[1],
            },
            Point {
                x: inner[0],
                y: inner[3],
            },
            Point {
                x: inner[2],
                y: inner[3],
            },
            Point {
                x: inner[2],
                y: inner[1],
            },
        ];
        polygons.push(Polygon {
            points: inner_points.map(to_subpixel),
        });
    }
    let Some(cell_capacity) = cell_capacity_bound(&polygons) else {
        return Ok(None);
    };
    let mut rasterizer = CellRasterizer::new(cell_capacity)?;
    for polygon in polygons {
        rasterizer.add_polygon(polygon)?;
    }
    let mut mask = coverage_mask(width, height, pixel_count)?;
    rasterizer.write_mask(&mut mask, width, height)?;
    Ok(Some(mask))
}

fn map_device_point(transform: [f64; 6], vertex: [f64; 2], height: u32) -> Option<Point> {
    let [a, b, c, d, e, f] = transform;
    let x = a * vertex[0] + c * vertex[1] + e;
    let y = f64::from(height) - (b * vertex[0] + d * vertex[1] + f);
    (x.is_finite() && y.is_finite()).then_some(Point { x, y })
}

fn stroke_polygon(segment: Segment, stroke_width: f64) -> Option<Polygon> {
    let dx = segment.end.x - segment.start.x;
    let dy = segment.end.y - segment.start.y;
    let length = dx.hypot(dy);
    if !length.is_finite() || length == 0.0 {
        return None;
    }
    let half_width = stroke_width * 0.5;
    let offset_x = dy / length * half_width;
    let offset_y = dx / length * half_width;
    let corners = [
        Point {
            x: segment.start.x - offset_x,
            y: segment.start.y + offset_y,
        },
        Point {
            x: segment.start.x + offset_x,
            y: segment.start.y - offset_y,
        },
        Point {
            x: segment.end.x + offset_x,
            y: segment.end.y - offset_y,
        },
        Point {
            x: segment.end.x - offset_x,
            y: segment.end.y + offset_y,
        },
    ];
    // Corners may lie outside the command clip or the canvas: strokes
    // centered on a clip boundary (axes spines) or ending exactly on a
    // clip corner (axes-clipped diagonals) legitimately spill over by up
    // to half the stroke width. Agg strokes first and clips coverage
    // after, so the quad is always emitted here; the cell writer only
    // stores in-canvas cells and the caller applies the device clip to
    // the finished mask. Rejecting here silently dropped every such
    // stroke to the tiny-skia fallback (legend spines + content fringe).
    // Only non-finite or absurd magnitudes fall through: the scanline
    // edge arithmetic runs in fixed-point subpixels, and the cell
    // capacity gate below already bounds allocation, not overflow.
    if corners.iter().any(|point| {
        !point.x.is_finite()
            || !point.y.is_finite()
            || point.x.abs() > MAX_STROKE_COORD
            || point.y.abs() > MAX_STROKE_COORD
    }) {
        return None;
    }
    Some(Polygon {
        points: corners.map(to_subpixel),
    })
}

fn to_subpixel(point: Point) -> SubpixelPoint {
    SubpixelPoint {
        x: (point.x * SUBPIXEL_SCALE as f64).round() as i64,
        y: (point.y * SUBPIXEL_SCALE as f64).round() as i64,
    }
}

fn cell_capacity_bound(polygons: &[Polygon]) -> Option<usize> {
    let mut capacity = 0usize;
    for polygon in polygons {
        for index in 0..polygon.points.len() {
            let start = polygon.points[index];
            let end = polygon.points[(index + 1) % polygon.points.len()];
            let x_cells = usize::try_from(
                (end.x - start.x)
                    .unsigned_abs()
                    .div_ceil(SUBPIXEL_SCALE as u64),
            )
            .ok()?;
            let y_cells = usize::try_from(
                (end.y - start.y)
                    .unsigned_abs()
                    .div_ceil(SUBPIXEL_SCALE as u64),
            )
            .ok()?;
            capacity = capacity
                .checked_add(x_cells)?
                .checked_add(y_cells)?
                .checked_add(8)?;
            if capacity > MAX_CELLS {
                return None;
            }
        }
    }
    Some(capacity.max(1))
}

fn coverage_alpha(area: i64) -> u8 {
    let magnitude = (area >> COVERAGE_SHIFT).unsigned_abs();
    magnitude.min(u64::from(u8::MAX)) as u8
}

fn write_cell(mask: &mut Mask, width: u32, row: u32, x: i64, alpha: u8) {
    if alpha == 0 || x < 0 || x >= i64::from(width) {
        return;
    }
    let index = row as usize * width as usize + x as usize;
    mask.data_mut()[index] = alpha;
}

fn write_span(mask: &mut Mask, width: u32, row: u32, start: i64, end: i64, alpha: u8) {
    if alpha == 0 {
        return;
    }
    let left = start.clamp(0, i64::from(width)) as usize;
    let right = end.clamp(0, i64::from(width)) as usize;
    if left >= right {
        return;
    }
    let row_start = row as usize * width as usize;
    mask.data_mut()[row_start + left..row_start + right].fill(alpha);
}

#[cfg(test)]
mod tests {
    use super::*;

    const IDENTITY: [f64; 6] = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0];

    fn gap_command() -> PathCommand {
        PathCommand::new(
            vec![
                [f64::NAN, f64::NAN],
                [38.823_529_411_764_71, 16.666_666_666_666_664],
                [48.235_294_117_647_06, 23.333_333_333_333_332],
                [f64::NAN, f64::NAN],
                [67.058_823_529_411_77, 30.0],
                [76.470_588_235_294_12, 36.666_666_666_666_664],
                [f64::NAN, f64::NAN],
                [95.294_117_647_058_83, 50.0],
                [104.705_882_352_941_17, 56.666_666_666_666_67],
                [f64::INFINITY, f64::INFINITY],
                [123.529_411_764_705_88, 63.333_333_333_333_33],
                [132.941_176_470_588_23, 70.0],
                [f64::NEG_INFINITY, f64::NEG_INFINITY],
                [151.764_705_882_352_93, 76.666_666_666_666_67],
                [161.176_470_588_235_3, 83.333_333_333_333_33],
                [f64::NAN, f64::NAN],
            ],
            None,
            IDENTITY,
            Some([255, 0, 0, 255]),
            None,
            2.0,
            CapSelector::Butt,
            JoinSelector::Miter,
            0.0,
            None,
            super::super::FillRuleSelector::NonZero,
            true,
            Some([20.0, 10.0, 160.0, 80.0]),
        )
        .expect("gap command")
    }

    #[test]
    fn gap_segments_match_pinned_agg_coverage_samples() {
        let mask = try_rasterize(&gap_command(), 200, 100, 20_000, 100.0 / 72.0)
            .expect("rasterize")
            .expect("eligible coverage");
        let at = |x: usize, y: usize| mask.data()[y * 200 + x];
        assert_eq!(mask.data().iter().filter(|alpha| **alpha != 0).count(), 265);
        assert_eq!(at(159, 15), 8);
        assert_eq!(at(160, 16), 241);
        assert_eq!(at(153, 20), 154);
        assert_eq!(at(132, 28), 5);
        assert_eq!(at(39, 83), 241);
    }

    #[test]
    fn straight_oblique_chain_uses_joined_miter_outline() {
        // Behavior update for the log-frame convergence: straight oblique
        // chains (and gentle oblique joins generally) are now eligible for
        // the 24.8 cell integrator with a JOINED miter outline, not the grid
        // fallback. For a straight run the miter reduces to the segment
        // normal, so the outline is the exact stroked parallelogram; the
        // committed log oracle carries the durable Agg-parity gate.
        let mut command = gap_command();
        command.vertices = vec![[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]];
        let mask = try_rasterize(&command, 8, 8, 64, 1.0)
            .expect("route")
            .expect("oblique chain eligible");
        assert!(mask.data().iter().any(|alpha| *alpha != 0));
    }

    #[test]
    fn oblique_chain_keeps_explicit_fallback_for_unsafe_geometry() {
        // Reversals, over-limit miters, fills, gaps, degenerate runs, and
        // close codes all stay on the existing tiny-skia path; two-vertex
        // pairs stay on the single-segment route.
        let mut reversal = gap_command();
        reversal.vertices = vec![[1.0, 4.0], [5.0, 4.0], [1.0, 4.0]];
        assert!(
            try_rasterize(&reversal, 8, 8, 64, 1.0)
                .expect("route")
                .is_none()
        );

        // ~169-degree turn: tangent dot below 2/16 - 1, past Agg's default
        // miter limit of 4.
        let mut acute = gap_command();
        acute.vertices = vec![[1.0, 4.0], [5.0, 4.0], [1.0, 4.5]];
        assert!(
            try_rasterize(&acute, 8, 8, 64, 1.0)
                .expect("route")
                .is_none()
        );

        let mut filled = gap_command();
        filled.vertices = vec![[1.0, 1.0], [4.0, 2.0], [6.0, 5.0]];
        filled.fill_rgba = Some([0, 0, 255, 255]);
        assert!(
            try_rasterize(&filled, 8, 8, 64, 1.0)
                .expect("route")
                .is_none()
        );

        let mut gapped = gap_command();
        gapped.vertices = vec![[1.0, 1.0], [f64::NAN, f64::NAN], [3.0, 3.0]];
        assert!(
            try_rasterize(&gapped, 8, 8, 64, 1.0)
                .expect("route")
                .is_none()
        );

        let mut degenerate = gap_command();
        degenerate.vertices = vec![[1.0, 1.0], [1.0, 1.0], [3.0, 3.0]];
        assert!(
            try_rasterize(&degenerate, 8, 8, 64, 1.0)
                .expect("route")
                .is_none()
        );

        // Two-vertex pairs stay on the pre-existing single-segment route
        // (the joined-oblique route requires a genuine join).
        let mut pair = gap_command();
        pair.vertices = vec![[1.0, 2.0], [6.0, 5.0]];
        pair.clip_rect = None;
        let pair_mask = try_rasterize(&pair, 8, 8, 64, 1.0)
            .expect("route")
            .expect("single-segment pair eligible");
        assert!(pair_mask.data().iter().any(|alpha| *alpha != 0));

        let mut closed = gap_command();
        closed.vertices = vec![[1.0, 1.0], [4.0, 2.0], [1.0, 5.0], [0.0, 0.0]];
        closed.codes = Some(vec![CODE_MOVETO, CODE_LINETO, CODE_LINETO, CODE_CLOSEPOLY]);
        assert!(
            try_rasterize(&closed, 8, 8, 64, 1.0)
                .expect("route")
                .is_none()
        );
    }

    #[test]
    fn rectilinear_open_chain_uses_cell_coverage() {
        // Named behavior update for the steps convergence: rectilinear open
        // chains (step polylines) are now eligible for the 24.8 cell
        // integrator with a JOINED miter outline, not the grid fallback.
        // This is a correct-new-behavior pin, not a tolerance change.
        let mut command = gap_command();
        command.vertices = vec![[1.0, 6.0], [1.0, 4.0], [5.0, 4.0], [5.0, 2.0]];
        command.codes = None;
        let mask = try_rasterize(&command, 8, 8, 64, 1.0)
            .expect("route")
            .expect("rectilinear chain eligible");
        assert!(mask.data().iter().any(|alpha| *alpha != 0));
    }

    #[test]
    fn rectilinear_chain_winding_matches_agg_vcgen_order() {
        // Winding pin for the joined rectilinear outline: Agg `vcgen_stroke`
        // emits open paths counter-clockwise (cap1, outline1, cap2,
        // outline2). The shared cell integrator floors
        // `(cover << 9) - area`, so the two fractional joint cells below
        // read one LSB lower under the opposite winding while every run
        // and cap byte stays identical.
        let command = PathCommand::new(
            vec![[1.0, 6.0], [1.0, 4.0], [5.0, 4.0]],
            None,
            IDENTITY,
            Some([255, 0, 0, 255]),
            None,
            2.0,
            CapSelector::Butt,
            JoinSelector::Miter,
            0.0,
            None,
            super::super::FillRuleSelector::NonZero,
            true,
            None,
        )
        .expect("chain command");
        let mask = try_rasterize(&command, 8, 8, 64, 100.0 / 72.0)
            .expect("route")
            .expect("rectilinear chain eligible");
        const EXPECTED: [u8; 64] = [
            0, 0, 0, 0, 0, 0, 0, 0, //
            0, 0, 0, 0, 0, 0, 0, 0, //
            114, 128, 114, 0, 0, 0, 0, 0, //
            228, 255, 253, 228, 228, 114, 0, 0, //
            228, 255, 255, 255, 255, 128, 0, 0, //
            204, 228, 228, 228, 228, 114, 0, 0, //
            0, 0, 0, 0, 0, 0, 0, 0, //
            0, 0, 0, 0, 0, 0, 0, 0, //
        ];
        assert_eq!(mask.data(), EXPECTED.as_slice());
    }

    #[test]
    fn triangle_fill_uses_fixed_cell_coverage() {
        let mut command = PathCommand::new(
            vec![[1.0, 1.0], [6.0, 1.0], [1.0, 6.0], [1.0, 1.0]],
            Some(vec![CODE_MOVETO, CODE_LINETO, CODE_LINETO, CODE_CLOSEPOLY]),
            IDENTITY,
            None,
            Some([31, 140, 242, 255]),
            0.0,
            CapSelector::Butt,
            JoinSelector::Miter,
            0.0,
            None,
            super::super::FillRuleSelector::NonZero,
            false,
            None,
        )
        .expect("triangle command");
        command.set_triangle_agg(true);
        let mask = try_rasterize_triangle_fill(&command, 8, 8, 64)
            .expect("triangle route")
            .expect("triangle coverage");
        assert!(mask.data().iter().any(|alpha| *alpha != 0));
        assert!(
            mask.data()
                .iter()
                .all(|alpha| *alpha == 0 || *alpha == u8::MAX)
        );
    }
}
