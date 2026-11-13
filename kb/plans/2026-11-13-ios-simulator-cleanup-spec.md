---
created: 2026-11-13
tags:
  - disk-cleanup
  - ios-simulator
  - mac-dev-cleanup
---

# iOS 模拟器只留一台、只留最新 iOS，mac-dev-cleanup 每日维持

任务 brief：[2026-11-13-ios-simulator-cleanup-brief.md](2026-11-13-ios-simulator-cleanup-brief.md)。同一脚本上一次扩展：[全局缓存清理段](2026-11-13-global-cache-sections-spec.md)。执行记录和总结：`tmp/2026-11-13-ios-sim-cleanup/SUMMARY.md`。

## PRD

### 背景

2026-11-13 查数据盘时，`~/Library/Developer/CoreSimulator/Devices` 有 10 GiB、11 台模拟器，全在 iOS 26.5 运行时上：

- iPhone 17（3.8 GiB）装着 condenser 和 vibench 的 ProbeUITests runner，用得最多；
- iPhone 17 Pro、17e、17 Pro Max 各 1.8–3.0 GiB，只装着 condenser；
- iPhone Air 和 6 台 iPad 从没用过。

每台模拟器里还有几个月的系统日志（unified logging），iPhone 17 一台就有 1.1 GiB。运行时只有 iOS 26.5（7.9 GiB）；`~/Library/Developer/Xcode/iOS DeviceSupport` 只有真机 Reorx16 的一个版本（5.7 GiB）。

这些都不会自己变少：agent 验收时会按需新建模拟器，Xcode 每装一个新运行时就自动建一套默认设备，Device Support 每遇到手机的一个新系统版本就多一份。现有的 sim 段只关掉开着的模拟器，不删任何东西。

### 目标

- 本机只剩一台指定模拟器：最新 iOS 运行时上的 iPhone 17，加上这个运行时本身。
- 所有 agent 默认用它，不新建模拟器、不下载运行时。
- `mac-dev-cleanup` 每天 06:00 维持这个状态。

### 功能与交互

**一次性操作：**

- 删除另外 10 台模拟器，再 `simctl delete unavailable`。
- `~/.claude/CLAUDE.md` 的「Testing and Acceptance」加一条规则（`~/.codex/AGENTS.md` 是它的软链接）：一律用最新 iOS 上的 iPhone 17；不新建模拟器、不下载运行时；用户明确要求别的机型或 iOS 版本时例外。
- `~/Code` 下各项目写死的模拟器名字逐个检查，指向被删设备的改掉，改不了的列进总结。

**sim 段新增四条规则**，接在现有「关掉模拟器」之后，随 06:00 任务运行，也可以 `--only sim` 单独运行，`--dry-run` 下只报告：

- **闲置模拟器**：指定模拟器以外、关机状态、`--sim-days`（默认 7）天没用过的模拟器，删除。agent 按用户要求新建的、Xcode 随新运行时建的默认设备，用完都会自己消失。
- **系统日志**：关机状态的模拟器里，超过 7 天的日志文件删除。
- **旧运行时**：每个平台只留最新的运行时。旧的在没有设备用它之后删除。
- **Device Support**：每个机型只留最新版本的文件夹。

**报告和失败处理：**

- 先打印保留的指定模拟器，然后四项各一行：个数、du、real；运行时这一行显示镜像大小。四项都为 0 时写「nothing to clean on disk」。
- 有 `xcodebuild` 或 `simctl` 进程在跑时，磁盘部分整天跳过，写明 pid。
- 找不到指定模拟器时，一台都不删，打 ⚠️。
- 新运行时到了却没有 iPhone 17 时，旧运行时被指定模拟器占着，打 ⚠️ 并给出 `simctl create` 命令。
- 删运行时失败时，打 ⚠️ 并给出手动命令，不算这一段失败。

### 不做的事

