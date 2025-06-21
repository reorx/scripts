#!/bin/bash

# Set default quality / optimization parameters if not set.
: ${JPEG_QUALITY:=80}
: ${PNGQUANT_SPEED:=3}
: ${GIF_COLORS:=64}
: ${GIF_LOSSY_LEVEL:=40}
: ${GIF_RESIZE_P:=65}

# Function to ensure a required command is installed.
ensure_command_installed() {
    local cmd="$1"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "Error: Required command '$cmd' is not installed. Exiting."
        exit 1
    fi
}

# Function to get file size in KB as an integer (macOS compatible)
get_file_size() {
    local file="$1"
    local size_bytes
    size_bytes=$(stat -f %z "$file")
    echo $(( size_bytes / 1024 ))
}

# Function to compress PNG images with pngquant
compress_png() {
    local file="$1"
    local new_ext=".new.png"
    pngquant --speed "$PNGQUANT_SPEED" --ext "${new_ext}" "$file"
    if [ $? -eq 0 ]; then
        local base_name="${file%.*}"
        local new_image="${base_name}${new_ext}"
        local old_size_kb=$(get_file_size "$file")
        local new_size_kb=$(get_file_size "$new_image")
        mv "$new_image" "$file"
        echo "Replaced '$file' (Old Size: ${old_size_kb} KB) with compressed PNG (New Size: ${new_size_kb} KB)."
    else
        echo "PNG compression failed for '$file'. The original image remains unchanged."
        exit 1
    fi
}

# Function to compress JPEG images with jpegoptim
compress_jpg() {
    local file="$1"
    local old_size_kb=$(get_file_size "$file")
    jpegoptim --max="$JPEG_QUALITY" "$file"
    if [ $? -eq 0 ]; then
        local new_size_kb=$(get_file_size "$file")
        echo "Compressed '$file' (Old Size: ${old_size_kb} KB, New Size: ${new_size_kb} KB) using jpegoptim with quality set to ${JPEG_QUALITY}."
    else
        echo "JPEG compression failed for '$file'. The original image remains unchanged."
        exit 1
    fi
}

# Function to compress GIF images with gifsicle
compress_gif() {
    local file="$1"
    local old_size_kb=$(get_file_size "$file")
    local resize_param="${GIF_RESIZE_P}x${GIF_RESIZE_P}%"
    gifsicle --batch -O3 --colors "$GIF_COLORS" --lossy="$GIF_LOSSY_LEVEL" --resize-geometry "$resize_param" "$file"
    if [ $? -eq 0 ]; then
        local new_size_kb=$(get_file_size "$file")
        echo "Compressed '$file' (Old Size: ${old_size_kb} KB, New Size: ${new_size_kb} KB) using gifsicle with colors=${GIF_COLORS}, lossy=${GIF_LOSSY_LEVEL}, resize=${resize_param}."
    else
        echo "GIF compression failed for '$file'. The original image remains unchanged."
        exit 1
    fi
}

# Check if an image file was specified as an argument.
if [ -z "$1" ]; then
    echo "Usage: $0 <image_file>"
    exit 1
fi

IMAGE_FILE="$1"
extension="${IMAGE_FILE##*.}"
extension_lower=$(echo "$extension" | tr '[:upper:]' '[:lower:]')

case "$extension_lower" in
    png)
        ensure_command_installed pngquant
        compress_png "$IMAGE_FILE"
        ;;
    jpg | jpeg)
        ensure_command_installed jpegoptim
        compress_jpg "$IMAGE_FILE"
        ;;
    gif)
        ensure_command_installed gifsicle
        compress_gif "$IMAGE_FILE"
        ;;
    *)
        echo "Warning: Unsupported file format '$extension'. Only PNG, JPG, JPEG, and GIF are supported."
        exit 1
        ;;
esac
