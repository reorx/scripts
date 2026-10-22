# Scripts Repository

Personal scripts for work tricks, productivity, and everyday life, plus agent skills under `skills/`.

## Rules

- One task = one self-contained file. Scripts don't import or call each other unless explicitly requested; when editing, touch only the script at hand.
- New scripts keep their extension (`.sh`, `.py`) and are made executable with `chmod +x`.
- Tests sit beside the script as `test_<name>.py` / `test-<name>.sh`, each a standalone runnable file.

## Python

- Standard library first; add third-party dependencies only when absolutely necessary.
- Declare dependencies with PEP 723 inline metadata and the shebang `#!/usr/bin/env -S uv run --script`. Run such scripts through `uv run <script>` or the shebang, never plain `python`.

## Bash

- Start with `set -euo pipefail`.

## Skills and linking

- A skill is `skills/<name>/SKILL.md` with optional `scripts/` and `references/`.
- `./link-skill skills/<name>` symlinks a skill into the agent skill dirs (`~/.claude`, `~/.agents`, `~/.codex`, OpenClaw).
- `./link-script <path>` symlinks a script into `~/.local/bin`; `-l` lists links, `-d <name>` removes one.

## Application preferences

- `app-defaults.py` inspects saved macOS preferences and scans ARM64 binaries for candidate keys. Keep candidates distinct from confirmed settings; mutations must back up first and verify by reading back. Run `uv run test_app_defaults.py` when changing it.

## YouTube transcripts

- `yt-transcript.py <url-or-id>` fetches one caption track through the `yt-dlp` binary and prints `[mm:ss]` lines (`--format plain|json`, `--lang`, `--list`). Default track: uploaded subtitles in the video's language, else that language's `-orig` ASR track — auto-dubbed videos carry one `-orig` per audio track, so match on `info.language`, not the suffix.
- Keep downloads to exactly one `--sub-langs` code: requesting several (e.g. `en.*,zh.*`) gets HTTP 429 from YouTube. Run `uv run test_yt_transcript.py` when changing it.

## Hacker News threads

- `skills/hnread/scripts/hn_flat.py` fetches with curl, falling back to requests and then the Algolia API (`--fetcher auto`); a 200 page without `table.fatitem` counts as a failure. Never give python-requests a browser User-Agent: HN answers that with HTTP 419, while curl (any UA) and requests' own UA pass.
- Algolia lists replies by id and drops deleted/dead comments with their whole subtree. One Firebase request (`kids` of the story) restores HN's top-level ranking; deeper levels stay chronological. Run `uv run skills/hnread/scripts/test_hn_flat.py` when changing the script.

## Git history squashing

- `skills/squash-docs/scripts/squash-docs.ts` folds linear runs of commits whose subject matches `--pattern` (default `docs:`) into one, reusing original trees and keeping merges; preview by default, `--apply` updates only the current branch behind a `refs/squash-docs-backup/` ref. It is the repo's only TypeScript script: Node >= 22.18, no dependencies, run `node test-squash-docs.ts` when changing it.

## Documentation

- `kb/docs/skill-invocation.md` — Read before changing skill invocation policies or synchronizing installed skills; explicit-only skills need both Claude Code and Codex settings.
- `kb/docs/app-defaults.md` — Read when inspecting or changing macOS application preferences or modifying `app-defaults.py`.
- `kb/docs/cc-format-hook.md` — Read before changing `cc-format --hook` or the Claude Code / Codex PostToolUse hooks that call it; Codex needs different reporting from Claude. Run `./test-cc-format.sh` after changes.
