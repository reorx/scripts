#!/bin/bash

# Download a web page as markdown via pure.md service
# Usage: puremd.sh [-o output_dir] <url>

# Parse options
output_dir="."
while getopts "o:" opt; do
    case $opt in
        o) output_dir="$OPTARG" ;;
        *) echo "Usage: $0 [-o output_dir] <url>"; exit 1 ;;
    esac
done
shift $((OPTIND - 1))

# Check if URL argument is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 [-o output_dir] <url>"
    echo "Example: $0 -o kb/docs https://reactrouter.com/start/framework/route-module"
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

# Ensure output directory exists
mkdir -p "$output_dir"
output_path="${output_dir}/${filename}"

# Download content using curl
echo "Downloading from: $puremd_url"
echo "Saving to: $output_path"

curl -sL ${PUREMD_API_TOKEN:+-H "x-puremd-api-token: ${PUREMD_API_TOKEN}"} "$puremd_url" -o "$output_path"

if [ $? -eq 0 ]; then
    echo "Successfully saved to $output_path"
else
    echo "Error downloading content"
    exit 1
fi
