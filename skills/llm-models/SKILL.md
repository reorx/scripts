---
name: llm-models
description: Look up current LLM model identifiers, pricing, and specs across providers using models.dev data. Use this skill whenever the user asks about model IDs, model names, pricing, context windows, or what models a provider offers — even if they don't say "models.dev". Also use when the user is writing code that needs a model ID and seems uncertain, when comparing costs between models or providers, or when checking what's the latest model from any provider. Covers 90+ providers including OpenAI, Anthropic, Google, Mistral, DeepSeek, xAI, Cohere, and many more.
---

# LLM Models

Query LLM model information from [models.dev](https://models.dev). The cached data includes model IDs, display names, pricing (per 1M tokens), context/output limits, modalities, and capability flags (reasoning, tool_call, etc.) across 90+ providers.

## Script

`scripts/llm-models.py` — requires `uv` to run. All commands below assume the skill directory as working directory.

## Commands

```bash
# Refresh cache (auto-runs on first use, re-run to get latest data)
uv run scripts/llm-models.py update

# List all providers
uv run scripts/llm-models.py providers

# List models — query format is provider:pattern (pattern is optional regex, case-insensitive)
uv run scripts/llm-models.py list anthropic              # all Anthropic models
uv run scripts/llm-models.py list anthropic:opus openai:gpt-4  # multiple queries at once
uv run scripts/llm-models.py list -p anthropic:4-6       # with pricing (USD per 1M tokens)
```

## Detailed data in cache

The script outputs model IDs and optionally pricing, but the cache file (`~/.local/share/llm-models/models.json`) contains richer per-model data. When the user needs details beyond IDs and pricing — such as context window size, output token limit, supported modalities, or whether a model supports reasoning — read the cache file directly and extract the relevant fields.

Each model entry has this structure:
- `id` — exact model identifier to use in API calls
- `name` — human-friendly display name
- `family` — model family (e.g. "claude", "gpt", "gemini")
- `cost.input` / `cost.output` — USD per 1M tokens
- `limit.context` / `limit.output` — token limits
- `modalities.input` / `modalities.output` — e.g. ["text", "image"]
- `reasoning`, `tool_call`, `attachment` — boolean capability flags
- `open_weights` — whether the model weights are open
- `release_date`, `last_updated`

## Workflow

1. **Run the script** from the skill directory using `uv run scripts/llm-models.py`. Always include `-p` when pricing is relevant to the question.
2. **For richer queries** (context windows, capabilities, comparisons across multiple fields), read the cache JSON directly and filter/format the results for the user.
3. **Present results concisely** — the user usually wants a quick answer, not a wall of data. If they ask "what's the model ID for Claude Opus?", give them the ID. If they ask to compare pricing, show a short table.
4. **If data seems stale or a model is missing**, run `update` first, then retry.
