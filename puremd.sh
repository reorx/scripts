#!/bin/bash

# Check if URL argument is provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 <url>"
    echo "Example: $0 https://reactrouter.com/start/framework/route-module"
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

# Download content using curl
echo "Downloading from: $puremd_url"
echo "Saving to: $filename"

curl -sL "$puremd_url" -o "$filename"

if [ $? -eq 0 ]; then
    echo "Successfully saved to $filename"
else
    echo "Error downloading content"
    exit 1
fi