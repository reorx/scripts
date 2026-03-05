#!/bin/bash

# Search documents in kb/docs/ using ripgrep
# Usage: search-docs.sh [-c context_lines] [-i] [-l] <pattern> [directory]

context_lines=2
rg_flags=()

while getopts "c:il" opt; do
    case $opt in
        c) context_lines="$OPTARG" ;;
        i) rg_flags+=("-i") ;;
        l) rg_flags+=("-l") ;;
        *) echo "Usage: $0 [-c context_lines] [-i] [-l] <pattern> [directory]"; exit 1 ;;
    esac
done
shift $((OPTIND - 1))

if [ $# -eq 0 ]; then
    echo "Usage: $0 [-c context_lines] [-i] [-l] <pattern> [directory]"
    echo ""
    echo "Search markdown documents in kb/docs/ (or specified directory)."
    echo ""
    echo "Options:"
    echo "  -c N    Context lines around matches (default: 2)"
    echo "  -i      Case-insensitive search"
    echo "  -l      List matching filenames only"
    echo ""
    echo "Examples:"
    echo "  $0 'react hooks'"
    echo "  $0 -i -c 5 'authentication' kb/docs/auth/"
    exit 1
fi

pattern="$1"
search_dir="${2:-kb/docs}"

if [ ! -d "$search_dir" ]; then
    echo "Error: Directory '$search_dir' does not exist."
    echo "Hint: Download some documents first with: bash scripts/puremd.sh -o kb/docs <url>"
    exit 1
fi

rg --heading --line-number -C "$context_lines" \
    --type md \
    "${rg_flags[@]}" \
    "$pattern" "$search_dir"

exit_code=$?
if [ $exit_code -eq 1 ]; then
    echo "No matches found for '$pattern' in $search_dir"
fi
exit $exit_code
