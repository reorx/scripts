---
created: 2026-11-13
tags:
  - disk-cleanup
  - dev-space
  - lacie
  - sqlite-backup
---

# 项目规则引擎：按项目精准清理、归档到 LaCie、live 主库离机备份

所属总 plan：[开发目录与全局缓存的精准清理和监控系统](2026-11-13-dev-disk-cleanup.md)。与 [全局缓存清理段](2026-11-13-global-cache-sections-spec.md) 并行，[监控与告警](2026-11-13-dev-space-watch-spec.md) 建在本期之上。

## PRD

### 背景

`~/Code` 各项目的占用里，可再生或很少再看的内容占了很大一部分：

- 验收时复制进 `tmp/<日期>-<任务>/` 的 DerivedData、`.build`、node_modules、sqlite 副本；
- `.next/cache`、SwiftPM 的 index-build 这类构建缓存；
- 服务每次迁移前自动留下的数据库备份；
- 早已没人碰的项目里整套的 node_modules / .venv。

7 个重点项目的调研报告在 `tmp/2026-11-13-dev-cleanup/<项目>.md`，每个项目要留什么、能删什么都不一样。

### 目标

- 每个项目一份声明式规则，再加一套所有项目共用的默认规则，每天自动执行。
- 需要保留、但很少看的证据和备份搬到 LaCie，原位置留软链接，可以一条命令恢复。
- vibench-live 主库每天在 LaCie 上留一份离机备份。

### 功能与交互

**一条命令执行清理**：`dev-space clean`。

- 不带参数时，执行所有项目的每日档规则。
- 可以按项目、规则、档位筛选。
- `-n` 只预览不动手，`-v` 逐项列出每个目标的路径、大小和最近修改时间。
- 06:00 任务用 `--scheduled` 调用。磁盘剩余低于 15 GiB 时，自动多执行吃紧档。

**报告**：

- 按项目、按规则各一行：处理了几项，du 多少。
- 被保护跳过的项单独列出原因：正被进程使用、被 git 跟踪、含不能上 exFAT 的内容、命中保护名单。
- 最后一行写总 du 和磁盘剩余空间的实际变化。
- 每一次删除、归档都记入审计日志，事后可以查到删了什么、为什么删。

**三种动作**：

- **删除**：只删可再生的生成物。
- **归档**：
  - 搬到 `/Volumes/LaCie/DevArchive/<项目>/`，按家目录下的相对路径存放。
  - 复制后逐个文件读回比对，一致才删除本地，原位置换成软链接。
  - LaCie 没挂载时整类跳过，并写明原因。
- **SQLite 备份**：
  - 对正在运行的库做一致快照，校验完整性后压缩存到 LaCie。
  - 每天一份，保留最近 7 天每天一份，再加最近 8 周每周一份。
  - 当天已有备份时跳过。

**恢复**：`dev-space restore <路径>` 把归档的目录或文件从 LaCie 复制回原位置，替换掉软链接。LaCie 上的那份保留不动。

**查看规则**：`dev-space rules [项目]` 列出某个项目实际生效的规则，包括默认规则。

**所有项目共用的默认规则**（作用于 `~/Code` 下每个 git 项目，cw_edge 和 vibench-live 除外）：

| 规则 | 内容 | 档位 |
|---|---|---|
| tmp 构建产物 | `tmp/` 里 7 天未改动的 DerivedData、`.build`、node_modules、`.venv`、`target` | 每日（吃紧时 3 天） |
| tmp 数据库副本 | `tmp/` 子目录里 7 天未改动的 sqlite / db 副本 | 每日（吃紧时 3 天） |
| 验收证据归档 | 14 天没改动的 `tmp/<日期>-<任务>/` 目录搬到 LaCie | 每日 |
| 编辑器索引与构建缓存 | 7 天未改动的 SwiftPM index-build、Next.js `.next/cache` | 每日 |
| 闲置项目依赖 | 项目 30 天没有提交、也没有改动时，删掉它的 node_modules、`.venv`、`.build`、`.next` 等依赖和构建目录 | 每日（吃紧时 14 天） |

**7 个重点项目各自的规则**，在报告的基础上整理，并落实用户已确定的决策：

- vibench：
  - tmp 里的库拷贝；
  - 发布用的 tar 包，保留最新 2 个；
  - 开发库的迁移前备份，保留最新 3 个；
  - e2e 运行目录。
- vibench-live：
  - 部署快照本地只留最新 2 份，其余每天归档；
  - 迁移前备份全部归档；
  - 主库每天离机备份；
  - 身份文件备份和活库永远不碰。
