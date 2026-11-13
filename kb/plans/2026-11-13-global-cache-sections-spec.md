---
created: 2026-11-13
tags:
  - disk-cleanup
  - mac-dev-cleanup
  - go
  - pnpm
  - npm
  - uv
  - cargo
  - codex
---

# 全局缓存清理段：go、pnpm、npm、codex，uv 与 cargo 改为一周

所属总 plan：[开发目录与全局缓存的精准清理和监控系统](2026-11-13-dev-disk-cleanup.md)。与 [项目规则引擎](2026-11-13-dev-space-rules-spec.md) 并行开发。

## PRD

### 背景

`mac-dev-cleanup` 每天 06:00 已经会清 cargo 共享 target（21 天）和 uv 缓存（90 天，按创建时间算）。其余全局开发缓存没人管：

- go 模块缓存约 7.4 GiB；
- pnpm 的 store、dlx、metadata 约 18 GiB（按 du 算）；
- npm 的 `_cacache` 和 `_npx` 约 3.4 GiB；
- codex 会话每天增长约 60 MB，`~/.codex` 共 5.6 GiB。

用户的目标是一周没用就算过期，但有用的缓存要留下。现有 uv 的 90 天策略今天实际一点空间都腾不出来。cargo 如果直接改成 7 天，常用依赖每周会被重编一次：这台 Mac 上的 atime 只记录「重编后第一次构建」的时间，不是真正的最近使用时间。

调研：`tmp/2026-11-13-dev-cleanup/global-caches.md`、`agent-sessions.md`，原型在同目录 `proto/`。

### 目标

- 06:00 的任务把上述缓存中已过期、无人引用的部分清掉。
- 正在使用或被活跃项目引用的条目原样保留。
- 每一段都报告 du 大小和真实腾出的空间。
- 同一个任务里，同时接入项目规则和监控两步。

### 功能与交互

**新增四段，默认随每日任务运行，也可以用 `--only <段名>` 单独运行，`--dry-run` 下只报告。**

- **go**：
  - 保留两类模块版本：一是 `~/Code` 下最近活跃的项目在 go.sum 里引用的版本，二是 7 天内下载的版本。其余版本的解压目录和下载包都删掉。
  - go 自带的构建缓存会自己清理，不处理。
  - 有 go 命令正在运行时，本次跳过。
- **pnpm**：
  - 不用 `pnpm store prune`。在这台机器上，它会把整个 store 清空。
  - store 里保留被现存 node_modules 引用的包，删除无人引用、并且超过 7 天的包。
  - dlx 临时目录和 metadata 缓存超过 7 天未用的删除。
- **npm**：
  - `_cacache` 里超过 7 天的索引项和它们独占的内容删除。
  - `_npx` 里超过 7 天未运行的目录删除，正在运行的 npx 进程所在目录跳过。
- **codex**：
  - 7 天未更新的会话压缩成 zstd。压缩后 `codex resume` 照常可用。
  - 30 天未更新的会话用官方 `codex delete` 删除，索引同步清理。
  - 正被 codex 进程打开的会话、置顶会话、还有活跃子会话的父会话都跳过。
  - 不再被任何进程使用的旧版本安装包删除。

**两项调整：**

- **uv**：
  - 被最近活跃项目的 lock 文件引用的 wheel 保留。
  - 脚本还在的 `uv run --script` 环境保留。
  - 其余下载的 wheel 和缓存环境满 7 天删除。
- **cargo**：
  - 默认改为 7 天。
  - 先修正「最近使用」时间，让每天都在用的依赖不会被清掉。

**接入 06:00 任务的两段：**

- `projects`：调用 dev-space 跑项目规则，放在所有缓存段之前。
- `watch`：调用 dev-space 做监控，放在最后。

**报告和失败处理：**

- 每段一行汇总：清了几项，du 多少，真实多少。没东西可清时写「nothing to clean」。
- 跳过时写明原因：工具未安装、布局版本不认识、有进程正在使用。
- 某一段失败不影响其余各段，整体退出码为 2。

### 不做的事

- 不处理 go 构建缓存，它会自己清理。
- 不处理 `~/.cargo/registry`，cargo 自己会清理。
- 不对 codex 数据库做 VACUUM：需要所有 codex 进程退出，只列入一次性清单。
- 不处理其他 agent 的会话目录（`~/.hermes`、`~/.openclaw` 等），它们都很小或没有过期必要。
- 不改 pnpm、npm、codex 的全局配置。

