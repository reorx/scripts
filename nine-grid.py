#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pillow",
# ]
# ///
"""Crop photos to squares at the same position and compose a 3x3 grid.

Each photo is cropped to a square whose side equals its short edge.
A position value from 0 to 1 sets where the square's center falls on
the long edge (0 = start, 0.5 = middle, 1 = end; clamped to fit).
Photos fill the grid from the top row, left to right. Empty cells
are filled with white.
"""

import argparse
import sys

from PIL import Image, ImageOps


def crop_square(img: Image.Image, position: float) -> Image.Image:
    w, h = img.size
    side = min(w, h)
    long_edge = max(w, h)
    center = position * long_edge
    offset = int(round(center - side / 2))
    offset = max(0, min(offset, long_edge - side))
    if w >= h:
        box = (offset, 0, offset + side, side)
    else:
        box = (0, offset, side, offset + side)
    return img.crop(box)


def main():
    parser = argparse.ArgumentParser(
        description="Crop photos to squares and compose a 3x3 grid."
    )
    parser.add_argument("images", nargs="+", help="input images, up to 9, in grid order")
    parser.add_argument(
        "-p", "--position", type=float, default=0.5,
        help="0-1, center of the square on the long edge (default: 0.5)",
    )
    parser.add_argument(
        "-s", "--size", type=int, default=800,
        help="output cell size in pixels (default: 800)",
    )
    parser.add_argument(
        "-o", "--output", default="grid.jpg",
        help="output file path (default: grid.jpg)",
    )
    args = parser.parse_args()

    if len(args.images) > 9:
        sys.exit("error: at most 9 images are allowed")
    if not 0 <= args.position <= 1:
        sys.exit("error: position must be between 0 and 1")

    cell = args.size
    canvas = Image.new("RGB", (cell * 3, cell * 3), "white")

    for i, path in enumerate(args.images):
        img = Image.open(path)
        img = ImageOps.exif_transpose(img).convert("RGB")
        square = crop_square(img, args.position)
        square = square.resize((cell, cell), Image.LANCZOS)
        x = (i % 3) * cell
        y = (i // 3) * cell
        canvas.paste(square, (x, y))
        print(f"[{i + 1}/{len(args.images)}] {path}: {img.size[0]}x{img.size[1]} -> cell ({i % 3}, {i // 3})")

    canvas.save(args.output, quality=90)
    print(f"saved: {args.output} ({cell * 3}x{cell * 3})")


if __name__ == "__main__":
    main()
