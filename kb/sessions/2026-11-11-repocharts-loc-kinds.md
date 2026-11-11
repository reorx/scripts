---
created: 2026-11-11
tags:
  - repocharts
  - python
  - terminal-charts
---

# repocharts：网格线改点号，代码行数图按 src/tests/docs 分层堆叠

## 概要

`repocharts.py` 的 y 轴网格线原先用 `▔`，用户觉得不好看，想换回点；但居中的 `·` 会比刻度值低半行。实测用户的 iTerm2 字体（Mononoki Nerd Font Mono）后改用 `˙`（dot above，约在格子顶边下 0.2 行），提交 `8afa7e8`。随后把代码行数图拆成 src、tests、docs 三层堆叠柱，各用一种颜色（无颜色时用 `█ ▓ ░` 底纹），标题下加图例（每类的行数和窗口内增量），新增 `-k` 选择显示哪几类、`--src/--tests/--docs` 修正分类、`dir/` 目录 glob。先写行为测试再实现，79 个测试通过，提交 `f227b9c`。campus_watch（1349 个提交）运行 0.46 秒，与改动前无差别。

## 修改的文件

- `repocharts.py`：`GRID = '˙'`；新增 `classify`/`matches`/`kind_rules` 分类；`read_loc_changes` 按类别返回增量；`Series` 按类别存行数；`stack_bounds`/`stack_cell`/`bar_rows` 做堆叠（一格最多两层：前景方块 + 背景色）；`paint_row`/`shade` 上色与无色底纹；`legend`；`-k`、`--src/--tests/--docs` 参数。
- `test_repocharts.py`：新增 `Kinds`、`StackedBars`、`Painting` 等测试，更新已有测试适配图例行和新数据结构。
- `AGENTS.md`：Repo charts 一节补充网格线字形、分类规则与堆叠的取舍。

## 注意事项

- 刻度值在行顶边，居中的 `·` 会读低半行；要让它准确只能把柱子整体下移半行，会让小值全部塌成 `▁`，所以不用。
- 内置规则里 docs 先于 tests 匹配，`kb/test-plan.md` 才不会被算成 tests；代价是放在 `tests/fixtures/` 下的 Markdown 会算 docs，需要 `--tests tests/` 纠正。
- 重命名按"删除 + 新增"计，文件换类别时行数跟着转移。
- 一个字符格最多表达两层，柱顶那格只能用一种颜色，所以比 1/8 行还薄的层会在相邻柱子间时有时无（scripts 仓库的 tests 层即如此）；图例里是确切数字。`--log` 下上层看起来更薄。
- 终端渲染用 `tmp/render_ansi.py` 按 iTerm2 配色模拟，`tmp/pty_capture.py` 通过 pty 抓带颜色的输出；截图在 `tmp/2026-11-11-repocharts-kinds/`（模拟图，非真实截图）。

## 遗留问题

- 用户尚未在真实终端里确认分层配色和 `˙` 的观感。
- 可能的后续：`--files` 选项列出 HEAD 下每类的文件和行数，方便调规则；`skills/*/SKILL.md` 目前算 docs，用户可能想算 src。
- 早先建议但未做：谷峰时提示 `--log`、LOC 图非零基线、`./link-script repocharts.py`。