### 验收标准

- `mac-dev-cleanup --dry-run` 列出 go、pnpm、npm、codex、uv、cargo 各段的计划，每段同时显示 du 大小和真实大小。
- 在活跃项目里跑一次 `pnpm install`、`uv sync`、`go build`，三个都不需要重新下载依赖。
- 压缩过的 codex 会话能在 `codex resume` 列表里看到并打开。被删的会话从列表里消失，没有留下打不开的条目。
- 正在运行的 npx MCP 进程、常驻的 `uv run` 任务、打开中的 codex 会话都不受影响。
- `--selftest` 覆盖每段的选择逻辑并全部通过。

## Tech Design

### 现状

- 全部逻辑都在 `skills/systools/scripts/mac-dev-cleanup` 里，是单文件 uv script，标准库实现，带 `--selftest`。
  - `run_sections` 让每段相互隔离：一段崩溃不影响其余各段，整体退出码为 2。
  - `--dry-run` 下，有东西可清时退出码为 1。
  - 段列表 `DEFAULT_TARGETS` 现在是 `browser, sim, cargo, uv, clones`。`DISK_TARGETS` 决定是否打印内存前后对比。
- **cargo 段**：
  - 在临时目录建一个 stub 项目，经 `cargo metadata` 找到共享 target。
  - 拿到 cargo 的全部构建锁之后，先跑 `cargo sweep --time 21`，再跑 `cargo sweep --maxsize 20GiB`。
  - `reset_polluted_atimes` 会把被外部读过的 fingerprint json 的 atime 拨回 mtime。
- **uv 段**：
  - `plan_uv_cleanup` 按创建时间筛条目：wheel 和缓存环境超过 `--uv-days`（90）天才删，孤儿 archive 和旧 bucket 超过 1 天即删。
  - `apply_uv_plan` 把要删的条目先改名进 trash 目录，再整体删除。
  - 缓存锁的持有者里，有启动不到 10 分钟的就整段跳过。
- **调研结论**：报告在 `tmp/2026-11-13-dev-cleanup/global-caches.md`、`agent-sessions.md`，原型在同目录 `proto/`。实现前又实测核对了以下几点：
  - **APFS clone 的度量**：原型读的 `0x200` 其实是 `ATTR_CMNEXT_EXT_FLAGS`，克隆过的文件恒为 `0x41`，所以报告里的 real 数字都偏低。真正的克隆成员数是 `ATTR_CMNEXT_CLONE_REFCNT`（`0x1000`）：单独一份时为 1，克隆 N 份时为 N。同一组成员共享 `ATTR_CMNEXT_CLONEID`（`0x100`）。`ATTR_CMNEXT_PRIVATESIZE`（`0x8`）是只删这一个文件能释放的字节数。
  - **atime 规则**：这台 Mac 只在读取时 atime < mtime 的情况下才更新 atime，没有 Linux relatime 那种「超过 24 小时也更新」的规则，ctime 也不影响。
    - 把 atime 拨到 mtime 之前（下称「上膛」）后，下一次读取会把 atime 记成当时的时间。
    - 在 `~/Library/Caches` 下上膛的文件，3 分钟内没有被 Spotlight 等后台服务读过。
    - cargo 1.98 无需重编的构建会读 fingerprint 单元里的 hash、dep-info、json 和 `invoked.timestamp`。
    - cargo-sweep 0.8.0（`fingerprint.rs` 的 `last_used_time`）取单元目录里所有文件 atime 的最大值。
  - **codex**：对照 `rust-v0.167.0`。
    - `open_rollout_line_reader` 和 `materialize_rollout_for_append` 对 `.jsonl.zst` 的处理不受 feature flag 控制，flag 只控制后台压缩 worker。
    - 写锁协议：所有 writer 都先对 `thread-writer-locks/.coordination.lock` 加 flock，再对 `<id>.lock` 加 flock。发布压缩文件时只拿协调锁，并探测线程锁是否空闲。
    - `codex delete` 同时删除 `.jsonl` 和 `.jsonl.zst`。被 fork 引用、或带附属子线程的会话，它会拒绝删除。
    - 在一条一次性会话上实测：`codex delete --force <uuid>` 无头运行，约 2 秒，退出码 0，`threads` 行、`thread_items` 和 rollout 文件全部删除。不带 `--force` 时没有终端可确认，退出码 1。
  - **pnpm 10.15.0**：
    - store 的 index 文件名是 `<hash>-<name>@<version>.json`。scoped 包用 `@scope+name`，与 `node_modules/.pnpm/` 下的目录名一致，原型把两边转换得不一致。
    - 有 44 个 index 带 `sideEffects.<key>.added`，这些文件也要保留，原型没处理。
  - **其他工具版本**：go 1.25.7（`GOMODCACHE=~/go/pkg/mod`），npm 11.20.0，codex 0.167.1，uv 0.9.17。

