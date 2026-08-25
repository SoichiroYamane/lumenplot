"""Quickstart: render your first PNG with the lumenplot backend.

Status: pre-alpha. Public API: unstable. Production use: not recommended.
This example targets the Phase-3B slice of the ``lumenplot-mpl``
distribution: the supported input surface is a small whitelisted subset of
Matplotlib, and everything here may change without notice.

What it does:

1. selects the lumenplot Matplotlib backend *before* any figure work;
2. builds an undecorated frame as its own fixture choice (decorated axes
   are strict-eligible too): one axes with ``axison`` disabled and one
   ``Line2D`` with explicit butt caps and miter joins;
3. writes ``quickstart.png`` at 144 DPI into the working directory.

Run it::

    pip install .
    python examples/quickstart.py

The script exits 0 after writing the PNG.
"""

from __future__ import annotations

import matplotlib

# The lumenplot backend must be selected before pyplot or any figure is
# created (and before the stock Agg backend would be picked).
matplotlib.use("module://lumenplot_mpl.backend")

from lumenplot_mpl.backend import FigureCanvasLumenPlot  # noqa: E402
from matplotlib import figure  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

#: Output path, resolved against the current working directory.
OUTPUT_PATH = "quickstart.png"


def main() -> int:
    # Strict mode renders the eligible trace. This example keeps the frame
    # undecorated as its own fixture choice: a plain Figure (no pyplot global
    # state) with one axes whose axison is turned off, plus a single Line2D
    # whose stroke style matches the fixed native contract (butt caps, miter
    # joins; no markers, dashes, or titles).
    #
    # Turning decorations off is not an eligibility requirement — decorated
    # frames are strict-eligible too since PR #63 / ADR-0015 §4a (solid major
    # gridlines, major ticks, spines render natively, subject to that
    # amendment's conditions: facecolor 'none', label-less ticks).
    #
    # Hybrid mode keeps the same strict native path first but falls back to
    # whole-frame Agg output with a structured diagnostic whenever content
    # leaves the strict whitelist:
    #
    #     canvas = FigureCanvasLumenPlot(fig, mode="hybrid")
    fig = figure.Figure(figsize=(4.0, 3.0), dpi=100)
    canvas = FigureCanvasLumenPlot(fig)
    ax = fig.add_axes([0.1, 0.1, 0.8, 0.8])
    ax.axison = False
    ax.add_line(
        Line2D(
            [0.0, 2.5, 5.0, 7.5, 10.0],
            [1.0, 3.0, 2.0, 4.0, 3.5],
            color="red",
            linewidth=2.0,
            solid_capstyle="butt",
            solid_joinstyle="miter",
        )
    )
    ax.set_xlim(0.0, 10.0)
    ax.set_ylim(0.0, 5.0)

    fig.savefig(OUTPUT_PATH, dpi=144)
    print(f"wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
