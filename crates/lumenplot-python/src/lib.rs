//! Private PyO3 seam for the `lumenplot_mpl._native` extension module.
//!
//! Phase-3A surface (`render_line_png`) is frozen byte-for-byte; the
//! Phase-3B slice adds `render_frame_png(spec: dict) -> bytes` per manager
//! decisions 2/3 (comment thread of the planning card). The frame rasterizer
//! itself lives in [`crate::frame`], which is free of interpreter types:
//! this module validates while holding the GIL, copies the caller's spec into
//! owned Rust IR exactly once, drops every Python reference before rendering,
//! and contains panics at the boundary.

mod frame;

use std::ops::Range;
use std::panic::{AssertUnwindSafe, catch_unwind};

use lumenplot::__private::{
    BridgeError, LinePngGeometry, LinePngStyle, OwnedLinePngRequest,
    render_line_png as render_facade_line_png,
};
use numpy::{
    PyArrayDescrMethods, PyArrayDyn, PyArrayMethods, PyUntypedArray, PyUntypedArrayMethods, dtype,
};
use pyo3::buffer::PyUntypedBuffer;
use pyo3::exceptions::{PyRuntimeError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{
    PyAny, PyAnyMethods, PyBytes, PyDict, PyDictMethods, PyList, PyListMethods, PyModule,
    PyModuleMethods, PyString, PyType,
};

use crate::frame::{
    CapSelector, Command, FillRuleSelector, FrameError, FrameSpec, ImageCommand, JoinSelector,
    PathCommand,
};

/// Exact-type check for built-in NumPy `ndarray` objects.
///
/// The comparison is done against the live Python-level `numpy.ndarray`
/// type object rather than a cached C-API type pointer, so the result
/// never depends on NumPy import order or C-API initialization state.
fn is_exact_ndarray(object: &Bound<'_, PyAny>) -> PyResult<bool> {
    let numpy = PyModule::import(object.py(), "numpy")?;
    let ndarray_type = numpy.getattr("ndarray")?.cast::<PyType>()?.clone();
    Ok(std::ptr::eq(
        object.get_type_ptr(),
        ndarray_type.as_ptr() as *mut pyo3::ffi::PyTypeObject,
    ))
}

/// Data-pointer extraction without unsafe code.
///
/// `__array_interface__["data"][0]` is the address of the array's first
/// stored element. It is read through NumPy's own Python surface, so no
/// raw pointer arithmetic on the object header is needed here.
fn data_pointer(object: &Bound<'_, PyAny>) -> PyResult<usize> {
    let interface = object.getattr("__array_interface__")?;
    let data = interface.get_item("data")?;
    let address: usize = data.get_item(0)?.extract()?;
    Ok(address)
}

const MAX_POINTS: usize = 1_000_000;

fn lumenplot_error(py: Python<'_>, code: &str, category: &str, message: &str) -> PyErr {
    let package = match PyModule::import(py, "lumenplot_mpl") {
        Ok(package) => package,
        Err(_) => return PyRuntimeError::new_err(message.to_owned()),
    };
    let error_type = match package.getattr("LumenPlotError") {
        Ok(error_type) => error_type,
        Err(_) => return PyRuntimeError::new_err(message.to_owned()),
    };
    match error_type.call1((code, category, message)) {
        Ok(value) => PyErr::from_value(value),
        Err(error) => error,
    }
}

fn bridge_error(py: Python<'_>, error: BridgeError) -> PyErr {
    lumenplot_error(
        py,
        error.code().as_str(),
        error.category().as_str(),
        error.message(),
    )
}

fn type_error(name: &str, detail: &str) -> PyErr {
    PyTypeError::new_err(format!("{name} {detail}"))
}

fn validation_error(message: &'static str) -> PyErr {
    PyValueError::new_err(message)
}

fn internal_error(message: &'static str) -> PyErr {
    PyRuntimeError::new_err(message)
}

fn frame_error(error: FrameError) -> PyErr {
    match error {
        FrameError::Validation(message) => validation_error(message),
        FrameError::OutOfMemory => internal_error("allocation failed"),
        FrameError::Internal(message) => internal_error(message),
    }
}

fn frame_error_to_pyerr(error: FrameError) -> PyErr {
    frame_error(error)
}

fn extract_f64_values<'py>(value: &Bound<'py, PyAny>, name: &str) -> PyResult<Vec<f64>> {
    value
        .extract::<Vec<f64>>()
        .map_err(|_| type_error(name, "must be a sequence of real numbers"))
}