- campus_watch：Next.js 构建缓存；30 天以上的生产库 dump 归档，本地留最新 2 个；下载物和旧发布包为手动档。
- stickyfingers：tmp 里的 DerivedData、评审用的包副本；`.build` 闲置 7–14 天后删除。
- vocalflow-mac：tmp 里的 DerivedData 和更新包副本；SwiftPM 输出；主 DerivedData 闲置 14 天后删除。正在运行的 Debug App 不受影响。
- feishu-lite：构建产物、ruff/pytest 缓存；旧 DMG 只留 2 个（手动档）。
- condenser：tmp 里的重型拷贝；iOS DerivedData；tmp 根目录的旧快照库。常驻 probe 用到的部分不碰。
- agent-session-manager：tmp 里的索引库拷贝。

**任何规则都绕不过的安全底线**：

- 只处理 git 已忽略的内容。git 跟踪的、未忽略的未跟踪文件（可能是正在写的东西），一律不碰。
- 正被任何进程打开、作为工作目录或可执行文件使用的目录，跳过。
- 不跟随软链接，不碰已经归档过的软链接，不处理规则所属目录之外的东西。
- 命中保护名单（活库、身份文件备份等）的，跳过。
- 归档时，含 `.git`、软链接、`.app`、密钥类文件（`.env`、私钥、`.gnupg` 等）的目录不搬：exFAT 没有权限位，密钥会裸露在外接盘上。

### 不做的事

- 不删除整个项目、兄弟副本或 git worktree：这些在一次性清单里，由用户逐项批准。
- 不清理全局缓存：那是 ② 的范围。
- 不做监控和告警：那是 ③ 的范围。
- 不加密 LaCie 上的归档和备份。

### 验收标准

- `dev-space clean -n -v` 列出的每一项，都符合上面的默认规则或项目规则；安全底线里的东西一项都不出现。
- 真实执行后，审计日志里的条目和报告一致，磁盘剩余空间回升。
- 对一个已归档的目录执行 `dev-space restore`，内容和归档前一致（文件数、大小、修改时间）。
- 断开 LaCie 时执行，归档和备份写明「LaCie 未挂载，跳过」，其余规则照常。
- vibench-live 的离机备份能解压，`integrity_check` 通过，行数和活库一致；同一天再跑一次不会重复备份。
- 有进程在使用的目录（如 vibench 的 `tmp/hosted-pwa-relay`）不被删除。

## Tech Design

### 现状

- `mac-dev-cleanup`（`skills/systools/scripts/`）是单文件 uv 脚本，靠 `--selftest` 做行为检查，每天 06:00 由 `launchd/com.reorx.mac-dev-cleanup.plist` 触发。cargo 段和 uv 段的写法是本期的参照：
  - 先「重命名进回收站目录」，再删除；
  - 同时报告 du 和卷剩余空间的变化；
  - 不认识的布局就跳过。
- 同目录有 `test_mac_keepawake.py`：用 `importlib.machinery.SourceFileLoader` 加载没有扩展名的脚本，用 unittest 写行为测试。本期照这个做法。
- 规则草稿在各项目报告的 TOML 里，格式是统一下发的 `tmp/2026-11-13-dev-cleanup/BRIEF.md`。报告提出的引擎需求有：`**` 递归匹配、`exclude`、`keep_newest`、进程占用检测、伴随文件（`.sha256`）、规则顺序、exFAT 安全检查。

### 方案

新增 `skills/systools/scripts/dev-space`，单文件、只用标准库、`#!/usr/bin/env -S uv run --script`，Python ≥ 3.11（需要 `tomllib`）。规则写在 `skills/systools/config/dev-space.toml`。

执行流程：

1. 读配置，校验。
2. 展开出「规则 × 基准目录」，再按 glob 找出候选目标。
3. 对每个候选依次过安全检查和时间条件。
4. 执行动作，写审计日志，汇总报告。

关键决策：

- **规则用声明式 TOML，不给每个项目写脚本。**
  - 7 份报告提出的需求都能用同一组字段表达。
  - 分析 agent 的提案也能直接产出同样格式。
  - 安全检查只需要在引擎里实现一次。
  - 被否决：每个项目一个 `cleanup.sh`。各自实现安全检查，没法统一审计。
- **自己实现 glob 匹配，不用 `glob.glob`。**
  - 需要一边遍历一边剪枝：不进 `.git`，不进已匹配的目标（取最外层），不进不可能匹配的子树。
  - `glob.glob("**")` 会把 node_modules 走一遍，大项目要几分钟。
