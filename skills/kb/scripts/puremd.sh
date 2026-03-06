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

# Remove https:// prefix
url_without_protocol="${url#https://}"

# Build pure.md URL
puremd_url="https://pure.md/${url_without_protocol}"

# Extract filename from last segment of URL
filename="$(basename "$url_without_protocol").md"

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
echo "Downloading from: $puremd_url"
echo "Saving to: $output"

curl -sL ${PUREMD_API_TOKEN:+-H "x-puremd-api-token: ${PUREMD_API_TOKEN}"} "$puremd_url" -o "$output"

if [ $? -eq 0 ]; then
    echo "Successfully saved to $output"
else
    echo "Error downloading content"
    exit 1
fi