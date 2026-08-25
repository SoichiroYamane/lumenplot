"""E2E proof for task t_f62d90a3: strict-mode render keeps the figure background.

Runs the public adapter (lumenplot_mpl.backend) against the REAL compiled
native seam and decodes the emitted PNG. Before the D2 fix the canvas was
fully transparent regardless of figure facecolor.
"""
import sys

sys.path.insert(0, "/home/sy/dev/rust/lumenplot/.worktrees/t_f62d90a3/python")
sys.path.insert(0, "/home/sy/dev/rust/lumenplot/.worktrees/t_f62d90a3/tests/python")

import matplotlib
matplotlib.use("module://lumenplot_mpl.backend")

from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from lumenplot_mpl.backend import FigureCanvasLumenPlot

from test_phase3b_backend import _decode_rgba8

fig = Figure(figsize=(2.0, 1.0), dpi=100)
canvas = FigureCanvasLumenPlot(fig)
fig.set_facecolor((0.13, 0.55, 0.87))  # a distinctive sky blue
ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
ax.axison = False
ax.add_line(
    Line2D(
        [0.0, 10.0], [0.0, 5.0],
        color="red", linewidth=2.0,
        solid_capstyle="butt", solid_joinstyle="miter",
    )
)
ax.set_xlim(0.0, 10.0)
ax.set_ylim(0.0, 5.0)

result = canvas.render_png()
width, height, rows = _decode_rgba8(result.png_bytes)

corner = tuple(rows[0][0:4])
expected_corner = (33, 140, 222, 255)  # sRGB8 of (0.13, 0.55, 0.87)

red_ink = sum(
    1
    for row in rows
    for x in range(0, len(row), 4)
    if row[x] >= 190 and row[x + 1] < 60 and row[x + 2] < 60 and row[x + 3] == 255
)
bg_pixels = width * height

print(f"canvas: {width}x{height}")
print(f"corner pixel: {corner} (expected {expected_corner})")
print(f"opaque red ink pixels: {red_ink}")
assert corner == expected_corner, "background lost in strict-mode render"
assert red_ink > 0, "stroke ink missing"
print("E2E PASS: strict-mode output preserves figure facecolor and stroke")
