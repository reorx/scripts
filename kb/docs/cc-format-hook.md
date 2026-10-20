---
created: 2026-10-17
updated: 2026-10-20
tags:
  - codex
  - claude-code
  - hooks
  - formatting
---

# cc-format 的 agent hook 模式

Claude Code 和 Codex 的全局 PostToolUse hook 用同一条命令 `cc-format --hook`，matcher 都是 `Edit|MultiEdit|Write`：

- Claude Code：`~/.claude/settings.json`，软链到 iCloud 的 `zack-fair/share/settings.json`，编辑时要写软链目标。
- Codex：`~/.codex/hooks.json`。Codex 把 `apply_patch` 当作 `Edit`/`Write` 来匹配，事件里的 `tool_name` 仍是 `apply_patch`。

`--hook` 从 stdin 读事件，按 `tool_name` 分两路：

- **Claude Code**（Edit/MultiEdit/Write）：取 `tool_input.file_path`，扩展名是 `.py/.ts/.tsx/.js` 就 `exec cc-format <path>`，输出和退出码原样透传，行为等同于原来那条内联 jq 命令。
- **Codex**（`apply_patch`）：`tool_input.command` 是 patch 原文。先进入事件的 `cwd`，取 `Add File` / `Update File` / `Move to` 行的路径（容忍首尾空白，去重），按扩展名和文件是否存在过滤。移走的旧路径、删除的文件因此自然被跳过。然后逐个格式化，**始终 exit 0**，结果通过 stdout 的 JSON 回报：
  - 文件内容有变化：`additionalContext` 列出这些文件，提示模型先重读。
  - 格式化失败：错误写进 `additionalContext`，同时给 `systemMessage`。

## 为什么 Codex 要额外回报

2026-10-19 用 Codex 0.163.0 实测：

- Claude Code 的 harness 会自动告诉模型 "PostToolUse hook modified … (likely a formatter)"，Codex 不会。模型下一个 patch 照旧内容写 context 就会失败，例如 ruff 把双引号改成单引号之后。
- Codex 对 PostToolUse 的 exit 2 会用 stderr **替换**工具结果，模型看到的是 `Script failed`，而文件其实已经写入了。code mode 里 promise 还会 reject，同一脚本后面的步骤不再执行。Claude Code 则保留工具结果，只在后面追加 hook 错误。ruff 遇到语法错误就是 exit 2，而分几次 patch 改文件时中间状态有语法错误很常见。
- 这台机器上 Codex 的编辑全部走 code mode：`exec` 里的 JS 调 `tools.apply_patch(...)`，嵌套调用照常触发 hook。patch 校验失败（`Failed to find expected lines`）时不触发。

两边都只覆盖编辑工具，用 shell 写文件（Claude 的 Bash、Codex 的 `exec_command`）都不会触发。

## 启用

hooks.json 里的命令一改，hash 就会变，Codex 会跳过这个 hook，直到在 Codex CLI 的 `/hooks` 里重新审阅并 trust。改 cc-format 本身不需要重新 trust，这也意味着 trust 审查覆盖不到 cc-format 的改动。

## 测试与验收

- `./test-cc-format.sh`：hook 模式的行为测试，用真实的 ruff/biome。覆盖 Claude 事件、Codex 多文件 patch（新增、修改、移动、删除、带空格路径、绝对路径）、格式化失败和开关关闭。cc-format 被 toggle 关闭时测试会直接退出。
- 格式化器选择（prettier/biome 配置检测）的测试在 `tmp/cc-format-test/test.sh`，未入库。
- 2026-10-20 的 Codex 端到端验收：用 `codex exec --dangerously-bypass-hook-trust` 跑真实会话，验证了三点：新建后再修改同一文件能成功；有语法错误的文件不再让 patch 显示为失败；同一脚本里后面的 patch 继续执行。输出在 `tmp/2026-10-20-cc-format-hook/`。

2026-10-17 曾用 `codex-cc-format.py` 做适配：把 patch 转成伪造的 Claude 事件，再跑 Claude 原命令。它保证的只是命令字符串一致，上面两条行为差异都没处理，2026-10-20 被本模式替换。
