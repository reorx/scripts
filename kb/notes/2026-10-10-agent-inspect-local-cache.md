---
created: 2026-10-10
tags:
  - icloud
  - agent-inspect-session
---

# Keep statusline metrics outside iCloud

## Superseded: on-demand transcript inspection

Later on 2026-10-10, caching was removed at the user's request: occasional
inspection should not require continuous background writes. The inspector now
reads only local transcripts on invocation. It ignores old caches and no longer
accepts `--cache-statusline`; cache timestamps are absent from JSON output.
Window inference and `--context-window` remain available. Missing window data
still yields unknown rather than an invented percentage.

On this Mac, the cache pipeline was removed from `~/.claude/settings.json`, and
the local cache directory and legacy compatibility symlink were deleted. The
statusline's five-second refresh remains for its existing running-turn timer;
it no longer invokes the inspector. Other installations with the old pipeline
must likewise remove the `agent-inspect-session.sh --cache-statusline |` prefix.

Validation: the new stale-cache regression failed against the previous script.
After removing caching, all 29 JSON cases and CLI checks passed, including
fresh transcript reads, compaction, missing transcripts, ignoring old caches,
no cache creation, and rejection of the removed writer option. Bash syntax and
the local settings JSON were also checked.

## Unknown-context fallback

On-demand inspection now emits actionable guidance when percentage cannot be
calculated. Recorded token usage takes precedence (including zero); 100000
tokens triggers a recommendation to summarize work and consider a new session.
Without token data, the same recommendation triggers at 400000 approximate
UTF-8 bytes of message and tool text since the last compaction. These thresholds
are heuristics, not model limits. Bytes are never converted into invented tokens.
Known windows without token data still use the byte fallback.

The byte estimate excludes metadata, images, Claude sidechains and Codex display
events. Compaction resets it, using Codex replacement history when present.
It does not reconstruct exact conversation branches, hidden prompts or pruned
tool results. Both below-threshold readings and absent evidence explicitly avoid
claiming that context pressure is low. JSON exposes `assessment_basis`,
`context_bytes`, `context_high`, `warning_threshold` and `guidance`; text output
also includes recorded token usage and the advice.

Validation: 40 JSON cases and CLI checks passed, including UTF-8 bytes, tool
content, compaction, exact threshold boundaries, zero tokens and missing data.
A real Claude transcript with 342358 tokens and no identifiable window emitted
the expected new-session guidance; a Codex session retained its percentage.

## Historical cache relocation

The Claude statusline invokes `agent-inspect-session.sh --cache-statusline`.
Every callback writes an atomic snapshot including a fresh `updated_at`, even
when token usage is unchanged. On this Mac, `~/.claude` points into iCloud Drive,
so storing these snapshots beneath the config directory caused continuous
sync activity. Logs attributed nsurlsessiond connections to com.apple.bird and
showed repeated successful remote-change fetches for this cache directory.
The evidence does not identify which device originated every remote change.

Reads and writes now use `${XDG_CACHE_HOME:-$HOME/Library/Caches}/agent-inspect-session`.
Keep XDG_CACHE_HOME on local, unsynced storage if configured. Callback freshness
semantics remain unchanged; queries do not fall back to the old cloud cache.

On this Mac, the existing cache directory was moved to
`~/Library/Caches/agent-inspect-session`, preserving its data. A compatibility
symlink at `~/.claude/agent-inspect-session` redirects callbacks already executing
the old script to local storage. New invocations use the new path directly.
This is a local-machine fix; another machine running an old script needs the
same code update. Clash settings were not changed.

Validation: the regression first failed against the old implementation. The
suite then passed all 30 JSON cases plus CLI checks, including a cloud-symlinked
Claude config, local-only cache creation, and leaving legacy cloud data untouched.
Bash syntax and git whitespace checks passed. A real active session continued
updating locally and returned current context metrics, while the compatibility
symlink's inode and modification time stayed unchanged. A post-change process
sample showed nsurlsessiond, bird and fileproviderd at 0% CPU; this is not proof
that all unrelated iCloud transfers have finished.
