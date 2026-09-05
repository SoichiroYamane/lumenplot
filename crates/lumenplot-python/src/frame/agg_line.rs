//! Agg-compatible coverage for bounded, simple Line2D strokes.
//!
//! Matplotlib's pinned Agg oracle converts stroked polygon vertices to 24.8
//! fixed-point coordinates and integrates signed edge area per pixel. Tiny-skia
//! uses a 4x4 coverage grid, which is intentionally faster but leaves visible
//! 1/16 coverage steps on oblique stroke fringes. This module implements the
//! same fixed-point area model for isolated, undashed butt-capped segments in
//! the adapter-only `agg_srgb` path. Unsupported geometry falls through to the
//! existing tiny-skia rasterizer; native/export linear-light rendering is never
//! routed here.

use tiny_skia::Mask;

use super::{
    CODE_LINETO, CODE_MOVETO, CODE_STOP, CapSelector, FrameError, JoinSelector, PathCommand,
    coverage_mask,
};

const SUBPIXEL_SHIFT: u32 = 8;
const SUBPIXEL_SCALE: i64 = 1 << SUBPIXEL_SHIFT;
const SUBPIXEL_MASK: i64 = SUBPIXEL_SCALE - 1;
const COVERAGE_SHIFT: u32 = SUBPIXEL_SHIFT * 2 + 1 - 8;
const MAX_CELLS: usize = 1_000_000;
const AUTO_SNAP_VERTEX_LIMIT: usize = 1_024;
const AXIS_ALIGNMENT_EPSILON: f64 = 1.0e-4;

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
        || command.fill_rgba.is_some()
        || !matches!(command.cap, CapSelector::Butt)
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

    let bounds = raster_bounds(command, width, height);
    let mut polygons = Vec::new();
    polygons
        .try_reserve_exact(segments.len())
        .map_err(|_| FrameError::OutOfMemory)?;
    for segment in segments {
        let Some(polygon) = stroke_polygon(segment, stroke_width, bounds) else {
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

fn extract_segments(
    command: &PathCommand,
    height: u32,
) -> Result<Option<Vec<Segment>>, FrameError> {
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

fn map_device_point(transform: [f64; 6], vertex: [f64; 2], height: u32) -> Option<Point> {
    let [a, b, c, d, e, f] = transform;
    let x = a * vertex[0] + c * vertex[1] + e;
    let y = f64::from(height) - (b * vertex[0] + d * vertex[1] + f);
    (x.is_finite() && y.is_finite()).then_some(Point { x, y })
}

#[derive(Clone, Copy)]
struct RasterBounds {
    left: f64,
    top: f64,
    right: f64,
    bottom: f64,
}

fn raster_bounds(command: &PathCommand, width: u32, height: u32) -> RasterBounds {
    let canvas = RasterBounds {
        left: 0.0,
        top: 0.0,
        right: f64::from(width),
        bottom: f64::from(height),
    };
    let Some([x, y, clip_width, clip_height]) = command.clip_rect else {
        return canvas;
    };
    RasterBounds {
        left: canvas.left.max(x),
        top: canvas.top.max(f64::from(height) - (y + clip_height)),
        right: canvas.right.min(x + clip_width),
        bottom: canvas.bottom.min(f64::from(height) - y),
    }
}

fn stroke_polygon(segment: Segment, stroke_width: f64, bounds: RasterBounds) -> Option<Polygon> {
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
    if corners.iter().any(|point| {
        !point.x.is_finite()
            || !point.y.is_finite()
            || point.x < bounds.left
            || point.x > bounds.right
            || point.y < bounds.top
            || point.y > bounds.bottom
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
    fn multi_segment_runs_use_existing_rasterizer() {
        let mut command = gap_command();
        command.vertices = vec![[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]];
        assert!(
            try_rasterize(&command, 8, 8, 64, 1.0)
                .expect("route")
                .is_none()
        );
    }
}
