# Rime QuickAdd - 快速添加词库工具

## 概述

通过快捷键将选中的文字快速添加到 Rime 输入法（鼠须管 + 雾凇拼音）词库中，自动转换拼音并立即生效。

## 技术方案

### 工作流程

```
选中文字 -> 按快捷键 -> Raycast 触发脚本 -> 复制选中文字 -> 转换拼音 -> 写入词库 -> 重新部署 -> 通知结果
```

### 组件

1. **Python 脚本** (`rime-quickadd.py`)
   - 从剪贴板获取文字 (`pbpaste`)
   - 使用 `pypinyin` 库转换拼音（词组模式，自动处理多音字）
   - 追加词条到用户词库文件
   - 调用鼠须管重新部署
   - 通过 `osascript` 发送系统通知（成功/失败）

2. **Raycast Script Command** (`rime-quickadd.sh`)
   - 绑定快捷键（在 Raycast 中配置）
   - 先执行 Cmd+C 复制选中文字到剪贴板
   - 调用 Python 脚本处理

3. **用户词库文件** (`~/Library/Rime/cn_dicts/quickadd.dict.yaml`)
   - 存放快速添加的词条
   - 需要在 `rime_ice.dict.yaml` 中导入

### 词库配置

在 `~/Library/Rime/rime_ice.dict.yaml` 的 `import_tables` 中添加：

```yaml
import_tables:
  - cn_dicts/8105
  - cn_dicts/base
  - cn_dicts/ext
  - cn_dicts/tencent
  - cn_dicts/others
  - cn_dicts/quickadd  # 快速添加词库
```

### 词库文件格式

`quickadd.dict.yaml`:

```yaml
# Rime dictionary
# encoding: utf-8

---
name: quickadd
version: "1.0"
sort: by_weight
...

# 词条格式：词语<Tab>拼音（空格分隔）
# 示例：
# 雾凇拼音	wu song pin yin
```

### 关键技术点

1. **拼音转换**
   - 使用 `pypinyin` 库，style 为 `NORMAL`（无声调）
   - 多音字使用默认读音（词组模式会自动选择常用音）
   - 拼音之间用空格分隔

2. **重新部署**
   ```bash
   /Library/Input\ Methods/Squirrel.app/Contents/MacOS/Squirrel --reload
   ```

3. **系统通知**
   ```bash
   osascript -e 'display notification "内容" with title "标题"'
   ```

4. **Raycast Script Command**
   - 使用 Bash 脚本包装
   - 通过 AppleScript 执行 Cmd+C
   - 需要设置 `@raycast.mode` 为 `silent`

## 文件清单

| 文件 | 位置 | 说明 |
|------|------|------|
| `rime-quickadd.py` | `~/Code/scripts/` | 主脚本 |
| `rime-quickadd.sh` | `~/Code/scripts/raycast/` | Raycast Script Command |
| `quickadd.dict.yaml` | `~/Library/Rime/cn_dicts/` | 用户词库 |

## 初始化步骤

### 1. 创建词库文件

创建 `~/Library/Rime/cn_dicts/quickadd.dict.yaml`：

```yaml
# Rime dictionary
# encoding: utf-8

---
name: quickadd
version: "1.0"
sort: by_weight
...

```

### 2. 修改词库配置

编辑 `~/Library/Rime/rime_ice.dict.yaml`，在 `import_tables` 末尾添加：

```yaml
  - cn_dicts/quickadd  # 快速添加词库
```

### 3. 重新部署

运行命令或点击菜单栏"重新部署"：

```bash
/Library/Input\ Methods/Squirrel.app/Contents/MacOS/Squirrel --reload
```

### 4. 配置 Raycast

1. 打开 Raycast 设置 -> Extensions -> Script Commands
2. 添加 `~/Code/scripts/raycast/` 目录
3. 找到 "Rime QuickAdd" 命令，设置快捷键（如 `Cmd+Shift+A`）

## 使用方式

1. 用鼠标选中任意文字
2. 按下设定的快捷键
3. 收到通知提示添加成功/失败
4. 下次输入对应拼音时即可命中该词

## 依赖

- Python 3.x (通过 uv 运行)
- pypinyin (脚本内联依赖，uv 自动安装)
- Raycast
- 鼠须管 (Squirrel)

## 边界情况处理

- **空选择**：提示"未选中任何文字"
- **非中文字符**：保留原样，仅转换中文部分的拼音
- **重复词条**：检查是否已存在，存在则提示"词条已存在"
- **多音字**：使用 pypinyin 的词组模式自动选择常用读音

## 后续可扩展

- [ ] 支持手动修正拼音（弹出输入框）
- [ ] 支持设置词频权重
- [ ] 支持删除已添加的词条
- [ ] 支持查看最近添加的词条
