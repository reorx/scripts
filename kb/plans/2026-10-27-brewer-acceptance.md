---
created: 2026-10-27
tags:
  - homebrew
  - acceptance
---

# brewer 实机验收 brief

- 执行者：Codex（Astra），由 Claude 委派。Claude 写了这份 brief 和 brewer 的实现；PRD 里的产品决定已经由用户确认。
- 目录：`/Users/reorx/Code/scripts`，master 分支。这是和 Claude 共用的工作区，`brewer.py`、`test_brewer.py`、两份 plan 还没有提交。
- 开始前先读：`kb/plans/2026-10-27-brewer.md`（PRD + Tech Design）、`brewer.py`、`test_brewer.py`、`AGENTS.md`。

## 目标

在真实终端和真实 Homebrew 数据上验证 brewer 的终端流程和 TUI 交互，**不升级任何 formula**。单元测试已经覆盖了逻辑（用假 brew），这次要看的是单元测试看不到的东西：TUI 在真终端里的渲染和按键、TUI 退出后终端输出能不能接上、非交互模式、真实版本号的分级结果是否合理。

## 完成标准

`tmp/2026-10-27-brewer/acceptance-report.md` 存在，并且：

- 逐条列出 PRD「验收标准」，每条写明 通过 / 不通过 / 本次未验（以及原因），附上证据文件名；
- 每个 TUI 场景都有 `tmux capture-pane` 抓下来的文本，存在同一目录（建议 `NN-<场景>.txt`）；
- 发现的问题写明复现步骤、预期和实际表现。

## 已经定下的决定（不要重新讨论）

| 问题 | 决定 | 谁定的 |
|---|---|---|
| 扫描范围 | 只看手动安装过的 formula（installed on request），不看 cask | 用户 |
| 白名单写入时机 | TUI 按回车时立即写入 | 用户 |
| brew 连带升级 | 不阻止，汇总里列为 "Also upgraded by Homebrew" | 用户 |
| 版本分级 | 看第一个不同的段：第 1 段为 major，第 2 段为 minor，其余为 patch；0.x 不特殊处理 | Claude（已写进 PRD，用户已确认） |
| 输出语言 | 终端和 TUI 的文案用英文，和仓库里其他脚本一致 | Claude |

如果你认为哪条决定有问题，写进报告的「意见」一节，不要直接改代码。

## 范围

1. **单元测试**：`uv run test_brewer.py` 全部通过。
2. **outdated**：`uv run brewer.py outdated --no-update --whitelist <临时白名单>`。检查 Major/Minor 分组是否合理，对几个真实的边界版本号（tap formula、`RELEASE.` 前缀、`3.5a` 这类带字母后缀的、只改 revision 的）逐一核对分级；白名单里的项要带 `whitelist` 标记，最后一行的计数要对。
3. **TUI 主流程**：在 tmux 里开一个 160x45 的会话，运行 `uv run brewer.py upgrade --dry-run --no-update --whitelist <临时白名单>`。临时白名单里放两三个本机有 patch 更新的 formula（比如 `watch`、`zsh`，先用 outdated 确认它们确实过时）。依次验证：
   - 白名单项先在终端里出现 `[1/N] …` 和 `would run: brew upgrade --formula …`，然后才进入 TUI；
   - TUI 的列、级别颜色、顶部状态行、底部按键提示，长描述会被截断；
   - ↑/↓、j/k 移动光标；空格勾选和取消；d 标记白名单并自动勾选升级；对带白名单标记的项按空格，两个标记一起去掉；再按一次 d 只去掉白名单标记；状态行的计数随之变化；
   - 回车后回到终端，打印 Selected / Would whitelist，再逐个打印 would run，最后是 Summary（各个 "Would …" 分组和最后一行计数）；
   - dry-run 结束后，临时白名单文件和运行前完全一样。
4. **取消**：再跑一次，在 TUI 里按 q，终端里应出现 "Review cancelled"；再试一次 Esc。
5. **窄终端**：把 tmux 窗口调到 100x30 再打开 TUI，看列表能不能用（横向滚动或截断都可以，但不能乱掉）。
6. **非交互**：`uv run brewer.py upgrade --dry-run --no-update --whitelist <临时白名单> < /dev/null | cat`，不进 TUI，需要确认的项以列表形式打印出来。
7. **whitelist 子命令**：用一个临时白名单文件，先手写几行注释和条目，然后跑 list / add（包括一个纯依赖 formula，比如 `libpng`，应该出现警告）/ rm（包括一个不存在的名字），检查注释是否保留、输出是否和 PRD 描述一致。

## 不在范围内

- 修改 `brewer.py` 或测试。发现 bug 只记进报告，由 Claude 修。
- 性能测量、cask。

## 怎么做，以及绝对不能做的事

- **绝不运行不带 `--dry-run` 的 `brewer upgrade`，也不直接跑 `brew upgrade`。** 这台机器是用户的日常环境，升级一个 formula 可能连带升级一串依赖，没法撤回。
- **一律加 `--no-update`，不跑 `brew update`**：没必要，而且会改动本机的 tap 状态。
- **一律用 `--whitelist tmp/2026-10-27-brewer/<文件>`，不碰 `~/.config/brewer/whitelist`**：那是用户真实的白名单。
- **在 TUI 里不要按 `o`**：它会在用户的默认浏览器里打开网页。这个功能单元测试已经覆盖了。
- 用 tmux 驱动 TUI：`tmux new-session -d -s brewer-accept -x 160 -y 45`，`send-keys` 发按键，每个关键状态都 `capture-pane -p` 存成文本（需要看颜色时加 `-e`）。用到的 tmux 会话结束前全部 kill 掉，不要留下后台进程。

## 约束

- 只能在 `tmp/2026-10-27-brewer/` 下新建文件，别的目录不要改。
- 不要 commit、push 或 merge。`AGENTS.md`、`kb/` 下的文件由 Claude 在验收后统一更新，你不要动。

## 完成后

- 留下 `tmp/2026-10-27-brewer/acceptance-report.md` 和各场景的抓屏文本；
- 回复里给出报告路径，用一两句话说结论：有没有不通过的项，有哪些意见。