- **「最近修改」取目标内所有文件（含软链接本身）的 mtime 最大值，不看目录的 mtime，并且提前退出**：
  - 找到一个比截止时间新的文件就停止遍历。
  - 不看目录 mtime，是因为删掉一个子目录（比如本工具刚删掉的 DerivedData）会刷新父目录的 mtime，让证据目录的归档无端推迟 14 天。
  - 空目录用它自己的 mtime。
  - atime 在这台 Mac 上不可靠，不用。
- **安全检查放在引擎里，规则绕不过去。**
  - git 状态：每个 worktree 批量调用一次 `git ls-files` 和 `git check-ignore --stdin`。
  - 进程占用：整次运行只取一次 `lsof -nP -w -F n -u <uid>` 快照，按路径前缀匹配，覆盖 cwd、txt 和打开的文件。
- **执行顺序固定**：每个项目先执行删除，再归档，最后备份。同一种动作里，先默认规则，再项目规则（按文件顺序）。
  - 先删重型产物，再归档剩下的证据，归档的体积才小。
  - condenser 两条规则匹配有重叠，按顺序执行后，后一条遇到不存在的目标就跳过。
- **归档先复制、校验，再替换。**
  1. 复制到 `<dest>.partial-<pid>`，边复制边计算源文件的 sha256，并保留 mtime。
  2. 从 LaCie 读回，逐个比对 hash。
  3. 把 `.partial` 重命名为正式目标。
  4. 本地目标重命名进回收站，原位置建软链接。
  5. 删除回收站。

  软链接建失败时，把回收站里的内容移回原位。
- **挂载判断**：归档根如果在 `/Volumes/<卷>/` 下，必须 `os.path.ismount('/Volumes/<卷>')` 成立。否则盘没挂时，可能把数据写进系统盘上的同名空目录。
- **SQLite 备份用 `VACUUM INTO`**，和 vibench deploy 的做法一致。
  - 以只读 URI 打开源库，`VACUUM INTO` 写到本地状态目录的临时文件。
  - 对副本做 `integrity_check`，然后 gzip 流式写到 LaCie 的 `.partial`，再解压读回比对 hash，最后重命名。
  - 不直接写到 LaCie：exFAT 上 SQLite 的文件锁行为没有保证。
- **真实释放量**：
  - 预估时，用 `getattrlist` 的 clone id 和引用计数（`ATTR_CMNEXT_CLONEID` / `CLONE_REFCNT`）判断：一个 clone 组或硬链接组的成员全部在待删集合里，才计入。算法取自原型 `tmp/2026-11-13-dev-cleanup/proto/apfs.py`，补上硬链接计数。
  - 实际执行时，额外报告卷剩余空间的变化。

### 数据变动

**配置 `skills/systools/config/dev-space.toml`**：

```toml
[settings]
code_root = "~/Code"
archive_root = "/Volumes/LaCie/DevArchive"
state_dir = "~/.local/state/dev-space"
pressure_free = "15GiB"            # 低于它时 --scheduled 加跑吃紧档
defaults_exclude = ["~/Code/cw_edge", "~/Code/vibench-live"]   # 不套默认规则的目录
protect = []                       # 全局保护 glob（是它或包含它的目标都不碰）

[[defaults.rules]]                 # 默认规则，作用于 code_root 下每个 git 项目（顶层目录）
# 字段同项目规则

[projects.<name>]
root = "~/Code/<name>"
related = []                       # 属于本项目的其他目录（兄弟副本、~/Library 下的数据）
alert_size = "15GiB"               # ③ 用
skip_defaults = []                 # 本项目不套用的默认规则 id，"*" 表示全部
protect = []                       # 本项目的保护 glob

[[projects.<name>.rules]]
id = "kebab-id"                    # 必填，项目内唯一
why = "..."                        # 必填
action = "delete"                  # delete | archive | sqlite-backup
when = "daily"                     # daily | pressure | manual，默认 manual
paths = ["tmp/**/*.sqlite"]        # 相对 root，或绝对、~ 路径；* ? [..] **
exclude = []                       # 是它或包含它的目标跳过
age_days = 0                       # 目标内最新 mtime 早于 N 天
pressure_age_days = 3              # 吃紧档下替代 age_days（可选）
keep_newest = 0                    # 按最新 mtime 保留前 N 个匹配
idle_days = 0                      # 目标所在 worktree 闲置 N 天（无提交、无未提交改动）
pressure_idle_days = 14            # 吃紧档下替代 idle_days（可选）
companions = [".sha256"]           # 随目标一起处理的同名后缀文件
# sqlite-backup 专用：source = "<db 路径>"，keep_daily = 7，keep_weekly = 8
```

