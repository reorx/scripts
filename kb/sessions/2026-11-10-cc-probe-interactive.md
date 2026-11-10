---
created: 2026-11-10
tags:
  - cc-probe
  - claude-code
  - token-usage
---

# cc-probe 增加交互模式抓包（`--interactive`）

## 概要

按 [任务说明](../plans/2026-11-10-cc-probe-interactive.md) 给 `cc-probe` 加了 `--interactive`。它在 pty 里启动交互式的 claude（或 `--via` 指定的命令），等 TUI 画完后输入 `say ok`，隔一会儿单独发回车，抓到第一个带 `system` 的请求后立刻结束整个进程组。之后报告、`--count`、`--save`、`diff`、`--expect-*`、`--max-tokens` 都和 `-p` 模式共用。完成标准 1 到 4 全部满足。

## 修改的文件

- `cc-probe.py`：
  - 新增 `--interactive`、`Terminal`（pty 加进程组）、`wait_for_prompt`、`run_interactive`；
  - `claude_args`、`child_env`、`capture` 加了交互分支，`-p` 分支的行为不变；
  - `--count exact` 拆出 `count_each`：某一项 count_tokens 失败时只估算这一项，另外加一个 `tool-preamble` 项；
  - 报告头部和 `meta` 标明交互模式。
- `test_cc_probe.py`：
  - 假 claude 在没有 `-p` 时模拟 2.1.321 的 TUI；
  - 新增 9 个交互模式测试和 2 个计数测试；
  - 假 count_tokens 在请求带工具时加 300 tokens 的固定前言，也可以对指定请求回 400。
- `AGENTS.md`：在 “Claude Code request probe” 一节加了一条，说明交互模式和几个坑。

## 测试结果

- 先写测试：新加的 11 个测试全部失败，原有 24 个通过。
- 实现后，`uv run test_cc_probe.py` 35 个测试全部通过（约 54 秒，其中 9 个交互模式测试约 23 秒）。`TestInteractive` 又单独连跑 3 次，都通过，没有时序抖动。

## 完成标准 2：真实 claude（2.1.321）

三条命令都 exit 0：

```
$ cc-probe --interactive --via cl --no-mcp --expect-present AskUserQuestion \
    --expect-absent SendFeedback --expect-absent Workflow --expect-absent ScheduleWakeup
cc-probe · Claude Code 2.1.321 (cli) · interactive · via `cl` · ~/Code/scripts
Total  24,818 tokens [count_tokens] · 68,089 chars · 8 tools in full, 17 deferred · 35 skills · 10 agents
  Artifact            off
    1,942    5,327  tool              AskUserQuestion

$ cc-probe --interactive --via 'with-loop cl' --no-mcp --expect-present ScheduleWakeup
cc-probe · Claude Code 2.1.321 (cli) · interactive · via `with-loop cl` · ~/Code/scripts
Total  26,513 tokens [count_tokens] · 72,756 chars · 9 tools in full, 17 deferred · 35 skills · 10 agents
    1,701    4,667  tool              ScheduleWakeup

$ cc-probe --interactive --no-mcp --expect-present Workflow --expect-present Artifact
cc-probe · Claude Code 2.1.321 (cli) · interactive · claude · ~/Code/scripts
Total  46,568 tokens [count_tokens] · 133,346 chars · 13 tools in full, 19 deferred · 54 skills · 10 agents
  Artifact            on
    1,887    5,403  tool              Workflow
```

直接运行 `claude` 时，Artifact 不靠 `CLAUDE_CODE_ARTIFACT=1` 也在，说明交互模式默认就带 Artifact，不注入这个变量的决定是对的。

## 完成标准 3：工具的 tokens

```
$ cc-probe --interactive --via cl --no-mcp --count exact --kind 'tool*' --all
Total  24,818 tokens [count_tokens (per item)] · 68,089 chars · 8 tools in full, 17 deferred · 35 skills · 10 agents
All items
   tokens    chars  kind              name
    1,766    5,327  tool              AskUserQuestion
    1,590    4,783  tool              Agent
      894    2,565  tool              Bash
      712    1,965  tool              Read
      623    1,826  tool              Skill
      535    1,466  tool              ToolSearch
      348    1,001  tool              Edit
      286        0  tool-preamble     (tool use system prompt)
      236      663  tool              Write
       93      214  tool              DeferredToolPlaceholder
```

合计 7,083，和第 8 节完全一致。AskUserQuestion、Agent、Bash、Read 也逐个对得上。没有哪一项 count_tokens 失败：去掉 `DeferredToolPlaceholder` 后计数是成功的，单独给它计数的情况在这里不会出现。

## 完成标准 4：残留

每次真实运行前后都用 `tmp/residue.py` 对比了 `~/.claude/projects/` 的文件、`~/.claude/sessions/`、`history.jsonl` 的行数，以及命令行含 claude 或 mcp 的进程。上面 4 条命令，加上一次不带 `--no-mcp` 的运行（context7、shadcn 两个 MCP server 已连上），结果都是：

```
new project files: none
new sessions/ entries: none
new history rows: none
new claude/mcp processes: none
```

所以不需要删 session 文件，也没有写删除的代码。

## 我自己做的决定、和说明不一致的地方

1. **pty 的实现方式和参考脚本不同**：用的是 `pty.openpty()` 加 `subprocess.Popen(start_new_session=True)`，没用 `pty.fork()`。原因是假 API 的线程已经在跑，这时 fork 会触发 Python 3.12 的 `DeprecationWarning`（多线程下 fork 可能死锁）。实测 claude 不需要控制终端也能正常工作。结束进程时对整个进程组先发 SIGTERM，3 秒后再发 SIGKILL，期间一直读 pty，防止子进程写满缓冲区卡住。
   - 坑：macOS 上如果进程组里只剩僵尸进程，`killpg(pgid, 0)` 返回的是 EPERM，不是 ESRCH，所以两种都当作“已经没有进程了”处理。
