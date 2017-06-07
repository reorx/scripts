#!/usr/bin/env python
# coding: utf-8

import os
import re
import sys
import shlex
import logging
import subprocess
import argparse


__version__ = '0.1.0'


PY3 = sys.version_info >= (3,)


lg = logging.getLogger('magnet')
cmd_lg = logging.getLogger('cmd')
result_lg = logging.getLogger('cmd')


def main():
    # the `formatter_class` can make description & epilog show multiline
    parser = argparse.ArgumentParser(
        description="convert torrent file to magnet uri",
        epilog="",
        formatter_class=argparse.RawDescriptionHelpFormatter)

    # arguments
    parser.add_argument('file', metavar="FILE", nargs='+', type=str, help="")

    # options
    #parser.add_argument('-t', '--aa', type=int, default=0, help="")
    #parser.add_argument('-b', '--bb', type=str, help="")
    #parser.add_argument('-c', '--cc', action='store_true', help="")

    parser.add_argument('--no-trim', action='store_true', help="no trim for magnet uri")

    # --version
    parser.add_argument('--version', action='version',
                        version='%(prog)s {version}'.format(version=__version__))

    args = parser.parse_args()

    for i in args.file:
        print torrent_to_magnet(i, trim=not args.no_trim)


def torrent_to_magnet(path, trim=True):
    _, out, err = run_cmd_raise_if_fail(['aria2c', '-S', path])
    return parse_aria2c_output(out, trim)


ARIA2C_MAGNET_LINE_START = 'Magnet URI:'
ARIA2C_MAGNET_REGEX = re.compile(r'(magnet:[\S]+$)')


def parse_aria2c_output(out, trim=True):
    keyline = None
    for line in out.splitlines():
        if line.startswith(ARIA2C_MAGNET_LINE_START):
            keyline = line
            break
    if not keyline:
        return
    r = ARIA2C_MAGNET_REGEX.search(keyline)
    if not r:
        return
    magnet = r.group()
    if trim:
        pos = magnet.find('&')
        if pos != -1:
            magnet = magnet[:pos]
    return magnet


class CommandFailed(Exception):
    pass


def run_cmd(cmd, shlex_reformat=False, shell=False, **kwargs):
    if shlex_reformat and shell:
        raise ValueError('shlex_reformat and shell are mutually exclusive')

    if shell:
        if not isinstance(cmd, str):
            raise ValueError('cmd must be str when shell=True')
        kwargs['shell'] = shell

    # reformat cmd
    if shlex_reformat:
        if isinstance(cmd, list):
            cmd_str = ' '.join(cmd)
        else:
            cmd_str = cmd
        cmd = shlex.split(cmd_str)

    cmd_lg.debug('cmd: %s, %s', cmd, kwargs)

    extra_env = kwargs.pop('env', {})
    if extra_env:
        env = os.environ.copy()
        env.update(extra_env)
        kwargs['env'] = env

    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    out, err = p.communicate()
    if PY3:
        out, err = out.decode(), err.decode()

    result_lg.debug('cmd=%s returncode=%s out=%s err=%s', cmd, p.returncode, out, err)
    return p.returncode, out, err


def run_cmd_raise_if_fail(cmd, **kwargs):
    rc, out, err = run_cmd(cmd, **kwargs)
    if rc != 0:
        raise CommandFailed(
            'cmd: {}, exit: {}, out: {}, err: {}'.format(
                cmd, rc, out[:2000], err[:2000],
            ))
    return rc, out, err


if __name__ == '__main__':
    main()
