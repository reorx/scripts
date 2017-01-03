#!/usr/bin/env python
# coding: utf-8
# ref: https://golang.org/cmd/go/ (meta tag)
# NOTE: wsgiref seems to be a HTTP/1.0 server

import os
import sys
from wsgiref.simple_server import make_server


def get_import_path(path):
    return 'foo.example.com{}'.format(get_repo_path(path))


def get_vcs(path):
    return 'git'


def get_repo_url(path):
    # the repo path should be in PROJECT/REPO format,
    # path like /mss/protos/golang/rpc/cashier should be converted to /mss/protos
    return 'ssh://git@bar.example.com{}.git'.format(get_repo_path(path))


def get_repo_path(path):
    sp = path.split('/')
    if len(sp) > 3:
        sp = sp[:3]
    repo_path = '/'.join(sp)
    return repo_path


def log(s):
    sys.stdout.write(s + '\n')
    sys.stdout.flush()


# <meta> should be like:
# <meta name="go-import" content="github.com/reorx/gouken git https://github.com/reorx/gouken.git">
template = """
<html>
    <meta name="go-import" content="{import_path} {vcs} {repo_url}">
</html>"""[1:]


def simple_app(environ, start_response):
    path = environ['PATH_INFO']
    headers = [('Content-type', 'text/html')]
    status = '200 OK'
    body = ''
    if path == '/':
        status = "418 I'm a teapot"
    elif path == '/favicon.ico':
        status = '404 Not Found'
    else:
        #sp = path.split('/')
        #if len(sp) > 3:
        #    status = '404 Not Found'
        #else:
        import_path = get_import_path(path)
        vcs = get_vcs(path)
        repo_url = get_repo_url(path)
        log('import_path={} repo_url={} vcs={}'.format(import_path, repo_url, vcs))
        body = template.format(
            import_path=import_path,
            vcs=vcs,
            repo_url=repo_url,
        )

    start_response(status, headers)
    return body


def main():
    port = int(os.environ.get('PORT', '12345'))
    httpd = make_server('', port, simple_app)
    log('Serving on port {}...'.format(port))
    httpd.serve_forever()


if __name__ == '__main__':
    main()
