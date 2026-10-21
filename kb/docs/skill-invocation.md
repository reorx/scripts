---
created: 2026-10-17
tags:
  - skills
  - codex
  - claude-code
---

# Skill 调用方式

本仓库的 skill 按用户逐项确认的选择控制自动调用，两端使用各自的正式配置。

| Skill | 调用方式 |
| --- | --- |
| `create-skill` | 仅显式调用 |
| `flyctl` | 仅显式调用 |
| `hnread` | 仅显式调用 |
| `llm-models` | 允许自动调用 |
| `macos-launchd-agents` | 允许自动调用 |
| `obsidian` | 允许自动调用 |
| `squash-docs` | 允许自动调用 |
| `systools` | 允许自动调用 |

同级 `devblocks` 仓库中，用户另外指定以下 skill 仅显式调用：`agentsmd-enhance`、`agentsmd-enhance-cn`、`browser-ext`、`herdr-coordinator`、`macos-app-bootstrap`、`tmuxp`。用户提到的 “tmuxup” 按现有 skill 名称 `tmuxp` 处理。该仓库使用 SKM 管理安装，调用方式约束也记录在其 `AGENTS.md`。

## 两端配置

Claude Code 在 `SKILL.md` 的 YAML frontmatter 中设置：

```yaml
disable-model-invocation: true
```

用户仍可以通过 `/skill-name` 调用。保留 `user-invocable` 默认值；设为 `false` 会隐藏用户调用入口。

Codex 在 skill 目录的 `agents/openai.yaml` 中设置：

```yaml
policy:
  allow_implicit_invocation: false
```

用户仍可以通过 `$skill-name` 调用。这两个配置同时保存在同一个 skill 目录中；修改已有 `openai.yaml` 时保留其界面和依赖配置。description 也应与调用方式一致，避免要求自动触发。

允许自动调用的 skill 无需添加配置，使用两端默认行为。

## 安装与生效

本机的这些 skill 由 SKM 管理安装，新增配置文件后通过 SKM 刷新现有安装。SKM 对 Claude Code 使用软链接，对标准目录 `~/.agents/skills` 使用文件树，同一文件系统下使用硬链接。仓库另有 `./link-skill skills/<name>` 工具用于软链接安装；已有 SKM 登记的安装应继续由 SKM 管理。

检查实际安装路径后再同步。本机核查时，Claude Code 的这些 skill 目录是指向仓库的软链接；`~/.agents/skills` 则是独立目录，已有部分文件与仓库文件共用硬链接。编辑器可能替换文件、打断硬链接；新增 `agents/openai.yaml` 也不会因其他文件共用硬链接而自动出现。同步后需对比 `SKILL.md` 和 `agents/openai.yaml` 的内容，不能只检查仓库。

配置更新后，在新会话中检查是否生效；Codex 未检测到更新时重启。已经读入当前会话的 skill 内容不会因修改磁盘配置而被撤回。

Codex 的 `skills/list` 接口可检查 skill 是否被发现和正常加载；本机版本的返回值不包含调用策略，因此不能用它单独验证禁止隐式调用的行为。

## 参考

- [OpenAI 官方文档：Build skills](https://learn.chatgpt.com/docs/build-skills#optional-metadata)
- [Claude Code 官方文档：Control who invokes a skill](https://code.claude.com/docs/en/skills#control-who-invokes-a-skill)
- 仓库源文件：`skills/<name>/SKILL.md`、`skills/<name>/agents/openai.yaml`
- 安装脚本：`link-skill`
