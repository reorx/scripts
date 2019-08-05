#!/usr/bin/env python

import re
import os
import argparse
import subprocess


def main():
    epilog = """\
Environment vars:
- GIT_LIST_ISSUES_URL
"""
    # the `formatter_class` can make description & epilog show multiline
    parser = argparse.ArgumentParser(description="List JIRA issues in commits", epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)

    # arguments
    parser.add_argument('revision', metavar="REVISION", type=str, help="e.g. 1.9..1.10, c5f897f..6132241")

    # options
    #parser.add_argument('-a', '--aa', type=int, default=0, help="")
    #parser.add_argument('-b', '--bb', type=str, help="")
    #parser.add_argument('-c', '--cc', action='store_true', help="")

    args = parser.parse_args()

    base_url = os.environ.get('GIT_LIST_ISSUES_URL')

    cmd = ['git', 'log', '--oneline', args.revision]
    commits = subprocess.check_output(cmd).decode()

    """
    7d26cd3 (HEAD -> master, tag: 1.10, origin/master, origin/HEAD) empty for 1.10
    3798e8a Merge pull request #135 in MSS/cashier from feature/MSS-420-cashier-new-check-transaction-limit-order-quote-alter to master
    """
    commit_re = re.compile(r'^(\w+)\s(\(.+\)\s)?(.+)$')
    issue_key_re = re.compile(r'\/([A-Z]+-\d+)')

    issue_keys = []
    for i in commits.split('\n'):
        i = i.strip()
        if not i:
            continue

        # parse commits
        #print(i)
        rv = commit_re.search(i)
        if not rv:
            continue
        #print(rv.groups())
        hash, branch_info, message = rv.groups()

        # match issue key
        rv1 = issue_key_re.search(message)
        if not rv1:
            continue
        key = rv1.group()[1:]

        key_url_display = ''
        if base_url:
            key_url = base_url + key
            key_url_display = f' ({key_url})'

        line = f"""- {key}{key_url_display}:
  {message}"""
        print(line)

        issue_keys.append(key)


if __name__ == '__main__':
    main()
