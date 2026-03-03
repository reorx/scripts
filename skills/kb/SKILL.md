---
name: kb
description: >-
  Manage the project's kb/ knowledge base folder. Use this skill when notes, plans, session summaries,
  or todo files are produced during development, or when the user wants to write, organize, or move
  such files into the kb/ directory. Also triggers for /kb summarize session or /kb 总结 session.
---

# KB - Project Knowledge Base

Maintain a `kb/` folder at the project root as the project's evolving knowledge base. The folder has four sub-directories:

| Directory | Purpose |
|-----------|---------|
| `kb/plans/` | Development plans for features or work items, intended for Coding Agents |
| `kb/sessions/` | Session summaries (what was done on a given date) |
| `kb/notes/` | Research findings, ideas, discussion notes |
| `kb/todos/` | Task checklists for a piece of work, using `- [x]` / `- [ ]` syntax |

## Initialization

Before writing any file, ensure the target directory exists. Create it if needed:

```bash
mkdir -p kb/plans kb/sessions kb/notes kb/todos
```

## File Naming Convention

All files follow the pattern:

```
YYYY-MM-DD-<slug>.md
```

- Date is today's date (obtain via `date +%Y-%m-%d`)
- `<slug>` is a short English phrase summarizing the content, words joined by `-`

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

1. **Which directory** the file belongs in (plans, sessions, notes, or todos)
2. **What action** to take — create a new file, move an existing file, or update an existing file

Examples:

| User says | Action |
|-----------|--------|
| `/kb 将调研情况记录到笔记中` | Create a note in `kb/notes/` summarizing the research from context |
| `/kb 将刚才生成的文件放到 plans 下面` | Move/copy the plan file from context into `kb/plans/` |
| `/kb create a todo for the auth feature` | Create a todo checklist in `kb/todos/` |
| `/kb summarize session` or `/kb 总结 session` | Create a session summary in `kb/sessions/` — see below |

When the intent is ambiguous, ask the user which directory to use.

## Summarize Session

When the user says `/kb summarize session` or `/kb 总结 session`, create a session summary file in `kb/sessions/` following the instructions in [summarize-session](references/summarize-session.md).

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
2. Determine the target directory (plans / sessions / notes / todos)
3. Ensure the directory exists (`mkdir -p`)
4. Determine file content:
   - If the user wants to **move/place** an existing file from context: read it, add frontmatter if missing, write to the target directory
   - If the user wants to **create** new content: gather information from the conversation context, compose the content with proper frontmatter
   - If the user wants to **summarize a session**: follow [summarize-session](references/summarize-session.md) instructions
5. Name the file as `YYYY-MM-DD-<slug>.md`
6. Write the file and confirm the path to the user

## Proactive Trigger

Auto-invoke this skill in cases like:

- A **Plan** has been written/finalized in the conversation — offer to save it to `kb/plans/`
- **Research or investigation** results are ready — offer to save as a note in `kb/notes/`
