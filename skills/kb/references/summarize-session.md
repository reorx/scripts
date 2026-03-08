总结当前 session 所做的事情，写入项目根目录下的 `kb/sessions/` 目录中（即 `<project-root>/kb/sessions/`）。如果目录不存在，先创建它。

## 文件命名

文件名格式：`YYYY-MM-DD-<session-title>.md`

- 日期为当天日期, 通过 `date +%Y-%m-%d` 获取
- `<session-title>` 根据 session 内容用英文短语概括，单词间用 `-` 连接

## 文件结构

用 Markdown 编写，包含以下部分：

### 一级标题

session 的中文标题，一句话概括本次 session 做了什么。

### 二级标题：概要

用一段话总结 session 的背景、遇到的问题、采取的方案和最终效果。

### 二级标题：修改的文件

列出本次 session 影响到的文件，每个文件附带简要说明改了什么。

### 二级标题：Git 提交记录

列出本次 session 中所有的 git commit，包含 commit hash（短格式）和 commit message。用列表形式呈现，例如：

- `a1b2c3d` feat: add user authentication
- `e4f5g6h` fix: resolve login redirect issue

如果 session 中没有提交任何 commit，写明"本次 session 无 git 提交"。

### 二级标题：注意事项

提炼 session 中有价值的、值得参考的内容，包括但不限于：

- 可复用的 pattern 或最佳实践
- 常见错误及其规避方式
- 代码层面的注意事项或设计决策
