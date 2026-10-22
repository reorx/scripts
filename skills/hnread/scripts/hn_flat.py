#!/usr/bin/env -S uv run --script
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

    # Use one fetcher only; the default "auto" tries curl, then requests, then the Algolia API
    uv run hn-flat.py "https://news.ycombinator.com/item?id=12345" --fetcher algolia

    # Condense long discussions to 50% of original size
    uv run hn-flat.py "https://news.ycombinator.com/item?id=12345" --condense 0.5

    # Skip frontmatter for plain markdown
    uv run hn-flat.py "https://news.ycombinator.com/item?id=12345" --no-frontmatter --stdout
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString

# Overridable so tests can stand in a local server
ALGOLIA_ITEM_URL = os.environ.get('HNREAD_ALGOLIA_ITEM_URL', 'https://hn.algolia.com/api/v1/items/{id}')
FIREBASE_ITEM_URL = os.environ.get('HNREAD_FIREBASE_ITEM_URL', 'https://hacker-news.firebaseio.com/v0/item/{id}.json')

# (connect, read) seconds; a short connect timeout moves on quickly when a host is unreachable
TIMEOUT = (10, 30)

REMOVED_TEXTS = ('[deleted]', '[dead]', '[flagged]')


class FetchError(Exception):
    """A fetcher could not get the thread."""


class FetchFailed(Exception):
    """Every fetcher tried for a thread failed."""


@dataclass
class Comment:
    id: str
    author: str
    text: str
    indent: int
    children: list['Comment'] = field(default_factory=list)
    # Deleted, dead or low-score comment kept only so that its replies land in its place
    removed: bool = False

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


@dataclass
class Thread:
    title: str
    link_url: str
    comments: list[Comment]


def get_cache_path(url: str, cache_dir: str, fmt: str = 'html') -> Path:
    """Generate cache file path for a URL; fmt is the extension of what was fetched (html or json)."""
    # Use URL hash for filename to handle special characters
    url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
    # Extract item ID for readability
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    item_id = params.get('id', ['unknown'])[0]
    filename = f'hn_{item_id}_{url_hash}.{fmt}'
    return Path(cache_dir) / filename


