---
name: obsidian
description: Search notes, open files, and create zettelkasten notes in an Obsidian vault. Use this skill whenever the user mentions Obsidian, their vault, searching notes, finding notes by tag or content, opening a note, creating a new note, zettelkasten, zettel, or doing anything related to their Obsidian knowledge base — even if they just say "find that note about X", "save this as a note", "open my note on Y", "create a zettel note", or "new zettel". Also triggers when the user wants to look up information they've previously written down, or wants to save research/content to their personal knowledge base.
---

# Obsidian Skill

Search and open notes via the `obsidian` CLI (requires the Obsidian app to be running). Create notes with the bundled script — **never** with `obsidian create` (see §3 for why).

## 1. Searching Notes

```bash
# Text search — returns matching file paths
obsidian search query="meeting notes"
obsidian search query="project plan" path="Work"    # limit to folder
obsidian search query="todo" limit=10               # cap results
obsidian search query="meeting" format=json         # structured output

# Text search with line context (grep-style path:line: text)
# Use when the user wants to see WHAT matched, not just WHERE
obsidian search:context query="TODO"
obsidian search:context query="bug" path="Engineering"

# Tags
obsidian tags counts sort=count                     # all tags by frequency
obsidian tag name="project" verbose                 # files carrying a tag
obsidian tags file="Project Notes"                  # tags of one file

# Frontmatter properties
obsidian properties counts                          # all properties in vault
obsidian property:read name="status" file="Project"

# Discovery
obsidian files folder="Zettelkasten"                # list files in folder
obsidian backlinks file="Topic Note" counts         # what links TO this note
obsidian links file="Topic Note"                    # what this note links to
obsidian orphans                                    # no incoming links
obsidian recents                                    # recently opened

# Read content
obsidian read file="Note Name"
obsidian read path="folder/note.md"
```

To find notes by tag: `obsidian tag name="tagname" verbose` lists the files, then read the relevant ones. For complex lookups, combine approaches (search text then check tags, or list a folder then search within it).

## 2. Opening Files

```bash
obsidian open file="My Note"                        # by name (wikilink resolution)
obsidian open path="folder/subfolder/note.md"       # by exact path
obsidian open file="My Note" newtab
obsidian search:open query="search terms"           # open Obsidian's search UI
```

## 3. Creating Zettelkasten Notes

**Always create notes with `{this_skill_dir}/scripts/ob-zettel-create.sh`. Never use `obsidian create`.** The CLI takes content as a command-line argument (silently truncated at ARG_MAX, ~256KB on macOS), its stdout can be polluted by installer warnings, and it needs the app running just to write a plain-text file. The script writes the file directly to the vault on disk, then opens it via `obsidian open`.

```bash
# Usage: ob-zettel-create.sh [-t TAG]... [-n] [--src FILE] TITLE [< content]

ob-zettel-create.sh "My Note Title"                                   # empty note, opens in Obsidian
ob-zettel-create.sh -t "literature" -t "psychology" "Cognitive Biases"
echo "Some content" | ob-zettel-create.sh -t "reference" "API Patterns"
ob-zettel-create.sh --src /path/to/draft.md "Project Proposal"        # content from file
ob-zettel-create.sh -n "Quiet Note"                                   # skip opening in Obsidian
```

Content source priority: `--src FILE` > piped stdin > empty. For long generated content, write it to a temp file first and pass `--src` rather than piping a giant heredoc.

Tags are written as a `#tag` line at the top of the note. Notes are named `YYYYMMDD.HH Title.md` (e.g., `20260317.14 Cognitive Biases.md`).

**Environment variables**:
- `OBSIDIAN_VAULT_PATH` (required) — absolute path to the vault root
- `OBSIDIAN_ZETTEL_DIR` (optional, default `80 Zettelkasten Notes`) — zettel directory relative to vault root
