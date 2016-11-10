#!/usr/bin/env python
# coding: utf-8

from __future__ import print_function

import os
import datetime
import requests
import logging
import logging.config


USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/52.0.2743.116 Safari/537.36"

DOWNLOAD_DIR = os.environ.get('BING_DOWNLOAD_DIR')
if not DOWNLOAD_DIR:
    raise ValueError('BING_DOWNLOAD_DIR env is not set')
DOWNLOAD_DIR = os.path.expanduser(DOWNLOAD_DIR)

LOG_LEVEL = os.environ.get('BING_LOG_LEVEL', 'INFO')

MARK_FILE = '/tmp/bingphoto.mark.txt'

logging.config.dictConfig({
    'version': 1,
    'disable_existing_loggers': False,
    'loggers': {
        '': {
            'handlers': ['stream'],
            'level': LOG_LEVEL,
        },
        'requests': {
            'level': 'DEBUG',
        }
    },
    'handlers': {
        'stream': {
            'class': 'logging.StreamHandler',
            'formatter': 'common',
        },
    },
    'formatters': {
        'common': {
            'format': '%(asctime)s %(levelname)s %(name)s: %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S'
        },
    },
})

lg = logging.getLogger('bingphoto')


class RequestFailed(Exception):
    pass


def send_request():
    try:
        response = requests.get(
            url="http://cn.bing.com/HPImageArchive.aspx",
            params={
                "format": "js",
                "idx": "0",
                "n": "1",
                "setmkt": "zh-cn",
                "setlang": "zh-cn",
            },
            headers={
                "User-Agent": USER_AGENT,
            },
        )
    except requests.exceptions.RequestException as e:
        raise RequestFailed(str(e))
    else:
        return response


def download_photo(url, filepath):
    resp = requests.get(url, headers={'User-Agent': USER_AGENT})
    if resp.status_code != 200:
        raise RequestFailed('could not download photo: {}, {}'.format(resp.status_code, resp.content))

    lg.info('writing to file %s', filepath)
    with open(filepath, 'wb') as f:
        for chunk in resp.iter_content(1024 * 10):
            f.write(chunk)


def main():
    today = datetime.datetime.now().strftime('%Y-%m-%d')

    # check mark
    if os.path.exists(MARK_FILE) and os.path.isfile(MARK_FILE):
        with open(MARK_FILE, 'r') as f:
            mark = f.read().strip()
        if mark == today:
            lg.info('task was done earier before, mark %s', mark)
            return

    resp = send_request()
    if resp.status_code != 200:
        raise RequestFailed('could not get images json: {}, {}'.format(resp.status_code, resp.content))
    for i in resp.json()['images']:
        lg.info('image data: %s', i)
        url = i['url']
        ext = url.split('.')[-1]
        filename = '{}-{}.{}'.format(i['startdate'], i['enddate'], ext)
        filepath = os.path.join(DOWNLOAD_DIR, filename)

        download_photo(url, filepath)

    # write mark
    with open(MARK_FILE, 'w') as f:
        f.write(today)


if __name__ == '__main__':
    main()
