#!/usr/bin/env -S ${HOME}/.local/bin/uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pypinyin",
# ]
# ///

# @raycast.schemaVersion 1
# @raycast.title Rime QuickAdd
# @raycast.mode silent
# @raycast.icon 📝
# @raycast.packageName Rime
# @raycast.description 将选中的文字添加到 Rime 词库
# @raycast.author reorx

"""
Rime QuickAdd - 快速添加词条到 Rime 词库

从选中文字复制到剪贴板，转换为拼音，添加到用户词库，并触发重新部署。
"""

# ============ 配置 ============
# 词库文件路径，默认使用 quickadd.dict.yaml（可参与造句）
DICT_FILE_PATH = "~/Library/Rime/quickadd.dict.yaml"
# =============================

import subprocess
import sys
import time
from pathlib import Path

from pypinyin import lazy_pinyin

DICT_FILE = Path(DICT_FILE_PATH).expanduser()
SQUIRREL_BIN = "/Library/Input Methods/Squirrel.app/Contents/MacOS/Squirrel"


def notify(title: str, message: str):
    """发送 macOS 系统通知"""
    subprocess.run([
        "osascript", "-e",
        f'display notification "{message}" with title "{title}"'
    ], check=False)


def copy_selection():
    """发送 Cmd+C 复制选中文字到剪贴板"""
    subprocess.run([
        "osascript", "-e",
        'tell application "System Events" to keystroke "c" using command down'
    ], check=False)
    time.sleep(0.1)


def get_clipboard() -> str:
    """获取剪贴板内容"""
    result = subprocess.run(["pbpaste"], capture_output=True, text=True)
    return result.stdout.strip()


def to_pinyin(text: str) -> str:
    """将中文转换为拼音，空格分隔"""
    return " ".join(lazy_pinyin(text))


def word_exists(word: str) -> bool:
    """检查词条是否已存在于词库中"""
    if not DICT_FILE.exists():
        return False
    content = DICT_FILE.read_text(encoding="utf-8")
    in_header = True
    for line in content.splitlines():
        # 跳过 YAML 头部（... 之前的内容）
        if in_header:
            if line == "...":
                in_header = False
            continue
        if line.startswith(word + "\t") or line == word:
            return True
    return False


def add_word(word: str, pinyin: str):
    """添加词条到词库文件"""
    with open(DICT_FILE, "a", encoding="utf-8") as f:
        f.write(f"{word}\t{pinyin}\n")


def reload_rime():
    """触发鼠须管重新部署"""
    subprocess.run([SQUIRREL_BIN, "--reload"], check=False)


def main():
    # 复制选中文字
    copy_selection()

    # 获取剪贴板内容
    word = get_clipboard()

    if not word:
        notify("Rime QuickAdd", "剪贴板为空")
        sys.exit(1)

    # 检查是否过长
    if len(word) > 20:
        notify("Rime QuickAdd", f"文字过长：{word[:10]}...")
        sys.exit(1)

    # 检查是否已存在
    if word_exists(word):
        notify("Rime QuickAdd", f"词条已存在：{word}")
        sys.exit(0)

    # 转换拼音
    pinyin = to_pinyin(word)

    # 添加到词库
    add_word(word, pinyin)

    # 重新部署
    reload_rime()

    # 通知成功
    notify("Rime QuickAdd", f"已添加：{word} ({pinyin})")


if __name__ == "__main__":
    main()
