# -*- coding: utf-8 -*-
"""Generate multi-size app.ico from the ALE Workbench logo (icon.svg)."""
import os
from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")

# Palette from frontend/public/icons/icon.svg
BG = "#102438"   # dark navy rounded square
BAR = "#72d3cf"  # teal bars (the "ALE" strokes)
BAR2 = "#4ca6b2" # lighter teal underline
DOT = "#9fe3dc"  # accent dot


def make_icon(size):
    s = size / 64.0
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def rr(x0, y0, x1, y1, r, fill):
        d.rounded_rectangle(
            [x0 * s, y0 * s, x1 * s, y1 * s],
            radius=max(1, int(r * s)), fill=fill)

    rr(0, 0, 64, 64, 14, BG)            # background
    rr(10, 21, 54, 29, 2, BAR)          # top bar
    rr(15, 31, 49, 39, 2, BAR)          # middle bar
    rr(20, 41, 44, 49, 2, BAR)          # bottom bar
    rr(24, 53, 40, 55, 1, BAR2)         # underline
    d.ellipse([(32 - 3.5) * s, (13 - 3.5) * s, (32 + 3.5) * s, (13 + 3.5) * s], fill=DOT)
    return img


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    master = make_icon(256)
    master.save(OUT, format="ICO", sizes=[(s, s) for s in sizes])
    im = Image.open(OUT)
    print("wrote", OUT, os.path.getsize(OUT), "bytes, sizes:", im.info.get("sizes"))


if __name__ == "__main__":
    main()
