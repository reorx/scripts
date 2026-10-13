---
created: 2026-10-13
updated: 2026-10-13
tags:
  - macos
  - preferences
  - cli
---

# 检查和修改 macOS 应用偏好

`app-defaults.py` 用来查看应用已经保存的设置，查找原生代码中的候选偏好键，并对指定键进行修改、删除和恢复。可以传入应用名称、完整 `.app` 路径或 Bundle ID；静态扫描需要找到应用本体。

## 已保存值与代码默认值

macOS 的 `defaults` 访问偏好域，应用通常使用自己的 Bundle ID，例如 Graker 的 `com.graker.app`。脚本从 `Contents/Info.plist` 获取这个 ID，再用 `defaults export <domain> -` 导出 plist，保留布尔、整数、浮点、数组、字典等类型。

导出结果只是已保存值。某个键尚未保存，不代表应用没有该设置；应用也可能在代码里写死默认值，使用注册默认值、其他 suite、全局偏好、ByHost、数据库、JSON 文件或钥匙串。写入一个任意键不会让应用自动支持它。

`scan` 使用 `xcrun lipo` 和 `xcrun otool` 检查主 ARM64 可执行文件，追踪部分 `NSUserDefaults` 调用并恢复字符串键。它可以补充未保存的候选键，但不能生成完整配置 schema，也不自动提取所有代码默认值。动态拼接的键、框架、插件和 Electron/JavaScript 配置不在完整覆盖范围内。

扫描结果提供候选类型、读写调用及对应函数和地址。JSON 中的 `receiver_identified` 表示是否追踪到了 `NSUserDefaults` 接收者；未确认接收者的调用更需要核实。即使确认了接收者，调用也可能属于其他 suite，而非主 Bundle ID 偏好域。仅写入的键未必影响应用功能。

## 查看设置

首次在 scripts 仓库运行 `./link-script app-defaults.py`，之后可直接使用命令。脚本通过 `uv` 运行，只使用 Python 标准库。静态扫描额外需要 Apple Command Line Tools。

```bash
app-defaults.py inspect Graker
app-defaults.py inspect /Applications/Ghostty.app --json
app-defaults.py inspect com.graker.app --filter tool_panel
app-defaults.py scan Graker
app-defaults.py scan Graker --filter timeout --json
```

`inspect` 和 `scan` 不修改偏好、不启动应用、不访问钥匙串。`--filter` 按键名过滤。默认遮蔽常见敏感键以及部分 JSON 字符串中的凭据，二进制数据只显示长度；遮蔽按名称启发式进行，并非内容分类器。确实需要原始值时用 `inspect --show-secrets`。

若同时存在普通偏好和沙盒偏好，工具要求显式选择来源：

```bash
app-defaults.py inspect Example --store standard
app-defaults.py inspect Example --store container
```

自动模式会在仅有沙盒文件时选择它。沙盒模式操作 `~/Library/Containers/<Bundle ID>/Data/Library/Preferences/<Bundle ID>.plist` 对应的路径偏好域，不枚举共享 App Group 或其他 suite。

## 修改和删除

先退出目标应用，再修改并重新打开。应用运行时可能使用缓存或把旧值写回；脚本的读回验证确认存储值，实际功能是否生效仍要观察应用。

```bash
# 先预览，不写入也不创建备份
app-defaults.py set Graker tool_panel_is_wide true --type bool --dry-run

# 修改一个键，自动备份后读回验证
app-defaults.py set Graker tool_panel_is_wide true --type bool
app-defaults.py set Graker tool_panel_last_height 600 --type float
app-defaults.py set Graker appLanguage zh-Hans --type string

# 删除保存的覆盖值，应用可能回退到代码默认值或继承值
app-defaults.py delete Graker tool_panel_is_wide
```

`--type` 必填，支持 `string`、`bool`、`int`、`float`、`json` 和 `data`。JSON 用于 plist 兼容的数组、字典或标量；不支持 `null` 和非有限数值。Data 使用十六进制。字符串作为独立参数传给 `defaults`，工具不会通过 shell 再执行它。

Graker 的模型请求超时是代码里的常量，没有发现对应的偏好读取。设置一个 `timeout` 键不能改变这些常量。扫描没有结果也不能证明其他应用绝对不存在超时设置；可能需要进一步分析其请求构造代码或其他配置来源。

## 备份与恢复

每次实际修改、删除或恢复之前，都会保存当前完整偏好域。备份默认位于 `~/Library/Application Support/app-defaults/backups/`，路径打印到标准错误；新建目录权限为 `700`，备份文件权限为 `600`。备份保存原始值，因此也可能包含敏感数据。

```bash
app-defaults.py backup Graker
app-defaults.py restore Graker '/完整路径/备份文件.plist'
```

备份包含 Bundle ID、偏好来源和格式版本；恢复时必须匹配。恢复替换整个偏好域，备份之后新增的键也会被移除。恢复本身也先备份当前状态，因此可以撤销恢复。沙盒备份恢复时仍需选择相同来源。

本工具生成的备份带有元数据，不是直接交给 `defaults import` 的裸偏好 plist。

## 维护入口

- 脚本：`app-defaults.py`
- 行为测试：`uv run test_app_defaults.py`，需要 macOS 的 `plutil`。
- 安装链接：`./link-script app-defaults.py`
