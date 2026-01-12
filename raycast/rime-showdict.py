#!/usr/bin/env -S ${HOME}/.local/bin/uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

# @raycast.schemaVersion 1
# @raycast.title Rime Show Dict
# @raycast.mode fullOutput
# @raycast.icon 📖
# @raycast.packageName Rime
# @raycast.description 显示和搜索 quickadd 词库
# @raycast.author reorx
# @raycast.argument1 { "type": "text", "placeholder": "搜索词 (可选)", "optional": true }

"""
Rime Show Dict - 显示和搜索 quickadd 词库
"""

# ============ 配置 ============
# 词库文件路径，默认使用 quickadd.dict.yaml（可参与造句）
DICT_FILE_PATH = "~/Library/Rime/quickadd.dict.yaml"
# =============================

import sys
from pathlib import Path

DICT_FILE = Path(DICT_FILE_PATH).expanduser()


def parse_dict() -> list[tuple[str, str]]:
    """解析词库文件，返回 (词, 拼音) 列表"""
    if not DICT_FILE.exists():
        return []

    entries = []
    in_header = True

    for line in DICT_FILE.read_text(encoding="utf-8").splitlines():
        # 跳过 YAML 头部
        if in_header:
            if line == "...":
                in_header = False
            continue

        # 跳过空行和注释
        if not line or line.startswith("#"):
            continue

        # 解析词条
        parts = line.split("\t")
        if len(parts) >= 2:
            entries.append((parts[0], parts[1]))
        elif len(parts) == 1 and parts[0]:
            entries.append((parts[0], ""))

    return entries


def main():
    query = sys.argv[1].strip() if len(sys.argv) > 1 else ""

    entries = parse_dict()

    if query:
        # 搜索：匹配词或拼音
        filtered = [
            (word, pinyin) for word, pinyin in entries
            if query in word or query in pinyin
        ]
    else:
        filtered = entries

    # 输出
    total = len(entries)
    shown = len(filtered)

    if query:
        print(f"搜索: \"{query}\" | 匹配: {shown}/{total}")
    else:
        print(f"总计: {total} 条")

    print("-" * 40)

    if not filtered:
        print("(无结果)")
    else:
        for word, pinyin in filtered:
            print(f"{word}\t{pinyin}")


if __name__ == "__main__":
    main()
