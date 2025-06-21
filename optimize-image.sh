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

# Function to output size comparison after compression.
echo_size_comparison() {
    local file="$1"
    local old_size="$2"
    local new_size
    new_size=$(get_file_size "$file")
    echo "'$file' compressed   (size ${old_size}KB -> ${new_size}KB)"
}

# Function to create a backup of the file.
# The backup is only made if BACKUP_DIR environment variable is set.
# If BACKUP_DIR is not provided, the function returns immediately (no-op).
# Backup file will have name format: basename.YYYY-MM-DD-HH-MM.ext
backup_file() {
    local file="$1"
    if [ -z "$BACKUP_DIR" ]; then
        return
    fi
    mkdir -p "$BACKUP_DIR"
    local filename
    filename=$(basename -- "$file")
    local base_name="${filename%.*}"
    local ext="${filename##*.}"
    local timestamp
    timestamp=$(date +"%Y-%m-%d-%H-%M")
    local new_name="${base_name}.${timestamp}.${ext}"
    cp "$file" "$BACKUP_DIR/$new_name"
}

# Function to compress PNG images with pngquant
compress_png() {
    local file="$1"
    backup_file "$file"
    local new_ext=".new.png"
    local old_size_kb
    old_size_kb=$(get_file_size "$file")
    pngquant --speed "$PNGQUANT_SPEED" --ext "${new_ext}" "$file"
    if [ $? -eq 0 ]; then
        local base_name="${file%.*}"
        local new_image="${base_name}${new_ext}"
        mv "$new_image" "$file"
        echo_size_comparison "$file" "$old_size_kb"
    else
        echo "PNG compression failed for '$file'. The original image remains unchanged."
        exit 1
    fi
}

# Function to compress JPEG images with jpegoptim
compress_jpg() {
    local file="$1"
    backup_file "$file"
    local old_size_kb
    old_size_kb=$(get_file_size "$file")
    jpegoptim --max="$JPEG_QUALITY" "$file"
    if [ $? -eq 0 ]; then
        echo_size_comparison "$file" "$old_size_kb"
    else
        echo "JPEG compression failed for '$file'. The original image remains unchanged."
        exit 1
    fi
}

# Function to compress GIF images with gifsicle
compress_gif() {
    local file="$1"
    backup_file "$file"
    local old_size_kb
    old_size_kb=$(get_file_size "$file")
    local resize_param="${GIF_RESIZE_P}x${GIF_RESIZE_P}%"
    gifsicle --batch -O3 --colors "$GIF_COLORS" --lossy="$GIF_LOSSY_LEVEL" --resize-geometry "$resize_param" "$file"
    if [ $? -eq 0 ]; then
        echo_size_comparison "$file" "$old_size_kb"
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
