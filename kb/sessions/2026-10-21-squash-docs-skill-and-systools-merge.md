---
created: 2026-10-21
tags:
  - skills
  - git
  - skm
  - monitoring
---

# 将 squash-docs 迁为通用 skill，并把 systools 副本里的改动并回仓库

## 概要

用户希望把 vibench 里的 `scripts/squash-docs.ts` 变成通用脚本并配一个 skill。脚本迁到 `skills/squash-docs/scripts/`，两份原测试合并到根目录的 `test-squash-docs.ts`；通用化时先写用例再实现，新增了 `--title` 标题模板、预览中的改写范围与“已推送 / 被其他分支或标签引用”提醒，以及 apply 后的撤销命令。之后按用户要求把 skill 改成仅显式调用，删除了 vibench 的副本（vibench `db05f67`）。安装时 `skm install` 被 `~/.agents/skills/systools` 卡住：该副本在 2026-10-19 被直接改过（缩短了 description，新增监控告警一节和 reference）。review 之后，把这些内容修改后并回仓库，删除过期副本，由 `skm install` 重新生成，SKM 恢复正常。

## 修改的文件

- `skills/squash-docs/scripts/squash-docs.ts`：从 vibench 迁入；`buildPlan` 改为接收选项对象，新增 `--title`、`rewrittenCommits`、预览提醒和撤销提示。
- `test-squash-docs.ts`：合并原有两份测试，补充标题模板、改写范围、远程/标签提醒和撤销的用例；Node 26 与 22.23 下 26 项全部通过。
- `skills/squash-docs/SKILL.md`、`skills/squash-docs/agents/openai.yaml`：流程是先预览、用户确认后再 apply、不自动推送；两端都设为仅显式调用。
- `skills/systools/SKILL.md`：description 从 1359 字符压到 930，保留各工具的触发短语；末尾新增 “Local Monitoring: Process CPU Alerts” 一节。
- `skills/systools/references/process-alert-policies.md`：并回并重写，写明监控项目路径 `~/Documents/macos-monitoring`，命令和当前阈值交给项目文档，这里只保留判断规则和工作顺序。
- `kb/docs/skill-invocation.md`：调用方式表新增 squash-docs；写明直接运行 `skm install`，以及不要手改 `~/.agents/skills` 下的副本。
- `AGENTS.md`：新增 Git history squashing 一节。

## 注意事项

- Skill 规范限制 description 不超过 1024 字符。systools 原来的 description 超长，这很可能是 10 月 19 日那个 agent 改它的原因；但改短后丢掉了全部触发短语，所以这次重写时既压缩长度，又保留了关键短语。
- 副本里的 reference 没写监控项目在哪，内容又大半重复了项目自己的 `kb/docs/process-rules.md`，两份文档迟早会不一致。并回前逐条对照了 `scripts/process_rules.py` 和 `hermes_alert_filter.py`（selector 排除、拒绝未知键、暂停规则拒绝覆盖、未完成的 deleteRules 会拒绝部署、窗口秒数 / 15），确认 reference 描述的都是生成器现有的行为。
- SKM 以 inode 相同或内容一致来判断托管副本，`_materialize_tree` 只补缺失文件、不更新已有文件。所以要原地改仓库文件（保留硬链接），否则副本过期后 `skm install` 会停在覆盖确认，后面的 skill 不刷新、锁文件也不写入。
- 给 skill 写参数示例时，正则不要放进 Markdown 表格：表格里的 `\|` 会被 agent 原样复制，正则的含义就变了。
- 改动前的 systools 副本备份在忽略目录 `tmp/2026-10-21-systools-drift/`。

## 遗留问题

- `~/Documents/macos-monitoring/AGENTS.md` 的文档索引没有列出 `kb/docs/process-rules.md`，在项目里工作的 agent 不容易找到它。这次只在 systools 里给了路径，没有改那个项目。

## 已解决的已知问题

- **SKM：`~/.agents/skills/systools` 有仓库里没有的改动，`skm install` 整体中断**：改动 review 后并回仓库，删除过期副本，再运行 `skm install`。验证结果：命令完整跑完，锁文件里有 squash-docs 和 systools，两个副本与仓库 `diff -r` 一致，并且共用 inode。

## 相关文档

- [Skill 调用方式](../docs/skill-invocation.md) — 本次更新：新增 squash-docs，补充 SKM 安装说明。