### 方案

各缓存段的整体思路一样：先确定「谁还在用、被谁引用」，再删除既没人用、又超过 7 天的条目。

**判断信号**

| 缓存 | 怎么判断还在用 |
|---|---|
| go | 引用：最近活跃项目的 go.sum |
| uv | 引用：最近活跃项目的 lock 文件和 `.venv`，以及 `~/Code` 下还存在的脚本 |
| pnpm | 引用：现存的 `node_modules/.pnpm` |
| npm、codex | 最后写入时间 |
| cargo | 修正后的真实最近使用时间 |

**共用规则**

- 遇到不认识的版本或布局时，整段跳过并打 ⚠️，不猜。
- 有同类进程刚启动不到 10 分钟时，可能正在安装，整段跳过，照搬 uv 段的做法。pnpm、npm 只算会写缓存的子命令（pnpm 的 `install`、`add`、`dlx`，npm 的 `install`、`ci`、`update` 等）；`pnpm exec vite preview`、`npm run dev` 这类只读的不算，否则验收时起的预览服务会让整段跳过（dry-run 实测撞上过）。`npx`/`npm exec` 也不算：每个 agent 会话都用它拉起 MCP 服务，完整 dry-run 时就因此跳过了 npm 段；它们装包时持有 `_npx/<hash>/concurrency.lock`（本段会避开），写进 `_cacache` 的东西也在 1 天宽限内。
- 删除一律先改名进同一卷上的 trash 目录，再整体删除。

**关键决策**

- **clone-aware 真实度量，`measure_real(paths) -> (du, real)`**：
  - 按 inode 去重。硬链接只有全部链接都在删除集合里，才算可释放。
  - 按 cloneid 分组。整组成员都在集合里，按一份大小计入。只有部分成员在集合里，只计各成员的 private 字节。
  - 目录本身的块照算。
  - dry-run 报告每段的 du 和 real。真实运行时再加报卷剩余空间的实际变化。
  - 被否决：只用 PRIVATESIZE 求和。集合内互为克隆的文件 private 都是 0，会严重低估。
- **共享的 `~/Code` 索引，`CodeIndex`**：
  - 一次运行只遍历一遍 `~/Code`。
  - 不进入 `.git`、`tmp`、`.venv`、`venv`、`target`、`__pycache__`、`vendor`、`site-packages`、`.build`、`DerivedData`、`.next`、`dist`、`build`、`~/Code/go`（废弃的 GOPATH），以及任何 `pkg/mod`。`node_modules` 记下位置，但不深入。
  - 收集的内容：go.mod 所在目录，`uv.lock` 和 `pylock*.toml`，`.venv` 的 dist-info，带 `.pnpm` 的 node_modules，PEP 723 脚本文件名。PEP 723 脚本的认定：`.py` 文件，或没有扩展名的可执行文件，前 4 KB 含 `# /// script`。
  - 「活跃」= 所在 git 仓库最近一次提交，或关键文件的 mtime，在 30 天内。
  - 跳过 `tmp/` 的理由：那里的拷贝不算活跃，会由项目规则清掉；里面的 node_modules 是 clone，store 删了也不影响它们。
