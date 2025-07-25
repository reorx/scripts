#!/usr/bin/env python3

import os
import subprocess
import functools
from operator import getitem
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, List, Dict, Any, Union


class Options:
    items_per_line = 3
    tab = 2


def get_node_type(name: str) -> str:
    path = Path(name)
    if path.is_dir():
        return 'dir'
    elif path.is_file():
        return 'file'
    else:
        raise TypeError(f'Unknown file type: {name}, {path.stat()}')


@contextmanager
def cdctx(path: str):
    old_cwd = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


class Node:
    def __init__(self, name: str):
        self.name = name
        self.type = get_node_type(name)
        self.is_git: Optional[bool] = None
        self.pushed: Optional[bool] = None

    def _ensure_type(self, node_type: str) -> None:
        if node_type != self.type:
            raise TypeError(f'Should be type {node_type} to perform this operation')

    def check_git(self) -> None:
        self._ensure_type('dir')
        with cdctx(self.name):
            if Path('.git').exists():
                self.is_git = True
                try:
                    result = subprocess.run(
                        ['git', 'status', '--porcelain'],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    uncleared = result.stdout.strip()
                    self.pushed = not bool(uncleared)
                except subprocess.CalledProcessError:
                    self.pushed = False
            else:
                self.is_git = False

    def __str__(self) -> str:
        is_git = 'git' if self.is_git is True else ''
        if self.pushed is True:
            pushed = 'pushed'
        elif self.pushed is False:
            pushed = 'not pushed'
        else:
            pushed = ''
        return f'<{self.type} {self.name}, {is_git}, {pushed}>'


class NodeList:
    def __init__(self, *paths: str):
        nodes: Dict[str, Any] = {}
        for path in paths:
            segments = path.split('/')
            last_pos = len(segments) - 1
            last_item = nodes
            for i, segment in enumerate(segments):
                if i < last_pos:
                    last_item = last_item.setdefault(segment, {})
                else:
                    last_item.setdefault(segment, [])
        self.nodes = nodes

    @staticmethod
    def _getitem_by_path(d: Dict[str, Any], path: str) -> Any:
        if not path:
            return d
        return functools.reduce(lambda x, y: getitem(x, y), [d] + path.split('/'))

    def __getitem__(self, key: str) -> Any:
        return self._getitem_by_path(self.nodes, key)

    def __setitem__(self, key: str, value: Any) -> None:
        i = key.rfind('/')
        a = key[:i]
        b = key[i + 1:]
        self[a][b] = value

    def __delitem__(self, key: str) -> None:
        pass

    def len(self, path: str) -> int:
        v = self[path]
        if isinstance(v, dict):
            length = 0
            for k in v:
                length += self.len(f'{path}/{k}')
        else:
            length = len(v)
        return length


def list_nodes() -> List[Node]:
    nodes = []
    try:
        for item in os.listdir('.'):
            if item.strip():
                nodes.append(Node(item))
    except OSError:
        pass
    return nodes


def echo(s: str, indent: Optional[int] = None, prefix: Optional[str] = None) -> None:
    if prefix:
        s = prefix + s
    if indent:
        s = ' ' * indent + s
    print(s)


def echo_nodes(nodes: List[Node], indent: Optional[int] = None, prefix: str = '│ ') -> None:
    options = Options()
    lines = []
    col_max_widths = [0 for _ in range(options.items_per_line)]
    line_buf = []

    for i, node in enumerate(nodes):
        line_buf.append(node.name)

        pos = i % options.items_per_line
        text_len = len(node.name)
        if col_max_widths[pos] < text_len:
            col_max_widths[pos] = text_len

        if len(line_buf) >= options.items_per_line:
            lines.append(line_buf)
            line_buf = []

    if line_buf:
        # Fix line_buf length to be exact the same as items_per_line
        line_buf.extend((options.items_per_line - len(line_buf)) * [''])
        lines.append(line_buf)

    # Echo lines
    padding = 2
    line_tpl = ''.join(f'{{:<{i + padding}}}' for i in col_max_widths)
    for line in lines:
        line_str = line_tpl.format(*line)
        echo(line_str, indent, prefix)


def main() -> None:
    options = Options()
    echo(f'cwd: {os.getcwd()}')
    echo('Scanning..\n')
    nodes = NodeList(
        'file',
        'dir/_',
        'dir/git/_',
        'dir/git/pushed',
    )

    for node in list_nodes():
        if node.type == 'dir':
            node.check_git()

            if node.is_git:
                if node.pushed:
                    nodes['dir/git/pushed'].append(node)
                else:
                    nodes['dir/git/_'].append(node)
            else:
                nodes['dir/_'].append(node)
        else:
            nodes['file'].append(node)

    # Show them all
    tab = options.tab

    k = 'file'
    echo(f'Files ({nodes.len(k)}):')
    echo_nodes(nodes[k], tab)
    echo('')

    echo(f'Directories ({nodes.len("dir")}):')
    echo(f'Git ({nodes.len("dir/git")}):', tab)
    
    k = 'dir/git/pushed'
    echo(f'Pushed ({nodes.len(k)}):', tab * 2)
    echo_nodes(nodes[k], tab * 2)
    echo('')
    
    k = 'dir/git/_'
    echo(f'Not pushed ({nodes.len(k)}):', tab * 2)
    echo_nodes(nodes[k], tab * 2)
    echo('')
    
    k = 'dir/_'
    echo(f'Normal ({nodes.len(k)}):', tab)
    echo_nodes(nodes[k], tab)


if __name__ == '__main__':
    main()
