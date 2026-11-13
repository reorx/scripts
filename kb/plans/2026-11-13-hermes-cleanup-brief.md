---
created: 2026-11-13
tags:
  - disk-cleanup
  - hermes
  - brief
---

# 任务 brief：清理 `~/.hermes` 里不必要的工具和过期数据

- **执行者**：herdr 新 tab 里的 Claude 会话。
- **工作目录**：`~/Code/scripts`，只用来放报告。操作对象是 `~/.hermes`。
- **起草人**：主会话（Claude）起草。用户的原话只有一句：「看看哪些工具是不必要的，我记得它装了很多工具类的东西，把不必要的都删了」。下面标着「主会话」的决定没经过用户确认，你可以不同意，把理由写进报告。
- **开工前先读**：本文件；`~/.hermes/config.yaml`；`~/.hermes/hermes-agent/` 里负责安装和定位工具的源码（找 `tools/`、`facts.json`、`installs/` 是怎么写进去、怎么被读的）。

## 背景

数据盘一度只剩 7 GiB，今天按项目清理后回到 56 GiB。`~/.hermes` 有 3.1 GiB，还没有任何清理方案。Hermes Agent 用户还在用：gateway 已经连续运行 18 天（`~/.hermes/gateway.pid`），也配了 cron。

当前大小（du）：

| 路径 | 大小 |
|---|---|
| `tools/` | 938M，包含 agent-browser-0.26.0、chromium-1208、cua-driver-0.21.0、ffmpeg-9.0.1、node-26.7.0、npm-12.0.2、python-3.14.7、ripgrep-15.2.0、uv-0.12.3，另有 `facts.json` |
| `hermes-agent/` | 922M |
| `installs/c203201be9a84532` | 730M |
| `cache/` | 352M |
| `state.db` + wal | 120M |
| `bin/` | 54M |
| `lsp/` | 33M |
| `skills/` | 26M |
| `sessions/` | 22M |
| `logs/` | 20M |

另外还有 `checkpoints/`、`backups/`、`.curator_backups/`、`audio_cache/`、`image_cache/`。

注意：`tools/python-3.14.7…/bin/python3` 正被 gateway 的子进程使用（`ps` 里能看到）。

## 目标

弄清 `~/.hermes` 里每个大头是什么、是否在用。确定不需要的删掉，留下的写明理由。删完之后 Hermes 照常工作。

## 完成标准

- `~/Code/scripts/tmp/2026-11-13-hermes-cleanup/REPORT.md` 写好：
  - 一张表覆盖上面每一项和你发现的其他大项：路径、du、真实释放量（APFS clone 和硬链接会让 du 偏大，删前删后各看一次 `df -k /`）、是什么、谁在用、判断依据、怎么处理；
  - 删除前后的 `du -sh ~/.hermes` 和 `df -h /`；
  - 「待用户决定」一节；
  - 「建议纳入每日清理的规则」一节，例如 cache、logs 的过期规则。
- 删除之后 Hermes 仍然可用：
  - gateway 进程还在（PID 和启动时间没变）；
  - 如果 Hermes 有 `doctor`、`status` 这类自检命令，跑一遍并通过；
  - 一个不触发对外动作的最小 CLI 调用正常。
- 拿不准的项没有删，都列在「待用户决定」里。

## 已经做出的决定

| 问题 | 决定 | 谁定的 |
|---|---|---|
| 不必要的工具能不能删 | 能，用户授权了 | 用户 |
| 什么算不必要 | 同时满足三条：config 里没启用、近 30 天日志和会话里没用过、Hermes 能按需重新安装。三条里有一条不确定，就放进「待用户决定」 | 主会话 |
| 用户数据和凭据 | 一律不动：`.env`、`auth.json`、`state.db*`、`sessions/`、`memories`、`cron/`、`config.yaml`、`channel_directory.json`、`skills/` 里用户自己写的内容 | 主会话 |
| 改 config 关掉功能 | 不改。如果删掉某个工具后 Hermes 会自动再装回来，写进报告，让用户决定要不要在 config 里关掉 | 主会话 |
| gateway | 不停，不重启。只有重启后才能生效的删除，先不做，写进「待用户决定」 | 主会话 |

## 范围

- **tools/**：
  - 每个工具的用途：Hermes 在哪段代码里定位和安装它；
  - 是否被运行中的进程使用：`ps`，以及对目录跑 `lsof +D`；
  - config 里是否启用；
  - 最近用没用过：看 `logs/` 和 `sessions/`。
  - 同一工具有多个版本的，旧版本是重点。
- **installs/c203201be9a84532**：
  - 它是什么，是不是旧安装或旧版本；
  - 当前在用的是哪一份：`~/.local/bin/hermes` 指向哪里，`.install_method` 写的是什么。
- **hermes-agent/**（922M）：
  - 里面是 git checkout 加 venv，还是 node_modules；
  - 有没有能安全删除的构建产物、旧版本、缓存。
- **其余目录**：`cache/`、`logs/`、`checkpoints/`、`backups/`、`.curator_backups/`、`audio_cache/`、`image_cache/`、`lsp/`，清掉其中的过期内容，按各自的再生成本决定过期天数，并写明理由。
- **清理方式**：Hermes 自带卸载或清理命令（类似 `hermes tools …`、`hermes cleanup`）的，优先用自带命令，不要直接 `rm`。

## 不在范围内

- 升级或重装 Hermes。
- 改动 `~/.claude`、`~/.codex`、`~/.cache` 等其他目录。
- 修改 `~/Code/scripts` 里的 dev-space、mac-dev-cleanup 代码和配置。要建议，写进报告。
- 任何会让 Hermes 对外发消息、触发 cron 或连接渠道的操作。

## 怎么做

1. 先只读调研，在报告里列出删除清单，再开始删。
2. 删每一项之前，用 `lsof` 和 `ps` 确认没有进程在用。
3. 每删一组就做一次「完成标准」里的可用性检查。坏了马上停下，在报告里写清删了什么、怎么恢复（例如用哪条命令重新安装）。
4. 需要看 `.env` 时用 envops skill，不要用 cat 或 Read。这是用户的全局规则。
5. 临时脚本放在 `~/Code/scripts/tmp/2026-11-13-hermes-cleanup/`，不要在命令行里塞大段内联代码。

## 约束

- 只修改 `~/.hermes` 里的内容。报告和脚本写到 `~/Code/scripts/tmp/2026-11-13-hermes-cleanup/`。
- 不要在 `~/Code/scripts` 里提交，也不要改 `kb/`、`AGENTS.md`。这些由主会话汇总后统一更新。

## 完成后

- 用中文写报告。
- 最后一条回复只写两样东西：报告路径，以及三行以内的结果摘要（释放了多少、删了哪些、有几项待用户决定）。