- 校验：
  - 未知字段、未知 action / when、缺 `id` 或 `why`、项目内 id 重复，都直接报错退出，指出是哪个项目的哪条规则。
  - 拼错的字段（如 `age_day`）如果被静默忽略，规则会悄悄失效，所以必须报错。
- `paths` 的基准目录：
  - 项目规则的相对路径只对 root 展开。要碰 related 目录，必须写绝对路径或 `~` 路径。否则 vibench 的规则会悄悄作用到 vibench-live 和 vibench-old 上。
  - 默认规则对 root 和每个是 git 项目的 related 目录各展开一次。
- 匹配到的目标必须落在 root 或某个 related 之内（按 realpath 判断）。

**状态目录 `~/.local/state/dev-space/`**：

- `actions.jsonl`：审计日志，每行一条。字段有 ts、project、rule、action、path、dest、du_bytes、files。
- `archive-manifest.jsonl`：每次归档、恢复的记录。LaCie 根目录也追加一份 `MANIFEST.jsonl`，盘离开这台机器也能知道东西从哪来。
- `trash/`：回收站，与数据同卷，所以 rename 是原子操作。
- `tmp/`：SQLite 备份的临时文件。

**LaCie 上的布局**：

- `DevArchive/<项目>/<相对 $HOME 的路径>`：归档的目录或文件。
- `DevArchive/<项目>/sqlite-backups/<规则 id>/<库名>-<UTC 时间>.sqlite.gz`：SQLite 备份。

### 逻辑变动

`dev-space` 内的模块划分（单文件，按段落组织）：

- **配置**：`load_config(path) -> Config`，用 dataclass `Settings`、`Project`、`Rule` 承载并校验。`effective_rules(config, project_dir)` 合并默认规则和项目规则。默认规则作用于 code_root 下有 `.git` 的顶层目录，扣掉 `defaults_exclude`、`skip_defaults`。不在 `projects` 里的目录，作为只套默认规则的匿名项目。
- **匹配**：
  - `compile_glob(pattern)` 把 pattern 拆成段，支持 `**`。
  - `match_units(base, patterns) -> list[Path]` 用 `os.scandir` 自上而下遍历：判断前缀能否匹配，不能就剪枝；跳过 `.git`；目标一旦匹配，不再深入。
- **度量**：
  - `newest_mtime(path, stop_after)`：可提前退出。
  - `measure(paths) -> (du, real)`：按 inode 去重；clone 组或硬链接组的成员全部在集合内才计入 real。
- **安全检查**：`Guard` 持有本次运行的 lsof 快照、各 worktree 的 git 信息缓存和保护 glob。`guard.reason(unit) -> str | None` 返回跳过原因。依次检查：
  1. 是不是软链接；
  2. 是否越界；
  3. 是否命中保护名单或 exclude；
  4. 是否被 git 跟踪；
  5. 在 worktree 内时是否被 ignore；
  6. 是否被进程使用。
