---
created: 2026-11-09
tags:
  - mole-review
  - whitelist
---

# 恢复 whitelist 命名并与 Mole 共用配置

## 概要

用户确认 Mole 原生 whitelist 就是跳过清理的保护名单，因此撤销上一轮术语改名，改为直接读写 `~/.config/mole/whitelist`。保留 X 只处理当前行、空格只标记删除的修复。

## 修改的文件

- `mole-review.py`：恢复 whitelist 标识符、界面和 `--whitelist` 参数，默认接入 Mole 文件；删除日志仍写到 `~/.config/mole-review/deleted.log`。默认共享文件不存在时提示先在 Mole 菜单保存，避免创建只有新路径的文件而替换默认保护规则。
- `test_mole_review.py`：验证默认路径、日志位置、缺失共享配置提示、自定义文件兼容，以及外部写入后重新加载和 X 追加时保留已有内容。
- `AGENTS.md`、`kb/known-issues.md`：同步现行配置与术语。
- 本机配置：用已安装 Mole 1.69.0 的 `load_whitelist` / `save_whitelist_patterns` 初始化默认和安全规则，再合并原 ignore-list 两条规则，核对全部保留后移除旧文件。备份在 `tmp/2026-11-09-mole-shared-whitelist/`。

## 验证

- 修改前两项测试复现默认文件未共享、日志随共享配置移动的问题。
- 完整测试 90 项通过，追加的共享文件重新加载测试单独通过。
- 用 Mole 自身的 `load_mole_whitelist` 和 `is_path_whitelisted` 确认迁移的两条路径均受保护，未执行真实清理。

## 注意事项

- 本机原先没有 Mole whitelist 文件；直接迁入两条规则会替换可选默认保护，故先保存 Mole 的有效默认规则。
- 默认模式下 X、取消保护和编辑文件都直接影响 Mole 清理；指定自定义 `--whitelist` 文件则与 Mole 分离。
- Mole 有额外内置安全保护；从配置中移除一项不代表一定能让 Mole 删除该路径。

## 相关文档

- [上一轮命名调整](2026-11-09-mole-review-ignore-list.md) — 本轮撤销其中的术语改名，保留当前行操作修复。