- 不清理 MobileAsset（模拟的 iOS 自己下载的模型、语音、字体）：删了会重新下载。
- 不清理指定模拟器里的 app 数据。
- 不升级 Xcode，不下载新运行时，不替用户在新运行时上建 iPhone 17（旧设备里的 app 不会跟过去，什么时候换由用户决定）。
- 不碰 dev-space 及其配置。

### 验收标准

- `xcrun simctl list devices` 只剩 iPhone 17，原来装的 condenser 和 ProbeUITests runner 及数据都在。
- CLAUDE.md 有这条规则，codex 经软链接拿到同样内容。
- 项目里写死的模拟器名字已经处理或列出。
- 新规则的 selftest 先写、先失败，实现后全部通过。
- 本机 `--dry-run --only sim`：日志一项有可删内容，Device Support 和运行时两项为 0。
- 真实运行一次 `--only sim`，df 核对释放量。

## Tech Design

### 现状

- `cleanup_simulators(dry_run)`：`simctl list devices -j` 找出 Booted 设备，`simctl shutdown all`，再退出 Simulator.app（不听 AppleScript 就发信号）。只回收进程。
- 段列表和隔离机制见上一份 spec；`sim` 不在 `DISK_TARGETS` 里，会打印内存前后对比。
- **实测前提**（2026-11-13，Xcode 27.2，iOS 26.5 运行时）：
  - **最后使用时间**：拿一台待删的 iPhone Air boot 再 shutdown。boot 时 `device.plist` 写入 `lastUsedAt`（`simctl list devices -j` 里也有），文件 mtime 变；shutdown 时文件 mtime 再变，`lastUsedAt` 不变。后来又发现 `xcodebuild -showBuildSettings -destination 'name=iPhone 17'` 选中设备时也会写 `lastUsedAt`。data 目录的 mtime 不可用：11 月 6 日 18:22:20 所有设备的 data 目录被同一时刻改过，其中包括从没用过的设备。
  - **日志结构**：`data/var/db/diagnostics/{Persist,Special,Signpost,HighVolume}/*.tracev3` 是日志本体，按序号滚动，文件关闭后 mtime 即最后写入时间；`data/var/db/uuidtext/<2位>/<UUID>` 和 `uuidtext/dsc/` 存每个二进制的格式串，日志条目按 UUID 引用它们。iPhone Air 第一次 boot 后 uuidtext 就有 125 MiB，常用设备 325 MiB。iPhone 17：diagnostics 755 MiB，其中超过 7 天的 `.tracev3` 646 MiB（206 个文件）。
  - **运行时**：`simctl runtime list -j` 每个镜像有 `identifier`、`platformIdentifier`、`runtimeIdentifier`、`version`、`build`、`state`、`deletable`、`sizeBytes`、`lastUsedAt`。`simctl runtime delete <id>` 支持 `--dry-run`。在临时 LaunchAgent（gui 域、无 tty、无 sudo）里，`runtime list` 和 `runtime delete --dry-run` 都正常。
  - **xcodebuild destination**：Xcode 27.2 下 `OS=latest`（也是默认值）解析到已装的最新运行时上的设备（iOS 26.5 的 iPhone 17），不要求装 iOS 27。指向不存在的设备名时直接报错。

### 方案

**判断信号**

| 规则 | 判断依据 |
|---|---|
| 闲置模拟器 | max(`lastUsedAt`, `device.plist` mtime)；没有 `lastUsedAt` 时就是创建时间 |
| 系统日志 | 单个 `.tracev3` 的 mtime |
| 旧运行时 | 同平台有更新的 Ready 镜像，且剩下的设备都不在它上面 |
| Device Support | 同目录、同机型有更新的版本 |

**关键决策**

- **指定模拟器的认定，`kept_sim_devices`**：
  - 名字等于 `SIM_KEEP_NAME`（脚本顶部常量，`iPhone 17`），并且在「有这个名字的可用设备」的运行时里版本最新的那个上。按名字不按 UDID：运行时升级后 UDID 会变。
  - 同名设备在更新的运行时上显示不可用（运行时还没挂载）时，一起保留。一台同名的都不可用时，同名的全部保留。
  - 找不到任何同名设备时，`plan_sim_devices` 返回空：名字写错了，不能因此把所有模拟器删掉。
  - 新运行时上没有 iPhone 17 时，旧运行时上的那台仍是指定设备，旧运行时因此保留，日志里提示 `simctl create`。不自动新建：旧设备里的 app 和数据不会跟过去，换不换由用户决定。
