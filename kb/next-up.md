# Next Up

- **2026-09-30** 看 `~/Library/Logs/mac-dev-cleanup.log` 里 06:00 那次运行：cargo target 一步是否真的跑了（不是 skipped 或 cargo sweep failed），前后大小是否合理。这是新 PATH（含 `~/.cargo/bin`）第一次在正式任务里运行。
- **2026-10-20** 共享 cargo target 改成依赖 `debug = false` 后，旧的「依赖带行号」产物应该在 21 天后全部被清掉。届时看 `du -sh ~/Library/Caches/cargo-target`，对照 2026-09-29 的 18.9 GiB，确认稳定下来的大小（预计明显低于 20 GiB 上限）。
- **2026-10-29，荣耀手机重新连接后**：执行 `kb/plans/2026-10-28-honor-system-cleanup.md` 的第一、二期；先用 `adb devices -l` 核实设备，再用 `uv run honor-cleanup.py` 只读核对第三方白名单。按各期清单处理系统应用，验证保留功能、重启后包状态及弹窗；结果记录到各期计划。第三期另行分项验证，通知审核仍暂缓。本条不是自动执行任务。
