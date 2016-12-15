#!/usr/bin/env python
# coding: utf-8
# ref: https://golang.org/cmd/go/ (meta tag)
# NOTE: wsgiref seems to be a HTTP/1.0 server

import os
from wsgiref.simple_server import make_server


def get_import_path(path):
    return 'git.corp.16financial.com{}'.format(path)


def get_vcs(path):
    return 'git'


def get_repo_url(path):
    return 'ssh://git@git.corp.16financial.com{}.git'.format(path)


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
        body = template.format(
            import_path=get_import_path(path),
            vcs=get_vcs(path),
            repo_url=get_repo_url(path),
        )

    start_response(status, headers)
    return body


def main():
    port = int(os.environ.get('PORT', '12345'))
    httpd = make_server('', port, simple_app)
    print 'Serving on port {}...'.format(port)
    httpd.serve_forever()


if __name__ == '__main__':
    main()
