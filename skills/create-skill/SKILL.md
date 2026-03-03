---
name: create-skill
description: This is the skill to create skills. Use when user want to create a new skill. 中文语境下，当用户需要创建一个新技能时，使用这个技能。
---

Create an agent skill based on what user describes. If no input, ask user to provide information about the skill to create.

The skill directory should be created under the skills/ dir of the current project.

## Directory structure

A skill is a directory containing at minimum a `SKILL.md` file:

```
skill-name/
└── SKILL.md          # Required
```

Tip: You can optionally include additional directories such as `scripts/`, `references/`, and `assets/` to support your skill.

## SKILL.md format

The `SKILL.md` file must contain YAML frontmatter followed by Markdown content.

### Frontmatter (required)

```yaml
---
name: skill-name
description: A description of what this skill does and when to use it.
---
```

With optional fields:

```yaml
---
name: pdf-processing
description: Extract text and tables from PDF files, fill forms, merge documents.
license: Apache-2.0
metadata:
  author: example-org
  version: "1.0"
---
```

| Field           | Required | Constraints                                                                                                       |
| --------------- | -------- | ----------------------------------------------------------------------------------------------------------------- |
| `name`          | Yes      | Max 64 characters. Lowercase letters, numbers, and hyphens only. Must not start or end with a hyphen.             |
| `description`   | Yes      | Max 1024 characters. Non-empty. Describes what the skill does and when to use it.                                 |
| `license`       | No       | License name or reference to a bundled license file.                                                              |
| `compatibility` | No       | Max 500 characters. Indicates environment requirements (intended product, system packages, network access, etc.). |
| `metadata`      | No       | Arbitrary key-value mapping for additional metadata.                                                              |
| `allowed-tools` | No       | Space-delimited list of pre-approved tools the skill may use. (Experimental)                                      |


For more detailed explanation of each field, please refer to [specification](references/specification.md).


### Body content

The Markdown body after the frontmatter contains the skill instructions. There are no format restrictions. Write whatever helps agents perform the task effectively.

Recommended sections:

* Step-by-step instructions
* Examples of inputs and outputs
* Common edge cases

Note that the agent will load this entire file once it's decided to activate a skill. Consider splitting longer `SKILL.md` content into referenced files.

## Optional directories

### scripts/

Contains executable code that agents can run. Scripts should:

* Be self-contained or clearly document dependencies
* Include helpful error messages
* Handle edge cases gracefully

Supported languages depend on the agent implementation. Common options include Python, Bash, and JavaScript.

### references/

Contains additional documentation that agents can read when needed:

* `REFERENCE.md` - Detailed technical reference
* `FORMS.md` - Form templates or structured data formats
* Domain-specific files (`finance.md`, `legal.md`, etc.)

Keep individual [reference files](#file-references) focused. Agents load these on demand, so smaller files mean less use of context.

### assets/

Contains static resources:

* Templates (document templates, configuration templates)
* Images (diagrams, examples)
* Data files (lookup tables, schemas)

## Progressive disclosure

Skills should be structured for efficient use of context:

1. **Metadata** (\~100 tokens): The `name` and `description` fields are loaded at startup for all skills
2. **Instructions** (\< 5000 tokens recommended): The full `SKILL.md` body is loaded when the skill is activated
3. **Resources** (as needed): Files (e.g. those in `scripts/`, `references/`, or `assets/`) are loaded only when required

Keep your main `SKILL.md` under 500 lines. Move detailed reference material to separate files.

## File references

When referencing other files in your skill, use relative paths from the skill root:

```markdown
See [the reference guide](references/REFERENCE.md) for details.

Run the extraction script:
scripts/extract.py
```

Keep file references one level deep from `SKILL.md`. Avoid deeply nested reference chains.

## Scripts

Skills can run shell commands or bundle reusable scripts in a `scripts/` directory.

### One-off commands

When an existing package does what you need, reference it directly in `SKILL.md` without a `scripts/` directory. Use runner tools that auto-resolve dependencies:

| Runner   | Ecosystem | Example                              |
| -------- | --------- | ------------------------------------ |
| `uvx`    | Python    | `uvx ruff@0.8.0 check .`            |
| `npx`    | Node.js   | `npx eslint@9 --fix .`              |
| `bunx`   | Bun       | `bunx eslint@9 --fix .`             |
| `go run` | Go        | `go run golang.org/x/tools/cmd/goimports@v0.28.0 .` |

Always pin versions. State prerequisites in `SKILL.md` rather than assuming them.

### Bundled scripts

Use **relative paths from the skill root** to reference scripts. List them in `SKILL.md` so the agent knows they exist:

```markdown
## Available scripts
- **`scripts/validate.sh`** — Validates configuration files
- **`scripts/process.py`** — Processes input data
```

Then instruct the agent to run them:

````
## Workflow

1. Run the validation script:
   ```bash
   bash scripts/validate.sh "$INPUT_FILE"
   ```

2. Process the results:
   ```bash
   python3 scripts/process.py --input results.json
   ```
````

Note: The same relative-path convention works in support files like `references/*.md` — script execution paths (in code blocks) are relative to the **skill directory root**, because the agent runs commands from there.

For self-contained scripts, declare dependencies inline so the agent can run them with a single command:

- **Python** (PEP 723 + `uv run`):
  ```python
  # /// script
  # dependencies = ["beautifulsoup4>=4.12,<5"]
  # ///
  ```
  Run: `uv run scripts/extract.py`

- **Bun** (auto-install via versioned imports):
  ```typescript
  import * as cheerio from "cheerio@1.0.0";
  ```
  Run: `bun run scripts/extract.ts`

### Designing scripts for agents

Key principles — agents run in non-interactive shells and read stdout/stderr to decide next steps:

- **No interactive prompts.** Accept all input via flags, env vars, or stdin. Scripts that block on TTY input will hang.
- **`--help` output.** Include a brief description, available flags, and examples. Keep it concise — it enters the agent's context window.
- **Helpful errors.** Say what went wrong, what was expected, and what to try. Avoid opaque messages like "Error: invalid input".
- **Structured output.** Prefer JSON/CSV over free-form text. Send data to stdout, diagnostics to stderr.
- **Idempotency.** Agents may retry. "Create if not exists" beats "create and fail on duplicate".
- **Safe defaults.** Destructive operations should require explicit flags (`--confirm`, `--force`).
- **Bounded output.** Default to summaries or reasonable limits. Support `--offset` for pagination or `--output FILE` for large results, since agent harnesses may truncate beyond ~10-30K characters.

For the full reference, see [using-scripts](references/using-scripts.md).
