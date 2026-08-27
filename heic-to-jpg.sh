#!/bin/bash
# heic-to-jpg.sh — Convert HEIC images to JPEG with a sane size, using macOS built-in sips.
#
# The output image keeps the aspect ratio. The script downscales the long edge
# to MAX_DIM pixels if the source is larger; it never upscales.
#
# Usage: heic-to-jpg.sh [-q quality] [-m max_dim] [-o output_dir] <file.heic> [more.heic ...]

set -euo pipefail

# Defaults, can also be set via environment variables.
: "${JPEG_QUALITY:=82}"
: "${MAX_DIM:=1600}"
OUTPUT_DIR=""

usage() {
    echo "Usage: $(basename "$0") [-q quality] [-m max_dim] [-o output_dir] <file.heic> [more.heic ...]" >&2
    echo "  -q <1-100>   JPEG quality (default $JPEG_QUALITY)" >&2
    echo "  -m <pixels>  Max long-edge size, downscale only (default $MAX_DIM, 0 = keep original size)" >&2
    echo "  -o <dir>     Output directory (default: same directory as the source file)" >&2
    exit 1
}

while getopts ":q:m:o:h" opt; do
    case "$opt" in
        q) JPEG_QUALITY="$OPTARG" ;;
        m) MAX_DIM="$OPTARG" ;;
        o) OUTPUT_DIR="$OPTARG" ;;
        h | *) usage ;;
    esac
done
shift $((OPTIND - 1))

[ $# -ge 1 ] || usage

get_file_size_kb() {
    echo $(( $(stat -f %z "$1") / 1024 ))
}

# Get the long edge of an image in pixels.
get_long_edge() {
    sips -g pixelWidth -g pixelHeight "$1" | awk '/pixel/ {print $2}' | sort -n | tail -1
}

convert_one() {
    local src="$1"

    if [ ! -f "$src" ]; then
        echo "Error: file not found: $src" >&2
        return 1
    fi

    local filename base_name out_dir dst
    filename=$(basename -- "$src")
    base_name="${filename%.*}"
    out_dir="${OUTPUT_DIR:-$(dirname -- "$src")}"
    mkdir -p "$out_dir"
    dst="$out_dir/$base_name.jpg"

    if [ -e "$dst" ]; then
        echo "Error: output already exists, skip: $dst" >&2
        return 1
    fi

    # Only downscale when the source long edge is larger than MAX_DIM.
    local long_edge resample_args=()
    long_edge=$(get_long_edge "$src")
    if [ "$MAX_DIM" -gt 0 ] && [ "$long_edge" -gt "$MAX_DIM" ]; then
        resample_args=(--resampleHeightWidthMax "$MAX_DIM")
    fi

    # ${arr[@]+...} keeps bash 3.2 happy with an empty array under `set -u`.
    sips -s format jpeg -s formatOptions "$JPEG_QUALITY" \
        ${resample_args[@]+"${resample_args[@]}"} "$src" --out "$dst" >/dev/null

    echo "$src (${long_edge}px, $(get_file_size_kb "$src")KB) -> $dst ($(get_long_edge "$dst")px, $(get_file_size_kb "$dst")KB)"
}

failed=0
for f in "$@"; do
    convert_one "$f" || failed=1
done
exit "$failed"