- **go 段**：
  - 待删的是这样的版本：既没被活跃 go.sum 里不带 `/go.mod` 后缀的行引用，解压时间（目录 mtime）又超过 7 天。
  - toolchain 只保留活跃 go.mod 的 `go`、`toolchain` 行精确要求的版本，外加最新的一个。
  - 要删的版本删解压目录，再删 `cache/download/.../@v/<ver>.zip` 和 `.ziphash`。
  - `.mod`、`.info`、`.lock`、`list` 很小，又是 go.sum 里 `/go.mod` 行做模块图时要用的，一律保留，所以重建不需要再拉 go.mod。
  - 删除每个版本前，先对 `<ver>.lock` 拿非阻塞 flock，拿不到就跳过。随后 `chmod u+w` 顶层目录，改名进 trash，再递归 chmod 并删除。
  - 不在 go 进程运行时整段跳过：gopls 常驻，那样会永远跳过。gopls 和编译读的源码都属于活跃项目引用的版本，本来就会保留。
  - go-build 缓存每天会自己修剪掉 5 天没用的条目，本段只打印 `trim.txt` 的年龄，超过 3 天时报警。
- **pnpm 段**（只认 `pnpm store path` 以 `/v10` 结尾的布局）：
  - store：
    - 待删的 index：它的 `<name>@<version>` 不在任何现存 node_modules 的 `.pnpm` 目录名里（全局 `global/5/node_modules` 和本次保留的 dlx 也算），并且 index 的 mtime 超过 7 天。
    - 保留文件集 = 所有保留 index 的 `files` 加上 `sideEffects.*.added`。不在保留集里的 `files/` 文件全删，这也就清掉了孤儿文件。
    - 先删 index，后删文件。中途中断只会留下孤儿，下一轮再收。
    - 被否决：`pnpm store prune`。它按 nlink==1 判断，而这里的 store 全是 clone，会被整个清空。
  - dlx：`<key>/pkg` 软链接的 lstat mtime 超过 7 天，整个 key 删除；否则只保留 `pkg` 指向的那个子目录。进程命令行里出现了的目录跳过。
  - metadata：`metadata*` 和 `v11/metadata*` 下的文件按单个文件的 mtime，超过 7 天删除。
- **npm 段**：
  - `_cacache`：
    - 每个 key 以索引桶里最后一行为准。`time` 超过 7 天算过期，`integrity: null` 是墓碑。
    - 内容文件没有被任何存活 key 引用就删除。
    - 索引桶里全部 key 都过期，就删除整个桶文件。有存活 key 的桶，原子重写成只剩存活行。
    - 顺序：先删内容，再改索引。
    - `tmp/` 下超过 1 天的文件删除。
  - `_npx`：目录 mtime 超过 7 天，没有 `concurrency.lock`，进程命令行里也没出现，就删除。删除前先自己 `mkdir concurrency.lock` 占锁。npm < 11 时只跳过 `_npx`。
  - 有 npm 安装类子命令启动不到 10 分钟时，整段跳过。npx/`npm exec`（常驻的 MCP 进程）不算。
- **codex 段**（要求 `state_5.sqlite` 存在，且 `threads` 表有 `id`、`rollout_path`、`updated_at`、`is_pinned`、`archived` 列）：
  - 最后使用时间 = max(`threads.updated_at`、rollout 的 mtime、`history.jsonl` 里该会话的最新 ts)。按 `thread_spawn_edges` 连通的一组线程取组内最大值，组里有一个活跃，整组都留。
  - 压缩（7 天）：严格照 codex 自己的发布协议做，被否决的方案是打开 codex 的实验 flag。
    1. 用 `zstd -3` 写到同目录的 `rollout-compress-*.jsonl.zst.tmp`。
    2. 解压校验 sha256，复制 mode、atime、mtime。
    3. 拿 `.coordination.lock`（最多等 30 秒），探测 `<id>.lock` 空闲。
    4. 复检源文件的 size、mtime、ino 没变，用不覆盖的方式发布成 `.jsonl.zst`。
    5. 再复检一次，然后删除源文件。
    - 被 lsof 打开的文件，以及 `.zst` 已存在的，都跳过。没有 `zstd` 命令时只跳过压缩。
    - rollout 里有 base64 图片，抽样实测 `zstd -3` 只省 46%。dry-run 因此真跑一遍 `zstd -3` 只计字节（约 5 秒），报告精确的可释放量，不用固定比例估算。
  - 删除（30 天）：逐个调用 `codex delete --force <uuid>`，跳过置顶、被 lsof 打开、写锁被占用的会话。每轮最多删 200 个，总共最多 10 分钟。codex 拒绝删除的（被引用、有子线程）记一行原因，不算这一段失败。
  - 旧版本包：`packages/standalone/releases/*` 中既不是 `current` 指向、也没被任何进程命令行引用的目录，删除。`app-server-daemon` 的旧版本 codex 自己会回收，不动。
