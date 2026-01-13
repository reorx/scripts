#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "beautifulsoup4",
#     "requests",
# ]
# ///
"""
hn-flat.py - Fetch and flatten Hacker News discussions into readable markdown.

Usage:
    uv run hn-flat.py <url> [options]

Examples:
    # Basic usage - saves to hn.<id>.md in current directory
    uv run hn-flat.py "https://news.ycombinator.com/item?id=12345"

    # Print to stdout
    uv run hn-flat.py "https://news.ycombinator.com/item?id=12345" --stdout

    # Save to specific file or directory
    uv run hn-flat.py "https://news.ycombinator.com/item?id=12345" -o discussion.md
    uv run hn-flat.py "https://news.ycombinator.com/item?id=12345" --out-dir ./hn-posts

    # Use cache to avoid repeated fetching
    uv run hn-flat.py "https://news.ycombinator.com/item?id=12345" --cache-dir ~/.cache/hn

    # Condense long discussions to 50% of original size
    uv run hn-flat.py "https://news.ycombinator.com/item?id=12345" --condense 0.5

    # Skip frontmatter for plain markdown
    uv run hn-flat.py "https://news.ycombinator.com/item?id=12345" --no-frontmatter --stdout
"""

import argparse
import hashlib
import os
import re
import sys
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString


@dataclass
class Comment:
    id: str
    author: str
    text: str
    indent: int
    children: list["Comment"] = field(default_factory=list)

    def descendant_count(self) -> int:
        """Count all descendants recursively."""
        count = len(self.children)
        for child in self.children:
            count += child.descendant_count()
        return count

    def weight(self) -> float:
        """Calculate weight for condensing: (children_count + 1) * comment_length / 10"""
        return (self.descendant_count() + 1) * len(self.text) / 10

    def depth(self) -> int:
        """Calculate the depth of this comment (0 for root-level comments)."""
        return self.indent // 40  # HN uses 40px per indent level

    def is_leaf(self) -> bool:
        """Check if this comment has no children."""
        return len(self.children) == 0


def get_cache_path(url: str, cache_dir: str) -> Path:
    """Generate cache file path for a URL."""
    # Use URL hash for filename to handle special characters
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    # Extract item ID for readability
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    item_id = params.get("id", ["unknown"])[0]
    filename = f"hn_{item_id}_{url_hash}.html"
    return Path(cache_dir) / filename


def fetch_html(url: str, verbose: bool = False, cache_dir: str | None = None) -> str:
    """Fetch HTML content from URL, with optional caching."""
    # Check cache first
    if cache_dir:
        cache_path = get_cache_path(url, cache_dir)
        if cache_path.exists():
            if verbose:
                print(f"Loading from cache: {cache_path}", file=sys.stderr)
            html = cache_path.read_text(encoding="utf-8")
            if verbose:
                print(f"Loaded {len(html)} bytes from cache", file=sys.stderr)
            return html

    if verbose:
        print(f"Fetching {url}...", file=sys.stderr)

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    if verbose:
        print(f"Fetched {len(response.text)} bytes", file=sys.stderr)

    # Save to cache
    if cache_dir:
        cache_path = get_cache_path(url, cache_dir)
        os.makedirs(cache_dir, exist_ok=True)
        cache_path.write_text(response.text, encoding="utf-8")
        if verbose:
            print(f"Saved to cache: {cache_path}", file=sys.stderr)

    return response.text


def extract_text_from_element(element) -> str:
    """Extract plain text from HTML element, stripping all formatting."""
    if element is None:
        return ""

    texts = []
    for child in element.children:
        if isinstance(child, NavigableString):
            texts.append(str(child))
        elif child.name == "p":
            # Paragraph break
            if texts and texts[-1] != "\n\n":
                texts.append("\n\n")
            texts.append(extract_text_from_element(child))
            texts.append("\n\n")
        elif child.name == "br":
            texts.append("\n")
        elif child.name in ("a", "i", "b", "code", "pre", "span", "font"):
            # Strip formatting, keep text
            texts.append(extract_text_from_element(child))
        else:
            texts.append(extract_text_from_element(child))

    result = "".join(texts)
    # Clean up multiple newlines
    result = re.sub(r"\n{3,}", "\n\n", result)
    return unescape(result.strip())


def is_flagged_comment(comment_div) -> bool:
    """Check if comment is flagged as inappropriate (has c73 class)."""
    commtext = comment_div.select_one("div.commtext")
    if commtext and "c73" in commtext.get("class", []):
        return True
    return False


def is_deleted_comment(comment_div) -> bool:
    """Check if comment is deleted or dead."""
    commtext = comment_div.select_one("div.commtext")
    if commtext:
        text = commtext.get_text(strip=True)
        if text in ("[deleted]", "[dead]", "[flagged]"):
            return True
    # Also check if there's no commtext at all but has a comhead
    comhead = comment_div.select_one("span.comhead")
    if comhead and not commtext:
        return True
    return False