def fetch_with_curl(url: str) -> str:
    """Fetch URL with the curl binary."""
    result = subprocess.run(
        [
            'curl',
            '--silent',
            '--show-error',
            '--fail',
            '--location',
            '--connect-timeout',
            str(TIMEOUT[0]),
            '--max-time',
            str(sum(TIMEOUT)),
            url,
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        raise FetchError(result.stderr.decode('utf-8', 'replace').strip().removeprefix('curl: '))
    return result.stdout.decode('utf-8')


def fetch_with_requests(url: str) -> str:
    """Fetch URL with python-requests."""
    # Keep the library's own User-Agent: HN answers 419 when python-requests poses as a browser
    response = requests.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def fetch_ranked_kids(item_id: str) -> list[int]:
    """Fetch the ids of an item's direct replies, in HN's ranking, from the official API."""
    response = requests.get(FIREBASE_ITEM_URL.format(id=item_id), timeout=TIMEOUT)
    response.raise_for_status()
    return (response.json() or {}).get('kids', [])


def order_by_rank(nodes: list[dict], ranked_ids: list[int]) -> list[dict]:
    """Sort Algolia nodes by ranked_ids; nodes missing from it keep their order at the end."""
    rank = {node_id: i for i, node_id in enumerate(ranked_ids)}
    return sorted(nodes, key=lambda node: rank.get(node['id'], len(rank)))


def fetch_from_algolia(url: str) -> str:
    """Fetch the whole thread as JSON from the Algolia HN API, top-level comments ranked as on HN."""
    item_id = extract_id_from_url(url)
    response = requests.get(ALGOLIA_ITEM_URL.format(id=item_id), timeout=TIMEOUT)
    response.raise_for_status()
    item = response.json()
    # Algolia lists replies by id. One request to HN's official API restores the ranking of top-level
    # comments; deeper levels would need a request per comment, so they stay chronological.
    try:
        ranked_ids = fetch_ranked_kids(item_id)
    except requests.RequestException as e:
        print(f'Could not fetch the HN ranking ({e}); top-level comments stay chronological', file=sys.stderr)
    else:
        item['children'] = order_by_rank(item['children'], ranked_ids)
    return json.dumps(item, ensure_ascii=False)


# name -> (fetch function, format of what it returns); auto mode tries them in this order
FETCHERS = {
    'curl': (fetch_with_curl, 'html'),
    'requests': (fetch_with_requests, 'html'),
    'algolia': (fetch_from_algolia, 'json'),
}
FETCH_ERRORS = (FetchError, FileNotFoundError, requests.RequestException)


def extract_text_from_element(element) -> str:
    """Extract plain text from HTML element, stripping all formatting."""
    if element is None:
        return ''

    texts = []
    for child in element.children:
        if isinstance(child, NavigableString):
            texts.append(str(child))
        elif child.name == 'p':
            # Paragraph break
            if texts and texts[-1] != '\n\n':
                texts.append('\n\n')
            texts.append(extract_text_from_element(child))
            texts.append('\n\n')
        elif child.name == 'br':
            texts.append('\n')
        elif child.name in ('a', 'i', 'b', 'code', 'pre', 'span', 'font'):
            # Strip formatting, keep text
            texts.append(extract_text_from_element(child))
        else:
            texts.append(extract_text_from_element(child))

    result = ''.join(texts)
    # Clean up multiple newlines
    result = re.sub(r'\n{3,}', '\n\n', result)
    return unescape(result.strip())


def is_low_score_comment(comment_div) -> bool:
    """Check if HN grays the comment out for a low score (any color class on commtext but c00)."""
    commtext = comment_div.select_one('div.commtext')
    classes = commtext.get('class', []) if commtext else []
    return any(re.fullmatch(r'c[0-9a-f]{2}', cls) and cls != 'c00' for cls in classes)


def is_deleted_comment(comment_div) -> bool:
    """Check if comment is deleted or dead."""
    commtext = comment_div.select_one('div.commtext')
    if commtext:
        text = commtext.get_text(strip=True)
        if text in REMOVED_TEXTS:
            return True
    # Also check if there's no commtext at all but has a comhead
    comhead = comment_div.select_one('span.comhead')
    if comhead and not commtext:
        return True
    return False


def parse_comments(soup: BeautifulSoup, verbose: bool = False) -> list[Comment]:
    """Extract comments from a parsed HN page into a flat list with indent levels.

    Deleted, dead and low-score comments stay in the list marked as removed, so that
    build_comment_tree can put their replies in their place.
    """
    comments = []

    # Find all comment table rows
    comment_rows = soup.select('tr.athing.comtr')

    if verbose:
        print(f'Found {len(comment_rows)} comment rows', file=sys.stderr)

    for row in comment_rows:
        # Replies inside a collapsed flagged or dead comment, which HN hides by default
        if 'noshow' in row.get('class', []):
            continue

        # Get indent level from the indent image width
        indent_td = row.select_one('td.ind img')
        indent = int(indent_td.get('width', 0)) if indent_td else 0

        comment_id = row.get('id', '')
        author_elem = row.select_one('a.hnuser')
        author = author_elem.get_text() if author_elem else 'unknown'

        comment_div = row.select_one('td.default div.comment')
        commtext = comment_div.select_one('div.commtext') if comment_div else None
        text = extract_text_from_element(commtext) if commtext else ''

        removed = not text or is_deleted_comment(comment_div) or is_low_score_comment(comment_div)
        if removed and verbose:
            print(f'Skipping deleted, dead or low-score comment {comment_id}', file=sys.stderr)

        comments.append(Comment(id=comment_id, author=author, text=text, indent=indent, removed=removed))

    if verbose:
        print(f'Parsed {sum(not c.removed for c in comments)} valid comments', file=sys.stderr)

    return comments


def extract_post_metadata(soup: BeautifulSoup) -> dict:
    """Extract post title and link URL from a parsed HN page."""
    title_elem = soup.select_one('tr.athing.submission span.titleline a')
    title = title_elem.get_text() if title_elem else 'Unknown'
    link_url = title_elem.get('href') if title_elem else ''
    return {'title': title, 'link_url': link_url}


def parse_html_thread(html: str, verbose: bool = False) -> Thread:
    """Parse an HN item page into a Thread."""
    if verbose:
        print('Parsing HTML...', file=sys.stderr)
    soup = BeautifulSoup(html, 'html.parser')
    # Error and rate-limit pages can come back with status 200
    if not soup.select_one('table.fatitem'):
        raise FetchError('the page has no HN item in it')
    metadata = extract_post_metadata(soup)
    comments = build_comment_tree(parse_comments(soup, verbose))
    return Thread(title=metadata['title'], link_url=metadata['link_url'], comments=comments)


def convert_algolia_children(nodes: list[dict], depth: int = 0) -> list[Comment]:
    """Convert Algolia comment nodes to Comments; replies to a removed comment take its place."""
    comments = []
    for node in nodes:
        text = extract_text_from_element(BeautifulSoup(node['text'], 'html.parser')) if node.get('text') else ''
        if not node.get('author') or not text or text in REMOVED_TEXTS:
            comments.extend(convert_algolia_children(node['children'], depth))
            continue
        replies = convert_algolia_children(node['children'], depth + 1)
        comments.append(
            Comment(id=str(node['id']), author=node['author'], text=text, indent=depth * 40, children=replies)
        )
    return comments


def parse_algolia_thread(raw: str, verbose: bool = False) -> Thread:
    """Parse an Algolia HN API item into a Thread."""
    item = json.loads(raw)
    comments = convert_algolia_children(item['children'])
    if verbose:
        print(f'Parsed {sum(c.descendant_count() + 1 for c in comments)} valid comments', file=sys.stderr)
    print(
        'Note: thread from the Algolia API. Replies under each top-level comment are chronological, not ranked. '
        'Algolia has no scores or flags, so low-score comments and some replies HN hides under flagged '
        'comments are included.',
        file=sys.stderr,
    )
    return Thread(title=item.get('title') or 'Unknown', link_url=item.get('url') or '', comments=comments)


PARSERS = {
    'html': parse_html_thread,
    'json': parse_algolia_thread,
}


def load_cached_thread(url: str, cache_dir: str, verbose: bool = False) -> Thread | None:
    """Load a thread from a cached HN page or Algolia item, if either exists."""
    for fmt, parse in PARSERS.items():
        cache_path = get_cache_path(url, cache_dir, fmt)
        if cache_path.exists():
            print(f'Loading from cache: {cache_path}', file=sys.stderr)
            return parse(cache_path.read_text(encoding='utf-8'), verbose)
    return None


def save_cached_thread(url: str, cache_dir: str, fmt: str, raw: str, verbose: bool = False) -> None:
    """Save what a fetcher returned so the next run can skip the network."""
    cache_path = get_cache_path(url, cache_dir, fmt)
    os.makedirs(cache_dir, exist_ok=True)
    cache_path.write_text(raw, encoding='utf-8')
    if verbose:
        print(f'Saved to cache: {cache_path}', file=sys.stderr)


def load_thread(url: str, fetcher: str = 'auto', cache_dir: str | None = None, verbose: bool = False) -> Thread:
    """Load a thread from the cache, else fetch it; 'auto' tries each fetcher until one returns a thread."""
    if cache_dir:
        thread = load_cached_thread(url, cache_dir, verbose)
        if thread is not None:
            return thread

    names = list(FETCHERS) if fetcher == 'auto' else [fetcher]
    for name in names:
        fetch, fmt = FETCHERS[name]
        print(f'Fetching {url} with {name}...', file=sys.stderr)
        try:
            raw = fetch(url)
            thread = PARSERS[fmt](raw, verbose)
        except FETCH_ERRORS as e:
            print(f'{name} failed: {e}', file=sys.stderr)
            continue
        if cache_dir:
            save_cached_thread(url, cache_dir, fmt, raw, verbose)
        return thread
    raise FetchFailed(', '.join(names))


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
    """Build a tree structure from flat comments based on indent levels.

    Removed comments are left out, and their replies take their place.
    """
    root_comments = []
    # (indent, list that deeper comments go into) for each ancestor of the current comment
    stack: list[tuple[int, list[Comment]]] = []

    for comment in flat_comments:
        # Pop from stack until we find parent
        while stack and stack[-1][0] >= comment.indent:
            stack.pop()

        siblings = stack[-1][1] if stack else root_comments
        if comment.removed:
            stack.append((comment.indent, siblings))
        else:
            siblings.append(comment)
            stack.append((comment.indent, comment.children))

    return root_comments


def format_comment_text(text: str, indent_str: str) -> str:
    """Format multi-line comment text with proper indentation."""
    lines = text.split('\n')
    result_lines = []

    for i, line in enumerate(lines):
        if i == 0:
            result_lines.append(line)
        else:
            # Indent continuation lines to align with content after "- @user: "
            if line.strip():
                result_lines.append(indent_str + '  ' + line)
            else:
                result_lines.append('')

    return '\n'.join(result_lines)


def render_markdown(comments: list[Comment], depth: int = 0) -> str:
    """Render comment tree as markdown list."""
    lines = []
    indent_str = '  ' * depth

    for comment in comments:
        desc_count = comment.descendant_count()
        count_str = f' [+{desc_count}]' if desc_count > 0 else ''

        # Format the first line
        formatted_text = format_comment_text(comment.text, indent_str)
        line = f'{indent_str}- @{comment.author}{count_str}: {formatted_text}'
        lines.append(line)

        # Render children
        if comment.children:
            child_md = render_markdown(comment.children, depth + 1)
            lines.append(child_md)

    return '\n'.join(lines)


def get_all_leaves(
    comments: list[Comment], parent: Comment | None = None
) -> list[tuple[Comment, Comment | None, list[Comment]]]:
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


def condense_comments(
    root_comments: list[Comment], target_rate: float, verbose: bool = False, step_size: int = 4
) -> list[Comment]:
    """Condense comments by removing low-weight leaves until target rate is reached."""
    import copy

    # Deep copy to avoid modifying original
    comments = copy.deepcopy(root_comments)
    original_md = render_markdown(comments)
    original_length = len(original_md)

    if verbose:
        print(f'Original length: {original_length} chars', file=sys.stderr)
        print(f'Target rate: {target_rate}', file=sys.stderr)
        print(f'Step size: {step_size}', file=sys.stderr)

    iteration = 0
    while True:
        current_md = render_markdown(comments)
        current_length = len(current_md)
        current_rate = current_length / original_length if original_length > 0 else 1.0

        if verbose:
            print(f'Current rate: {current_rate:.3f} ({current_length}/{original_length})', file=sys.stderr)

        if current_rate <= target_rate:
            break

        # Get all leaf comments
        leaves = get_all_leaves(comments)

        if not leaves:
            if verbose:
                print('No more leaves to remove', file=sys.stderr)
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
            print(f'Iteration {iteration}: removed {removed_count} leaves', file=sys.stderr)

    return comments


def extract_id_from_url(url: str) -> str:
    """Extract the item ID from a HN URL."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    if 'id' in params:
        return params['id'][0]
    return 'unknown'


def main():
    epilog = """
Examples:
  %(prog)s "https://news.ycombinator.com/item?id=12345"
      Fetch and save to hn.12345.md

  %(prog)s "https://news.ycombinator.com/item?id=12345" --stdout
      Print to stdout instead of file

  %(prog)s "https://news.ycombinator.com/item?id=12345" --cache-dir ~/.cache/hn
      Cache HTML to avoid repeated fetching

  %(prog)s "https://news.ycombinator.com/item?id=12345" --fetcher algolia
      Use only the Algolia API instead of trying curl, requests, then Algolia

  %(prog)s "https://news.ycombinator.com/item?id=12345" --condense 0.5
      Condense to 50%% of original size by removing low-weight comments

  %(prog)s "https://news.ycombinator.com/item?id=12345" --no-frontmatter -o out.md
      Save without YAML frontmatter
"""
    parser = argparse.ArgumentParser(
        description='Fetch and flatten Hacker News discussions into readable markdown.',
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('url', help='Hacker News item URL')

    # Mutually exclusive output options
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument('-o', '--output', metavar='FILE', help='Output file path')
    output_group.add_argument('--out-dir', metavar='DIR', help='Output directory (filename auto-generated)')

    parser.add_argument('--stdout', action='store_true', help='Print to stdout instead of file')
    parser.add_argument('--condense', type=float, metavar='RATE', help='Condense comments to target rate (0.0-1.0)')
    parser.add_argument(
        '--condense-step-size',
        type=int,
        default=4,
        metavar='N',
        help='Number of comments to remove per condense iteration (default: 4)',
    )
    parser.add_argument('--cache-dir', metavar='DIR', help='Directory to cache/load fetched pages')
    parser.add_argument(
        '--fetcher',
        choices=['auto', *FETCHERS],
        default='auto',
        help='How to fetch the thread; auto (default) tries curl, then requests, then the Algolia API',
    )
    parser.add_argument('--no-frontmatter', action='store_true', help='Omit YAML frontmatter from output')
    parser.add_argument('--verbose', action='store_true', help='Show progress to stderr')

    args = parser.parse_args()

    # Fetch and parse
    try:
        thread = load_thread(args.url, args.fetcher, args.cache_dir, args.verbose)
    except FetchFailed as e:
        print(f'Error: could not fetch {args.url} with {e}.', file=sys.stderr)
        if args.fetcher == 'auto':
            print(
                'HN and Algolia may be rate limiting this client. Wait a few minutes before retrying.', file=sys.stderr
            )
        else:
            print('Run with --fetcher auto (the default) to fall back to the other fetchers.', file=sys.stderr)
        sys.exit(1)
    comment_tree = thread.comments

    # Condense if requested
    if args.condense is not None:
        comment_tree = condense_comments(comment_tree, args.condense, args.verbose, args.condense_step_size)

    # Render markdown
    markdown = render_markdown(comment_tree)

    # Prepend frontmatter unless disabled
    if not args.no_frontmatter:
        frontmatter = generate_frontmatter(thread.title, args.url, thread.link_url)
        markdown = frontmatter + markdown

    # Output
    if args.stdout:
        print(markdown)
    else:
        item_id = extract_id_from_url(args.url)
        filename = f'hn.{item_id}.md'
        if args.output:
            output_path = args.output
        elif args.out_dir:
            os.makedirs(args.out_dir, exist_ok=True)
            output_path = os.path.join(args.out_dir, filename)
        else:
            output_path = filename
        with open(output_path, 'w') as f:
            f.write(markdown)
        print(f'Output: {output_path}', file=sys.stderr)
        if args.cache_dir:
            for fmt in PARSERS:
                cache_path = get_cache_path(args.url, args.cache_dir, fmt)
                if cache_path.exists():
                    print(f'Cache:  {cache_path}', file=sys.stderr)


if __name__ == '__main__':
    main()