fn extract_fixed_f64<'py, const N: usize>(
    value: &Bound<'py, PyAny>,
    name: &str,
) -> PyResult<[f64; N]> {
    let values = extract_f64_values(value, name)?;
    if values.len() != N {
        return Err(lumenplot_error(
            value.py(),
            "invalid-input",
            "input",
            "sequence has an invalid length",
        ));
    }
    values
        .try_into()
        .map_err(|_| lumenplot_error(value.py(), "internal", "internal", "internal error"))
}

fn extract_rgba<'py>(value: &Bound<'py, PyAny>, name: &str) -> PyResult<[u8; 4]> {
    let values = value
        .extract::<Vec<i64>>()
        .map_err(|_| type_error(name, "must be a sequence of integer channels"))?;
    if values.len() != 4 || values.iter().any(|channel| !(0..=255).contains(channel)) {
        return Err(lumenplot_error(
            value.py(),
            "invalid-input",
            "input",
            "RGBA channels must be integers in the range 0..=255",
        ));
    }
    Ok([
        values[0] as u8,
        values[1] as u8,
        values[2] as u8,
        values[3] as u8,
    ])
}

fn dense_span_error(py: Python<'_>) -> PyErr {
    lumenplot_error(
        py,
        "invalid-input",
        "input",
        "x and y elements must lie inside the array's base allocation",
    )
}

/// Resolve the root allocation that ultimately owns the array data.
///
/// NumPy views keep a reference to their owning object in `base`. Walking
/// that chain reaches either a plain buffer owner (from `frombuffer` and
/// friends) or an exact `ndarray` whose own data pointer is the storage
/// anchor. The returned extent is the true byte size of that root
/// allocation, independent of what any view reports.
fn resolve_root_extent<'py>(
    py: Python<'py>,
    array: &Bound<'py, PyUntypedArray>,
) -> PyResult<(Bound<'py, PyAny>, usize, usize)> {
    let mut current: Bound<'py, PyAny> = array.clone().into_any();
    loop {
        // Buffer owners such as `memoryview` have no `base` attribute; they
        // are already the allocation root for their view chains.
        let Ok(base) = current.getattr("base") else {
            break;
        };
        if base.is_none() {
            break;
        }
        // Only exact ndarray bases can be interpreted as storage anchors;
        // anything else (writeable flags objects, multi-views onto other
        // owners) is still walked through its own `base`.
        if is_exact_ndarray(&base)? {
            current = base;
            continue;
        }
        if !base.hasattr("nbytes")? {
            // Non-buffer, non-array owner: the true root allocation cannot
            // be resolved, so fail closed rather than letting the view act
            // as its own root.
            return Err(dense_span_error(py));
        }
        current = base;
    }

    if is_exact_ndarray(&current)? {
        let itemsize = current
            .getattr("dtype")?
            .getattr("itemsize")?
            .extract::<usize>()?;
        // The element count of an N-D root allocation is the product of ALL
        // shape dimensions. `PyUntypedArrayMethods::len` cannot be used here:
        // `current` is a plain Python object, so `len()` would dispatch to
        // the Python protocol and report `shape[0]` only — undercounting
        // every root with more than one dimension and raising a raw
        // `TypeError` for 0-d roots. The empty product of an empty shape is
        // 1, which is exactly the element count of a 0-d array.
        let size: usize = current
            .getattr("shape")?
            .extract::<Vec<usize>>()?
            .into_iter()
            .product();
        let extent = itemsize.saturating_mul(size);
        // The storage anchor is the data pointer of the root array, i.e.
        // the address of its first stored element.
        let root_data_ptr = data_pointer(&current)?;
        return Ok((current, extent, root_data_ptr));
    }

    // Non-ndarray buffer owners (e.g. the `memoryview` left behind by
    // `np.frombuffer`) hold their storage outside the object header, so
    // `as_ptr()` would report the PyObject address rather than the data
    // address. The buffer protocol exposes the true data pointer and byte
    // length of the root allocation.
    let buffer = PyUntypedBuffer::get(&current).map_err(|_| dense_span_error(py))?;
    let extent = buffer.len_bytes();
    if extent == 0 {
        return Err(dense_span_error(py));
    }
    let root_ptr = buffer.buf_ptr() as usize;
    Ok((current, extent, root_ptr))
}

