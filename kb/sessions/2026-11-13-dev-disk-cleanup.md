---
created: 2026-11-13
tags:
  - disk-cleanup
  - dev-space
  - mac-dev-cleanup
  - lacie
  - codex
---

# 开发目录与全局缓存的清理和监控：建成 dev-space、扩展 mac-dev-cleanup，完成首次真实运行

## 概要

数据卷只剩 7 GiB。用户要求按项目制定清理方案，并把方案固化成脚本，同时监控开发目录和全局缓存，过期标准是一周。不常用、但还需要的东西搬到 LaCie，原处留软链接；入口仍是每天 06:00 的 `mac-dev-cleanup`。

先派 agent 只读调研 7 个项目、全局缓存和 codex 会话，报告在 `tmp/2026-11-13-dev-cleanup/`。然后写了一个总 plan 加三份 spec，实现分三部分：

- ① 新工具 `dev-space`：规则引擎，带不可关闭的安全底线、LaCie 归档和恢复，以及 vibench-live 主库的每日离机备份。
- ② `mac-dev-cleanup` 新增 go、pnpm、npm、codex 四段。uv 改为按引用判断，cargo 加了 7 天上膛。另有 `projects` 和 `watch` 两段，转调 dev-space。
- ③ `dev-space scan/watch`：测量、阈值告警，并为规则覆盖不到的大项目派只读 codex 写规则提案。

用户批准后做了首次真实运行，剩余空间从 7.0 GiB 回到 53.5 GiB。再执行用户批准的一次性清单，又释放 4.3 GiB，最终 56.4 GiB。首次运行暴露了两个问题，都已修复：一是匹配进入了只读的 Go 模块缓存，二是 codex 级联删除被误报为拒绝。

## 修改的文件

- `skills/systools/scripts/dev-space`：新工具（上一次提交）。这次改为匹配时不进入只读目录。
- `skills/systools/scripts/test_dev_space.py`：33 个行为用例。新增用例 `test_read_only_dirs_are_matched_but_never_searched`。
- `skills/systools/config/dev-space.toml`：默认规则和 8 个项目的规则。这次清掉了 vibench `related` 里已不存在的目录（vibench-old、kifix2、mdev-sandbox、p6-scratch、`~/Documents/vibench-backups`）。
- `skills/systools/scripts/mac-dev-cleanup`：新增 go、pnpm、npm、codex 四段，以及 `projects`、`watch` 两段，uv 和 cargo 改造。这次把 codex 删除循环抽成 `delete_codex_threads`：rollout 已不在的拒绝计为已删。selftest 加了两条检查。
- `skills/systools/references/dev-space-analysis.md`：派给 codex、也给人工 agent 用的分析提示词。
- `skills/systools/SKILL.md`：新增 dev-space 一节，更新 mac-dev-cleanup 各段说明。这次补充了 codex 级联删除的说明。
- `AGENTS.md`：新增 Dev disk cleanup 条目。
- `kb/plans/2026-11-13-dev-disk-cleanup.md`：总 plan。这次勾选完成的步骤，新增「首次真实运行」一节。
- `kb/plans/2026-11-13-dev-space-rules-spec.md`、`-global-cache-sections-spec.md`、`-dev-space-watch-spec.md`：三份 spec。这次给规则 spec 补了只读目录剪枝的说明。
- `kb/next-up.md`：删掉已完成的「首次运行后核对」，给 06:00 和一周后两项加上日期。
- `kb/known-issues.md`：新增「LaCie 未加密」条目。

不在仓库里的改动（用户批准的一次性清单，见 `tmp/2026-11-13-dev-cleanup/onetime-targets.txt` 和 `onetime-apply.log`）：

- 删除：`~/Code/go`、`~/Code/vibench-p6-scratch`、`~/Documents/vibench-backups`、campus_watch 的旧 `ansible/venv` 和 ffmpeg 压缩包、feishu-lite 改名前的遗留目录、vibench 的 74M HAR、stickyfingers 的两个 DerivedData 和两个 fury-regress 目录、vocalflow 下载的 caddy、condenser 的 `ios/.build/DerivedData`。
- `condenser/.venv`：验证时被 `uv sync` 卸掉 5 个 dev 包，已用 `uv sync --extra dev` 装回。

## 注意事项

