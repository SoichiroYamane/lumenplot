use std::ops::Range;
use std::panic::{AssertUnwindSafe, catch_unwind};

use lumenplot::__private::{
    BridgeError, LinePngGeometry, LinePngStyle, OwnedLinePngRequest,
    render_line_png as render_facade_line_png,
};
use numpy::{
    PyArrayDescrMethods, PyArrayDyn, PyArrayMethods, PyUntypedArray, PyUntypedArrayMethods, dtype,
};
use pyo3::exceptions::{PyAttributeError, PyRuntimeError, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{PyAny, PyAnyMethods, PyBytes, PyModule, PyModuleMethods, PyType};

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
            // Non-buffer, non-array owner: stop here; the span check below
            // will reject reads that escape the reported view anyway because
            // the extent falls back to zero for unknown roots.
            break;
        }
        current = base;
    }

    if is_exact_ndarray(&current)? {
        let itemsize = current
            .getattr("dtype")?
            .getattr("itemsize")?
            .extract::<usize>()?;
        let size = current.len()?;
        let extent = itemsize.saturating_mul(size);
        // The storage anchor is the data pointer of the root array, i.e.
        // the address of its first stored element.
        let root_data_ptr = data_pointer(&current)?;
        return Ok((current, extent, root_data_ptr));
    }

    let nbytes: Bound<'py, PyAny> = current
        .getattr("nbytes")
        .map_err(|_| PyAttributeError::new_err("nbytes"))?;
    let nbytes_value: isize = nbytes.extract().map_err(|_| dense_span_error(py))?;
    let extent = if nbytes_value < 0 {
        0
    } else {
        nbytes_value as usize
    };
    let root_ptr = current.as_ptr() as usize;
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
    Ok(())
}
