---
created: 2026-11-09
tags:
  - mole-review
  - bugfix
---

# Mole Review 忽略列表命名与删除标记分离

## 概要

把用于隐藏已审核条目的 whitelist 统一改为 ignore list，覆盖函数、变量、界面、帮助和 CLI 参数。X 只切换当前行的忽略状态，不再批量操作空格标记的待删除条目；被忽略路径的删除标记仍会清除。

## 修改的文件

- `mole-review.py`：改名为 `--ignore-list`，默认文件为 `~/.config/mole-review/ignore-list`；修正 X 的目标选择。
- `test_mole_review.py`：同步命名，新增多条删除标记下忽略当前行、取消忽略保留其他标记、忽略当前行清除其删除标记的测试。
- `AGENTS.md`、`kb/known-issues.md`：同步当前术语与操作约定。
- 本机 `~/.config/mole-review/whitelist` 已迁移为 `ignore-list`，更新文件头，逐行核对两条规则均保留，旧文件已移除。

## 注意事项

- 修改前新增回归测试，确认旧逻辑错误地写入全部删除标记；修改后原有完整测试 84 项通过，另补两项边界测试并单独验证忽略列表测试组。
- Mole 自身的 `~/.config/mole/whitelist` 及对应外部函数名保持不变，它们不属于 Mole Review 的命名范围。
- CLI 自定义配置参数改用 `--ignore-list`；未实现免审核自动清理的 whitelist 功能。

## 遗留问题

无新增问题。
