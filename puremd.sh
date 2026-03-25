#!/bin/bash

# Check if URL argument is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <url> [output_path]"
    echo "  output_path: file path or directory (trailing / creates dir if needed)"
    echo "Example: $0 https://reactrouter.com/start/framework/route-module"
    echo "         $0 https://reactrouter.com/start/framework/route-module docs/"
    exit 1
fi

# Get the URL from first argument
url="$1"

# Check if URL is already a .md or .txt file
if [[ "$url" == *.md ]] || [[ "$url" == *.txt ]]; then
    download_url="$url"
    filename="$(basename "$url")"
else
    # Remove https:// prefix
    url_without_protocol="${url#https://}"
    # Build pure.md URL
    download_url="https://pure.md/${url_without_protocol}"
    filename="$(basename "$url_without_protocol").md"
fi

# Determine output path
if [ -n "$2" ]; then
    if [[ "$2" == */ ]] || [ -d "$2" ]; then
        mkdir -p "$2"
        output="$2/$filename"
    else
        output="$2"
    fi
else
    output="$filename"
fi

# Download content using curl
echo "Downloading from: $download_url"
echo "Saving to: $output"

curl -sL ${PUREMD_API_TOKEN:+-H "x-puremd-api-token: ${PUREMD_API_TOKEN}"} "$download_url" -o "$output"

if [ $? -eq 0 ]; then
    filesize=$(stat -f '%z' "$output")
    if [ "$filesize" -ge 1048576 ]; then
        human_size="$(awk "BEGIN {printf \"%.1fM\", $filesize/1048576}")"
    elif [ "$filesize" -ge 1024 ]; then
        human_size="$(awk "BEGIN {printf \"%.1fK\", $filesize/1024}")"
    else
        human_size="${filesize}B"
    fi
    echo "Successfully saved to $output ($human_size)"
    if [ -n "$PREVIEW" ]; then
        echo "--- Preview ---"
        head -n 20 "$output"
    fi
else
    echo "Error downloading content"
    exit 1
fi