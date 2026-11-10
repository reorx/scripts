---
created: 2026-11-10
tags:
  - cc-probe
  - claude-code
  - token-usage
---

# cc-probe 增加交互模式抓包（`--interactive`）

- **执行者**：在 herdr 新 tab 里启动的 Claude Code agent。
- **工作目录**：`~/Code/scripts`，当前分支。不开新分支，不用 worktree。
- **任务说明的作者**：dotfiles 仓库那个 session 里的 Claude。需求来自用户：“给 cc-probe 做改动”，让它能抓交互模式的请求。下面的决定大多是我（作者）做的，用户没有逐条确认。你如果有更好的做法，可以在总结里提出来。
- **开始前先读**：
  - `AGENTS.md` 的 “Claude Code request probe” 一节；
  - `cc-probe.py` 和 `test_cc_probe.py`；
  - 参考实现 `/Users/reorx/Code/dotfiles/tmp/2026-11-10-system-tools/interactive_capture.py`：一个已经跑通的临时脚本，用 pty 抓交互模式的请求；
  - `/Users/reorx/Code/dotfiles/kb/notes/2026-11-03-claude-code-lean-settings-plan.md` 第 8 节：这次调研的结论和实测数字。

## 背景

`cc-probe` 现在只跑 `claude -p`，但有些工具只在交互模式下才会发出，比如 AskUserQuestion 和 SendFeedback。用户平时看的是交互 session 里 `/context` 的数字，所以用 `-p` 抓包得到的结论和用户看到的对不上。

今天在 dotfiles 里用一个临时脚本抓过交互模式的请求，方法已经验证可行。现在要把这个能力做进 `cc-probe`。

## 目标

`cc-probe --interactive` 在 pty 里启动交互式的 claude，或者 `--via` 指定的 zsh 命令；向它输入一句话，抓到第一个主模型请求后结束进程。之后的流程和现有的 `-p` 模式一样：生成报告、`--count`、`--save`、`diff`、`--expect-*`、`--max-tokens` 都照常可用。

## 完成标准

1. `uv run test_cc_probe.py` 全部通过，其中包括新写的交互模式行为测试。这些测试用假 claude，不依赖真实的 claude。
2. 用真实的 claude 跑下面几条命令（Claude Code 2.1.321，用户当前的配置），每条都 exit 0：
   ```sh
   cc-probe --interactive --via cl --no-mcp --expect-present AskUserQuestion \
     --expect-absent SendFeedback --expect-absent Workflow --expect-absent ScheduleWakeup
   cc-probe --interactive --via 'with-loop cl' --no-mcp --expect-present ScheduleWakeup
   cc-probe --interactive --no-mcp --expect-present Workflow --expect-present Artifact
   ```
   最后一条是直接运行 `claude`，这时 Artifact 和 Workflow 都应该在。如果 Artifact 不在，先查清是交互模式默认就不带，还是被别的配置关掉了，在总结里写明结论，不要直接改断言。
3. `cc-probe --interactive --via cl --no-mcp --count exact --kind 'tool*' --all` 列出的工具 tokens 加起来约等于 7,083，和第 8 节的实测一致，误差在几十以内。下面这些工具的数字也要对得上：AskUserQuestion 1,766、Agent 1,590、Bash 894、Read 712。
4. 跑完之后没有残留：
   - `pgrep -fl claude` 里没有本工具启动的 claude 进程，MCP 子进程也算在内；
   - `~/.claude/projects/` 下没有新增的 session 文件。如果交互模式会留下 session 文件，就只删本次抓包对应的那一个（按请求 `metadata` 里的 session_id 确认），并在总结里说明。

## 已经做出的决定