- **uv 段改动**：
  - `plan_uv_cleanup` 新增 `pins`（活跃项目引用的 `(规范化名, 版本)`）和 `scripts`（脚本文件名）两个参数。
  - wheel：创建超过 7 天且未被引用，删除。
  - `uv run --script` 环境：创建超过 7 天且脚本已不存在，或者创建超过 30 天，删除。
  - `simple-v18` 下的文件超过 7 天删除。
  - 源码构建的 wheel、正在运行的环境，规则不变。
  - `--uv-days` 默认改为 7。
- **cargo 段：上膛**
  - sidecar 文件 `~/.local/state/mac-dev-cleanup/cargo-lastuse.json` 记录每个 fingerprint 单元上次上膛时的真实最近使用时间。
  - 每次运行时，在持有 cargo 锁期间做三步：
    1. 算出每个单元的真实最近使用 L：sidecar 里的值，与单元内非 json 文件中未上膛（atime ≥ mtime）者的 atime，取最大。两者都没有时，退回文件 mtime 的最大值。
    2. 把单元内所有文件的 atime 设为 L，然后跑 sweep。
    3. 把幸存单元的 L 写回 sidecar，再把全部文件上膛到 atime = mtime − 1 秒。
  - dry-run 也做第 2 步，让 cargo-sweep 的估算准确；sweep 结束后把 atime 精确还原。这一步只改动 ctime。
  - 中途崩溃时，文件停在「未上膛、atime = L」的状态，下一轮照常能算出 L，不丢信息。
  - `--cargo-days` 默认改为 7。`reset_polluted_atimes` 被第 2 步取代，删除。
- **`projects` 和 `watch` 两段**：调用同目录下的 `dev-space`（按 `Path(__file__).resolve().parent` 找；文件不存在时打印一行跳过）。命令行约定见总 plan 的 Tech Design。
  - `projects`：
    - 命令为 `dev-space clean --scheduled`，dry-run 时加 `-n`。
    - 退出码 2 视为本段失败；dry-run 下退出码 1 表示有东西可清。
  - `watch`：
    - 正常运行为 `dev-space watch --agent`；dry-run 时为 `dev-space watch --no-record --no-notify`（dev-space 实际提供的参数），不派 agent、不写历史、不发通知。
    - 退出码非 0 视为本段失败。
  - 子进程直接继承 stdout。启动前先 flush，日志顺序不乱。
- **段的顺序**：`browser, sim, projects, cargo, uv, go, pnpm, npm, codex, clones, watch`。`DISK_TARGETS` 加入除 browser、sim、games 以外的所有新段。

### 数据变动

- 新增状态文件 `~/.local/state/mac-dev-cleanup/cargo-lastuse.json`，格式为 `{"<相对 target 的单元路径>": <epoch 秒>}`，以原子方式重写。已经不存在的单元，对应条目丢弃。
- 不改任何工具的配置。

### 逻辑变动（都在 `mac-dev-cleanup`）

- **新增 `measure_real`**：基于 `getattrlist` 和 `ctypes`。
- **新增 `CodeIndex`**：懒加载，一次运行共用。
- **共用小工具**：`make_trash`、`rmtree_force`（go 目录全是 0555）、`busy_pids`、`try_flock`、`report_sizes`。go 目录要先 chmod，npm 要先占锁，所以各段按需包装。
- **go**：`go_escape`、`go_sum_refs`、`toolchain_wants`、`go_extracted`、`go_downloads`、`plan_go_cleanup`、`apply_go_plan`、`cleanup_go`。
- **pnpm**：`pnpm_key`、`pnpm_nm_keys`、`index_key`、`store_file_path`、`plan_pnpm_store`、`plan_pnpm_dlx`、`plan_pnpm_metadata`、`cleanup_pnpm`；`PNPM_BUSY_RE` 只认写 store 的子命令。
- **npm**：`read_bucket`、`plan_cacache`、`apply_cacache_plan`、`plan_npx`、`apply_npx_plan`、`cleanup_npm`；`NPM_BUSY_RE` 同理。
- **codex**：`load_codex_threads`、`codex_history`、`codex_locked_ids`、`plan_codex`、`codex_publication_lock`、`compress_rollout`、`zstd_size`、`plan_codex_releases`、`cleanup_codex`。
- **uv**：`plan_uv_cleanup` 加参数；`uv_refs`；`cleanup_uv` 把引用传进去，并报告 real。
- **cargo**：`plan_cargo_lastuse`、`apply_lastuse`、`rearm_target`，`sweep_target` 改用它们。
- **两个转调段**：`run_dev_space`，供 `projects` 和 `watch` 共用。
- **argparse**：
  - `--only` 增加 `projects, go, pnpm, npm, codex, watch`。
  - `--cargo-days` 和 `--uv-days` 默认改为 7。
  - 新增 `--go-days`、`--pnpm-days`、`--npm-days`（默认都是 7），`--codex-compress-days`（7），`--codex-delete-days`（30）。
