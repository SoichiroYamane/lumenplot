"""PRAC-A-D evidence workload: numeric native-vs-Agg comparison.

Compares the strict-mode decorated-axes native PNG against the same figure
rendered through stock Agg. Byte identity with Agg is never asserted
(ADR-0015 section 5); this records a declared semantic-tolerance result.

Usage: python pracad_native_vs_agg_compare.py <native.png> <agg.png>
"""

import struct
import sys
import zlib


def load_png_rgba(path):
    data = open(path, "rb").read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    w = h = color = None
    idat = b""
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        if ctype == b"IHDR":
            w, h, depth, color = struct.unpack(">IIBB", chunk[:10])
            assert depth == 8, "8-bit PNGs only"
        elif ctype == b"IDAT":
            idat += chunk
        pos += 12 + ln
    raw = zlib.decompress(idat)
    channels = {2: 3, 6: 4}[color]
    stride = w * channels
    px = bytearray(w * h * channels)
    prev = bytearray(stride)
    i = 0
    for y in range(h):
        f = raw[i]
        i += 1
        line = bytearray(raw[i:i + stride])
        i += stride
        if f == 1:
            for x in range(channels, stride):
                line[x] = (line[x] + line[x - channels]) & 255
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 255
        elif f == 4:
            for x in range(stride):
                a = line[x - channels] if x >= channels else 0
                c = prev[x - channels] if x >= channels else 0
                b = prev[x]
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                best = a if pa <= pb and pa <= pc else (
                    b if pb <= pc else c)
                line[x] = (line[x] + best) & 255
        px[y * stride:(y + 1) * stride] = line
        prev = line
    return w, h, channels, bytes(px)


def main():
    native_path, agg_path = sys.argv[1], sys.argv[2]
    w1, h1, ch1, px1 = load_png_rgba(native_path)
    w2, h2, ch2, px2 = load_png_rgba(agg_path)
    print(f"native: {w1}x{h1} ch{ch1}; agg: {w2}x{h2} ch{ch2}")
    assert (w1, h1) == (w2, h2), "canvas dimensions must match"

    tol = 40
    diffs = 0
    maxdiff = 0
    m = min(len(px1), len(px2))
    # Compare RGB triplets only (alpha semantics differ by design).
    rgb1 = [px1[i] for i in range(m) if (i % ch1) < 3]
    rgb2 = [px2[i] for i in range(min(len(px2), m)) if (i % ch2) < 3]
    n = min(len(rgb1), len(rgb2))
    for i in range(n):
        d = abs(rgb1[i] - rgb2[i])
        if d > maxdiff:
            maxdiff = d
        if d > tol:
            diffs += 1
    print(
        f"rgb samples beyond tol({tol}): {diffs} of {n} "
        f"({100.0 * diffs / n:.3f}%); max channel delta: {maxdiff}"
    )

    def bbox(px, ch, pred):
        xs, ys = [], []
        for y in range(h1):
            for x in range(w1):
                i = (y * w1 + x) * ch
                r, g, b = px[i], px[i + 1], px[i + 2]
                if pred(r, g, b):
                    xs.append(x)
                    ys.append(y)
        return (min(xs), min(ys), max(xs), max(ys)) if xs else None

    red = lambda r, g, b: r > 180 and g < 90 and b < 90
    dark = lambda r, g, b: r < 120 and g < 120 and b < 130
    print("red-line ink bbox  native:", bbox(px1, ch1, red),
          " agg:", bbox(px2, ch2, red))
    print("dark deco ink bbox native:", bbox(px1, ch1, dark),
          " agg:", bbox(px2, ch2, dark))


if __name__ == "__main__":
    main()
