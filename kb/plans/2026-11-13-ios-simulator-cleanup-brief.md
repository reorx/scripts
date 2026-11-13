---
created: 2026-11-13
tags:
  - disk-cleanup
  - ios-simulator
  - mac-dev-cleanup
  - brief
---

# 任务 brief：iOS 模拟器只留一台、只留最新 iOS，并加入每日自动清理

- **执行者**：herdr 新 tab 里的 Claude 会话。
- **工作目录**：`~/Code/scripts`（master 分支，直接在当前 checkout 上工作）。
- **起草人**：主会话（Claude）。用户的要求见下面「用户的四条要求」，是用户原话的整理。标着「主会话」的决定没经过用户确认，你可以不同意，把理由写进总结。
- **开工前先读**：
  - 本文件；
  - `AGENTS.md`；
  - `skills/systools/SKILL.md` 里 mac-dev-cleanup 的 sim 一节；
  - `skills/systools/scripts/mac-dev-cleanup` 的 `cleanup_simulators`（约 373 行）和 selftest 部分（`def check(`、各 `selftest_*`）；
  - `kb/plans/2026-11-13-global-cache-sections-spec.md`：同一个脚本最近一次扩展的写法，新段和新规则照它的风格写。

## 背景

数据盘今天从 7 GiB 清到 56 GiB。查 iOS 相关目录时的情况（2026-11-13）：

- `~/Library/Developer/CoreSimulator/Devices` 一共 10G，有 11 台模拟器，都在 iOS 26.5 运行时上：

  | 模拟器 | 大小 | 内容 |
  |---|---|---|
  | iPhone 17 | 3.8G | 装着 condenser 和 vibench 的 ProbeUITests runner；系统日志 1.1G，MobileAsset 1.6G |
  | iPhone 17 Pro | 3.0G | 只装着 condenser；日志 0.5G |
  | iPhone 17e | 1.9G | 只装着 condenser；日志 0.25G |
  | iPhone 17 Pro Max | 1.8G | 只装着 condenser；日志 0.16G |
  | iPhone Air 和 6 台 iPad | 各 17M | 从没用过 |

  系统日志指 `data/var/db/diagnostics` 和 `data/var/db/uuidtext`；MobileAsset 指 `data/private/var/MobileAsset`，是模拟的 iOS 自己下载的模型、语音、字体等。
- 运行时镜像只有 iOS 26.5（7.9G），在 `/Library/Developer/CoreSimulator`，用 `xcrun simctl runtime list` 查看。
- `~/Library/Developer/Xcode/iOS DeviceSupport` 有 5.7G，只有一个 `iPhone17,3 26.5.2 (23F84)`，对应用户的真机 Reorx16 当前的系统版本。
- 现有的 sim 段只负责关掉开着没用的模拟器，不删任何东西。

## 用户的四条要求

1. 精简模拟器：不需要那么多，选一台最有代表性的长期使用。
2. 在系统提示词里写明：除非用户特别说明，一律用这台指定的模拟器，避免 agent 验收时又去装新的模拟器。
3. iOS 版本始终只留最新的。
4. 给 cleanup 脚本加三条自动规则：
   - 已关机模拟器里的旧系统日志；
   - Device Support 每个机型只留最新版本；
   - 旧的模拟器运行时。

## 目标

- 本机只剩一台指定模拟器（加上最新运行时）。
- 所有 agent 默认用它。
- `mac-dev-cleanup` 每天自动维持这个状态：
  - 删旧日志；
  - 删旧 Device Support；
  - 新运行时到了以后删旧运行时；
  - 清掉长期没用的非指定模拟器。

## 完成标准

- `xcrun simctl list devices` 里只剩指定模拟器。原 iPhone 17 上的 condenser 等 app 和数据还在。
- `~/.claude/CLAUDE.md` 的「Testing and Acceptance」一节有一条简短规则，写明指定模拟器、什么时候可以例外，以及不要新建模拟器、不要下载运行时。`~/.codex/AGENTS.md` 是它的软链接，codex 会自动拿到同样的规则。
- `~/Code` 下各项目里写死的模拟器名字（Makefile、脚本、AGENTS.md、CLAUDE.md、xcodebuild `-destination`、`simctl boot` 等）都已经找出来：
  - 指向被删设备的，已经改成指定模拟器；
  - 改不了的，列进总结。
- `mac-dev-cleanup` 新规则的 selftest 先写、先失败，实现后全部通过（`uv run skills/systools/scripts/mac-dev-cleanup --selftest`）。
- `mac-dev-cleanup --dry-run --only sim` 在本机的输出合理：
  - 日志一项有可删内容；
  - Device Support 和运行时两项都是 0，因为现在都只有一个版本。
- 真实运行一次 `--only sim`，用 df 核对释放量。
- 总结写在 `tmp/2026-11-13-ios-sim-cleanup/SUMMARY.md`，包括：做了什么、自己做了哪些决定、对 brief 的异议、释放量、改了哪些项目文件。

## 已经做出的决定

