"""E2E proof for task t_d456087d (PRAC-A-D): decorated axes render natively.

Runs the public adapter (lumenplot_mpl.backend) against the REAL compiled
native seam on an ``axison=True`` figure (solid major gridlines, major tick
strokes, visible spines, plus one eligible content Line2D), then decodes the
emitted PNG and compares against the same figure rendered through stock Agg.
Byte identity with Agg is never asserted (ADR-0015 section 5); this records a
declared semantic-tolerance result: matching canvas geometry and the expected
decoration ink present in both rasters.
"""
import io
import os
import sys

WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Prepend the worktree packages so a pip-installed lumenplot_mpl cannot shadow
# the tree under test.
sys.path.insert(0, os.path.join(WORKSPACE, "tests", "python"))
sys.path.insert(0, os.path.join(WORKSPACE, "python"))

import matplotlib

matplotlib.use("module://lumenplot_mpl.backend")

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from lumenplot_mpl.backend import FigureCanvasLumenPlot

from test_phase3b_backend import _decode_rgba8


def build(fig):
    ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
    ax.set_facecolor("none")  # lane contract: no axes background fill
    ax.tick_params(labelbottom=False, labelleft=False)  # T-lane deliverable
    ax.grid(True)  # solid major gridlines
    ax.add_line(
        Line2D(
            [0.0, 10.0], [0.0, 5.0],
            color="red", linewidth=2.0,
            solid_capstyle="butt", solid_joinstyle="miter",
        )
    )
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(0.0, 5.0)
    return ax


def ink_bbox(rows, width, height, pred):
    xs, ys = [], []
    for y in range(height):
        row = rows[y]
        for x in range(width):
            if pred(row[x * 4], row[x * 4 + 1], row[x * 4 + 2]):
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


red_ink = lambda r, g, b: r > 180 and g < 90 and b < 90
dark_ink = lambda r, g, b: r < 120 and g < 120 and b < 130

fig = Figure(figsize=(2.0, 1.0), dpi=100)
build(fig)

canvas = FigureCanvasLumenPlot(fig)
result = canvas.render_png(mode="strict")
assert result.diagnostics == (), f"strict diagnostics: {result.diagnostics}"
nw, nh, nrows = _decode_rgba8(result.png_bytes)

agg_canvas = FigureCanvasAgg(fig)
buf = io.BytesIO()
agg_canvas.print_png(buf)
aw, ah, arows = _decode_rgba8(buf.getvalue())

print(f"strict diagnostics: {result.diagnostics}")
print(f"native canvas: {nw}x{nh}; agg canvas: {aw}x{ah}")
assert (nw, nh) == (aw, ah) == (200, 100)

for name, pred in (("red line", red_ink), ("dark decoration", dark_ink)):
    nb = ink_bbox(nrows, nw, nh, pred)
    ab = ink_bbox(arows, aw, ah, pred)
    slack = 3
    print(f"{name}: native bbox {nb}, agg bbox {ab}")
    assert nb is not None and ab is not None, f"{name} ink missing"
    for n_coord, a_coord in zip(nb, ab):
        assert abs(n_coord - a_coord) <= slack, (
            f"{name} bbox diverges beyond {slack}px: {nb} vs {ab}"
        )

# The white figure background must be preserved end to end (D2 fix base).
corner = tuple(nrows[0][0:4])
assert corner == (255, 255, 255, 255), f"background lost: {corner}"

print(
    "E2E PASS: decorated axes render strictly natively; geometry matches Agg "
    "within tolerance and the figure background is preserved"
)
