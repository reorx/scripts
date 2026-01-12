# Raycast Script Commands

本目录包含用于 [Raycast](https://raycast.com) 的 Script Commands。

## 安装

1. 打开 Raycast 设置 → Extensions → Script Commands
2. 点击 "Add Script Directory"
3. 选择此目录 (`~/Code/scripts/raycast/`)
4. 刷新后即可在 Raycast 中搜索使用

详细文档参考：https://github.com/raycast/script-commands

## 依赖

部分脚本使用 [uv](https://github.com/astral-sh/uv) 运行 Python。需要确保 `uv` 安装在以下路径之一：

- `/opt/homebrew/bin/uv` (Homebrew on Apple Silicon)
- `/usr/local/bin/uv` (Homebrew on Intel)
- `~/.local/bin/uv` (uv 默认安装路径)

安装 uv：
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 词库配置

两个 Rime 脚本顶部都有 `DICT_FILE_PATH` 变量，默认使用 `quickadd.dict.yaml`。

### rime_ice 用户（推荐）

如果你使用 [雾凇拼音 (rime_ice)](https://github.com/iDvel/rime-ice)，需要在 `rime_ice.dict.yaml` 的 `import_tables` 中添加 quickadd：

```yaml
import_tables:
  - cn_dicts/8105
  - cn_dicts/base
  # ... 其他词库
  - quickadd  # 添加这一行
```

然后创建 `~/Library/Rime/quickadd.dict.yaml`：

```yaml
# Rime dictionary
# encoding: utf-8

---
name: quickadd
version: "1.0"
sort: by_weight
...

```

重新部署后即可使用。与 `custom_phrase.txt` 不同，quickadd 词库可以参与造句。

### 非 rime_ice 用户

如果你使用其他 Rime 方案，需要：

1. 创建 `quickadd.dict.yaml` 文件（格式同上）

2. 在你的主词库 `.dict.yaml` 的 `import_tables` 中添加 quickadd

3. 或者修改脚本中的 `DICT_FILE_PATH` 指向你自己的词库文件

## 脚本列表

### Rime QuickAdd

`rime-quickadd.py`

快速将选中的文字添加到 Rime 输入法词库。

**功能：**
- 复制当前选中的文字
- 自动转换为拼音 (使用 pypinyin)
- 添加到 `~/Library/Rime/quickadd.dict.yaml`
- 触发鼠须管重新部署
- 发送系统通知显示结果

**使用方式：**
1. 选中任意中文文字
2. 触发 "Rime QuickAdd" 命令（建议设置快捷键）
3. 等待通知确认添加成功

### Rime Show Dict

`rime-showdict.py`

显示和搜索 quickadd 词库内容。

**功能：**
- 显示所有已添加的词条
- 显示词条总数
- 支持按词或拼音搜索

**使用方式：**
1. 触发 "Rime Show Dict" 命令
2. 可选输入搜索关键词过滤结果
