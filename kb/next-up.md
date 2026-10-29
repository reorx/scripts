# Next Up

- **2026-09-30** 看 `~/Library/Logs/mac-dev-cleanup.log` 里 06:00 那次运行：cargo target 一步是否真的跑了（不是 skipped 或 cargo sweep failed），前后大小是否合理。这是新 PATH（含 `~/.cargo/bin`）第一次在正式任务里运行。
- **2026-10-20** 共享 cargo target 改成依赖 `debug = false` 后，旧的「依赖带行号」产物应该在 21 天后全部被清掉。届时看 `du -sh ~/Library/Caches/cargo-target`，对照 2026-09-29 的 18.9 GiB，确认稳定下来的大小（预计明显低于 20 GiB 上限）。
- **荣耀第一批禁用体验后**：2026-10-29 第一批 14 项已全部停用，等待用户体验桌面、锁屏、相机/图库、输入法语音、通信和支付应用；首次重启后用 `adb -s AB9UUT4510000125 shell pm list packages -d --user 0` 核对仍停用，检查弹窗及保留功能。结果记入 `kb/plans/2026-10-28-honor-assistant-cleanup-spec.md`。验收通过且用户要求继续后再进行第二期；第三期另行分项验证，通知审核仍暂缓。
