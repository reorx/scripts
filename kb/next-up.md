# Next Up

- **2026-09-30** 看 `~/Library/Logs/mac-dev-cleanup.log` 里 06:00 那次运行：cargo target 一步是否真的跑了（不是 skipped 或 cargo sweep failed），前后大小是否合理。这是新 PATH（含 `~/.cargo/bin`）第一次在正式任务里运行。
- **2026-10-20** 共享 cargo target 改成依赖 `debug = false` 后，旧的「依赖带行号」产物应该在 21 天后全部被清掉。届时看 `du -sh ~/Library/Caches/cargo-target`，对照 2026-09-29 的 18.9 GiB，确认稳定下来的大小（预计明显低于 20 GiB 上限）。
