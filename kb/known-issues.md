# Known Issues

> 当前 app 已知、待后续处理的问题：缺陷、简化实现、未验收项、待建流程。只反映最新状态——解决了就删掉条目，经过记到 `kb/sessions/`。

## mole-review：同一次终端读取里，排在 `/` 前面的 Space 会丢失

- 记录：2026-09-23（tmux `send-keys Space Space / d x` 批量发送时发现）
- textual 的非 priority 绑定在焦点控件自己的队列里处理。`/` 是 priority 绑定，会先在 app 队列里同步切走焦点，此时已转发给表格、排在后面处理的 Space 找不到 `space` 绑定，就被丢掉了；同理，输入框在 Focus 事件里全选文本，批量到达的 `/…/` 可能覆盖掉第一个 `/`。
- 人手打字的间隔远大于这个窗口，实际不会触发；`/` 后面紧跟的字母已保证进输入框、不会误触发删除或 whitelist（有回归测试）。暂不处理。

## mole-review：删除是永久删除，不进废纸篓（有意为之）

- 记录：2026-09-23
- 与 mole 自身行为一致，确认框里已写明。如需可撤销，改成移动到 `~/.Trash`，约 5 行改动，在 `delete_path()`。

## mole-review：侧栏比例条颜色写死为深琥珀色，浅色主题下对比度差

- 记录：2026-09-23
- `BAR_STYLE = 'on #5a4a1e'` 是 Rich 样式，拿不到 textual 主题变量；默认深色主题下清晰，从命令面板切到浅色主题时深色文字压在深色条上会发暗。
- 处理方向：在 `watch_theme` 里按 `self.current_theme.dark` 切换两套条色。

## mac-dev-cleanup：cargo 一步撞上构建就整天跳过，不补跑

- 记录：2026-09-29
- 06:00 那一刻若有 cargo 构建持有 target 锁，这一步只打一行「skipped this run」就结束，要等第二天。实现时就这么简化了：共享 target 一天不清理问题不大，加重试反而可能和长时间的 release 构建一直撞。
- 若日志里经常出现 skipped，再改成隔几分钟重试几次。

## mac-dev-cleanup：cargo 一步只清共享 target，不管项目自带的 target/

- 记录：2026-09-29
- 只清 `~/.cargo/config.toml` 里 `build.target-dir` 指向的那个目录。项目用 `.cargo/config.toml` 改回本地 `target/` 的不在范围内。要覆盖它们，可以用 cargo-sweep 的 `-r` 扫 `~/Code`，但那会逐个跑 `cargo metadata`，更慢，也更容易误伤。

## com.reorx.mac-dev-cleanup.plist 注释里有 `--`，严格 XML 解析器读不了

- 记录：2026-09-29（早就存在，这次才发现）
- 注释里引用的 shebang `uv run --script` 含 `--`，XML 规范不允许注释里出现它。launchd 和 plutil 能容忍，所以任务一直正常；Python 的 `plistlib`（expat）会直接报错，launchd-list 靠 plutil 兜底才读得出来。想彻底消除，就把注释里的 `--script` 改写掉。