/// Validate that every reachable element address lies inside the root
/// allocation before any read is performed.
///
/// API-0003 accepts safe logical positive, negative, and zero strides and
/// traverses logical order, so safety comes from bounds validation rather
/// than stride rejection. The full element-address range is computed from
/// the view's data pointer and stride; it must fit inside the resolved root
/// extent. This rejects far-stride views whose logical span escapes the
/// backing buffer while keeping ordinary reversed, strided-in-bounds, and
/// broadcast views accepted.
fn validate_reachable_span<'py>(
    py: Python<'py>,
    array: &Bound<'py, PyUntypedArray>,
    length: usize,
) -> PyResult<()> {
    let (_root, root_extent, root_ptr) = resolve_root_extent(py, array)?;
    // The address the element traversal actually starts from.
    let view_ptr = data_pointer(array.as_any())?;
    if view_ptr == 0 || root_ptr == 0 {
        return Err(dense_span_error(py));
    }
    let itemsize = array.dtype().itemsize();
    let stride = array.strides()[0];

    // Zero-length arrays never traverse memory. NumPy reports them as
    // aligned regardless of the data pointer, but Rust slice semantics do
    // not, so a misaligned pointer is rejected even at length zero.
    if length == 0 {
        if view_ptr % std::mem::align_of::<f64>() != 0 {
            return Err(dense_span_error(py));
        }
        return Ok(());
    }

    // Element addresses relative to the view data pointer:
    //   lowest = min(0, (length - 1) * stride), highest = max(0, ...)
    //
    // Zero strides never move the address, so a zero-stride traversal reads
    // only the single element under the data pointer instead of claiming a
    // wide byte span. Any arithmetic overflow cannot describe a real span
    // and is rejected.
    let signed_stride = stride;
    let (first_offset, last_offset) = if length <= 1 || signed_stride == 0 {
        (Some(0usize), Some(0usize))
    } else if signed_stride > 0 {
        let last = (length - 1).checked_mul(signed_stride as usize);
        (Some(0usize), last)
    } else {
        // Negative strides: elements sit below the data pointer. The lowest
        // address is the first element read; the highest is element 0.
        let back = (length - 1).checked_mul(signed_stride.unsigned_abs());
        (back, Some(0usize))
    };
    let Some(first_offset) = first_offset else {
        return Err(dense_span_error(py));
    };
    let Some(last_offset) = last_offset else {
        return Err(dense_span_error(py));
    };

    let low_ok = view_ptr
        .checked_sub(first_offset)
        .is_some_and(|addr| addr >= root_ptr);
    match view_ptr
        .checked_add(last_offset)
        .and_then(|addr| addr.checked_add(itemsize))
        .and_then(|addr| addr.checked_sub(root_ptr))
    {
        Some(high_end) if low_ok && high_end <= root_extent => Ok(()),
        _ => Err(dense_span_error(py)),
    }
}