| 问题 | 决定 | 谁定的 | 原因 / 影响 |
|---|---|---|---|
| 选项名 | `--interactive` | 作者 | 可以在总结里提别的名字 |
| 取哪个请求 | 第一个带 `system` 的 `/v1/messages` 请求，**不是**工具最多的那个 | 作者，已实测 | 假 API 回 400 时，Claude Code 重试 3 次后会关掉 tool search，把全部 29 个工具完整重发（约 34k）。取最大的那个会得到错误的结论 |
| 抓到之后 | 立刻结束 claude，不等它重试 | 作者 | 少等一会儿，也少发几个请求 |
| pty 实现 | 只用标准库（`pty`、`select`、`os`） | 仓库规则 | `AGENTS.md` 要求优先用标准库 |
| 结束进程 | 结束整个进程组：先 SIGTERM，再 SIGKILL | 作者 | claude 会拉起 MCP、hook 等子进程。只杀 claude 本身，子进程会残留 |
| `CLAUDE_CODE_ARTIFACT=1` | 交互模式**不**注入 | 作者，待你验证 | 这个变量是为了让 `-p` 模式和交互模式一致才加的，交互模式本身应该不需要。按完成标准第 2 条验证 |
| `-p` 专用参数 | 交互模式不传 `-p` 和 `--no-session-persistence` | 作者 | 这两个只在 `-p` 下有意义。有没有残留 session 文件，按完成标准第 4 条检查 |
| 输入的方式 | 先等 TUI 启动，再输入 `say ok`，隔约 1 秒后单独发 `\r` | 参考脚本实测 | 文字和回车一起发可能不会提交。用户开了 vim 编辑模式，启动时默认在 insert 模式。不要只靠固定的 sleep：轮询假 API 有没有收到请求，再加一个总超时（沿用 `--timeout`） |

## 范围

- `cc-probe.py`：
  - 新增 `--interactive`；
  - 抓包时，假 API、去掉 `HERDR_*`、`--via`、`--settings` 合并、`--no-mcp`、`--no-hooks` 这些已有逻辑都沿用，不要另写一套；
  - 在报告的头部注明这次是交互模式抓的。
- 解析：交互模式请求的结构可能和 `-p` 模式不同。参考脚本看到的 `messages` 是 `user` 加 `role: system` 两条。要确认现有解析能正确分类，不能出现一大块没有归类的内容。需要改的话，同时更新 `test_cc_probe.py` 里假 claude 生成的请求结构。
- 计数：
  - 单独给 deferred 占位工具（`DeferredToolPlaceholder`）调 `count_tokens` 会返回 400；
  - 现有的 `exact` 模式是逐项去掉后计数，参考脚本里这种做法对每个工具都成功了，但要确认不会因为某一项 400 就让整次计数失败。
- `test_cc_probe.py`：先写行为测试。假 claude 在没有 `-p` 时，要从 tty 读到回车后才发请求，并且至少连续发两个请求（第一个带 deferred，后一个是完整工具的“回退”请求），用来验证取的是第一个。
- `AGENTS.md`：只更新 “Claude Code request probe” 一节，补一两句交互模式的说明和坑。

## 不在范围内

- 不重构现有 `-p` 路径的逻辑。改到共用函数时，`-p` 模式的现有测试要全部继续通过。
- 不改 dotfiles 仓库，不改 `~/.claude/settings.json`，不改 `~/.zshrc_fn`。
- 不加第三方依赖。
- 发现的其他问题（比如 `-p` 模式解析不准）记到总结的“遗留问题”里，不要顺手修。

## 怎么做

- 先写测试（BDD）：先写交互模式的行为测试，跑一遍确认失败，再实现。
- 用真实 claude 验证时，**一定**要确认 `ANTHROPIC_BASE_URL` 指向本地假 API，不能发出真实的模型请求。
- 一定要去掉 `HERDR_*` 环境变量：你自己就在 herdr pane 里运行，不去掉的话，被抓包的 claude 会通过 hook 改掉 pane 的 agent 状态。
- 凭证规则和现在一样：只用于 `count_tokens`，只在凭证是 `sk-ant-` 开头时使用，不打印，不写到磁盘上。`--save` 要去掉 `metadata`。
- 临时文件放在 `tmp/`，或者用 Python 的 `tempfile`。

## 约束

- 只改 `cc-probe.py`、`test_cc_probe.py`、`AGENTS.md`（只改上面说的那一节），再新建总结文件。
- 在当前分支上提交，`git add` 时只加你改过的文件，不 push。
- `kb/next-up.md`、`kb/todo.md` 不要动。

## 完成后

- 把总结写到 `kb/sessions/2026-11-10-cc-probe-interactive.md`，格式参照同目录下已有的文件。内容包括：
  - 测试结果；
  - 完成标准第 2、3 条的真实输出（贴关键几行）；
  - 你自己做的决定、和本说明不一致的地方；
  - 遗留问题。
- 提交后在终端里简短回复：完成了什么、commit hash、总结文件路径。
