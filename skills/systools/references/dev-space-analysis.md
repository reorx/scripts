# Disk-usage analysis of a dev project — brief for a read-only agent

`dev-space watch --agent` hands this brief to `codex exec -s read-only` when a project under `~/Code` grew
past its alert size and the existing rules don't cover it. A human can give the same brief to any agent.

## Your job

Find out what takes the space in the project, decide what is safe to delete, what should move to the
archive drive, and what must stay, and write **rule proposals** in the format below. A human reviews them
and merges them into `~/Code/scripts/skills/systools/config/dev-space.toml`. You change nothing.

## Hard rules

- **Read-only.** No delete, move, `git clean`, `git worktree remove/prune`, `cargo clean`, `pnpm prune`,
  no builds, no tests. `du`, `find`, `ls`, `stat -f '%Sm %Sa %SB'`, `git status/log/worktree list/check-ignore`,
  reading files, `lsof`, `ps` are fine. Scope `du` (`du -sh dir/*`, `du -d 2`); don't rerun it on the same tree.
- Only generated, ignored or untracked content is a candidate. Read the project's `AGENTS.md`, `CLAUDE.md`
  and `kb/` docs: they explain what dirs are for (fixtures, recorded data, caches the app needs).
- Check what is in active use: recent mtimes, recent commits, processes with cwd or open files inside.
  atime is unreliable on this Mac (it only updates while atime < mtime); don't use it.
- `du` overstates APFS clones (pnpm/uv installs are clones of their store): deleting one copy frees nothing
  while another lives. Say so when it applies.

## What the engine already guarantees

You don't need rules for these; the engine enforces them on every rule:

- never touches git-tracked files, or untracked files that are not git-ignored;
- skips anything a process has open, uses as cwd or runs from;
- never follows symlinks, never leaves the project's root/related dirs;
- archive refuses dirs with `.git`, symlinks, `.app` bundles, secrets (`.env`, keys) or exFAT-illegal names.

Defaults already apply to every git project (see `dev-space rules <project>`): build trees and DB copies in
`tmp/` after 7 days, SwiftPM index-build and `.next/cache` after 7 days, dependency dirs of projects idle
30 days, and archiving `tmp/<date>-<task>/` evidence after 14 days. Propose only what they miss.

## Rule format

```toml
[projects.<name>]
root = "~/Code/<name>"
related = []            # other dirs of this project (sibling copies, ~/Library data), ~ or absolute
alert_size = "6GiB"     # healthy size after cleanup x ~1.5
protect = []            # globs the engine must never touch (live DBs, credentials, fixtures)

[[projects.<name>.rules]]
id = "kebab-id"
why = "what it is, why it is safe, what regenerating it costs"
action = "delete"       # delete | archive (to LaCie, symlink left) | sqlite-backup
when = "daily"          # daily | pressure (also when the disk is low) | manual (by hand only)
paths = ["tmp/*/DerivedData"]  # relative to root; ~ or absolute for related dirs; * ? [..] **
exclude = []            # skip matches that are, or contain, these
age_days = 7            # newest file mtime inside the match must be older
pressure_age_days = 3   # optional, replaces age_days under disk pressure
keep_newest = 0         # never touch the N newest matches
idle_days = 0           # only when the git worktree had no commit/change for N days
companions = []         # suffixes handled with each match, e.g. [".sha256"]
# sqlite-backup: source = "<db path>", keep_daily = 7, keep_weekly = 8
```

The archive drive (LaCie, `/Volumes/LaCie/DevArchive`) is exFAT and may be unplugged: only plain data
(dumps, recordings, screenshots, old backups) fits, and the project must tolerate the path being a dangling
symlink. Prefer `delete` for anything regenerable; `manual` for anything whose loss you can't rule out.

## Your final message (saved verbatim as the proposal)

Write it in Chinese (paths, code and TOML in English):

1. Size table of the top consumers: path, size, what it is, ignored/tracked, last modified.
2. Proposed rules as one TOML block, each with an estimate of what it frees today.
3. One-time manual actions (with size and risk) that rules should not do — e.g. removing an obsolete copy.
4. Open questions for the user.