- **闲置模拟器，`plan_sim_devices`**：不在保留集合里、状态为 Shutdown、最后使用早于 `--sim-days`。在哪个运行时上、可用与否都一样处理。
  - 用 `simctl delete <udid>…` 逐台删，不用 `simctl delete unavailable`。运行时短暂未挂载时设备会显示不可用，批量命令会把指定设备一起删掉。不可用的设备走同一条闲置规则。（brief 要求的一次性 `delete unavailable` 照做了，当时所有设备都可用，是空操作。）
- **系统日志，`plan_sim_logs`**：只删 `diagnostics` 下 mtime 超过 `--sim-days` 的 `.tracev3`，只处理 Shutdown 状态、且本轮不会被删除的设备。
  - 选这个方案，不选「模拟器整体闲置 7 天就清空日志」：后者正好清不到最需要清的指定模拟器（天天在用，646 MiB 旧日志），而闲置的非指定模拟器本来就会被整台删掉。
  - uuidtext 不动：新日志还可能引用很早写入的格式串文件，按 mtime 删会让近期日志解码不出来。删除旧 `.tracev3` 等于提前做了 logd 自己的滚动删除，剩下的日志照常能解码。首次真实运行后开机 `log show` 核对过。
  - `logd.*.log`、`logdata.statistics.*` 等文本文件很小，不处理。
- **旧运行时，`plan_sim_runtimes`**：
  - 只看 `deletable` 且 `state == Ready` 的镜像。不是 Ready 的（正在添加、不可用）既不删，也不参与「谁最新」的比较，避免新运行时还在挂载时就把旧的删掉。
  - 按 `platformIdentifier` 分组，最新的 = 版本号按数字比较（`version_tuple`，`26.10` > `26.9`），同版本再比 build（`build_key`：`23F79` > `23F77` > `23F5054e`，正式版高于同一 train 的 beta）。
  - 其余镜像：如果和最新的是同一个 `runtimeIdentifier`（同版本的旧 build），设备会改用新 build，直接删；否则看本轮删完闲置设备后还剩的设备里有没有在它上面的，有就保留并列出设备名。
  - 真实运行时，删完设备后重新 `simctl list devices -j` 再规划一次：设备删除失败时，它的运行时不会被删。
  - 删除用 `simctl runtime delete <identifier>`。失败时降级为提醒，不让这一段失败。
- **Device Support，`plan_device_support`**：遍历 `~/Library/Developer/Xcode/* DeviceSupport`。文件夹名按 `<model> <version> (<build>)[ <arch>]` 解析，model 可缺（Xcode 14.3 以前的格式，归为一组）。同组按 (版本, build, mtime) 排序，只留最后一个。解析不了的名字不动。删除时先改名进同目录的 trash，再 `rmtree_force`（`remove_trees`）。
- **忙碌判断**：`ps` 里有命令以 `xcodebuild`、`simctl` 或 `xcrun simctl|xcodebuild` 开头的进程（`SIM_BUSY_RE`，任何年龄），磁盘部分本轮整体跳过。06:00 时 shutdown 在前，被打断的 xcodebuild 可能还在退出途中，跳过一天无妨。
- **报告**：四项一律打印，包括 0 项。运行时一行显示镜像 `sizeBytes`，不做 du。最后报卷剩余空间的实际变化。返回值是 du 字节数加运行时大小，供 dry-run 的退出码使用。

### 数据变动

- 无新状态文件，不改任何工具的配置。

### 逻辑变动（都在 `mac-dev-cleanup`）

