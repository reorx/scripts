---
created: 2026-11-13
tags:
  - disk-cleanup
  - mac-dev-cleanup
  - dev-space
  - launchd
---

# 开发目录与全局缓存的精准清理和监控系统

## PRD

### 背景

2026-11-13 数据卷只剩约 7 GiB（460 GiB 用了 99%）。增长主要来自两处：

- `~/Code` 下的项目（前 60 个目录合计约 94 GiB）。重点项目 vibench（连同 vibench-live 共约 27 GiB）、campus_watch、stickyfingers、vocalflow-mac 各有 7–14 GiB，大头是各项目 `tmp/<日期>-<任务>/` 里验收时复制的 DerivedData、`.app`、sqlite 副本，以及构建缓存和迁移前备份。
- 全局开发缓存：uv、pnpm、npm、go 模块缓存、cargo 共享 target、codex 会话。

每天 06:00 的 `mac-dev-cleanup` 已经能清 cargo target 和 uv 缓存，但项目目录、其他缓存和 agent 会话都没人管。用 `du` 看缓存还会严重虚高：uv、pnpm 的文件是 APFS clone，du 显示 14 GiB 的 uv 缓存，全删真实只释放 1.8 GiB。所以不能一刀切按大小删，要按「还有没有用」来删。

调研报告（每个项目一份，加全局缓存和 agent 会话）在 `tmp/2026-11-13-dev-cleanup/`。

### 目标

一套定期自动运行的精准清理系统：

- 只删已经过期、可以重新生成的东西，有用的缓存留下。
- 需要保留但很少用的数据迁到外接盘 LaCie，原位置留软链接。
- 每天监控各项目和缓存的占用。异常时通知用户；没有规则覆盖的大户，派 agent 只读分析并写出规则提案，由用户审核后合并。
- 补上 vibench-live 主库的离机备份。

### 共用概念

- **过期**：默认一周内没被使用（或没被任何活跃项目引用）就算过期。能拿到「最后使用」或「被引用」信号的，不按创建时间判断。
- **三档运行**：
  - 每日：06:00 自动运行。
  - 吃紧：磁盘剩余低于 15 GiB 时，自动多跑一档更激进的规则。
  - 手动：只在用户亲自运行时执行。
- **真实释放量**：每一步同时报告 du 大小，和实际腾出的磁盘空间（扣除 clone、硬链接共享的部分）。
- **归档**：搬到 `/Volumes/LaCie/DevArchive/<项目>/` 下，按家目录的相对路径存放，原位置留软链接，可以一条命令恢复。
  - LaCie 是 exFAT，放不了符号链接，也保不住可执行位，所以含 `.git`、符号链接或 `.app` 的内容一律不搬。
  - 盘没接上时，归档和备份跳过并在报告里说明。

### 分期

| 期 | spec | 内容 |
|---|---|---|
| ① | [项目规则引擎](2026-11-13-dev-space-rules-spec.md) | `dev-space` 工具的清理部分：所有项目共用的默认规则，7 个重点项目的专属规则，归档到 LaCie 与恢复，vibench-live 主库离机备份 |
| ② | [全局缓存清理段](2026-11-13-global-cache-sections-spec.md) | `mac-dev-cleanup` 新增 go、pnpm、npm、codex 段，uv 改为按引用保留，cargo 改 7 天并修正「最近使用」失真；在 06:00 任务里接入 ① 和 ③ |
| ③ | [监控与告警](2026-11-13-dev-space-watch-spec.md) | 每日测量、历史记录、阈值告警、macOS 通知、为超标且无规则的目录派 codex 写规则提案 |

① 和 ② 改的是不同文件，可以并行；③ 建在 ① 的工具上。

### 用户已确定的决策（2026-11-13）

