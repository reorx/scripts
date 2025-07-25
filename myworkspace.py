#!/usr/bin/env python
# coding: utf-8

import sh
import os
import functools
from operator import getitem
from contextlib import contextmanager


class options:  # NOQA
    items_per_line = 3
    tab = 2


def get_node_type(name):
    if os.path.isdir(name):
        return 'dir'
    elif os.path.isfile(name):
        return 'file'
    else:
        path = os.path.abspath(name)
        raise TypeError('WTF is this: {}, {}'.format(name, os.stat(path)))


@contextmanager
def cdctx(path):
    old_cwd = os.getcwd()
    os.chdir(path)
    yield
    os.chdir(old_cwd)


class Node(object):
    def __init__(self, name):
        self.name = name
        self.type = get_node_type(name)
        self.is_git = None
        self.pushed = None

    def _ensure_type(self, type):
        if type != self.type:
            raise TypeError('Should be type %s to perform' % type)

    def check_git(self):
        self._ensure_type('dir')
        with cdctx(self.name):
            if os.path.exists('.git'):
                self.is_git = True
                uncleared = sh.git('status', '--porcelain').strip()
                if uncleared:
                    self.pushed = False
                else:
                    self.pushed = True
            else:
                self.is_git = False

    def __str__(self):
        is_git = 'git' if self.is_git is True else ''
        if self.pushed is True:
            pushed = 'pushed'
        elif self.pushed is False:
            pushed = 'not pushed'
        else:
            pushed = ''
        return '<{type} {name}, {is_git}, {pushed}>'.format(
            type=self.type, name=self.name,
            is_git=is_git, pushed=pushed
        )


class NodeList(object):
    def __init__(self, *paths):
        nodes = {}
        for path in paths:
            segments = path.split('/')
            last_pos = len(segments) - 1
            last_item = nodes
            for i, segment in enumerate(segments):
                if i < last_pos:
                    last_item = last_item.setdefault(segment, {})
                else:
                    last_item.setdefault(segment, [])
        #print(nodes)
        self.nodes = nodes

    @staticmethod
    def _getitem_by_path(d, path):
        if not path:
            return d
        return functools.reduce(lambda x, y: getitem(x, y), [d] + path.split('/'))

    def __getitem__(self, key):
        return self._getitem_by_path(self.nodes, key)

    def __setitem__(self, key, value):
        i = key.rfind('/')
        a = key[:i]
        b = key[i + 1:]
        self[a][b] = value

    def __delitem__(self, key):
        pass

    def len(self, path):
        v = self[path]
        if isinstance(v, dict):
            length = 0
            for k in v:
                length += self.len(path + '/' + k)
        else:
            length = len(v)
        return length


def list_nodes():
    for i in sh.ls('-1').split('\n'):
        name = i.strip()
        if not name:
            continue
        yield Node(name)


def echo(s, indent=None, prefix=None):
    if prefix:
        s = prefix + s
    if indent:
        s = ' ' * indent + s

    print(s)


def echo_nodes(nodes, indent=None, prefix='│ '):
    lines = []
    col_max_widths = [0 for x in range(options.items_per_line)]
    line_buf = []

    for i, node in enumerate(nodes):
        line_buf.append(node.name)

        pos = i % options.items_per_line
        text_len = len(node.name)
        if col_max_widths[pos] < text_len:
            col_max_widths[pos] = text_len

        if len(line_buf) >= options.items_per_line:
            #line = '\t'.join(line_buf)
            #echo(line, indent, prefix)
            lines.append(line_buf)
            line_buf = []

    if line_buf:
        # Fix line_buf length to be exact the same as items_per_line
        line_buf.extend((options.items_per_line - len(line_buf)) * [''])
        lines.append(line_buf)

    # Echo lines
    padding = 2
    line_tpl = ''.join('{:<%s}' % (i + padding) for i in col_max_widths)
    for line in lines:
        line_str = line_tpl.format(*line)
        echo(line_str, indent, prefix)

    #col_width = max(len(word) for line in lines for word in line) + 2  # 2 is padding
    #for line in lines:
    #    line_str = "".join(word.ljust(col_width) for word in line)
    #    echo(line_str, indent, prefix)

    #widths = [max(map(len, col)) for col in zip(*lines)]
    #for row in table:
        #print('  '.join((val.ljust(width) for val, width in zip(row, widths))))


def main():
    echo('cwd: {}'.format(os.getcwd()))
    echo('Scanning..\n')
    nodes = NodeList(
        'file',
        'dir/_',
        'dir/git/_',
        'dir/git/pushed',
    )
    #nodes = {
    #    'file': [],
    #    'dir': {
    #        'git': {
    #            'pushed': [],
    #            '_': []
    #        },
    #        '_': []
    #    }
    #}

    for node in list_nodes():
        if node.type == 'dir':
            node.check_git()

            if node.is_git:
                if node.pushed:
                    nodes['dir/git/pushed'].append(node)
                    #nodes['dir']['git']['pushed'].append(node)
                else:
                    nodes['dir/git/_'].append(node)
                    #nodes['dir']['git']['_'].append(node)
            else:
                nodes['dir/_'].append(node)
                #nodes['dir']['_'].append(node)
        else:
            nodes['file'].append(node)

    # Show them all
    tab = options.tab

    k = 'file'
    echo('Files (%s):' % nodes.len(k))
    echo_nodes(nodes[k], tab)
    echo('')

    #
    echo('Directories (%s):' % nodes.len('dir'))
    # #
    echo('Git (%s):' % nodes.len('dir/git'), tab)
    # ##
    k = 'dir/git/pushed'
    echo('Pushed (%s):' % nodes.len(k), tab * 2)
    echo_nodes(nodes[k], tab * 2)
    echo('')
    # ##
    k = 'dir/git/_'
    echo('Not pushed (%s):' % nodes.len(k), tab * 2)
    echo_nodes(nodes[k], tab * 2)
    echo('')
    # #
    k = 'dir/_'
    echo('Normal (%s):' % nodes.len(k), tab)
    echo_nodes(nodes[k], tab)


if __name__ == '__main__':
    main()
