---
created: 2026-10-27
tags:
  - homebrew
  - acceptance
---

# brewer 第二轮实机验收 brief：卸载标记、详情面板、--no-review

- 执行者：Codex（Astra），由 Claude 委派。Claude 写了这份 brief 和这次的实现；下表里标"用户"的决定已经由用户确认。
- 目录：`/Users/reorx/Code/scripts`，master 分支。这是和 Claude 共用的工作区，`brewer.py`、`test_brewer.py`、plan 的改动还没有提交，不要动它们。
- 开始前先读：`kb/plans/2026-10-27-brewer.md`（PRD 的「确认界面」「汇总」「选项」「出错和边界情况」和末尾新增的验收标准，Tech Design 里卸载、详情面板、`--no-review` 相关的决策）、`brewer.py`、`test_brewer.py`。上一轮验收的报告在 `tmp/2026-10-27-brewer/acceptance-report.md`，可以参考它的形式。

## 目标

在真实终端和真实 Homebrew 数据上，验证这次新加的三项功能和一处修复，**不升级、不卸载任何 formula**。单元测试用假 brew 覆盖了逻辑，这次看的是单元测试看不到的东西：新的一列和红色 ✗ 在真终端里的渲染、警告提示框、详情面板的布局和面板里的按键、`--no-review` 在真 tty 下也不进 TUI。

## 完成标准

`tmp/2026-10-27-brewer-v2/acceptance-report.md` 存在，并且：

- 逐条列出 PRD「验收标准」里**最后 7 条**（从"确认界面里按下回车之后，Homebrew 不再停下来问是否继续升级"开始），每条写明 通过 / 不通过 / 本次未验（以及原因），附证据文件名；
- 每个 TUI 场景都有 `tmux capture-pane` 抓下来的文本，存在同一目录（`NN-<场景>.txt`，看颜色的加 `-e` 另存一份）；
- 发现的问题写明复现步骤、预期和实际表现。

## 已经定下的决定（不要重新讨论）

| 问题 | 决定 | 谁定的 |
|---|---|---|
| 卸载和升级的先后 | 先卸载，再升级选中项 | 用户 |
| 对被别的 formula 依赖的项按 x | 照样标记，弹出警告列出依赖方 | 用户 |
| 详情面板内容 | 名字、级别、版本、完整描述、主页、被哪些已装 formula 依赖；不显示许可证、tap、更新日志 | 用户 |
| 只升级白名单的参数名 | `--no-review` | 用户 |
| 关掉 brew 7 的升级确认提示 | brew 子进程设 `HOMEBREW_NO_ASK=1`（已单独提交 `fd2cc81`） | Claude |
| 没进确认界面时汇总尾行的说法 | `N left to review`（原来是 `not selected`） | Claude |
| 同批卸载的顺序 | 依赖别人的先卸，被依赖的后卸 | Claude |

如果你认为哪条决定有问题，写进报告的「意见」一节，不要改代码。

## 范围

1. **单元测试**：`uv run test_brewer.py` 全部通过（78 个）。
2. **TUI 卸载标记**：tmux 开 160x45 的会话，跑 `uv run brewer.py upgrade --dry-run --no-update --whitelist tmp/2026-10-27-brewer-v2/whitelist`（临时白名单里放一两个本机有 patch 更新的 formula，先用 `outdated --no-update` 确认）。验证：
   - 列表多了 `Rm` 一列，按 x 出现红色 ✗，顶部状态行的 `N to uninstall` 跟着变；
   - 对已有 ✓ 或 ★ 的行按 x，✓ ★ 消失；对 ✗ 的行按空格或 d，✗ 消失；再按 x 取消；
   - 对 `ghostscript`（本机被 `imagemagick` 依赖）按 x：出现警告提示框，写明被 imagemagick 依赖，行上照样有 ✗。如果 `imagemagick` 也在列表里，先给它标 ✗ 再标 ghostscript，应当不再提示。
3. **详情面板**：
   - 对 `peterldowns/tap/localias`（描述 91 字符，列表里被截断）按 i：面板里是完整描述、主页、`Required by none`；面板底部有按键提示；
   - 对 `ghostscript` 按 i：`Required by` 写着 imagemagick；
   - 面板打开时按空格、d、x、回车都不起作用（关掉面板后这一行的标记没变、TUI 没退出）；i、Esc、q 各自都能关掉面板，q 关的是面板，不是整个 TUI；
   - **不要按 o**。
4. **回车之后**：标几项 ✗、几项 ✓、一项 ★ 后回车。终端里依次出现 `Would whitelist` / `To uninstall` / `Selected`，`Uninstalling (N)` 阶段的 `would run: brew uninstall --formula …` 在升级的 `would run` 之前；Summary 里有 `Would uninstall` 一组；尾行的 not selected 计数不含卸载的项。
5. **窄终端**：100x30 下打开 TUI 和详情面板，三列标记和面板都不能乱。
6. **`--no-review`**：在 tmux 里（真 tty）跑 `uv run brewer.py upgrade --no-review --dry-run --no-update --whitelist tmp/2026-10-27-brewer-v2/whitelist`：不进 TUI，打印 `Needs review (N), skipped: --no-review` 和列表，白名单项照常 `would run`，尾行是 `N left to review`。
7. **非交互**：同样的命令去掉 `--no-review`，加 `< /dev/null | cat`：打印 `skipped: not a terminal`，尾行是 `left to review`。

## 不在范围内

- 修改 `brewer.py` 或测试。发现 bug 只记进报告，由 Claude 修。
- `HOMEBREW_NO_ASK` 的真实效果：只有真升级才会出现提示，这里不能跑；单元测试和 brew 源码已经确认过，报告里这条写"本次未验"即可。

## 怎么做，以及绝对不能做的事

- **绝不运行不带 `--dry-run` 的 `brewer upgrade`，也不直接跑 `brew upgrade` 或 `brew uninstall`。** 这台机器是用户的日常环境，升级可能连带一串依赖，卸载会删掉用户的工具，都没法撤回。
- **一律加 `--no-update`**，不跑 `brew update`。
- **一律用 `--whitelist tmp/2026-10-27-brewer-v2/<文件>`**，不碰 `~/.config/brewer/whitelist`。每次 dry-run 前后对比一下临时白名单文件，应当不变。
- **TUI 和详情面板里都不要按 `o`**：它会在用户的默认浏览器里打开网页。
- tmux 会话名用 `brewer-accept-v2`，结束前 kill 掉，不留后台进程。环境里如果有 `NO_COLOR`，看颜色时用 `env -u NO_COLOR` 跑。

## 约束

- 只能在 `tmp/2026-10-27-brewer-v2/` 下新建文件，别的目录不要改。
- 不要 commit、push 或 merge。`AGENTS.md`、`kb/` 由 Claude 在验收后统一更新。

## 完成后

- 留下 `tmp/2026-10-27-brewer-v2/acceptance-report.md` 和各场景的抓屏文本；
- 回复里给出报告路径，用一两句话说结论：有没有不通过的项，有哪些意见。