| 问题 | 决定 | 谁定的 |
|---|---|---|
| 指定哪一台 | **iPhone 17**，保留现有那台（UDID `75620740-DAD7-45D1-8BBF-264AFB150B12`）和它里面的数据。理由：标准尺寸，用得最多，condenser 和 vibench probe 都装在上面。如果你查到大多数项目写死的是另一台，可以改选，但要在总结里说明 | 主会话 |
| 指定设备怎么写进提示词和配置 | 写名字「iPhone 17」，并说明用最新 iOS 运行时上的那台，不写死 UDID：运行时升级后 UDID 会变 | 主会话 |
| 另外 10 台模拟器 | 用 `xcrun simctl delete` 删掉。用户已同意精简 | 用户 |
| 运行时 | 每个平台（iOS、watchOS 等）只留最新的一个。旧运行时没有设备在用时自动删除；`simctl delete unavailable` 一起做 | 用户（第 3 条） |
| Device Support | 每个机型（如 `iPhone17,3`）只留版本最新的文件夹，其余删除 | 用户（第 4 条） |
| 系统日志 | 只处理状态为 Shutdown 的模拟器，清理超过 7 天的日志 | 用户同意规则，天数由主会话定 |
| 非指定模拟器 | 新增第四条自动规则：非指定、关机状态、超过 7 天没启动过的模拟器，自动删除。这样 agent 偶尔按用户要求新建一台，用完会自己消失，Xcode 装新运行时时自动生成的默认设备也会被清掉。用户只同意了前三条规则，这条是主会话加的；你觉得不妥就只做前三条，并在总结里说明 | 主会话 |
| MobileAsset | 不清理。删掉之后模拟器会重新下载 | 主会话 |

## 范围

- **一次性操作**：
  - 删除 10 台模拟器；
  - `simctl delete unavailable`；
  - 改全局提示词；
  - 找出并修改项目里写死的模拟器名字。
- **mac-dev-cleanup 的 sim 段**，在现有「关掉闲置模拟器」之后增加：
  - 删除超过 7 天的旧日志；
  - Device Support 每个机型只留最新；
  - 删除旧运行时；
  - 删除非指定且闲置的模拟器。
  - 指定模拟器的名字放在脚本顶部常量或命令行参数里，跟现有段的写法保持一致。
- **文档**：
  - `skills/systools/SKILL.md` 的 sim 一节；
  - `kb/plans/` 下写一份 spec：`2026-11-13-ios-simulator-cleanup-spec.md`，包含 PRD 和 Tech Design，按仓库现有 spec 的写法；
  - 如有符合标准的问题，写进 `kb/known-issues.md`。

## 不在范围内

- 不清理 MobileAsset，也不清理指定模拟器里的 app 数据。
- 不升级 Xcode，不下载新运行时。
- 不碰 dev-space 及其配置。
- 不推送任何仓库。

## 怎么做，以及必须注意的事

- 这个仓库的规则是先写 selftest。在 `mac-dev-cleanup` 里新增 `selftest_*`：
  - 用假的目录结构和假的 `simctl` 输出（JSON）测试选择逻辑；
  - 必须覆盖：开机的模拟器不动、指定模拟器永不删除、只有一个版本时什么都不删、版本号要按数值比较（`26.10` 大于 `26.9`）。
- **系统日志**：先查清 unified logging 在模拟器里的文件结构再定删除范围。`uuidtext` 存的是格式串，新日志可能还引用很早写入的 uuidtext 文件，只按 mtime 删会让近期日志解码不出来。可行的做法有两种，选一种并写明理由：
  - 只删 `diagnostics` 下超过 7 天的 `.tracev3`；
  - 模拟器整体闲置超过 7 天时，日志整个清掉。
- **运行时**：用 `xcrun simctl runtime list -j` 和 `xcrun simctl runtime delete <id>`，先确认它在无 sudo 的 launchd 任务里能用。不能用的话，降级为只在日志里提醒，并写进总结。
- **判断上次启动时间**：`device.plist` 和 data 目录的 mtime，哪个能准确反映「最后一次 boot」要先实测（boot 一次、再 shutdown，看哪个变了），不要猜。
- **删除之前**：
  - 确认没有模拟器处于 Booted 状态；
  - 确认没有 `xcodebuild`、`simctl` 进程在跑。别的项目的 agent 可能正在验收：有开着的模拟器就跳过，等它们关掉，不要强关。
- **改其他项目的文件**：
  - 只改写死模拟器名字的那几行；
  - 用 `git commit -- <file>` 只提交这个文件，提交信息说明原因；
  - 该文件已经有别人未提交的改动时，不要改，写进总结；
  - 不推送。
- 临时脚本放在 `tmp/2026-11-13-ios-sim-cleanup/`，不要在命令行里塞大段内联代码。

## 约束

- 在 `~/Code/scripts` 里只 `git add` 你改过的文件，可以直接提交到 master，不推送。
- `kb/next-up.md` 和 `kb/sessions/` 不要动，由主会话汇总。如果需要「过几天再核对」的事项，写进总结，主会话会转录。
- `~/.claude/CLAUDE.md` 是 iCloud 里的文件（软链接），直接编辑即可，只加这一条规则，不改别的内容。

## 完成后

- 用中文写 `tmp/2026-11-13-ios-sim-cleanup/SUMMARY.md`。
- 最后一条回复只写两样东西：总结路径，以及三行以内的摘要（释放了多少、留下哪台、加了哪些规则、有几项要用户决定）。
