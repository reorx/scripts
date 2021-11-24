import sys
import subprocess as sp


def usage(*args):
    if args:
        print(*args)
    print('Usage: codepoint <chars>')


def main():
    try:
        chars = sys.argv[1]
    except IndexError:
        usage('invalid arguments, <chars> missing')
        sys.exit(1)

    if chars in ['-h', '--help']:
        usage()
        sys.exit()

    h = ['Char', 'Ord', 'Hex', 'Code_Point']
    d = [h]
    for i in chars:
        n = ord(i)
        x = hex(n)
        xs = str(x)[2:]
        if len(xs) < 4:
            xs = '0' * (4 - len(xs)) + xs
        cp = 'U+' + xs
        d.append([i, str(n), str(x), cp])
    text = '\n'.join(' '.join(l) for l in d) + '\n'
    p = sp.Popen(['column', '-t'], stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE)
    out, err = p.communicate(text.encode())
    if p.returncode == 0:
        print(out.decode())
    else:
        print('Out: {}\n\nErr:{}'.format(out.decode(), err.decode()))
        sys.exit(p.returncode)


if __name__ == '__main__':
    main()