fn copy_array<'py>(py: Python<'py>, value: &Bound<'py, PyAny>, name: &str) -> PyResult<Vec<f64>> {
    if !value.is_exact_instance_of::<PyUntypedArray>() {
        return Err(lumenplot_error(
            py,
            "invalid-input",
            "input",
            "x and y must be exact one-dimensional NumPy arrays",
        ));
    }

    let array = value.cast::<PyUntypedArray>().map_err(|_| {
        lumenplot_error(
            py,
            "invalid-input",
            "input",
            "x and y must be exact one-dimensional NumPy arrays",
        )
    })?;
    if array.ndim() != 1 {
        return Err(lumenplot_error(
            py,
            "invalid-input",
            "input",
            "x and y must be one-dimensional NumPy arrays",
        ));
    }
    let length = array.len();
    if length > MAX_POINTS {
        return Err(lumenplot_error(
            py,
            "invalid-input",
            "input",
            "x and y exceed the point limit",
        ));
    }
    if !array.is_aligned() {
        return Err(lumenplot_error(
            py,
            "invalid-input",
            "input",
            "x and y must be aligned NumPy arrays",
        ));
    }
    validate_reachable_span(py, array, length)?;

    let array_dtype = array.dtype();
    let values = if array_dtype.is_equiv_to(&dtype::<f64>(py)) {
        let typed = value.cast::<PyArrayDyn<f64>>().map_err(|_| {
            lumenplot_error(
                py,
                "invalid-input",
                "input",
                "x and y must use native-endian float32 or float64",
            )
        })?;
        let readonly = typed.try_readonly().map_err(|_| {
            lumenplot_error(
                py,
                "invalid-input",
                "input",
                "x and y could not be borrowed safely",
            )
        })?;
        let view = readonly.as_array();
        let mut owned = Vec::new();
        owned
            .try_reserve_exact(length)
            .map_err(|_| lumenplot_error(py, "out-of-memory", "resource", "allocation failed"))?;
        owned.extend(view.iter().copied());
        owned
    } else if array_dtype.is_equiv_to(&dtype::<f32>(py)) {
        let typed = value.cast::<PyArrayDyn<f32>>().map_err(|_| {
            lumenplot_error(
                py,
                "invalid-input",
                "input",
                "x and y must use native-endian float32 or float64",
            )
        })?;
        let readonly = typed.try_readonly().map_err(|_| {
            lumenplot_error(
                py,
                "invalid-input",
                "input",
                "x and y could not be borrowed safely",
            )
        })?;
        let view = readonly.as_array();
        let mut owned = Vec::new();
        owned
            .try_reserve_exact(length)
            .map_err(|_| lumenplot_error(py, "out-of-memory", "resource", "allocation failed"))?;
        owned.extend(view.iter().map(|value| f64::from(*value)));
        owned
    } else {
        return Err(lumenplot_error(
            py,
            "invalid-input",
            "input",
            "x and y must use native-endian float32 or float64",
        ));
    };

    if values.iter().any(|point| point.is_infinite()) {
        return Err(lumenplot_error(
            py,
            "invalid-input",
            "input",
            "x and y may contain NaN gaps but not infinite values",
        ));
    }
    let _ = name;
    Ok(values)
}

fn valid_segments(x: &[f64], y: &[f64], py: Python<'_>) -> PyResult<Vec<Range<usize>>> {
    if x.len() != y.len() {
        return Err(lumenplot_error(
            py,
            "invalid-input",
            "input",
            "x and y must have equal lengths",
        ));
    }
    let mut segments = Vec::new();
    segments
        .try_reserve(x.len() / 2 + 1)
        .map_err(|_| lumenplot_error(py, "out-of-memory", "resource", "allocation failed"))?;
    let mut start = None;
    for (index, (&x_value, &y_value)) in x.iter().zip(y).enumerate() {
        if x_value.is_finite() && y_value.is_finite() {
            if start.is_none() {
                start = Some(index);
            }
        } else if let Some(segment_start) = start.take() {
            segments.push(segment_start..index);
        }
    }
    if let Some(segment_start) = start {
        segments.push(segment_start..x.len());
    }
    Ok(segments)
}