- **验证命令要先确认不改状态。** 在已有 venv 的项目里跑普通 `uv sync`，会卸掉 extras 里的包，condenser 因此丢了 pytest。验证类命令应该用 `--dry-run`，或者按项目文档写的参数来跑（`uv sync --extra dev`）。
- **按名字判断出的"旧版本"，删之前要看工具怎么读它。** stickyfingers 的 kernel-eval 读的是 `kernels/fury/current/manifest.json`，只有 0.5.0 目录有这个文件，所以 `current` 不能改指向 0.5.1，0.5.0 也就留着。
- **lsof 命中要看是谁持有。** Fury 0.5.0 被 NotificationCenter 缓存了一个 helper 的 strings 文件，这不代表 Fury 在运行。vocalflow 的 `index-build` 被 sourcekit-lsp 持有，这说明项目正开着，它的 `.build` 应该整体跳过。
- **手动跑 mac-dev-cleanup 要用 launchd 的 PATH**（包含 `~/.cargo/bin`），否则 cargo 段会因为找不到 cargo-sweep 而跳过。
- **uv 段的避让会被别的会话触发。** 这次被 10 分钟内启动的评测进程挡了两次，等它跑满 10 分钟后重跑就过了。
- **只读目录**（Go 模块缓存、包管理器的 store）里的文件挪不出来，只能整棵删，删之前要先 chmod。一次性脚本删 `~/Code/go` 时也撞上了这一点。
- **观察记录**：`~/Code/vibench-old` 和 `vibench-kifix2` 今天被别处删除（kifix2 分支也没了）。dev-space 的 actions 里没有它们，废纸篓和 LaCie 上也没有。

## 遗留问题

- ③ 监控的实机验收还没做：用 3.5 GiB 的测试目录走一遍 `watch` 加 `--agent`，确认通知和提案生成，然后删掉测试目录。
- 06:00 定时任务的首次完整运行、首周观察，见 `kb/next-up.md`。
- LaCie 未加密，上面有生产库备份和生产 SQL dump，已记入 `kb/known-issues.md`，等用户决定是否改用加密卷。
- 凭据备份文件留在项目里，需要用户经 envops 处理：campus_watch `backend/*.env.bak.*`，condenser `.env.bak.20261110-205340`。
- 还没有清理方案的大户：`~/Library/Application Support/vocalflow/vocalflow.sqlite`（1.9G）。用户说这一项不用处理。
- 后续交给两个 herdr tab 处理，主会话只写 brief、核对结果：
  - `~/.hermes`：释放约 522M，3.1G → 2.6G。有 5 项待用户决定，包括 cua-driver、浏览器工具链和会话自动清理，见 `tmp/2026-11-13-hermes-cleanup/REPORT.md`。
  - iOS 模拟器：只留 iPhone 17，释放约 7.6G，sim 段加了四条每日规则。有 3 项待用户决定：手机是否已经是 iOS 27、要不要提前删 5.7G 的 Device Support、要不要换 iOS 27 运行时、paseo 是否设 `PASEO_IOS_SIMULATOR_NAME`。见 `tmp/2026-11-13-ios-sim-cleanup/SUMMARY.md`。
- 跳过了 vocalflow 的 `VocalFlowCore/.build/{index-build,out}`（约 1.16G），项目正在编辑器里使用。
- uv 缓存里约 1300 个 wheel 指针指向已不存在的 archive，是这次清理之前就有的。新建 venv 时会联网重新下载，不影响已有 venv。
- 每小时检查剩余空间这件事推迟，首周观察后再决定。

## 相关文档

- [开发目录与全局缓存的精准清理和监控系统](../plans/2026-11-13-dev-disk-cleanup.md) — 总 plan，本次新建并记录首次运行
- [项目规则引擎 spec](../plans/2026-11-13-dev-space-rules-spec.md) — ① 的依据，本次更新
- [全局缓存清理段 spec](../plans/2026-11-13-global-cache-sections-spec.md) — ② 的依据
- [监控与告警 spec](../plans/2026-11-13-dev-space-watch-spec.md) — ③ 的依据
- [~/.hermes 清理 brief](../plans/2026-11-13-hermes-cleanup-brief.md) — 本次新建，交给 hermes-clean tab
- [iOS 模拟器清理 brief](../plans/2026-11-13-ios-simulator-cleanup-brief.md) — 本次新建，交给 ios-sim tab
- [iOS 模拟器清理 spec](../plans/2026-11-13-ios-simulator-cleanup-spec.md) — 由 ios-sim tab 编写
