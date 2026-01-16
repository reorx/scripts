#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""
Fetch, cache, and filter LLM models from models.dev
"""

import argparse
import json
import re
import sys
from pathlib import Path

import httpx

API_URL = "https://models.dev/api.json"
CACHE_DIR = Path.home() / ".local" / "share" / "llm-models"
CACHE_FILE = CACHE_DIR / "models.json"


def update():
    """Fetch API and save to cache file."""
    print(f"Fetching models from {API_URL}...")
    response = httpx.get(API_URL, timeout=30)
    response.raise_for_status()
    data = response.json()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, indent=2))
    print(f"Saved to {CACHE_FILE}")

    # Show summary
    provider_count = len(data)
    model_count = sum(len(p.get("models", {})) for p in data.values())
    print(f"Cached {model_count} models from {provider_count} providers")


def load_cache():
    """Load cached models data."""
    if not CACHE_FILE.exists():
        print(f"Cache file not found. Run 'update' first.", file=sys.stderr)
        sys.exit(1)
    return json.loads(CACHE_FILE.read_text())


def parse_query(query):
    """Parse query string into (provider, pattern) tuple."""
    if ":" in query:
        provider, pattern = query.split(":", 1)
        return provider, pattern if pattern else None
    return query, None


def list_models(queries):
    """Filter and display models by provider and optional regex pattern."""
    data = load_cache()

    for query in queries:
        provider_id, pattern = parse_query(query)

        if provider_id not in data:
            print(f"Provider '{provider_id}' not found", file=sys.stderr)
            continue

        provider = data[provider_id]
        models = provider.get("models", {})

        if pattern:
            regex = re.compile(pattern, re.IGNORECASE)
            matched = [m for m in models.keys() if regex.search(m)]
        else:
            matched = list(models.keys())

        matched.sort()

        print(f"{provider_id}:")
        if matched:
            for model_id in matched:
                print(f"- {model_id}")
        else:
            print("  (no matches)")
        print()


def main():
    parser = argparse.ArgumentParser(description="Fetch and filter LLM models from models.dev")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("update", help="Fetch API and update local cache")

    list_parser = subparsers.add_parser("list", help="List models filtered by provider and pattern")
    list_parser.add_argument(
        "queries",
        nargs="+",
        metavar="QUERY",
        help="Query in format 'provider:pattern' (e.g., 'anthropic:opus', 'openai:gpt')"
    )

    args = parser.parse_args()

    if args.command == "update":
        update()
    elif args.command == "list":
        list_models(args.queries)


if __name__ == "__main__":
    main()