#[allow(clippy::too_many_arguments)]
#[pyfunction(signature = (x, y, *, viewport, canvas, plot_rect, logical_units_per_inch, output_dpi, line_rgba, line_width, background_rgba))]
fn render_line_png<'py>(
    py: Python<'py>,
    x: Bound<'py, PyAny>,
    y: Bound<'py, PyAny>,
    viewport: Bound<'py, PyAny>,
    canvas: Bound<'py, PyAny>,
    plot_rect: Bound<'py, PyAny>,
    logical_units_per_inch: f64,
    output_dpi: f64,
    line_rgba: Bound<'py, PyAny>,
    line_width: f64,
    background_rgba: Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyBytes>> {
    let viewport_values = extract_fixed_f64::<4>(&viewport, "viewport")?;
    let canvas_values = extract_fixed_f64::<2>(&canvas, "canvas")?;
    let plot_rect_values = extract_fixed_f64::<4>(&plot_rect, "plot_rect")?;
    let line_rgba_values = extract_rgba(&line_rgba, "line_rgba")?;
    let background_rgba_values = extract_rgba(&background_rgba, "background_rgba")?;
    let (x_values, y_values, segments) = {
        let x_values = copy_array(py, &x, "x")?;
        let y_values = copy_array(py, &y, "y")?;
        let segments = valid_segments(&x_values, &y_values, py)?;
        (x_values, y_values, segments)
    };
    drop(x);
    drop(y);
    drop(viewport);
    drop(canvas);
    drop(plot_rect);
    drop(line_rgba);
    drop(background_rgba);

    let geometry = LinePngGeometry::new(
        viewport_values,
        canvas_values,
        plot_rect_values,
        logical_units_per_inch,
    )
    .map_err(|error| bridge_error(py, error))?;
    let style = LinePngStyle::new(line_rgba_values, line_width, background_rgba_values)
        .map_err(|error| bridge_error(py, error))?;
    let request =
        OwnedLinePngRequest::new(x_values, y_values, segments, geometry, style, output_dpi)
            .map_err(|error| bridge_error(py, error))?;

    let rendered = catch_unwind(AssertUnwindSafe(|| {
        py.detach(move || render_facade_line_png(request))
    }));
    let bytes = match rendered {
        Ok(Ok(bytes)) => bytes,
        Ok(Err(error)) => return Err(bridge_error(py, error)),
        Err(_) => {
            return Err(lumenplot_error(
                py,
                "internal",
                "internal",
                "internal error",
            ));
        }
    };
    Ok(PyBytes::new(py, &bytes))
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(render_line_png, module)?)?;
    module.add_function(wrap_pyfunction!(render_frame_png, module)?)?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Phase-3B frame seam: `render_frame_png(spec: dict) -> bytes`.
//
// Binding contract (manager decisions 2/3 on the Phase-3B planning card):
// validation failures raise ValueError; internal/raster failures raise
// RuntimeError-family exceptions; panics never cross the boundary; the same
// spec produces identical bytes. Extraction happens while the GIL is held and
// copies the spec into owned IR exactly once; no Python borrow survives into
// the rasterizer.
// ---------------------------------------------------------------------------

fn required_key<'py>(command: &Bound<'py, PyDict>, key: &str) -> PyResult<Bound<'py, PyAny>> {
    let Some(value) = command.get_item(key)? else {
        return Err(validation_error("command dict is missing a required key"));
    };
    Ok(value.into_any())
}

fn optional_key<'py>(
    command: &Bound<'py, PyDict>,
    key: &str,
) -> PyResult<Option<Bound<'py, PyAny>>> {
    match command.get_item(key)? {
        Some(value) if !value.is_none() => Ok(Some(value.into_any())),
        _ => Ok(None),
    }
}

fn extract_f64_pair(value: &Bound<'_, PyAny>) -> PyResult<[f64; 2]> {
    let values = value
        .extract::<Vec<f64>>()
        .map_err(|_| type_error("vertex", "must be a [float, float] pair"))?;
    if values.len() != 2 {
        return Err(validation_error("vertex must contain exactly two floats"));
    }
    Ok([values[0], values[1]])
}

