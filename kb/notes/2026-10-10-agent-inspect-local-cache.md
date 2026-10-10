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
