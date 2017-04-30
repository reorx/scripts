#!/usr/bin/env python
# coding: utf-8

"""
lshosts.py - List IPs and domains in ~/.ssh/known_hosts
"""

from __future__ import print_function
import os
import sys
import string


def parse_line(l):
    sp = l.strip().split(' ')
    if len(sp) < 3:
        return None
    return sp[0]


def parse_hostport(l):
    h, p = tuple(l.split(':'))
    h = h.replace('[', '').replace(']', '')
    return (h, p)


def is_ip_hosts(hs):
    if hs[0][0][0] in string.digits:
        return True
    return False


def format_host(h):
    if h[1] is None:
        return h[0]
    else:
        return '{}:{}'.format(*h)


def print_usage():
    print(
        'Usage: ./lshosts.py [PATH]\n'
        '       ./lshosts.py -h | --help\n'
        '\n'
        'Arguments:\n'
        '  PATH    path to known_hosts file, default is ~/.ssh/known_hosts\n'
    )


def main():
    try:
        path = sys.argv[1]
    except IndexError:
        path = os.path.expanduser('~/.ssh/known_hosts')

    if path in ['-h', '--help']:
        print_usage()
        sys.exit(0)

    raw_hosts_list = []

    with open(path, 'r') as f:
        for i in f.readlines():
            pl = parse_line(i)
            if pl is None:
                continue
            raw_hosts_list.append(pl)

    hosts_list = []
    ip_hosts_list = []
    domain_hosts_list = []
    for i in raw_hosts_list:
        hosts = []
        for j in i.split(','):
            if ':' in j:
                hosts.append(parse_hostport(j))
            else:
                hosts.append((j, None))
        #print(hosts)
        hosts_list.append(hosts)
        if is_ip_hosts(hosts):
            ip_hosts_list.append(hosts)
        else:
            domain_hosts_list.append(hosts)

    ip_hosts_list = sorted(ip_hosts_list, key=lambda x: x[0][0])
    domain_hosts_list = sorted(domain_hosts_list, key=lambda x: x[0][0])

    print('IP hosts:')
    for i in ip_hosts_list:
        print(', '.join(format_host(j) for j in i))

    print()
    print('Domain hosts:')
    for i in domain_hosts_list:
        print('\t'.join(format_host(j) for j in i))


if __name__ == '__main__':
    main()