fn extract_transform(value: &Bound<'_, PyAny>) -> PyResult<[f64; 6]> {
    let values = value
        .extract::<Vec<f64>>()
        .map_err(|_| type_error("transform", "must be six finite floats"))?;
    if values.len() != 6 {
        return Err(validation_error(
            "transform must contain exactly six floats",
        ));
    }
    Ok([
        values[0], values[1], values[2], values[3], values[4], values[5],
    ])
}

fn extract_clip_rect(value: &Bound<'_, PyAny>) -> PyResult<[f64; 4]> {
    let values = value
        .extract::<Vec<f64>>()
        .map_err(|_| type_error("clip_rect", "must be [x, y, width, height] floats"))?;
    if values.len() != 4 {
        return Err(validation_error(
            "clip_rect must contain exactly four floats",
        ));
    }
    Ok([values[0], values[1], values[2], values[3]])
}

fn extract_rgba_option(value: Option<&Bound<'_, PyAny>>) -> PyResult<Option<[u8; 4]>> {
    let Some(value) = value else {
        return Ok(None);
    };
    let values = value
        .extract::<Vec<i64>>()
        .map_err(|_| type_error("rgba", "must be four integer channels"))?;
    if values.len() != 4 || values.iter().any(|channel| !(0..=255).contains(channel)) {
        return Err(validation_error(
            "rgba channels must be integers in the range 0..=255",
        ));
    }
    Ok(Some([
        values[0] as u8,
        values[1] as u8,
        values[2] as u8,
        values[3] as u8,
    ]))
}

fn selector_from(
    command: &Bound<'_, PyDict>,
    key: &str,
    allowed: &[(&'static str, &'static str)],
) -> PyResult<&'static str> {
    let value = required_key(command, key)?;
    let text: &str = value
        .cast::<PyString>()?
        .to_str()
        .map_err(|_| type_error(key, "must be a string"))?;
    for (candidate, selected) in allowed {
        if text == *candidate {
            return Ok(selected);
        }
    }
    Err(validation_error("command field has an unrecognized value"))
}

