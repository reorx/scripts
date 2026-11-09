# Known Issues

> 当前 app 已知、待后续处理的问题：缺陷、简化实现、未验收项、待建流程。只反映最新状态——解决了就删掉条目，经过记到 `kb/sessions/`。

## brewer：真实升级和卸载的结果判定只在假 brew 上验证过

- 记录：2026-10-27（`kb/plans/2026-10-27-brewer.md`，验收报告 `tmp/2026-10-27-brewer/acceptance-report.md`、`tmp/2026-10-27-brewer-v2/acceptance-report.md`）
- 两轮验收都只用了 `--dry-run --no-update`。用户第一次真实运行时撞上了 brew 7 默认的 `[y/n]` 确认，已修，但那次的汇总没有核对过。升级后重新扫描、连带升级识别、失败和 Ctrl-C 的汇总、回车时写入白名单，以及真实 `brew uninstall`（被依赖时被拒绝、顺带删掉孤立依赖），都只在假 brew 的单元测试里验证过。依据的假设是：brew 升级成功后 `brew outdated` 里不再有这一项，卸载被拒绝时退出码非 0。
- 处理方向：用户下一次真实运行 `brewer upgrade` 时，对照汇总、`brew outdated` 和 `brew list --formula` 核对一遍；没问题就删掉这一条。

## mole-review：同一次终端读取里，排在 `/` 前面的 Space 会丢失

- 记录：2026-09-23（tmux `send-keys Space Space / d x` 批量发送时发现）
- textual 的非 priority 绑定在焦点控件自己的队列里处理。`/` 是 priority 绑定，会先在 app 队列里同步切走焦点，此时已转发给表格、排在后面处理的 Space 找不到 `space` 绑定，就被丢掉了；同理，输入框在 Focus 事件里全选文本，批量到达的 `/…/` 可能覆盖掉第一个 `/`。
- 人手打字的间隔远大于这个窗口，实际不会触发；`/` 后面紧跟的字母已保证进输入框、不会误触发删除或 ignore list（有回归测试）。暂不处理。

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

## mac-dev-cleanup：cargo 一步的「最近使用」其实是「最近一次重编」，常用依赖每 21 天被清掉重编一次

- 记录：2026-10-27（做 uv 一步时发现，复现脚本 `~/Documents/tmp/2026-10-27-uv-cache/cargo_atime_probe.sh`）
- 这台 Mac 上读文件只在 atime < mtime 时才更新 atime。cargo 写完 fingerprint 哈希文件后，第一次空构建会把 atime 推到 mtime 之后，之后再空构建都不会更新（实测三次构建：第二次更新了，第三次没变）。所以 `cargo sweep --time 21` 看到的是重编后第一次构建的时间：每天都在用、但 21 天没重编的依赖也会被清掉，下次构建重编一遍。不会出错，代价是周期性的重编时间。
- 处理方向：想要真正的「最近使用」，得在每次清理后把 atime 重新调到 mtime 之前（「重新上膛」），同时把原来的 atime 另存一份，否则会丢掉上次使用时间；改 mtime 会影响 cargo 的新鲜度判断，不能动。也可以干脆接受，把 `--cargo-days` 调大。先观察重编频率是否真的扰人。

## mac-dev-cleanup：uv 一步碰上刚启动的 uv 就整天跳过；uv 升级换了缓存布局后只在日志里报警

- 记录：2026-10-27
- 和 cargo 一步同样的简化：06:00 那一刻若有 10 分钟内启动、持有缓存锁的 uv 进程（可能正在装包），只打一行「skipped this run」，第二天再来。
- 缓存布局按 uv 0.9.17 写死在 `UV_BUCKETS`。uv 升级后若桶名变了（二进制里找不到某个名字），这一步打 `⚠️` 跳过，但没人看日志的话会一直静默不清理。届时按 SKILL.md「uv step」一节核对新版源码，更新常量。

## mac-dev-cleanup：cargo 一步只清共享 target，不管项目自带的 target/

- 记录：2026-09-29
- 只清 `~/.cargo/config.toml` 里 `build.target-dir` 指向的那个目录。项目用 `.cargo/config.toml` 改回本地 `target/` 的不在范围内。要覆盖它们，可以用 cargo-sweep 的 `-r` 扫 `~/Code`，但那会逐个跑 `cargo metadata`，更慢，也更容易误伤。

## com.reorx.mac-dev-cleanup.plist 注释里有 `--`，严格 XML 解析器读不了

- 记录：2026-09-29（早就存在，这次才发现）
- 注释里引用的 shebang `uv run --script` 含 `--`，XML 规范不允许注释里出现它。launchd 和 plutil 能容忍，所以任务一直正常；Python 的 `plistlib`（expat）会直接报错，launchd-list 靠 plutil 兜底才读得出来。想彻底消除，就把注释里的 `--script` 改写掉。