- 顶部常量 `SIM_KEEP_NAME = "iPhone 17"`。
- sim 段新增：`SIM_BUSY_RE`、`SIM_RUNTIME_ID_RE`、`APPLE_BUILD_RE`、`DEVICE_SUPPORT_RE`、`XCODE_DIR`；数据类 `SimDevice`、`SimRuntime`；`runtime_key`、`build_key`、`parse_sim_devices`、`kept_sim_devices`、`plan_sim_devices`、`plan_sim_logs`、`parse_sim_runtimes`、`plan_sim_runtimes`、`plan_device_support`、`remove_trees`、`sim_label`、`runtime_label`。
- `cleanup_simulators(keep_name, days, dry_run)` 拆成 `shutdown_simulators`（原逻辑；没有开着的模拟器时打印「no simulator running」，不再提前返回）和 `prune_simulators`（新四条）。
- argparse 新增 `--sim-days`（默认 7），同时管闲置模拟器和日志。
- 模块 docstring 同步更新。

### 实施步骤

- [x] 实测前提：boot/shutdown 看哪个时间戳变；日志目录结构和各设备的可删量；`runtime delete` 的参数；launchd 下 `runtime delete --dry-run`；`OS=latest` 的解析。
- [x] selftest 先行：`selftest_sim` 写好后先跑，`NameError: runtime_key` 失败。
- [x] 实现四条规则和报告，`--selftest` 全部通过（233 项）。
- [x] 一次性：删除 10 台模拟器、`simctl delete unavailable`、改 CLAUDE.md、改项目文件。
- [x] 本机 `--dry-run --only sim`，再真实运行一次，df 核对。
- [x] 假 `xcrun` 端到端演练删设备、删运行时（成功和失败两种）、缺 iPhone 17 的提示：`tmp/2026-11-13-ios-sim-cleanup/e2e/`。
- [x] 更新 `SKILL.md` 和 `kb/known-issues.md`。

### 测试与验证

| PRD 验收标准 | 怎么验 |
|---|---|
| 只剩 iPhone 17，app 和数据都在 | `xcrun simctl list devices`；删除前后列 `data/Containers` 里的 bundle id 和大小做 diff；开机后 `simctl listapps` |
| CLAUDE.md 规则，codex 同步 | 编辑软链接目标；`~/.codex/AGENTS.md` → `../.claude/CLAUDE.md` |
| 项目里的模拟器名字 | `rg` 扫 `~/Code`，逐条判断：配置和指令改，历史记录（sessions、已完成的 plan）不改 |
| selftest | 覆盖：开机的模拟器不动、指定模拟器永不删除、找不到指定模拟器时什么都不删、只有一个版本时什么都不删、版本号按数字比较（运行时和 Device Support 都测）、未挂载的同名设备保留、非 Ready 的新运行时不挤掉旧的、uuidtext 不动、本轮被删设备的日志不重复计算、只读目录能删、不留 trash |
| dry-run 输出 | 见下 |
| df 核对 | 真实运行前后 `df -k` |

本机结果（2026-11-13）：

| 步骤 | 内容 | 释放 |
|---|---|---|
| 一次性删除 10 台模拟器 | Devices 11 GiB → 3.7 GiB | df 55.81 → 62.89 GiB，+7.08 GiB（APFS 后台回收，约 4 分钟后稳定；期间有其他进程写盘，仅供参考） |
| `--dry-run --only sim` | 闲置 0，日志 206 个 646 MiB，运行时 0，Device Support 0 | — |
| 真实运行 `--only sim` | 删除 206 个 `.tracev3` | 脚本报 +645.6 MiB，df +646.0 MiB |

### 风险与待定

- 真实的 `simctl runtime delete` 没跑过（只有一个运行时），已记入 known-issues。
- 换代时旧 iPhone 17 里的 app 和数据不会迁移：新运行时上有 iPhone 17 后，旧的那台闲置 7 天就被删。
- `SIM_BUSY_RE` 不限进程年龄，挂死的 `simctl`（2026-10-23 见过 `simctl list` 卡 60 秒）会让磁盘部分天天跳过，只能从日志里看到。