fn extract_path_command(command: &Bound<'_, PyDict>) -> PyResult<PathCommand> {
    let vertices_value = required_key(command, "vertices")?;
    let vertex_list = vertices_value
        .cast::<PyList>()
        .map_err(|_| type_error("vertices", "must be a list of [x, y] pairs"))?;
    let mut vertices = Vec::new();
    if vertices.try_reserve_exact(vertex_list.len()).is_err() {
        return Err(internal_error("allocation failed"));
    }
    for vertex in vertex_list.iter() {
        vertices.push(extract_f64_pair(&vertex)?);
    }

    let codes = match optional_key(command, "codes")? {
        Some(codes_value) => {
            let code_list = codes_value
                .cast::<PyList>()
                .map_err(|_| type_error("codes", "must be a list of integers or None"))?;
            let mut codes = Vec::new();
            if codes.try_reserve_exact(code_list.len()).is_err() {
                return Err(internal_error("allocation failed"));
            }
            for code in code_list.iter() {
                codes.push(
                    code.extract::<i64>()
                        .map_err(|_| type_error("codes", "must be a list of integers"))?,
                );
            }
            Some(codes)
        }
        None => None,
    };

    let transform = extract_transform(&required_key(command, "transform")?)?;
    let stroke_rgba = extract_rgba_option(optional_key(command, "stroke_rgba")?.as_ref())?;
    let fill_rgba = extract_rgba_option(optional_key(command, "fill_rgba")?.as_ref())?;

    let line_width_pt = optional_key(command, "line_width_pt")?
        .map(|value| {
            value
                .extract::<f64>()
                .map_err(|_| type_error("line_width_pt", "must be a float"))
        })
        .transpose()?
        .unwrap_or(if stroke_rgba.is_some() { 1.0 } else { 0.0 });
    let cap = match selector_from(
        command,
        "cap",
        &[
            ("butt", "butt"),
            ("round", "round"),
            ("projecting", "projecting"),
        ],
    )? {
        "round" => CapSelector::Round,
        "projecting" => CapSelector::Projecting,
        _ => CapSelector::Butt,
    };
    let join = match selector_from(
        command,
        "join",
        &[("miter", "miter"), ("round", "round"), ("bevel", "bevel")],
    )? {
        "round" => JoinSelector::Round,
        "bevel" => JoinSelector::Bevel,
        _ => JoinSelector::Miter,
    };

    let dash_offset_pt = optional_key(command, "dash_offset_pt")?
        .map(|value| {
            value
                .extract::<f64>()
                .map_err(|_| type_error("dash_offset_pt", "must be a float"))
        })
        .transpose()?
        .unwrap_or(0.0);
    let dashes = match optional_key(command, "dashes")? {
        Some(dashes_value) => {
            let dash_list = dashes_value
                .cast::<PyList>()
                .map_err(|_| type_error("dashes", "must be a list of floats or None"))?;
            let mut dashes = Vec::new();
            if dashes.try_reserve_exact(dash_list.len()).is_err() {
                return Err(internal_error("allocation failed"));
            }
            for dash in dash_list.iter() {
                dashes.push(
                    dash.extract::<f64>()
                        .map_err(|_| type_error("dashes", "must be a list of floats"))?,
                );
            }
            Some(dashes)
        }
        None => None,
    };

    let fill_rule = match selector_from(
        command,
        "fill_rule",
        &[("nonzero", "nonzero"), ("evenodd", "evenodd")],
    )? {
        "evenodd" => FillRuleSelector::EvenOdd,
        _ => FillRuleSelector::NonZero,
    };
    let antialias = optional_key(command, "antialias")?
        .map(|value| {
            value
                .extract::<bool>()
                .map_err(|_| type_error("antialias", "must be a bool"))
        })
        .transpose()?
        .unwrap_or(true);
    let clip_rect = optional_key(command, "clip_rect")?
        .map(|value| extract_clip_rect(&value))
        .transpose()?;

    PathCommand::new(
        vertices,
        codes,
        transform,
        stroke_rgba,
        fill_rgba,
        line_width_pt,
        cap,
        join,
        dash_offset_pt,
        dashes,
        fill_rule,
        antialias,
        clip_rect,
    )
    .map_err(frame_error_to_pyerr)
}

fn extract_image_command(command: &Bound<'_, PyDict>) -> PyResult<ImageCommand> {
    let x = required_key(command, "x")?
        .extract::<f64>()
        .map_err(|_| type_error("x", "must be a float"))?;
    let y = required_key(command, "y")?
        .extract::<f64>()
        .map_err(|_| type_error("y", "must be a float"))?;
    // Image dimensions are not self-describing from raw bytes, so they are
    // required keys of the image command (additive refinement of decision
    // 2/3's key list; recorded in the handoff).
    let width = required_key(command, "width")?
        .extract::<u32>()
        .map_err(|_| type_error("width", "must be a positive int"))?;
    let height = required_key(command, "height")?
        .extract::<u32>()
        .map_err(|_| type_error("height", "must be a positive int"))?;
    let rgba_value = required_key(command, "rgba")?;
    let rgba: Vec<u8> = rgba_value.extract().map_err(|_| {
        type_error(
            "rgba",
            "must be a bytes-like object of length width*height*4",
        )
    })?;
    let clip_rect = optional_key(command, "clip_rect")?
        .map(|value| extract_clip_rect(&value))
        .transpose()?;
    ImageCommand::new(x, y, width, height, rgba, clip_rect).map_err(frame_error_to_pyerr)
}