- 分析 agent 只写提案，不自行删除任何东西。
- codex 会话：7 天未更新的压缩，30 天未更新的用官方 `codex delete` 删除。
- 各项目 `tmp/` 里的验收证据（截图、报告、日志）：重型产物删掉后，14 天没改动的证据目录归档到 LaCie。
- vibench-live：
  - 部署快照本地只留最新 2 份，其余归档 LaCie。
  - 迁移前备份（`.live/data/*.bak-*`）全部放 LaCie。
  - 主库定期做一份离机备份到 LaCie。

### 不做的事

- `~/.claude`：用户明确暂不管。
- cw_edge：它自己的会话在处理。
- Docker：本机不跑 docker 命令。
- 自动 `git worktree remove`、删除整个项目或兄弟副本：这些列成一次性清单，由用户逐项批准后手动做。
- 让 agent 在无人值守时执行删除。
- 每小时检查剩余空间的独立任务：先观察每日一档是否够用。

### 验收标准（跨期）

- 06:00 任务跑完，日志里依次有进程清理、项目规则、各缓存段、监控四部分。每部分写明释放了多少（du 和真实），或者为什么跳过。
- 某个项目的规则在 dry-run 下列出的每一项，都是 git 未跟踪的生成物，或者备份、证据。线上主库、凭据、身份文件备份、正在被进程使用的目录，一项都不出现。
- 首次真实运行后，`df` 剩余空间明显回升，与报告的真实释放量相符。
- 断开 LaCie 后跑一遍，不报错，归档和备份步骤写明「未挂载，跳过」。
- 新建一个超过阈值、又没有规则的测试目录，跑监控后收到 macOS 通知，并且生成一份规则提案文件。

## Tech Design

### 跨期的关键决策

- **新工具 `skills/systools/scripts/dev-space` 与 `mac-dev-cleanup` 分开，06:00 任务仍以 `mac-dev-cleanup` 为唯一入口。**
  - 项目规则引擎、归档和监控是一块独立且会持续长大的逻辑（规则配置、历史、提案）；`mac-dev-cleanup` 已有约 1500 行。
  - `mac-dev-cleanup` 通过子进程调用 `dev-space`（用户明确要求以它为入口，所以这里是仓库「脚本互不调用」规则的例外）。
  - 被否决的做法：全部塞进 `mac-dev-cleanup`。文件会超过 3000 行，而且规则引擎没法单独测试。
- **项目规则集中放在 `skills/systools/config/dev-space.toml`，不放进各项目仓库。**
  - 一处可审计，分析 agent 的提案也合并到这里。
  - 不去改 7 个仓库，以免和那些仓库里正在进行的会话冲突。
- **06:00 任务里的顺序**：进程清理 → 项目规则 → 各缓存段 → 监控。
  - 项目规则先删掉陈旧的 node_modules / .venv，缓存段才能把只被它们引用的条目当成无人引用。
  - 监控放在最后，量的是清理之后的状态。
- **两个脚本各自实现「真实释放量」。**
  - 方法：`getattrlist` 读 clone 引用计数，再对比清理前后卷的剩余空间。
  - 两份代码各写一份，不互相 import，遵守仓库规则。
- **状态目录统一为 `~/.local/state/dev-space/`**，里面放历史、告警记录、提案、归档清单和回收站。

### 依赖和顺序

- ① 与 ② 并行开发：① 只动 `dev-space`、配置和测试，② 只动 `mac-dev-cleanup`。
- ② 在 `mac-dev-cleanup` 里新增 `projects` 和 `watch` 两段。它们只按下面的命令行约定调用 `dev-space`，所以不依赖 ① 的内部实现：
  - `dev-space clean --scheduled [-n]`：跑每日档；剩余空间低于吃紧阈值时，再加跑吃紧档。退出码与 `mac-dev-cleanup` 一致：0 表示成功，2 表示某个项目失败，dry-run 下有东西可清时返回 1。
  - `dev-space watch --agent`：测量、记录、告警、派提案。退出码 0，告警不算失败。
- ③ 在 ① 完成后做，同一个文件。

### 实施步骤

