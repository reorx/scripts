#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["prompt-toolkit>=3.0,<4"]
# ///
"""Download a thunderx:// JSON task list using a dedicated foreground aria2.

    ./thunder-download.py                     # paste a list, then press Enter
    ./thunder-download.py tmp/thunder.txt
    ./thunder-download.py tmp/thunder.txt -d /Volumes/Data/Downloads

Requires aria2c (brew install aria2). Downloads at most two files at once.
Ctrl-C saves progress; run the same command to resume. Permanent errors are
reported with a nonzero exit code after the remaining tasks finish.
"""

import argparse
import json
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from prompt_toolkit import prompt


def parse_tasks(text: str) -> list[str]:
    text = text.lstrip('\ufeff').strip()
    if not text.startswith('thunderx://'):
        raise ValueError('下载列表必须以 thunderx:// 开头')
    data = json.loads(text.removeprefix('thunderx://'))
    if not isinstance(data, dict):
        raise ValueError('下载列表必须是 JSON 对象')
    tasks = data.get('tasks')
    if not isinstance(tasks, list) or not tasks:
        raise ValueError('下载列表 tasks 必须是非空数组')
    urls = []
    for index, task in enumerate(tasks, 1):
        url = task.get('url') if isinstance(task, dict) else None
        if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
            raise ValueError(f'任务 {index} 的 URL 无效或包含空白/控制字符')
        parts = urlsplit(url)
        if parts.scheme not in {'http', 'https', 'ftp'} or not parts.hostname:
            raise ValueError(f'任务 {index} 必须使用有效的 HTTP、HTTPS 或 FTP 地址')
        urls.append(url)
    return list(dict.fromkeys(urls))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('file', nargs='?', type=Path, help='迅雷一键下载列表文件（省略时粘贴输入）')
    parser.add_argument(
        '-d',
        '--dir',
        '--directory',
        dest='directory',
        type=Path,
        default=Path.home() / 'Downloads',
        help='下载目录（默认：~/Downloads）',
    )
    return parser.parse_args(argv)


def aria2_command(executable: str, directory: Path) -> list[str]:
    return [
        executable,
        '--no-conf=true',
        '--enable-rpc=false',
        '--daemon=false',
        f'--dir={directory}',
        '--input-file=-',
        '--max-concurrent-downloads=2',
        '--max-connection-per-server=4',
        '--split=4',
        '--min-split-size=20M',
        '--continue=true',
        '--always-resume=true',
        '--auto-file-renaming=false',
        '--allow-overwrite=false',
        '--file-allocation=none',
        '--auto-save-interval=10',
        '--connect-timeout=15',
        '--timeout=60',
        '--max-tries=10',
        '--retry-wait=5',
        '--summary-interval=10',
        '--download-result=full',
    ]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    process = None
    try:
        if args.file is not None:
            urls = parse_tasks(args.file.read_text(encoding='utf-8-sig'))
        else:
            # prompt_toolkit preserves bracketed multiline paste until Enter,
            # including on macOS Python builds using libedit.
            print('请粘贴迅雷下载内容（支持多行），粘贴完成后按回车确认；Ctrl+C 取消。', flush=True)
            text = ''
            while True:
                text += prompt('> ' if not text else '… ') + '\n'
                try:
                    urls = parse_tasks(text)
                except json.JSONDecodeError:
                    # Also accept multiline input in terminals without
                    # bracketed paste support; wait for a complete JSON value.
                    continue
                break
        executable = shutil.which('aria2c')
        if not executable:
            raise RuntimeError('找不到 aria2c，请先安装：brew install aria2')
        directory = args.directory.expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        print(f'共 {len(urls)} 个任务，最多同时下载 2 个文件，保存到 {directory}', flush=True)
        process = subprocess.Popen(aria2_command(executable, directory), stdin=subprocess.PIPE, text=True)
        process.communicate('\n'.join(urls) + '\n')
        if process.returncode:
            print('部分任务下载失败；检查上方 aria2 结果，重新运行相同命令可续传。', file=sys.stderr)
        else:
            print('所有任务已完成。')
        return process.returncode if process.returncode >= 0 else 128 - process.returncode
    except KeyboardInterrupt:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGINT)
            process.wait()
        print('\n下载已停止，重新运行相同命令可续传。', file=sys.stderr)
        return 130
    except EOFError:
        print('错误：输入为空或下载列表不完整，请重新粘贴完整内容。', file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'错误：{exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