fn extract_command(command: &Bound<'_, PyAny>) -> PyResult<Command> {
    let dict = command
        .cast::<PyDict>()
        .map_err(|_| type_error("commands", "entries must be dicts"))?;
    let kind_value = required_key(dict, "kind")?;
    let kind: &str = kind_value
        .cast::<PyString>()?
        .to_str()
        .map_err(|_| type_error("kind", "must be a string"))?;
    match kind {
        "path" => extract_path_command(dict).map(Command::Path),
        "image" => extract_image_command(dict).map(Command::Image),
        _ => Err(validation_error("unknown command kind")),
    }
}

/// Extracts and validates the whole `spec` dictionary into owned IR while the
/// GIL is held.
fn extract_spec(spec: &Bound<'_, PyAny>) -> PyResult<FrameSpec> {
    let dict = spec
        .cast::<PyDict>()
        .map_err(|_| type_error("spec", "must be a dict"))?;
    let width_px: u64 = required_key(dict, "width_px")?
        .extract()
        .map_err(|_| type_error("width_px", "must be a positive int"))?;
    let height_px: u64 = required_key(dict, "height_px")?
        .extract()
        .map_err(|_| type_error("height_px", "must be a positive int"))?;
    let output_dpi: f64 = required_key(dict, "output_dpi")?
        .extract()
        .map_err(|_| type_error("output_dpi", "must be a float"))?;
    let commands_value = required_key(dict, "commands")?;
    let commands_list = commands_value
        .cast::<PyList>()
        .map_err(|_| type_error("commands", "must be a list of dicts"))?;

    let width_px = u32::try_from(width_px)
        .map_err(|_| validation_error("dimensions exceed the supported maximum"))?;
    let height_px = u32::try_from(height_px)
        .map_err(|_| validation_error("dimensions exceed the supported maximum"))?;
    let mut frame_spec =
        FrameSpec::new(width_px, height_px, output_dpi).map_err(frame_error_to_pyerr)?;

    // Optional canvas seed. The adapter (ADR 0015 §6) always sends
    // `background_rgba`; the seam treats it as additive so an absent key
    // keeps the frozen transparent-canvas behavior of the accepted slice.
    if let Some(background) = optional_key(dict, "background_rgba")? {
        let background_rgba = extract_rgba(&background, "background_rgba")?;
        frame_spec.set_background_rgba(background_rgba);
    }

    // Optional compositing model (architecture ruling 2026-08-25, an
    // additive amendment of ADR 0012): "linear" (default, frozen byte
    // behavior) or "agg_srgb" for the adapter's Agg-parity path.
    if let Some(mode_value) = optional_key(dict, "blend_mode")? {
        let mode: &str = mode_value
            .cast::<PyString>()
            .map_err(|_| type_error("blend_mode", "must be a string"))?
            .to_str()
            .map_err(|_| type_error("blend_mode", "must be a string"))?;
        match mode {
            "linear" => frame_spec.set_blend_mode(frame::BlendMode::Linear),
            "agg_srgb" => frame_spec.set_blend_mode(frame::BlendMode::AggSrgb),
            _ => {
                return Err(PyValueError::new_err(
                    "blend_mode is unrecognized; use 'linear' or 'agg_srgb'",
                ));
            }
        }
    }

    if frame_spec.reserve_commands(commands_list.len()).is_err() {
        return Err(internal_error("allocation failed"));
    }
    for entry in commands_list.iter() {
        frame_spec
            .push_command(extract_command(&entry)?)
            .map_err(frame_error_to_pyerr)?;
    }
    Ok(frame_spec)
}

#[pyfunction]
fn render_frame_png<'py>(
    py: Python<'py>,
    spec: Bound<'py, PyAny>,
) -> PyResult<Bound<'py, PyBytes>> {
    let frame_spec = extract_spec(&spec)?;
    drop(spec);

    let rendered = catch_unwind(AssertUnwindSafe(|| {
        py.detach(move || frame::render_frame_png(&frame_spec))
    }));
    match rendered {
        Ok(Ok(bytes)) => Ok(PyBytes::new(py, &bytes)),
        Ok(Err(error)) => Err(frame_error(error)),
        Err(_) => Err(lumenplot_error(
            py,
            "internal",
            "internal",
            "internal error",
        )),
    }
}
