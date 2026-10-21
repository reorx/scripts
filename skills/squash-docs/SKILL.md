---
name: squash-docs
description: >-
  Squash runs of consecutive docs commits (or any commits whose subject matches a regex) on the
  current git branch into single commits, keeping every tree, merge, author/date and the full
  original messages. Previews by default; --apply rewrites only the current branch, atomically,
  behind a backup ref. Use only when the user explicitly invokes squash-docs.
disable-model-invocation: true
---

# squash-docs

`scripts/squash-docs.ts` folds every linear run of two or more matching commits into one commit. It builds the new commit objects straight from the original trees: nothing is checked out, no rebase or merge runs, and conflict resolutions inside merges are reused byte for byte.

Requires Node >= 22.18 (runs TypeScript natively) and Git >= 2.38. No dependencies. Output is in Chinese.

## Workflow

1. **Preview** (read-only, the default):
   ```bash
   node scripts/squash-docs.ts --repo <repo>          # the 50 most recent commits, topological order
   node scripts/squash-docs.ts --repo <repo> --all    # all history reachable from HEAD
   ```
2. **Summarize the preview for the user**: the groups and their new subjects, `提交数 A → B`, `改写范围` (how many commits get new hashes), and every `注意` line — they say how many of those commits are already on a remote or still referenced by other branches or tags.
3. **Tune and preview again** if the groups are wrong (see Options). A common fix is `--files-pattern` so docs commits that also touched code stay separate.
4. **Apply only after the user explicitly confirms.** Rerun the exact same arguments plus `--apply`. If the preview showed `已推送到远程`, make sure the user knows the branch will need a force push before asking.
5. **Report** the printed `备份引用`, `校验报告` and `撤销` lines. Never push on your own; if the user wants to push rewritten published history, use `git push --force-with-lease` and only after they ask.

## Options

| Option | Meaning |
| --- | --- |
| `--repo <path>` | Repository or any directory inside it; default is the current directory |
| `--count <n>` | Window of the n most recent commits in topological order (default 50). Runs never extend past the window |
| `--all` | All history reachable from HEAD; mutually exclusive with `--count` |
| `--pattern <regex>` | JavaScript regex tested against the subject line only. Default `^docs(?:\([^)]*\))?:` matches `docs:` and `docs(scope):` |
| `--files-pattern <regex>` | Every changed path of a commit must match (example below). Empty commits still match |
| `--title <template>` | Subject of a squashed commit; `{files}` becomes the sorted, deduplicated changed paths. Default `update docs for {files}`; set it whenever `--pattern` is not about docs |
| `--apply` | Rewrite history; without it the script only previews |

Keep docs commits that also touched code out of the squash, and other commit types:

```bash
node scripts/squash-docs.ts --files-pattern '(?:\.md$|^kb/)'
node scripts/squash-docs.ts --pattern '^chore(?:\([^)]*\))?:' --title 'chore: tidy {files}'
node scripts/squash-docs.ts --pattern '^wip\b' --title 'wip'
```

## What gets squashed

- Only linear runs of two or more matching commits. Merge commits and fork points (commits with more than one child inside the window) always stay on their own, so merge topology and parent order are preserved.
- A squashed commit takes its subject from `--title`, its body from all original messages joined by blank lines, its author and committer (with dates) from the first commit of the run, and its tree from the last.
- Rewritten commits lose `gpgsig` / `mergetag` headers because those signatures would be invalid. Commits before the first squashed group keep their hashes and signatures.
- A run containing a non-UTF-8 message is refused rather than re-encoded.

## Preconditions for `--apply`

The script refuses, without touching any ref, unless: HEAD is on a branch (not detached), the worktree is clean including untracked files, no rebase / merge / cherry-pick / revert is in progress, the clone is complete (not shallow), and there are no replace refs or grafts. Ask the user to commit or stash; don't stash for them unasked.

## After applying

- Only the current branch moves. Other branches, tags and remote-tracking refs keep pointing at the old commits.
- Undo with the printed `git reset --keep refs/squash-docs-backup/<id>`. It is only right while the branch has no new commits since the squash; after that, rebase the new commits onto the backup instead.
- Backups accumulate and keep old objects alive. List them with `git for-each-ref refs/squash-docs-backup/`; once the user is satisfied, delete one with `git update-ref -d <ref>`.
- The JSON report in `$(git rev-parse --git-path squash-docs)/<id>.json` maps each original commit hash to its rewritten one.