def parse_comments(html: str, verbose: bool = False) -> list[Comment]:
    """Parse HTML and extract comments into a flat list with indent levels."""
    if verbose:
        print("Parsing HTML...", file=sys.stderr)

    soup = BeautifulSoup(html, "html.parser")
    comments = []

    # Find all comment table rows
    comment_rows = soup.select("tr.athing.comtr")

    if verbose:
        print(f"Found {len(comment_rows)} comment rows", file=sys.stderr)

    for row in comment_rows:
        # Get indent level from the indent image width
        indent_td = row.select_one("td.ind img")
        indent = int(indent_td.get("width", 0)) if indent_td else 0

        # Get comment div
        comment_div = row.select_one("td.default div.comment")
        if not comment_div:
            continue

        # Skip flagged comments
        if is_flagged_comment(comment_div):
            if verbose:
                print(f"Skipping flagged comment", file=sys.stderr)
            continue

        # Skip deleted/dead comments
        if is_deleted_comment(comment_div):
            if verbose:
                print(f"Skipping deleted/dead comment", file=sys.stderr)
            continue

        # Get author
        author_elem = row.select_one("a.hnuser")
        author = author_elem.get_text() if author_elem else "unknown"

        # Get comment text
        commtext = comment_div.select_one("div.commtext")
        text = extract_text_from_element(commtext) if commtext else ""

        # Skip empty comments
        if not text:
            continue

        # Get comment ID
        comment_id = row.get("id", "")

        comments.append(Comment(
            id=comment_id,
            author=author,
            text=text,
            indent=indent,
        ))

    if verbose:
        print(f"Parsed {len(comments)} valid comments", file=sys.stderr)

    return comments


def extract_post_metadata(html: str) -> dict:
    """Extract post title and link URL from HN page."""
    soup = BeautifulSoup(html, "html.parser")
    title_elem = soup.select_one('tr.athing.submission span.titleline a')
    title = title_elem.get_text() if title_elem else "Unknown"
    link_url = title_elem.get('href') if title_elem else ""
    return {"title": title, "link_url": link_url}


def generate_frontmatter(title: str, url: str, link_url: str) -> str:
    """Generate YAML frontmatter for output."""
    return f"""---
type: Hacker News Discussions
title: {title}
url: {url}
link_url: {link_url}
description: discussions are represented in markdown lists, nested replies are kept as-is. `[+N]` shows total descendant count.
---
"""


def build_comment_tree(flat_comments: list[Comment]) -> list[Comment]:
    """Build a tree structure from flat comments based on indent levels."""
    if not flat_comments:
        return []

    root_comments = []
    stack: list[Comment] = []  # Stack of (comment, indent_level)

    for comment in flat_comments:
        # Pop from stack until we find parent
        while stack and stack[-1].indent >= comment.indent:
            stack.pop()

        if stack:
            # This is a child of the last comment in stack
            stack[-1].children.append(comment)
        else:
            # This is a root-level comment
            root_comments.append(comment)

        stack.append(comment)

    return root_comments


def format_comment_text(text: str, indent_str: str) -> str:
    """Format multi-line comment text with proper indentation."""
    lines = text.split("\n")
    result_lines = []

    for i, line in enumerate(lines):
        if i == 0:
            result_lines.append(line)
        else:
            # Indent continuation lines to align with content after "- @user: "
            if line.strip():
                result_lines.append(indent_str + "  " + line)
            else:
                result_lines.append("")

    return "\n".join(result_lines)


def render_markdown(comments: list[Comment], depth: int = 0) -> str:
    """Render comment tree as markdown list."""
    lines = []
    indent_str = "  " * depth

    for comment in comments:
        desc_count = comment.descendant_count()
        count_str = f" [+{desc_count}]" if desc_count > 0 else ""

        # Format the first line
        formatted_text = format_comment_text(comment.text, indent_str)
        line = f"{indent_str}- @{comment.author}{count_str}: {formatted_text}"
        lines.append(line)

        # Render children
        if comment.children:
            child_md = render_markdown(comment.children, depth + 1)
            lines.append(child_md)

    return "\n".join(lines)


def get_all_leaves(comments: list[Comment], parent: Comment | None = None) -> list[tuple[Comment, Comment | None, list[Comment]]]:
    """Get all leaf comments with their parent and parent's children list."""
    leaves = []

    for comment in comments:
        if comment.is_leaf():
            leaves.append((comment, parent, comments))
        else:
            leaves.extend(get_all_leaves(comment.children, comment))

    return leaves


def calculate_depth(comment: Comment, comments: list[Comment], depth: int = 0) -> int:
    """Calculate the depth of a comment in the tree."""
    for c in comments:
        if c is comment:
            return depth
        if c.children:
            found = calculate_depth(comment, c.children, depth + 1)
            if found >= 0:
                return found
    return -1


