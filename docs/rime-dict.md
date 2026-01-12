Rime 输入法（中州韵/小狼毫/鼠须管）最大的优势就是高度可定制，自建词库是其核心玩法之一。

自建词库主要分为三个步骤：**创建词库文件** -> **挂载配置** -> **重新部署**。如果你的词源来自搜狗等其他输入法，还需要增加一步**格式转换**。

以下是详细的操作指南：

### 第一步：创建词库文件 (`.dict.yaml`)

Rime 的词库本质上是一个纯文本文件。

1. 进入你的 Rime **用户配置目录**：
* **Windows (小狼毫):** `%APPDATA%\Rime`
* **macOS (鼠须管):** `~/Library/Rime`
* **Linux (IBus/Fcitx):** `~/.config/ibus/rime` 或 `~/.local/share/fcitx5/rime`


2. 新建一个文件，命名为 `my_custom.dict.yaml`（文件名可以自定义，但必须以 `.dict.yaml` 结尾）。
3. 用文本编辑器（推荐 VS Code 或 Notepad++，**不要用记事本**以防编码问题）打开，写入以下内容：

```yaml
# Rime dictionary
# encoding: utf-8
#
# my_custom.dict.yaml
# 自定义词库示例

---
name: my_custom          # 必须与文件名(不含扩展名)一致
version: "1.0"
sort: by_weight          # 排序规则：by_weight(按权重) / original(按原本顺序)
use_preset_vocabulary: true # 是否导入预设词汇（通常为 true）
...

# 下面是词条部分，格式为：词语<Tab>拼音<Tab>权重
# 拼音和权重是可选的，权重越大越靠前

Rime输入法	rime shu ru fa	100
自定义词库	zi ding yi ci ku	1000
小狼毫	xiao lang hao
鼠须管	shu xu guan

```

> **注意：** 词语和拼音之间 **必须用 Tab 键（制表符）** 分隔，不能用空格。

---

### 第二步：挂载词库

创建好词库后，你需要告诉 Rime 去加载它。最推荐的方法是使用 `custom.yaml` 补丁文件，这样不会破坏原有的配置。

假设你使用的是 **朙月拼音 (luna_pinyin)** 方案：

1. 在用户配置目录下，找到或新建 `luna_pinyin.custom.yaml` 文件。
2. 输入以下内容（如果文件已存在，请在现有结构上修改，注意缩进）：

```yaml
patch:
  # 指定翻译器调用的主词库为下面的 extended 词库
  "translator/dictionary": luna_pinyin.extended

```

3. 接着，新建（或修改）名为 `luna_pinyin.extended.dict.yaml` 的文件，作为你的“总扩充词库”：

```yaml
---
name: luna_pinyin.extended
version: "1.0"
sort: by_weight
use_preset_vocabulary: true
import_tables:
  - luna_pinyin      # 导入系统默认的主词库
  - my_custom        # 导入你刚才创建的自定义词库
...
# 这里留空即可

```

**原理说明：** 我们不直接修改系统自带的 `luna_pinyin.dict.yaml`，而是创建一个扩展词库 `luna_pinyin.extended`，让它把“系统主词库”和“你的自定义词库”都吸纳进来，最后再让输入法去加载这个扩展词库。

---

### 第三步：重新部署

修改配置后，必须重新部署才能生效：

* **Windows:** 在任务栏图标右键 -> 点击「重新部署」。
* **macOS:** 在菜单栏图标点击 -> 点击「重新部署」。

试着输入你在 `my_custom.dict.yaml` 里添加的词，如果能打出来，说明成功了。

