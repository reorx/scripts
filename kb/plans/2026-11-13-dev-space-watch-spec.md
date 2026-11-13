---
created: 2026-11-13
tags:
  - disk-cleanup
  - dev-space
  - monitoring
  - codex
---

# 监控与告警：每日测量、阈值通知、为无规则的大户派 agent 写规则提案

所属总 plan：[开发目录与全局缓存的精准清理和监控系统](2026-11-13-dev-disk-cleanup.md)。依赖 [项目规则引擎](2026-11-13-dev-space-rules-spec.md)（同一个 `dev-space` 工具）。

## PRD

### 背景

清理规则只能覆盖已知的东西。新项目、新的产物类型、某个缓存突然膨胀，都要等到磁盘满了才被发现。这次就是这样：发现时剩余空间只有 7 GiB。用户希望系统能自己发现异常；没有现成规则时，派 agent 分析，写出规则提案。

### 目标

每天清理之后测量一次。用户在两种情况下会收到通知：一是磁盘吃紧、某个项目或缓存超标、增长异常，二是 LaCie 太久没接上、离机备份过期。对没有规则覆盖的超标项目，系统自动派 agent 做只读分析，写出规则提案，等用户审核。

### 功能与交互

- **`dev-space scan`**：
  - 打印一张表：剩余空间，`~/Code` 下每个项目（root 加 related 合计），各全局缓存。
  - 每行写当前大小、7 天前的大小和变化量、阈值，超标的行加标记。
  - 只看，不写记录。
- **`dev-space watch`**（每天 06:00 由 `mac-dev-cleanup` 在最后调用）：
  - 测量并记入历史，然后逐项判断：
    - 剩余空间：低于 40 GiB 告警，低于 15 GiB 严重告警；
    - 项目超过它的 `alert_size`；没有专属规则的项目，超过 3 GiB 就告警；
    - 7 天内增长超过 3 GiB；
    - 全局缓存超过预算；
    - vibench-live 的离机备份超过 3 天没更新。
  - 有告警时发一条 macOS 通知，汇总条数和最严重的一项；详情写在日志里。
  - 同一项告警 3 天内不重复通知，除非它升级了（例如从告警变成严重）。
- **`dev-space watch --agent`**：
  - 在上面的基础上，对超标但规则覆盖不了的项目派 codex 做只读分析：
    - 没有专属规则的项目超过 3 GiB；
    - 有规则、但清理后仍超标的项目。
  - 分析结果是一份提案文件，内容包括体积构成、建议规则（可直接合并的 TOML）、一次性清理建议和需要用户确认的问题。生成后再发一条通知，写明提案路径。
  - 同一项目 14 天内最多派一次，每次运行最多派 2 个。
  - agent 只读：不删、不改任何东西，提案也由用户（或用户指派的 agent 会话）审核后才合并进规则。
- **`dev-space proposals`**：列出待审核的提案，每份显示对应项目、生成时间和提案文件路径。

### 不做的事

- agent 自行执行清理或修改规则文件。
- 每小时检查剩余空间。等观察几周每日一档是否够用，再决定要不要加。
- 推送到手机。现在没有推送通道，只用 macOS 通知。
- 图表界面。

### 验收标准

- `dev-space scan` 在约 2 分钟内打印完整表格，大小与 `du -sh` 一致（误差小于 1%）。
- 连续两天运行 `watch` 后，`scan` 能显示变化量。
- 新建一个 3.5 GiB、没有规则的测试目录：
  - `watch` 发一条通知；
  - 第二天再跑不重复通知；
  - 带 `--agent` 时生成一份提案文件，并发通知；
  - agent 运行期间没有任何文件被删除或修改。
- 断开 LaCie 3 天后，`watch` 报告离机备份过期。

## Tech Design

### 现状

- 本期之前，`dev-space` 只有 `clean`、`restore`、`rules` 三个子命令（①）。配置在 `skills/systools/config/dev-space.toml`，状态目录是 `~/.local/state/dev-space/`。
- 本机没有推送通道。`cc-notify.py` 用 osascript 的 `display notification` 发通知，launchd 的用户 agent 也可以这样发。
- `codex exec` 0.167.1 的相关参数：`-s read-only`、`-C <dir>`、`--skip-git-repo-check`、`-o <file>`（把最后一条消息写入文件）。

### 方案

`watch` 依次做四件事：

1. `scan` 测量；
2. 写入历史；
3. `evaluate` 产出告警列表；
4. 去重后发通知；带 `--agent` 时派提案。

测量直接调用 `du -sk`，按目录逐个执行：C 实现比 Python 遍历快一个数量级。

关键决策：

- **以 du 为准，不算真实占用。** 监控看的是趋势和异常，du 稳定、可以和人工 `du` 对照。clone 带来的虚高对趋势没有影响。真实释放量由清理步骤报告。
- **提案用 `codex exec -s read-only`。**
  - 沙箱保证 agent 无法写任何文件；提案由 codex CLI 自己通过 `-o` 写出。
  - 提示词放在 `skills/systools/references/dev-space-analysis.md`，内容从这次调研的 `BRIEF.md` 整理而来，同一份也给人工派 agent 时用。
