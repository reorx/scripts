---
name: llm-models
description: Look up current LLM model identifiers and pricing across providers. Use when the user needs to find a model's exact ID, compare pricing between models, or check what models a provider offers.
---

# LLM Models

Query LLM model information from [models.dev](https://models.dev). Supports caching, provider listing, model filtering by regex, and pricing display.

## Available scripts

- **`scripts/llm-models.py`** — Main script for fetching and querying LLM models (requires `uv`)

## Commands

### Update cache

Fetch the latest model data from models.dev:

```bash
uv run scripts/llm-models.py update
```

### List providers

Show all available LLM providers:

```bash
uv run scripts/llm-models.py providers
```

### List models

Filter models by provider, with optional regex pattern:

```bash
# All models from a provider
uv run scripts/llm-models.py list anthropic

# Filter by pattern
uv run scripts/llm-models.py list anthropic:opus openai:gpt-4

# Show pricing info (per 1M tokens)
uv run scripts/llm-models.py list -p anthropic:4-6
```

Query format: `provider:pattern` — the pattern part is optional and supports regex (case-insensitive).

## Workflow

1. If the user asks about LLM models, pricing, or providers, run the appropriate command above.
2. The cache auto-populates on first use. Run `update` to refresh.
3. Multiple queries can be passed at once to `list`.
