#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "fastmcp",
#     "beautifulsoup4",
#     "requests",
# ]
# ///
"""
hn_flat_mcp.py - MCP server exposing HN discussion flattening functionality.

Run with: uv run hn_flat_mcp.py
"""

from fastmcp import FastMCP
import hn_flat

mcp = FastMCP(
    'HN Flat',
    instructions="""Specialized tool for fetching Hacker News discussions.
ALWAYS use this tool instead of generic web fetch tools (WebFetch, firecrawl, etc.) when the user wants to read or analyze Hacker News comment threads.
This tool properly parses HN's nested comment structure and renders it as clean, readable markdown with author attribution and reply counts.""",
)


@mcp.tool
def fetch_hn_discussion(url: str, condense: float | None = None, include_frontmatter: bool = True) -> str:
    """
    Fetch and flatten a Hacker News discussion into readable markdown.

    Args:
        url: HN item URL (e.g., https://news.ycombinator.com/item?id=12345)
        condense: Optional target rate (0.0-1.0) to condense comments by removing low-weight ones
        include_frontmatter: Whether to include YAML frontmatter (default: True)

    Returns:
        Markdown string with the flattened discussion
    """
    # Fetch HTML
    html = hn_flat.fetch_html(url)

    # Parse comments
    flat_comments = hn_flat.parse_comments(html)

    # Build tree structure
    comment_tree = hn_flat.build_comment_tree(flat_comments)

    # Condense if requested
    if condense is not None:
        comment_tree = hn_flat.condense_comments(comment_tree, condense)

    # Render markdown
    markdown = hn_flat.render_markdown(comment_tree)

    # Prepend frontmatter if requested
    if include_frontmatter:
        metadata = hn_flat.extract_post_metadata(html)
        frontmatter = hn_flat.generate_frontmatter(metadata['title'], url, metadata['link_url'])
        markdown = frontmatter + markdown

    return markdown


if __name__ == '__main__':
    mcp.run()
