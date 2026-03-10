---
name: kb
description: >-
  Manage the project's kb/ knowledge base folder. Use this skill when notes, plans, session summaries,
  todo files, or reference documents are produced during development, or when the user wants to write, organize, move,
  download, or search files in the kb/ directory. Also triggers for /kb summarize session, /kb ss, or /kb 总结 session.
  IMPORTANT: Proactively trigger this skill when a development plan has been written or finalized in conversation,
  or when research/investigation results are ready — offer to save them to kb/ even if the user didn't explicitly
  ask. Any time content is produced that would be valuable to preserve as project knowledge, this skill should activate.
---

# KB - Project Knowledge Base

Maintain a `kb/` folder at the project root as the project's evolving knowledge base. The folder has five sub-directories:

| Directory | Purpose |
|-----------|---------|
| `kb/plans/` | Development plans for features or work items, intended for Coding Agents |
| `kb/sessions/` | Session summaries (what was done on a given date) |
| `kb/notes/` | Research findings, ideas, discussion notes |
| `kb/todos/` | Task checklists for a piece of work, using `- [x]` / `- [ ]` syntax |
| `kb/docs/` | Downloaded reference documents (web pages saved as markdown) |

## Initialization

Before writing any file, ensure the target directory exists. Create it if needed:

```bash
mkdir -p kb/plans kb/sessions kb/notes kb/todos kb/docs
```

## Available Scripts

- **`scripts/puremd.sh`** — Download a web page as markdown via pure.md
- **`scripts/search-docs.sh`** — Search downloaded documents using ripgrep

## File Naming Convention

All files follow the pattern:

```
YYYY-MM-DD-<slug>.md
```

- Date is today's date (obtain via `date +%Y-%m-%d`)
- `<slug>` is a short English phrase summarizing the content, words joined by `-`

> **Note**: Files in `kb/docs/` are an exception — they use URL-derived filenames from the download script, not the date-slug pattern.

## Frontmatter

Every file MUST start with YAML frontmatter:

```yaml
---
created: YYYY-MM-DD
tags:
  - tag1
  - tag2
---
```

- `created`: today's date
- `tags`: relevant tags inferred from content. Use lowercase, hyphen-separated words.

## Handling User Intent

The user invokes this skill with `/kb <intent>`. Interpret the intent to determine:

1. **Which directory** the file belongs in (plans, sessions, notes, todos, or docs)
2. **What action** to take — create a new file, move an existing file, or update an existing file

Examples:

| User says | Action |
|-----------|--------|
| `/kb 将调研情况记录到笔记中` | Create a note in `kb/notes/` summarizing the research from context |
| `/kb 将刚才生成的文件放到 plans 下面` | Move/copy the plan file from context into `kb/plans/` |
| `/kb create a todo for the auth feature` | Create a todo checklist in `kb/todos/` |
| `/kb summarize session`, `/kb ss`, or `/kb 总结 session` | Create a session summary in `kb/sessions/` — see below |
| `/kb https://example.com/docs` | Download URL as markdown into `kb/docs/` |
| `/kb search "auth" in docs` | Search `kb/docs/` for the pattern |

When the intent is ambiguous, ask the user which directory to use.

## Summarize Session

When the user says `/kb summarize session`, `/kb ss`, or `/kb 总结 session`, create a session summary file in `kb/sessions/` following the instructions in [summarize-session](references/summarize-session.md).

The session file must also include the standard frontmatter with `created` date and `tags`.

## Todos Format

Files in `kb/todos/` use Markdown checkbox lists:

```markdown
- [x] todo item 1
- [ ] todo item 2
- [ ] todo item 3
```

## Workflow

1. Parse the user's intent from the arguments after `/kb`
2. Determine the target directory (plans / sessions / notes / todos / docs)
3. Ensure the directory exists (`mkdir -p`)
4. Determine file content:
   - If the user wants to **move/place** an existing file from context: read it, add frontmatter if missing, write to the target directory
   - If the user wants to **create** new content: gather information from the conversation context, compose the content with proper frontmatter
   - If the user wants to **summarize a session**: follow [summarize-session](references/summarize-session.md) instructions
5. Name the file as `YYYY-MM-DD-<slug>.md`
6. Write the file and confirm the path to the user

## Downloading and Searching Documents

### Download a Document

To save a web page as markdown into `kb/docs/`:

```bash
bash scripts/puremd.sh "<url>" kb/docs/
```

The second argument can be a directory (trailing `/`) or a specific file path. Use a file path when the URL basename doesn't make a good filename:

```bash
# URL basename is fine — saves as kb/docs/route-module.md
bash scripts/puremd.sh "https://reactrouter.com/start/framework/route-module" kb/docs/

# URL basename is not descriptive — specify a better name
bash scripts/puremd.sh "https://example.com/docs/v2/api" kb/docs/example-api-v2.md
```

The script creates the target directory automatically.

### Search Documents

```bash
# basic search
bash scripts/search-docs.sh "<pattern>"

# case-insensitive with more context
bash scripts/search-docs.sh -i -c 5 "<pattern>"

# list matching filenames only
bash scripts/search-docs.sh -l "<pattern>"

# search a subdirectory
bash scripts/search-docs.sh "<pattern>" kb/docs/some-subdir/
```

## Proactive Trigger

Without waiting for the user to say `/kb`, proactively ask the user whether they'd like to save content to `kb/` in these situations:

- A **development plan** has been written or finalized in the conversation → ask: "Want me to save this plan to `kb/plans/`?"
- **Research or investigation** results are ready (e.g. after exploring a codebase, comparing approaches, or summarizing findings) → ask: "Want me to save these findings to `kb/notes/`?"

Keep it lightweight — a single-line question at the end of your response. Don't interrupt the flow or force it if the content is trivial.
