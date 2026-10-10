---
created: 2026-10-10
tags:
  - icloud
  - agent-inspect-session
---

# Keep statusline metrics outside iCloud

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
