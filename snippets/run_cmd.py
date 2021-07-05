# coding: utf-8

import os
import sys
import shlex
import logging
import subprocess


PY3 = sys.version_info >= (3,)


lg = logging.getLogger('cmd')
result_lg = logging.getLogger('cmd')


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

    lg.debug('cmd: %s, %s', cmd, kwargs)

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
