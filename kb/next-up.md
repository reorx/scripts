# Next Up

- **荣耀系统应用禁用体验后**：2026-10-29 第一期 14 项及第二期用户指定的剪辑、平行空间、AI 通话、多屏协同已停用。等待用户体验桌面、锁屏、相机/图库、输入法语音、通信和支付，以及 Windows 连接、荣耀云和智慧空间；Windows 设置入口启动未成功，功能未验证，如连接受损先恢复多屏协同对比。首次重启后用 `adb -s AB9UUT4510000125 shell pm list packages -d --user 0` 核对状态，并检查默认语音引用及弹窗。结果记入 `kb/plans/2026-10-28-honor-assistant-cleanup-spec.md` 和 `kb/plans/2026-10-28-honor-unused-features-spec.md`。第二期其余 4 项未操作，第三期及通知审核暂缓，不自动推进。

## 2026-11-14 06:00 之后（首次真实运行后的第一次定时任务）

- **日志**：`~/Library/Logs/mac-dev-cleanup.log` 里 `projects` 和 `watch` 两段都跑了，没有 failed（首次手动运行时 tinyhost 的只读目录失败已修）。以下文件都应出现：
  - LaCie 上第二份 `vibench/sqlite-backups/live-db-offsite/*.sqlite.gz`；
  - `~/.local/state/dev-space/history.jsonl` 的第一行。

  首轮剩下的 77 个过期 codex 会话应在这一次删完，日志里不该再有「codex refused」。
  → 记到 `kb/plans/2026-11-13-dev-disk-cleanup.md`「首次真实运行」

## 2026-11-20 之后（首次真实运行一周）

- **首周观察**：
  - `dev-space scan` 的 7 天变化量；
  - cargo 段每天 cleaned 应接近 0，否则说明常用依赖还在被清掉重编；
  - 有没有 `dev-space proposals`；
  - 告警是否过多。过多就调 `config/dev-space.toml` 的 `[watch]` 阈值。

  → 记到同一 plan，并决定要不要加每小时的剩余空间检查
