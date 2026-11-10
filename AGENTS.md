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

## Tailscale forwards

- `tsfwd.sh` wraps `tailscale serve --tcp` and runs under macOS `/bin/bash` 3.2 (no `mapfile` or associative arrays). A forward is dead when `nc -z` to its `TCPForward` target fails; `-p` removes dead TCP forwards only and never touches Web handlers.
- `$TAILSCALE` points the script at another CLI; `test-tsfwd.sh` uses it to run against a stub and never touches the real tailnet. Run `./test-tsfwd.sh` when changing it.

## Sun Browser URL routing

- `sunbrowser.py <url>...` is `BROWSER` in the global Claude Code settings; Claude Code runs `$BROWSER <url>` for every page it opens (login, artifacts, clicked links). Hosts under `SUN_BROWSER_DOMAINS` (default `claude.ai,claude.com`, matched on dot boundaries, so subdomains count and `evilclaude.ai` does not) open in the AdsPower Sun Browser; other URLs go to `open`.
- Sun Browser is driven only through its DevTools HTTP endpoint: `PUT /json/new?<encoded url>`, then `/json/activate/<id>`. AdsPower launches it with `--remote-debugging-port=0`, so the port comes from `DevToolsActivePort` in the profile's `--user-data-dir`. With several profiles open, `SUN_BROWSER_PROFILE` picks one by AdsPower id.
- Never reach it through `open -a` or its bundle id: when it is not running that starts a bare SunBrowser without AdsPower's proxy and fingerprint. Not running is an error, with no fallback to the default browser. `/json/activate` only selects the tab, so the window is raised with `NSRunningApplication` by pid. Run `uv run test_sunbrowser.py` when changing it.

## Claude session search

- `claude_session_search.py` is the behavior baseline of `~/Code/agent-session-manager`: its `make parity` diffs the app's `asm` CLI against this script line by line, so a change to what the script prints or in what order has to land in `asm` too. Sessions list newest first prompt first, ties by last update, then by session ID (`newest_first`). Run `python3 test_claude_session_search.py` when changing it.

## Claude Code request probe

- `cc-probe.py` (linked as `cc-probe`) runs `claude -p` against a fake API on 127.0.0.1 that answers every request with 400, then reports what the first request carries: items by kind (system sections, tools, deferred tool names, skills by source, agents, CLAUDE.md files, MCP instructions), runtime state (version, model, effort, fast, permission mode, Artifact, claude.ai skills, git snapshot, MCP servers) and the settings keys that switch them. `--via <zsh command>` goes through a function from `~/.zshrc_fn` (`cl` and friends); `--save` plus `diff` compares two setups; `--expect-absent`/`--expect-present`/`--max-tokens` exit 1 when unmet.
- The parser follows the request layout of Claude Code 2.1.311: listings sit in a `role: system` message, MCP instructions between the agent and skill listings, loose paragraphs after the skill listing. When a release moves things, first update the fake claude in `test_cc_probe.py` to the new layout. Captured credentials go only to count_tokens and only when they are Anthropic's (`sk-ant-`); `--save` drops `metadata` (device and account ids). Run `uv run test_cc_probe.py` when changing it.
- `--interactive` types the prompt into the TUI on a pty (AskUserQuestion and SendFeedback exist only there) and keeps the first request with a `system`, killing claude's process group at once: after the 400s Claude Code drops tool search and resends every tool in full, so the largest request is the wrong one. It sets `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1` (no transcript, no `history.jsonl` row) and drops the env Claude Code gives its children (`CLAUDECODE`, `CLAUDE_CODE_CHILD_SESSION`, …). The TUI spaces words with `ESC[<n>G`, so screen text treats cursor moves as spaces; that is how the folder-trust dialog is detected and never typed into. `--count exact` adds a `tool-preamble` item, the tool use system prompt that removing any one tool leaves in place.

## Hacker News threads

- `skills/hnread/scripts/hn_flat.py` fetches with curl, falling back to requests and then the Algolia API (`--fetcher auto`); a 200 page without `table.fatitem` counts as a failure. Never give python-requests a browser User-Agent: HN answers that with HTTP 419, while curl (any UA) and requests' own UA pass.
- The HN page path follows HN's default view: `noshow` rows (replies hidden under a collapsed flagged/dead comment) are dropped; deleted comments and low-score ones (any `commtext` color class but `c00`) are dropped while their replies take their place.
- Algolia lists replies by id and has no scores or flags, so it keeps low-score comments and part of what HN hides. One Firebase request (`kids` of the story) restores HN's top-level ranking; deeper levels stay chronological. Run `uv run skills/hnread/scripts/test_hn_flat.py` when changing the script.

## Git history squashing

