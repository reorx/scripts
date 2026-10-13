---
created: 2026-10-13
tags:
  - macos
  - preferences
  - cli
---

# 将应用偏好调查做成通用检查和修改工具

## 概要

用户在分析 Graker 的 defaults 参数和模型请求超时之后，希望将调查方法做成可复用脚本。在现有 scripts 仓库 master 分支新增标准库 Python CLI，支持 inspect、scan、set、delete、backup 和 restore。已保存值与静态候选键分别展示，写入要求明确类型，实际变更先备份，再读回验证。

## 修改的文件

- `app-defaults.py`：应用解析、偏好导出和类型处理、ARM64 静态候选扫描、备份及变更命令。
- `test_app_defaults.py`：先编写行为用例；随后为恢复遗漏新增键和无关损坏 Info.plist 问题补充复现测试。
- `kb/docs/app-defaults.md`：使用方式、值与候选键的区别、偏好来源和恢复语义。
- `AGENTS.md`：工具入口、修改保障要求及文档索引。

## 注意事项

- `defaults export` 只能列出已保存值，不能当作完整设置 schema；静态扫描同样是候选发现，不保证键生效或属于主偏好域。
- 真实 macOS 验证发现 `defaults import` 会保留备份后新增的键；恢复改为整域 write，以完整替换快照，并读回核对。
- 应用查找使用 `plutil` 提取 Bundle ID，跳过无法解析的无关 Info.plist；选定应用的 plist 也通过 `plutil` 规范化。
- 18 项行为测试通过，覆盖类型、敏感信息遮蔽、歧义名称、备份权限、错误域拒绝、恢复完整性、静态键恢复和 dry-run 不变更。
- 使用随机临时偏好域验证六种写入类型、删除、新增键后恢复和清理。真实验证脚本及扫描产物留在忽略目录 `tmp/2026-10-13-app-defaults/`，测试结束删除临时偏好域。
- Graker、Ghostty 只读检查通过；Graker 的高度修改仅执行 dry-run，未修改这两个应用的设置。
- CLI 链接到 `~/.local/bin/app-defaults.py`，未启动应用或创建浏览器/模拟器资源。

## 遗留问题

静态扫描明确限于主 ARM64 文件中的部分调用。动态键、其他 suite 和硬编码请求超时需要继续针对目标代码调查，属于工具覆盖边界。

## 相关文档

- [检查和修改 macOS 应用偏好](../docs/app-defaults.md) — 本次新增的操作说明。
