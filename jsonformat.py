#!/usr/bin/env python

import sys
import json
import argparse


def main():
    # the `formatter_class` can make description & epilog show multiline
    parser = argparse.ArgumentParser(
        description="Format JSON file using Python builtin json library",
        formatter_class=argparse.RawDescriptionHelpFormatter)

    # arguments
    parser.add_argument('file', metavar="FILE", nargs='?', type=str,
                        help='JSON file input, read from stdin if not provided')

    # options
    parser.add_argument('-i', '--indent', type=int, default=2,
                        help='number of spaces to indent, default: 2')
    #parser.add_argument('-b', '--bb', type=str, help='')
    parser.add_argument('-w', '--write', action='store_true',
                        help='write back origin file, only works when input FILE is specified')

    args = parser.parse_args()

    if args.file:
        with open(args.file, 'r') as f:
            s = f.read()
    else:
        s = sys.stdin.read()

    kwargs = dict(sort_keys=True)
    if args.indent > 0:
        kwargs['indent'] = args.indent
    try:
        formatted = json.dumps(json.loads(s), **kwargs)
    except Exception:
        sys.stderr.write(f'Error!\n{s}\n')
        raise
    if args.file and args.write:
        print(f'Writing {args.file}')
        with open(args.file, 'w') as f:
            f.write(formatted + '\n')
    else:
        print(formatted)


if __name__ == '__main__':
    main()