2. **加了 `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1`**（说明里没有）。用顶层 session 实测：没有它的话，每次抓包都会往 `~/.claude/history.jsonl` 写一行 `say ok`，按上箭头翻历史时会看到。这个变量就是交互模式下对应 `--no-session-persistence` 的开关，源码里它会跳过 history，也会关掉 transcript。session 文件本来就不会生成，因为 claude 在收到回复之前就被结束了。
3. **交互模式去掉 Claude Code 给子进程设置的环境变量**（`CLAUDE_CHILD_ENV`：`CLAUDECODE`、`CLAUDE_CODE_CHILD_SESSION`、`CLAUDE_CODE_SESSION_ID`、`CLAUDE_CODE_ENTRYPOINT`、`CLAUDE_CODE_MESSAGING_*`、`CLAUDE_PID`、`CLAUDE_EFFORT` 等，来自源码里的 `Ypt()`）。这是在 Claude Code 里跑原型时发现的：被抓包的 claude 显示 “Transcript saving is off — inherited CLAUDE_CODE_CHILD_SESSION marker”，也就是它把自己当成了嵌套 session。我对比了三种情况抓到的请求：保留这些变量、去掉它们、去掉之后再加上 SKIP 变量。三次请求逐字节相同。所以这样做不影响结论，只是让抓包的 claude 不连父 session 的 messaging socket，而且不管从终端还是从 Claude Code 里运行，行为都一样。
4. **`--count exact` 多了一个 `tool-preamble` 项，`-p` 模式也会有**。这是满足完成标准 3 必须做的：逐个去掉工具时，每次得到的差值加起来只有 6,797。第 8 节的 7,083 是“有工具”和“完全没有工具”的差，比 6,797 多出约 286 tokens。这部分是只要请求里有工具，API 就会加上的 tool use system prompt，去掉任何一个工具它都还在。现在 exact 模式会多调一次 count_tokens（去掉全部工具），把这部分单独列成一项。`-p` 模式的 exact 报告也因此多了这一项，原有测试不受影响。
5. **exact 模式里某一项计数失败，只估算这一项**，标签显示为 `count_tokens (per item; N estimated: …)`。以前是一项失败就整次退回估算。
6. **加了信任对话框的保护**（说明里没有）。用一个没有信任过的目录实测时，TUI 先弹出 “Yes, I trust this folder” 对话框，原来的流程会把 `say ok` 和回车打进去。回车选中的是默认的 “No, exit”，所以没有授予信任：`~/.claude.json` 里没有新增条目，我核对过。现在检测到这个对话框就以 exit 2 报错，什么都不输入。
   - 坑：TUI 用 `ESC[<列号>G` 定位单词，不输出空格，所以屏幕文本把光标移动当作空格处理。报错时附带的屏幕文本也因此能读。
7. **等待 TUI 的方式**：先等到有输出，再等 1 秒没有新输出（最多 20 秒），然后输入文字，1 秒后发回车；之后轮询假 API，总时长受 `--timeout` 限制。实测 0.4 秒开始有输出，2.5 秒后安静下来，回车后约 0.1 秒请求就到了，整次运行约 7 秒。没有做“重按回车”，因为遇到意外的对话框时，回车可能会选中某个选项。
8. 选项名保留 `--interactive`。

## 研究过程中我自己造成的残留（已清理）

验证 “去掉子进程变量后会不会留 history” 时，原型跑了两次，没带 SKIP 变量，在 `~/.claude/history.jsonl` 末尾留下两行 `say ok`（session `5d9b7050…` 和 `1c3bafef…`）。清理方法：先确认它们正是文件的最后两行，而且 sessionId 对得上，再原地截断文件。这样 inode 不变，其他 session 追加的内容也不受影响。正式实现之后没有再产生这类残留。

## 遗留问题

- **`-p` 模式也会继承 Claude Code 给子进程的环境变量**：从 Claude Code 里运行 cc-probe 时，`-p` 抓包的 claude 会带着 `CLAUDECODE`、`CLAUDE_CODE_CHILD_SESSION`、`CLAUDE_CODE_MESSAGING_SOCKET` 等变量。交互模式已经验证过这些变量不影响请求内容，`-p` 模式没有验证。建议 `-p` 也按 `CLAUDE_CHILD_ENV` 去掉这些变量，这次按范围约定没有改。
- **交互模式依赖 2.1.321 TUI 的几个行为**，升级后可能失效：
  - 400 之后会重试，并把全部工具完整重发；
  - 启动时先发一个不带 `system` 的 `max_tokens: 1` quota 请求；
  - 单词之间用 `ESC[nG` 定位；
  - 信任对话框的文案是 “trust this folder”；
  - `CLAUDE_CODE_SKIP_PROMPT_HISTORY` 的效果。

  如果升级后抓不到请求，先看报错里附带的屏幕文本。
- 同时传 `--headless` 和 `--interactive` 时，`--headless` 会被静默忽略。
- 测试总时长从约 27 秒（原 24 个）增加到约 54 秒。

## 附带的观察

用 `cl`、`--no-mcp`，在本仓库目录下对比：

| | `-p` | 交互模式 |
|---|---:|---:|
| 整个请求（exact） | 22,984 | 24,818 |
| 工具合计（含 tool-preamble 286） | 5,534 | 7,083 |

交互模式多出 AskUserQuestion（1,766）和 claude-code-guide agent；Agent 和 Bash 的描述也比 `-p` 短（1,590 对 1,738，894 对 963）。所以 `-p` 抓包和 `/context` 看到的数字对不上，不只是因为少了几个工具。
