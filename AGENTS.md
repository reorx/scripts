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