- `skills/squash-docs/scripts/squash-docs.ts` folds linear runs of commits whose subject matches `--pattern` (default `docs:`) into one, reusing original trees and keeping merges; preview by default, `--apply` updates only the current branch behind a `refs/squash-docs-backup/` ref. It is the repo's only TypeScript script: Node >= 22.18, no dependencies, run `node test-squash-docs.ts` when changing it.

## Mole cleanup review

- `mole-review.py` shares `~/.config/mole/whitelist` with Mole (`--whitelist` overrides it): edits also affect `mo clean`. Initialize missing shared config with `mo clean --whitelist` and save before review, preserving Mole's optional defaults. Space marks deletion; `x` toggles only the current row's protection; `w` shows/hides protected rows. The default deletion log stays at `~/.config/mole-review/deleted.log`. Run `uv run test_mole_review.py` when changing it.

## Homebrew upgrades

- `brewer.py` (linked as `brewer`: `outdated`, `upgrade`, `whitelist`) looks only at formulae installed on request and levels each update by the first differing version segment (major / minor / patch, revision-only counts as patch). `upgrade` auto-upgrades `~/.config/brewer/whitelist`, reviews the remaining major/minor updates in a textual TUI (upgrade, whitelist or uninstall each, `i` for details; `--no-review` stops after the whitelist), and runs one `brew uninstall --formula` / `brew upgrade --formula` per formula, uninstalls first. brew subprocesses get `HOMEBREW_NO_ASK=1`: brew 7 otherwise stops at its own `[y/n]` prompt after the TUI already confirmed.
- Outcomes, including formulae brew upgraded along the way, come from diffing `brew outdated` before and after, never from parsing brew's text output. Tests run against a fake `brew` first in PATH; run `uv run test_brewer.py` when changing it. PRD and design: `kb/plans/2026-10-27-brewer.md`.

## Portless on 443

- `portless-443.sh` (linked as `portless-443.sh`; `install`/`uninstall` need `sudo ~/.local/bin/portless-443.sh …`, sudo's PATH lacks `~/.local/bin`) keeps the machine-wide Portless proxy on 443 as the LaunchDaemon `local.portless.proxy-443`, so every project's `https://<name>.localhost` works without a port after reboots. The no-sudo proxy on 1355 keeps running beside it; both read the same routes in `~/.portless`.
- The daemon is root but must act like `sudo portless proxy start --port 443`: Portless locates `~/.portless` through `SUDO_USER`/`HOME` and chowns what it writes to `SUDO_UID`/`SUDO_GID`, so the plist sets all four. Without them it would leave root-owned files in `~/.portless`. `install` refuses before writing anything if something other than Portless holds 443, then stops the hand-started 443 Portless. Subcommands are `cmd_*` functions: one named `install` shadowed install(1) and recursed forever. After upgrading Portless run `sudo launchctl kickstart -k system/local.portless.proxy-443`. Run `./test-portless-443.sh` when changing it: no root, never touches launchd; `install` runs end to end against fakes in PATH with a 20 s watchdog.

## Repo charts

- `repocharts.py [path] -b day|week|month` prints two bar charts on one time axis: non-merge commits per bucket by author date, then lines of code at the end of each bucket. The line count is the running numstat sum along HEAD's first-parent chain, with merges diffed against their first parent, by committer date, so the last total equals the text lines at HEAD. Binary files and lockfiles are left out (`--with-lockfiles`, `-x GLOB`).
- `-v/--values` prints a number under each bar: the commit count, and for lines of code the change in that bucket (signed, exact below 10,000), not the total. Columns widen to fit the widest number, so fewer buckets fit the terminal; both charts always share one column width.
- The numstat walk runs with `GIT_NO_LAZY_FETCH=1`. In a partial clone git would otherwise fetch missing blobs one commit at a time (minutes, and it fills the clone), so there the line chart is replaced by a `git backfill` hint. Run `uv run test_repocharts.py` when changing it.

## Documentation

- To clean the HONOR ALI-AN00 phone, use `honor-cleanup.py` (preview by default; `--apply` uninstalls). Its device identity and third-party app whitelist live at the top of the script. Run `uv run test_honor_cleanup.py` when changing it.
- `kb/docs/skill-invocation.md` — Read before changing skill invocation policies or synchronizing installed skills; explicit-only skills need both Claude Code and Codex settings.
- `kb/docs/app-defaults.md` — Read when inspecting or changing macOS application preferences or modifying `app-defaults.py`.
- `kb/docs/cc-format-hook.md` — Read before changing `cc-format --hook` or the Claude Code / Codex PostToolUse hooks that call it; Codex needs different reporting from Claude. Run `./test-cc-format.sh` after changes.