def condense_comments(root_comments: list[Comment], target_rate: float, verbose: bool = False, step_size: int = 4) -> list[Comment]:
    """Condense comments by removing low-weight leaves until target rate is reached."""
    import copy

    # Deep copy to avoid modifying original
    comments = copy.deepcopy(root_comments)
    original_md = render_markdown(comments)
    original_length = len(original_md)

    if verbose:
        print(f"Original length: {original_length} chars", file=sys.stderr)
        print(f"Target rate: {target_rate}", file=sys.stderr)
        print(f"Step size: {step_size}", file=sys.stderr)

    iteration = 0
    while True:
        current_md = render_markdown(comments)
        current_length = len(current_md)
        current_rate = current_length / original_length if original_length > 0 else 1.0

        if verbose:
            print(f"Current rate: {current_rate:.3f} ({current_length}/{original_length})", file=sys.stderr)

        if current_rate <= target_rate:
            break

        # Get all leaf comments
        leaves = get_all_leaves(comments)

        if not leaves:
            if verbose:
                print("No more leaves to remove", file=sys.stderr)
            break

        # Find leaf with minimum weight, using depth as tiebreaker (deeper first)
        def leaf_sort_key(leaf_info):
            leaf, parent, siblings = leaf_info
            weight = leaf.weight()
            # Calculate depth: negative because we want deeper comments first when weights are equal
            depth = 0
            if parent:
                # Approximate depth from the tree structure
                def find_depth(comments, target, d=0):
                    for c in comments:
                        if c is target:
                            return d
                        if c.children:
                            result = find_depth(c.children, target, d + 1)
                            if result >= 0:
                                return result
                    return -1
                depth = find_depth(root_comments, leaf)
            return (weight, -depth)  # Lower weight first, then deeper first

        leaves.sort(key=leaf_sort_key)

        # Remove up to step_size leaves at once
        removed_count = 0
        for i in range(min(step_size, len(leaves))):
            leaf_to_remove, parent, siblings = leaves[i]
            # Check if the leaf is still in siblings (may have been removed if parent was removed)
            if leaf_to_remove in siblings:
                siblings.remove(leaf_to_remove)
                removed_count += 1

        iteration += 1
        if verbose:
            print(f"Iteration {iteration}: removed {removed_count} leaves", file=sys.stderr)

    return comments


def extract_id_from_url(url: str) -> str:
    """Extract the item ID from a HN URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    if "id" in params:
        return params["id"][0]
    return "unknown"


def main():
    epilog = """
Examples:
  %(prog)s "https://news.ycombinator.com/item?id=12345"
      Fetch and save to hn.12345.md

  %(prog)s "https://news.ycombinator.com/item?id=12345" --stdout
      Print to stdout instead of file

  %(prog)s "https://news.ycombinator.com/item?id=12345" --cache-dir ~/.cache/hn
      Cache HTML to avoid repeated fetching

  %(prog)s "https://news.ycombinator.com/item?id=12345" --condense 0.5
      Condense to 50%% of original size by removing low-weight comments

  %(prog)s "https://news.ycombinator.com/item?id=12345" --no-frontmatter -o out.md
      Save without YAML frontmatter
"""
    parser = argparse.ArgumentParser(
        description="Fetch and flatten Hacker News discussions into readable markdown.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url", help="Hacker News item URL")

    # Mutually exclusive output options
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("-o", "--output", metavar="FILE", help="Output file path")
    output_group.add_argument("--out-dir", metavar="DIR", help="Output directory (filename auto-generated)")

    parser.add_argument("--stdout", action="store_true", help="Print to stdout instead of file")
    parser.add_argument("--condense", type=float, metavar="RATE",
                        help="Condense comments to target rate (0.0-1.0)")
    parser.add_argument("--condense-step-size", type=int, default=4, metavar="N",
                        help="Number of comments to remove per condense iteration (default: 4)")
    parser.add_argument("--cache-dir", metavar="DIR",
                        help="Directory to cache/load HTML files")
    parser.add_argument("--no-frontmatter", action="store_true",
                        help="Omit YAML frontmatter from output")
    parser.add_argument("--verbose", action="store_true", help="Show progress to stderr")

    args = parser.parse_args()

    # Fetch and parse
    html = fetch_html(args.url, args.verbose, args.cache_dir)
    flat_comments = parse_comments(html, args.verbose)
    comment_tree = build_comment_tree(flat_comments)

    # Extract metadata for frontmatter
    metadata = extract_post_metadata(html)

    # Condense if requested
    if args.condense is not None:
        comment_tree = condense_comments(comment_tree, args.condense, args.verbose, args.condense_step_size)

    # Render markdown
    markdown = render_markdown(comment_tree)

    # Prepend frontmatter unless disabled
    if not args.no_frontmatter:
        frontmatter = generate_frontmatter(metadata["title"], args.url, metadata["link_url"])
        markdown = frontmatter + markdown

    # Output
    if args.stdout:
        print(markdown)
    else:
        item_id = extract_id_from_url(args.url)
        filename = f"hn.{item_id}.md"
        if args.output:
            output_path = args.output
        elif args.out_dir:
            os.makedirs(args.out_dir, exist_ok=True)
            output_path = os.path.join(args.out_dir, filename)
        else:
            output_path = filename
        with open(output_path, "w") as f:
            f.write(markdown)
        if args.verbose:
            print(f"Written to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
