#!/bin/bash
set -euo pipefail

usage() {
  echo "Usage: $(basename "$0") [--jpeg [QUALITY]] <input.pdf> [output_dir]"
  echo ""
  echo "Split a PDF into one image per page."
  echo ""
  echo "Options:"
  echo "  --jpeg [QUALITY]  Convert to JPEG (default quality: 95)"
  echo ""
  echo "Arguments:"
  echo "  input.pdf         Path to the PDF file"
  echo "  output_dir        Output directory (default: ./images)"
  exit 1
}

JPEG=false
JPEG_QUALITY=95

# Parse options
while [[ $# -gt 0 ]]; do
  case "$1" in
    --jpeg)
      JPEG=true
      shift
      # Check if next arg is a number (quality)
      if [[ $# -gt 0 && "$1" =~ ^[0-9]+$ && "$1" -ge 1 && "$1" -le 100 ]]; then
        JPEG_QUALITY="$1"
        shift
      fi
      ;;
    -h|--help)
      usage
      ;;
    *)
      break
      ;;
  esac
done

if [[ $# -lt 1 ]]; then
  usage
fi

PDF_PATH="$1"
OUTPUT_DIR="${2:-./images}"

if [[ ! -f "$PDF_PATH" ]]; then
  echo "Error: file not found: $PDF_PATH" >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "Rendering PDF pages to PNG..."
/usr/bin/python3 -c "
import Quartz
from Quartz import PDFDocument
from Foundation import NSURL
import os, sys

pdf_path = sys.argv[1]
out_dir = sys.argv[2]

url = NSURL.fileURLWithPath_(pdf_path)
doc = PDFDocument.alloc().initWithURL_(url)
if doc is None:
    print(f'Error: cannot open PDF: {pdf_path}', file=sys.stderr)
    sys.exit(1)

count = doc.pageCount()
print(f'Total pages: {count}')

for i in range(count):
    page = doc.pageAtIndex_(i)
    box = page.boundsForBox_(Quartz.kPDFDisplayBoxMediaBox)
    w, h = box.size.width, box.size.height
    scale = 2.0
    sw, sh = int(w * scale), int(h * scale)

    cs = Quartz.CGColorSpaceCreateDeviceRGB()
    ctx = Quartz.CGBitmapContextCreate(None, sw, sh, 8, sw * 4, cs, Quartz.kCGImageAlphaPremultipliedLast)
    Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
    Quartz.CGContextFillRect(ctx, ((0, 0), (sw, sh)))
    Quartz.CGContextScaleCTM(ctx, scale, scale)

    Quartz.CGContextDrawPDFPage(ctx, page.pageRef())

    image = Quartz.CGBitmapContextCreateImage(ctx)
    out_path = os.path.join(out_dir, f'page-{i+1:02d}.png')
    dest = Quartz.CGImageDestinationCreateWithURL(
        NSURL.fileURLWithPath_(out_path), 'public.png', 1, None)
    Quartz.CGImageDestinationAddImage(dest, image, None)
    Quartz.CGImageDestinationFinalize(dest)
    print(f'  {os.path.basename(out_path)}')

print('PNG rendering done.')
" "$PDF_PATH" "$OUTPUT_DIR"

if $JPEG; then
  echo "Converting to JPEG (quality $JPEG_QUALITY)..."
  for f in "$OUTPUT_DIR"/page-*.png; do
    jpg="${f%.png}.jpg"
    magick "$f" -quality "$JPEG_QUALITY" "$jpg"
    rm "$f"
    echo "  $(basename "$jpg")"
  done
  echo "JPEG conversion done."
fi

echo "Output: $OUTPUT_DIR"
