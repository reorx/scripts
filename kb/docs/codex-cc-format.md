---
created: 2026-10-17
tags:
  - codex
  - hooks
  - formatting
---

# Codex 全局 cc-format hook

`codex-cc-format.py` 将 Codex `apply_patch` 的文件路径转换为 Claude Code hook 的 `tool_input.file_path`，逐文件执行保存在脚本中的原始 shell 命令。扩展名仍仅限 `.py/.ts/.tsx/.js`；实际执行 `cc-format "$file_path"`，共享既有格式化配置和开关。

全局入口是 `~/.codex/hooks.json`，配置 `PostToolUse`、`matcher: Edit|MultiEdit|Write`，同步调用 `uv run /Users/reorx/Code/scripts/codex-cc-format.py`。Codex 将 `apply_patch` 匹配为 Edit/Write，但输入字段仍为 `tool_input.command`。直接复制 Claude 的 shell 命令到 Codex 会因缺少 file_path 而不生效。

适配支持新增、修改、多文件及重命名目标，忽略删除和不存在的文件。与 Claude 的匹配范围一致，普通 Bash 写文件不会触发；不是文件系统监听器。适配器不修改 cc-format 本身。

## 启用与验证

在 Codex CLI 输入 `/hooks`，选择来自 `~/.codex/hooks.json` 的 hook，审阅并信任。官方机制会跳过尚未信任或定义已改变的 hook；新增会话后应检查它为 trusted。2026-10-17 安装验证时状态仍为 untrusted，等待用户完成此步骤。未设置全局信任绕过。

运行 `uv run test_codex_cc_format.py` 检查行为和 Claude 命令逐字一致性。如果未来 Claude hook 改动，该断言会提示同步适配器中的命令。

安装验证：5 项行为测试通过；Codex 0.163.0 的 hooks/list 在 Documents 和 scripts 两个目录均识别为 user 来源、enabled、同步执行，无配置错误。四种语言分别执行 Claude 原命令及 Codex 适配器，真实格式化结果逐字相同。尚未验证用户信任后的完整模型编辑事件链。

验证脚本、格式化样例、hooks/list 结果存于 `/Users/reorx/Documents/tmp/2026-10-17-codex-cc-format/`。

机制依据：[OpenAI Hooks 文档](https://learn.chatgpt.com/docs/hooks)。
