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
DICT_FILE_PATH = '~/Library/Rime/quickadd.dict.yaml'
DICT_NAME = 'quickadd'
# =============================

import subprocess
import sys
from datetime import date
from pathlib import Path

from pypinyin import lazy_pinyin

DICT_FILE = Path(DICT_FILE_PATH).expanduser()
SQUIRREL_BIN = '/Library/Input Methods/Squirrel.app/Contents/MacOS/Squirrel'

# Rime 词典文件的 YAML 头部模板
DICT_HEADER_TEMPLATE = """---
name: {name}
version: "{version}"
sort: by_weight
...

"""


def notify(title: str, message: str):
    """发送 macOS 系统通知"""
    subprocess.run(['osascript', '-e', f'display notification "{message}" with title "{title}"'], check=False)


APPLESCRIPT_GET_SELECTION = """
-- 1. 保存当前剪贴板内容
set savedClipboard to the clipboard

-- 2. 模拟 Command + C
tell application "System Events"
    keystroke "c" using command down
end tell

-- 等待系统完成复制动作
delay 0.1

-- 3. 获取选中文字
set selectedText to the clipboard

-- 4. 恢复之前的剪贴板内容
set the clipboard to savedClipboard

-- 5. 输出结果
return selectedText
"""


def get_selection() -> str:
    """通过 AppleScript 获取选中文字，并恢复剪贴板"""
    result = subprocess.run(
        ['osascript', '-e', APPLESCRIPT_GET_SELECTION], capture_output=True, text=True, encoding='utf-8'
    )
    return result.stdout.strip()


def get_input() -> str:
    """获取输入文字：优先 stdin，否则从选中文字"""
    if not sys.stdin.isatty():
        text = sys.stdin.read().strip()
        if text:
            return text
    text = get_selection()
    if not text:
        raise ValueError('could not get text')
    return text


def to_pinyin(text: str) -> str:
    """将中文转换为拼音，空格分隔"""
    return ' '.join(lazy_pinyin(text))


def ensure_dict_file():
    """确保词库文件存在，不存在则创建带有正确头部的文件"""
    if DICT_FILE.exists():
        return
    header = DICT_HEADER_TEMPLATE.format(
        name=DICT_NAME,
        version=date.today().isoformat(),
    )
    DICT_FILE.write_text(header, encoding='utf-8')


def word_exists(word: str) -> bool:
    """检查词条是否已存在于词库中"""
    if not DICT_FILE.exists():
        return False
    content = DICT_FILE.read_text(encoding='utf-8')
    lines = content.splitlines()

    # 检测是否有 YAML 头部（以 --- 开头）
    has_header = lines and lines[0].strip() == '---'
    in_header = has_header

    for line in lines:
        # 跳过 YAML 头部（... 之前的内容）
        if in_header:
            if line.strip() == '...':
                in_header = False
            continue
        # 跳过空行和注释
        if not line or line.startswith('#'):
            continue
        if line.startswith(word + '\t') or line == word:
            return True
    return False


def add_word(word: str, pinyin: str):
    """添加词条到词库文件"""
    with open(DICT_FILE, 'a', encoding='utf-8') as f:
        f.write(f'{word}\t{pinyin}\n')


def reload_rime():
    """触发鼠须管重新部署"""
    subprocess.run([SQUIRREL_BIN, '--reload'], check=False)


def main():
    debug = '--debug' in sys.argv

    # 获取输入文字
    try:
        word = get_input()
    except Exception as e:
        notify('Rime QuickAdd', f'Error: {e}')
        return

    if debug:
        print(f'[DEBUG] 输入文字: {word}')
        print(f'[DEBUG] 输入 repr: {repr(word)}')

    if not word:
        if debug:
            print('[DEBUG] 错误: 输入为空')
        else:
            notify('Rime QuickAdd', '剪贴板为空')
        sys.exit(1)

    # 检查是否过长
    if len(word) > 20:
        if debug:
            print(f'[DEBUG] 错误: 文字过长 ({len(word)} 字符)')
        else:
            notify('Rime QuickAdd', f'文字过长：{word[:10]}...')
        sys.exit(1)

    # 确保词库文件存在
    ensure_dict_file()

    # 检查是否已存在
    if word_exists(word):
        if debug:
            print('[DEBUG] 已添加过该词条')
        else:
            notify('Rime QuickAdd', f'已添加过：{word}')
        sys.exit(0)

    # 转换拼音
    pinyin = to_pinyin(word)
    line = f'{word}\t{pinyin}'

    if debug:
        print(f'[DEBUG] 拼音转换: {pinyin}')
        print(f'[DEBUG] 词库行: {line}')
        print(f'[DEBUG] 词库行 repr: {repr(line)}')
        print('[DEBUG] (debug 模式，未实际写入)')
        return

    # 添加到词库
    add_word(word, pinyin)

    # 通知成功
    notify('Rime QuickAdd', f'已添加：{word} ({pinyin})')

    # 重新部署
    reload_rime()


if __name__ == '__main__':
    main()