- [x] ① [项目规则引擎](2026-11-13-dev-space-rules-spec.md)
- [x] ② [全局缓存清理段](2026-11-13-global-cache-sections-spec.md)（与 ① 并行）
- [ ] ③ [监控与告警](2026-11-13-dev-space-watch-spec.md)：代码完成；实机的 3.5 GiB 测试目录走一遍 watch 加 `--agent` 还没做
- [x] 联调：`mac-dev-cleanup --dry-run` 全流程；向用户展示 dry-run 结果，批准后首次真实运行，用 `df` 核对
- [x] 一次性清单：整理各报告里的一次性动作，用户逐项批准后执行
- [x] 文档：`SKILL.md`、`AGENTS.md`、`kb/known-issues.md`、`kb/next-up.md`（首周观察日志），然后提交

### 首次真实运行（2026-11-13 10:30–10:47）

剩余空间 7.0 GiB → 53.5 GiB，加上一次性清单后 56.4 GiB。日志在 `tmp/2026-11-13-dev-cleanup/`（`first-run.log`、`rerun-cargo-uv.log`、`onetime-apply.log`）。

| 段 | 结果 |
|---|---|
| 项目规则 `dev-space clean --scheduled` | 1648 项，du 36.8 GiB，real 27.4 GiB；其中 vibench-live 的部署快照、迁移备份和各项目 14 天前的 tmp 证据归档到 LaCie |
| go | 删 632 个模块版本，+5.3 GiB |
| pnpm | dlx、未引用的 store 包、旧元数据，+8.7 GiB |
| npm | `_cacache` 和 48 个 `_npx` 包，+3.3 GiB |
| codex | 压缩 427 个会话（省 815 MiB），删 200 个（上限），删 1 个旧 release，+1.3 GiB；剩 77 个过期会话留给下一次 |
| uv | 14.2 → 9.1 GiB（du），real 约 1 GiB |
| cargo | 1362 个编译单元都在 7 天内用过，0 清理 |
| 一次性清单 | 4.3 GiB（`tmp/2026-11-13-dev-cleanup/onetime-targets.txt`） |

首次运行暴露并修掉的问题：

- tinyhost 的 `tmp-db-copies` 匹配到测试 HOME 里 Go 模块缓存 testdata 的 `*.db`，目录只读，挪不动，整条规则失败、退出码 2。现在匹配不进入只读目录（规则 spec 的「方案」一节）。
- codex 段报 10 个 `codex delete` 被拒，实际是父会话删除时一并带走的子会话。现在 rollout 已经不在的拒绝计为已删。

清理后的检查：vibench 离线 `pnpm install --frozen-lockfile` 通过；tinyhost 离线 `go list -deps -test` 通过；ansible、condenser 在已有 `.venv` 上离线 `uv sync` 都无需下载；通过 `codex app-server` 的 `thread/read` 读一个 `.jsonl.zst` 会话，读出 77 条记录，文件没动。

两个和这次清理无关、但检查时看到的现象：

- uv 缓存里约 1300 个 wheel 指针（`.http`）指向的 archive 早已不存在，大多是 8 月以前的。这次清理最多删了 232 个 archive，而且活跃项目锁定的 wheel 会保留，所以它们不是这次删的。uv 遇到这种指针会重新下载，只是新建 venv 时要联网。
- tinyhost 的 `go.mod` 要求 go1.27.0，本机此前从没下载过这个工具链（缓存里没有更早的 `.lock` 残留），检查时第一次下载。

### 各期都要更新的文档

- `skills/systools/SKILL.md`：`mac-dev-cleanup` 一节加上新段落，新增 `dev-space` 一节。
- `AGENTS.md`：新增 dev-space 条目，写明配置位置、测试命令，以及不能放宽的安全底线。

### 跨期风险

- 首次真实运行删除量大。必须先给用户看 dry-run，批准后再跑。
- `codex delete`、go、pnpm、npm 的内部布局会随版本变化。各段遇到不认识的版本或布局时跳过并报警，不猜测。uv 段已经这样处理。
