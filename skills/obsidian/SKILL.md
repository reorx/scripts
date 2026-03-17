---
name: obsidian
description: Search notes, open files, and create zettelkasten notes in Obsidian using the Obsidian CLI. Use this skill whenever the user mentions Obsidian, their vault, searching notes, finding notes by tag or content, opening a note, creating a new note, zettelkasten, zettel, or doing anything related to their Obsidian knowledge base — even if they just say "find that note about X", "save this as a note", "open my note on Y", "create a zettel note", or "new zettel". Also triggers when the user wants to look up information they've previously written down, or wants to save research/content to their personal knowledge base.
---

# Obsidian Skill

Interact with Obsidian via the `obsidian` CLI. The Obsidian app must be running for CLI commands to work.

## 1. Searching Notes

The Obsidian CLI provides powerful search capabilities. Use the right search method based on what the user is looking for.

### Text search — `obsidian search`

Search vault content by text query. Returns matching file paths.

```bash
# Basic text search
obsidian search query="meeting notes"

# Limit to a folder
obsidian search query="project plan" path="Work"

# Case-sensitive search
obsidian search query="APIKey" case

# Limit number of results
obsidian search query="todo" limit=10

# Get just the count of matches
obsidian search query="recipe" total

# Output as JSON for structured processing
obsidian search query="meeting" format=json
```

### Text search with context — `obsidian search:context`

Same as `search` but returns matching lines with surrounding context (grep-style `path:line: text` output). Use this when the user wants to see *what* matched, not just *where*.

```bash
# Search with line context
obsidian search:context query="TODO"

# Search within a specific folder
obsidian search:context query="bug" path="Engineering"

# JSON output with context
obsidian search:context query="deadline" format=json
```

### Tag search — `obsidian tag` and `obsidian tags`

Search and browse by tags.

```bash
# List all tags in the vault (with counts, sorted by frequency)
obsidian tags counts sort=count

# List tags for a specific file
obsidian tags file="Project Notes"

# Get info about a specific tag (occurrence count + file list)
obsidian tag name="project" verbose

# Just get the count for a tag
obsidian tag name="meeting" total
```

**Strategy for finding notes by tag**: First use `obsidian tag name="tagname" verbose` to list all files with that tag, then read the relevant ones.

### Property search — `obsidian properties`

Search by frontmatter properties.

```bash
# List all properties in the vault
obsidian properties counts

# Show properties for a specific file
obsidian properties file="My Note"

# Read a specific property value from a file
obsidian property:read name="status" file="Project"
```

### Combining search strategies

For complex lookups, combine multiple approaches:

1. **Find by content + filter by tag**: Search text first, then check tags on results
2. **Find by tag + read content**: Get files with a tag, then read specific ones
3. **Browse folder + search within**: Use `obsidian files folder="X"` to list files, then search within

### Other discovery commands

```bash
# List all files in a folder
obsidian files folder="Zettelkasten"

# List backlinks to a note (what links TO this note)
obsidian backlinks file="Topic Note" counts

# List outgoing links from a note (what this note links TO)
obsidian links file="Topic Note"

# Find orphan notes (no incoming links)
obsidian orphans

# Find dead-end notes (no outgoing links)
obsidian deadends

# List recently opened files
obsidian recents

# Read file content
obsidian read file="Note Name"
obsidian read path="folder/note.md"
```

## 2. Opening Files

Open any note in the Obsidian app:

```bash
# Open by name (wikilink-style resolution)
obsidian open file="My Note"

# Open by exact path
obsidian open path="folder/subfolder/note.md"

# Open in a new tab
obsidian open file="My Note" newtab
```

You can also open the search view in Obsidian's UI:

```bash
obsidian search:open query="search terms"
```

## 3. Creating Zettelkasten Notes

New notes are created in the zettelkasten directory by default. The directory is read from the `OBSIDIAN_ZETTEL_DIR` environment variable (a path relative to the vault root).

### Using the bundled script

The `scripts/ob-zettel-create.sh` script handles the full workflow: create a properly named zettelkasten note, optionally with tags and piped content, then open it in Obsidian.

```bash
# Create a simple note and open it
ob-zettel-create.sh "My Note Title"

# Create with tags
ob-zettel-create.sh -t "literature" -t "psychology" "Cognitive Biases in Decision Making"

# Pipe content into the note
echo "Some content here" | ob-zettel-create.sh -t "reference" "API Design Patterns"

# Pipe multi-line content
cat <<'EOF' | ob-zettel-create.sh -t "idea" "Project Proposal"
# Project Proposal

This is a detailed proposal...
EOF
```

**Naming convention**: Notes are named `YYYYMMDD.HH Title.md` (e.g., `20260317.14 Cognitive Biases.md`) and placed in `$OBSIDIAN_ZETTEL_DIR/`.

**Environment variables**:
- `OBSIDIAN_ZETTEL_DIR` (optional, defaults to `80 Zettelkasten Notes`) — zettelkasten directory relative to vault root
- `OBSIDIAN_VAULT` (optional) — vault name, uses active vault if unset

The script path is: `{this_skill_dir}/scripts/ob-zettel-create.sh`

### Using obsidian CLI directly

For cases where you need more control:

```bash
# Create a note at a specific path
obsidian create path="80 Zettelkasten Notes/20260317.14 My Note.md" content="# My Note\n\nContent here" open

# Create and open in new tab
obsidian create path="80 Zettelkasten Notes/20260317.14 My Note.md" open newtab
```

When generating content for a new note, prefer piping through the script rather than passing via `content=` parameter — the CLI passes `content` as a command-line argument which is subject to OS ARG_MAX limits (~256KB on macOS), so large content will be truncated.
