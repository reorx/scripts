# coding: utf-8
from __future__ import print_function
import os
import sys
import subprocess as sp


PY2 = sys.version_info.major == 2
if not PY2:
    unicode = str


def b_(s):
    """ensure binary type"""
    if PY2:
        if isinstance(s, unicode):
            return s.encode('utf8')
        return s
    if isinstance(s, str):
        return s.encode()
    return s


def t_(b):
    """ensure text type"""
    if PY2:
        if isinstance(b, str):
            return b.decode('utf8')
        return b
    if isinstance(b, bytes):
        return b.decode()
    return b


def usage(*args):
    if args:
        print(*args)
    print('Usage: codepoint <chars>')


if __name__ == '__main__':
    try:
        chars = sys.argv[1]
    except IndexError:
        usage('invalid arguments, <chars> missing')
        sys.exit(1)
    if chars == '-h':
        usage()
        sys.exit()

    h = [t_('Char'), t_('Ord'), t_('Hex'), t_('Code Point')]
    d = [h]
    for i in t_(chars):
        n = ord(i)
        x = hex(n)
        xs = str(x)[2:]
        if len(xs) < 4:
            xs = t_('0') * (4 - len(xs)) + xs
        cp = t_('U+') + xs
        d.append([i, str(n), str(x), cp.upper()])
    # add LF, or `column` in macos will raise `line too long` error
    text = t_('\n').join(t_(',').join(l) for l in d) + t_('\n')
    p = sp.Popen(
        ['column', '-s,', '-t'],
        stdin=sp.PIPE,
        stdout=sp.PIPE,
        stderr=sp.PIPE,
        env=os.environ.copy(),
    )

    out, err = p.communicate(b_(text))
    out = t_(out)
    err = t_(err)
    if p.returncode == 0:
        print(out)
    else:
        print(
            t_('Out: {}\n\nErr:{}').format(
                out, err,
            )
        )
        sys.exit(p.returncode)