- **派提案同步执行，单个超时 20 分钟。**
  - launchd 任务退出时会杀掉子进程，所以不能后台化。
  - 每次最多 2 个，最坏情况下把 06:00 任务延长 40 分钟，可以接受。

### 数据变动

在配置里新增：

```toml
[watch]
free_warn = "40GiB"
free_critical = "15GiB"
default_alert_size = "3GiB"     # 没有专属规则的项目
growth_alert = "3GiB"           # 7 天增长
realert_days = 3
backup_stale_days = 3
agent_cooldown_days = 14
agent_max_per_run = 2
agent_timeout_minutes = 20

[watch.caches]                  # 名称 = { path, budget }
uv = { path = "~/.cache/uv", budget = "12GiB" }
# pnpm-store、pnpm-cache、npm、go-mod、cargo-target、codex、CoreSimulator、iOS DeviceSupport、playwright、bun
```

在状态目录里新增：

- `history.jsonl`：每次 watch 写一行，字段为 `{"ts", "free", "items": {"project:<name>": bytes, "cache:<name>": bytes}}`。
- `alerts.json`：每项告警的 key → `{level, last_notified}`，用于去重。
- `proposals/<YYYY-MM-DD>-<project>.md`：codex 写出的提案。
- `proposals/agents.json`：每个项目上次派 agent 的时间，用于冷却。

### 逻辑变动

`dev-space` 新增以下内容：

- `measure_all(config) -> Snapshot`：
  - code_root 下的每个顶层目录归到所属项目：在某个项目 root 或 related 里的，计入该项目；其余各自成为匿名项目。
  - code_root 之外的 related 目录、各缓存路径单独测。
  - 剩余空间用 `os.statvfs`。
- `history_delta(history, name, days=7)`：取不晚于 7 天前的最近一条记录，计算差值。
- `evaluate(snapshot, history, config, now) -> list[Alert]`：
  - `Alert` 的字段：`key`、`level`（warn / critical）、`message`、`project`（可空）、`needs_agent`。
  - 离机备份是否过期，看 LaCie 上各 sqlite-backup 规则最新一份的时间。LaCie 未挂载时，改用 `actions.jsonl` 里最后一次成功备份的时间。
- `dedupe(alerts, state, now)`：只保留新出现、升级了、或距上次通知已超过 `realert_days` 的告警。
- `notify(title, body)`：调用 `osascript -e 'display notification …'`，参数做转义。
- `dispatch_proposals(alerts, config, now)`：
  - 选出 `needs_agent` 的项目，过滤冷却期，取前 `agent_max_per_run` 个。
  - 提示词 = 分析参考文档 + 项目名 + 目录列表 + 当前生效规则（`rules` 的输出）+ 体积。
  - 执行 `codex exec -s read-only --skip-git-repo-check -C <root> -o <proposal> <prompt>`。
  - 成功后更新 `agents.json` 并发通知。失败只记日志，不中断 watch。
- 命令行：
  - `scan [--json]`
  - `watch [--agent] [--no-record] [--no-notify]`
  - `proposals`
  - 退出码恒为 0，告警不算失败。只有配置错误返回 2。

### 实施步骤

- [x] `test_dev_space.py` 增加 watch 用例（见下）
- [x] 测量、历史、变化量
- [x] evaluate、dedupe、notify
- [x] 提案派发和 `proposals` 子命令；编写 `references/dev-space-analysis.md`
- [x] 配置里加 `[watch]` 和各缓存预算（按清理后的大小 × 1.5 取整）
- [ ] 实机：跑 `scan`；用 3.5 GiB 测试目录走一遍 watch 加 `--agent`，确认通知和提案；删掉测试目录

### 测试与验证

| 验收点 | 用例 |
|---|---|
| 测量归属 | related 目录计入所属项目；不在任何项目里的顶层目录成为匿名项目；`defaults_exclude` 只影响清理，不影响测量 |
| 变化量 | 有 8 天前和 1 天前两条记录时，取 8 天前那条；历史不足 7 天时不报增长 |
| 阈值 | 剩余空间分两档；有规则的项目用 `alert_size`，匿名项目用默认阈值；缓存按预算；备份过期 |
| 去重 | 同 key、同级别在 3 天内只通知一次；升级后立即通知；3 天后再次通知 |
| 派 agent | 只派 `needs_agent` 的项目；冷却期内不派；每次最多 N 个；用假的 `codex` 可执行文件验证参数里有 `-s read-only` 和 `-o`，并验证超时后能继续 |

实机：见实施步骤最后一项。观察一周日志，把首周的结果记入 `kb/next-up.md`。

### 风险与待定

- `du` 遍历整个 `~/Code`（约 100 GiB，大量小文件）每天大约 1–2 分钟，可以接受。如果变慢，再改成并行执行。
- codex 的只读沙箱能否正常运行 `du`、`git` 这类只读命令，需要实测；如果被沙箱拦截，提案质量会下降。
- 默认阈值 3 GiB 可能让长尾里几个 2–3.5 GiB 的项目（如 flotify、realphotos）首日就触发告警，这是有意的：它们正好是需要规则或需要闲置清理的对象。