- 模块 docstring 同步更新。

### 实施步骤

- [x] 实测前提：clone 的 refcnt 属性位、atime 规则、cargo 真实构建下的上膛、codex 读 `.zst` 的路径、`codex delete --force` 的无头行为。
- [x] selftest 先行：为各段的选择逻辑写行为用例，先跑出失败。
- [x] 实现 `measure_real`、`CodeIndex`，以及 go、pnpm、npm、codex 四段。
- [x] uv 改为引用式；cargo 上膛加 7 天。
- [x] `projects` 和 `watch` 两个转调段，更新段列表和 argparse。
- [x] `--selftest` 全部通过；每段 `--dry-run --only <段>` 的输出合理。
- [x] 更新 `SKILL.md` 和 `kb/known-issues.md`。

### 测试与验证

| PRD 验收标准 | 怎么验 |
|---|---|
| dry-run 列出各段计划，带 du 和 real | 逐段跑 `mac-dev-cleanup --dry-run --only <段>`，核对汇总行 |
| 活跃项目无需重新下载 | selftest：被活跃 go.sum、lock、node_modules 引用的条目不进删除集合。首次真实运行后，人工在活跃项目里 `pnpm install`、`uv sync`、`go build` |
| codex 压缩后能 resume，删除不留悬空项 | selftest 在合成的 `~/.codex` 上跑压缩协议（写锁被占用时跳过、源文件变化时放弃）。`codex delete --force` 已在一次性会话上实测 |
| 常驻进程不受影响 | selftest：进程命令行里出现的 dlx、_npx、uv 环境，lsof 打开的 rollout，被 flock 占用的 go 锁和 codex 写锁，全部跳过 |
| `--selftest` 通过 | `uv run skills/systools/scripts/mac-dev-cleanup --selftest` |

首次 dry-run（2026-11-13 10:10–10:30，剩余 6.8 GiB；日志在 `tmp/2026-11-13-dev-cleanup/dry-*.log`，完整流程 `dry-full.log` 用时 319 秒，其中 projects 段约 85 秒）：

| 段 | 计划 | du | real |
|---|---|---|---|
| cargo | 1362 个单元全在 7 天内构建过，0 项 | 0 | 0 |
| uv | 1324 项（wheel 213、env 228、index 870、孤儿 archive 13），保留 447 个活跃引用 | 5.0 GiB | 1.3 GiB |
| go | 632 个版本（解压树 630、zip 632），保留 6 个活跃项目引用的 145 个版本和 go1.26.8/1.26.10 工具链 | 5.2 GiB | 5.2 GiB |
| pnpm | dlx 38、store 包 1256（46297 个文件）、metadata 7259 | 8.0 GiB | 5.7 GiB |
| npm | `_cacache` 1610 个内容文件、重写 201 个桶，`_npx` 48 个 | 3.2 GiB | 3.2 GiB |
| codex | 压缩 424（实测省 813 MiB）、删除 277（首轮上限 200）、旧 release 1 | — | 1.8 GiB |
| 合计（缓存段） | | | 约 17.2 GiB |

### 风险与待定

- go、npm、pnpm 的真实删除只在 selftest 的 fixture 上跑过。首次真实运行要对照报告的 real 和卷剩余空间的实际变化，并在活跃项目里试一次安装。
- npm `_cacache` 的 `time` 在 304 重新校验后会不会刷新，没有实测。如果不刷新，常用包每 7 天会重新下载一次。代价只是流量。
- 脚本环境按文件名匹配脚本，`main.py` 这类常见名字会被一直保留（创建 30 天后仍会删除）。
- codex 删除依赖 `codex delete --force` 的命令行。升级后如果参数变了，会表现为本段报错，不会误删。