- **worktree**：`find_worktree(path)` 向上找 `.git`。`worktree_idle_seconds(wt)` 取 `git log -1 --format=%ct` 和 `git status --porcelain -z` 里各路径 mtime 的最大值，与当前时间的差就是闲置时长。如果规则有 `idle_days`，先对基准目录本身判断，不闲置就不展开 glob，省去整棵树的遍历。
- **选择**：`select(rule, units, tier, now)` 依次应用 age、keep_newest、idle。吃紧档下，用 `pressure_*` 字段替代原值。
- **动作**：
  - `delete_units`：重命名进 trash 后 rmtree。如果跨卷导致 rename 失败（`EXDEV`），直接 rmtree。伴随文件一起处理。
  - `archive_units`：先检查 exFAT 安全（软链接、`.git`、`*.app`、密钥名单、exFAT 非法字符 `: * ? " < > | \`），然后执行上面的复制、校验、替换流程。
  - `sqlite_backup`：见方案。保留策略的实现：按 UTC 日期分组，每天保留最新一份；在此基础上保留最近 `keep_daily` 天，加上最近 `keep_weekly` 个 ISO 周里每周最新的一份。
  - `restore(path)`：path 必须是指向 archive_root 的软链接。复制回 `<path>.restoring`，校验后替换软链接，并写入 manifest。
- **命令行**：
  - `clean [-n] [-v] [--scheduled | --tier daily|pressure|manual] [-p PROJECT]... [-r RULE]... [--config PATH]`
  - `restore PATH [-n]`
  - `rules [PROJECT]`
  - `scan`、`watch` 在 ③ 中加。
  - 档位是累加的：`pressure` 包含 `daily`，`manual` 包含全部。
  - 退出码：0 表示成功；2 表示某个项目执行出错，其余项目照常；`-n` 下有东西可清时返回 1。
  - 不是终端时（launchd 下），开头打印时间戳行。
- **报告**：
  - 每个项目一个标题行，每条规则一行：动作、数量、du、real。
  - 跳过的项按原因汇总一行，`-v` 时逐项列出。
  - 最后打印总计，以及卷剩余空间的前后变化。

### 实施步骤

- [x] 写 `test_dev_space.py` 的行为用例（见下），全部先失败
- [x] 实现配置加载与校验、glob 匹配、度量
- [x] 实现 Guard（git、lsof、保护名单、exclude）和选择逻辑，删除动作
- [x] 实现归档、恢复、exFAT 安全检查
- [x] 实现 SQLite 备份和保留策略
- [x] 命令行与报告；`rules` 子命令
- [x] 把 7 份报告的规则整理进 `config/dev-space.toml`：`auto` 改写成 `when`，落实用户决策，补上 protect / exclude
- [x] 在真实目录上跑 `dev-space clean -n -v --tier manual`，逐项核对，修正规则
- [x] `./link-script` 把 `dev-space` 链接进 `~/.local/bin`

### 测试与验证

`skills/systools/scripts/test_dev_space.py`，unittest。在临时目录里建真实的 git 仓库，时间用 `os.utime` 构造，lsof 快照和卷剩余空间由测试注入。用例：

| 验收点 | 用例 |
|---|---|
| 匹配 | `tmp/**/*.sqlite` 能匹配多层嵌套；`tmp/*/DerivedData` 只匹配第 2 层；node_modules 里的 node_modules 不单独算；不进入 `.git` |
| 时间 | 目标内任一文件比截止时间新就保留；`keep_newest` 保住最新 N 个；`idle_days`：近期有提交、或有近期未提交改动时不闲置 |
| 安全底线 | 含被跟踪文件、未被 ignore、软链接、软链接越界、命中 protect、命中或包含 exclude、在 lsof 快照里，这些目标全部跳过并给出原因 |
| 删除 | 删除后目标消失；伴随文件一起消失；dry-run 一个字节都不动；审计日志的条目和报告一致 |
| 档位 | 每日档不跑 manual 和 pressure；`--scheduled` 在剩余空间低于阈值时切到吃紧档，并使用 `pressure_age_days` |
| 默认规则 | 作用于 code_root 下的 git 项目；`defaults_exclude`、`skip_defaults` 生效；非 git 目录不套 |
| 归档 | 目标出现在假 LaCie 下，软链接指向它，mtime 保留，manifest 有记录；含软链接、`.git`、`.app`、`.env` 的目标被拒；归档根不是挂载点或不存在时跳过；`restore` 恢复后内容一致 |
| SQLite 备份 | 对 WAL 模式、仍有连接打开的库做备份，解压后 `integrity_check` 为 ok、行数一致；同一天第二次跳过；保留策略按日、按周正确淘汰 |
| 配置 | 未知字段、未知 action、重复 id 时报错，并指出项目和规则 |
| 度量 | clone 出来的两个文件只删一个时 real 为 0，两个都删时 real 为 1 份；硬链接同理 |

实机验证：

1. 在真实目录上跑 `dev-space clean -n -v --tier manual`。
2. 把清单中涉及 vibench-live、campus_watch tmp、stickyfingers kernel-eval 的条目逐一过目，确认活库、身份文件、`.app` 内核没有出现在待删列表里。
3. 展示给用户，用户批准后再真实执行。

### 风险与待定

- `lsof` 快照对全部进程只取一次，大约需要几秒。快照之后才打开的文件看不到，属于可接受的窗口：被处理的目标都已至少 7 天没改动。
- 只靠 mtime 判断，只读不写的使用者看不出来（例如常驻进程反复读一个旧目录）。lsof 只能抓到运行那一刻打开着的文件，所以证据类目录走归档而不是删除，可以恢复。
- exFAT 不保留权限，归档的证据和备份在 LaCie 上不加密。密钥类文件由检查名单拦下，数据库备份按用户要求放上去。
- vibench-live 快照的旧格式目录（数字命名）里有 bin 拷贝。可执行位会丢失，恢复时需要 `chmod`；如果里面有软链接，就会被拒绝归档并留在本地，需要实测确认。
