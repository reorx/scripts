#!/usr/bin/env PYTHONIOENCODING=UTF-8 /Users/reorx/.pyenv/versions/3.10.6/bin/python

# Read before Use:
# 1. Please change the absolute path of Python 3 executable in the first line
# 2. Python version should be of 3.7+

# <bitbar.title>Binance Price Ticker</bitbar.title>
# <bitbar.version>v1.0</bitbar.version>
# <bitbar.author>Reorx</bitbar.author>
# <bitbar.author.github>reorx</bitbar.author.github>
# <bitbar.desc>Displays Binance's ticker price for configured coin pairs</bitbar.desc>
# <bitbar.image>https://i.imgur.com/zJsoTl8.jpg</bitbar.image>
# <bitbar.dependencies>python</bitbar.dependencies>

# TODO
# - [x] ansi color for price up/down
# - [ ] ratio for last n hours
# - [ ] margin symbol

import os
import json
from pathlib import Path
import time
import datetime
from typing import Optional, Tuple, Union
from urllib import request, parse
from http.client import HTTPResponse, IncompleteRead


t0 = time.time()


#################
# Configuration #
#################


xbar_config_dir = Path(os.path.expanduser('~/.config/xbar'))
config_path = xbar_config_dir.joinpath('lemonsqueezy.json')

with open(config_path, 'r') as f:
    config = json.loads(f.read())

API_KEY = config['api_key']
STORE_ID = config['store_id']


#####################
# Utility Functions #
#####################


style = '|font=Hack size=11'


def render(s, extra_style=''):
    print(s + style + extra_style)


def http_request(method, url, params=None, headers=None, data: Optional[Union[dict, list, bytes]] = None, timeout=None, logger=None) -> Tuple[HTTPResponse, bytes]:
    if params:
        url = f'{url}?{parse.urlencode(params)}'
    if not headers:
        headers = {}
    if data and isinstance(data, (dict, list)):
        data = json.dumps(data, ensure_ascii=False).encode()
        if 'Content-Type' not in headers:
            headers['Content-Type'] = 'application/json; charset=utf-8'
    if logger:
        logger.info(f'request: {method} {url}')
    req = request.Request(url, method=method, headers=headers, data=data)
    res = request.urlopen(req, timeout=timeout)  # raises: (HTTPException, urllib.error.URLError)
    try:
        body_b: bytes = res.read()
    except IncompleteRead as e:
        body_b: bytes = e.partial
    if logger:
        logger.debug(f'response: {res.status}, {body_b}')
    return res, body_b


def get_usd_cny_rate():
    rate_path = xbar_config_dir.joinpath('usd_cny.json')
    if rate_path.exists():
        with open(rate_path, 'r') as f:
            rate_data = json.load(f)
            today = datetime.datetime.now().strftime('%Y-%m-%d')
            if rate_data['date'] == today:
                return rate_data['cny']
    url = 'https://cdn.jsdelivr.net/gh/fawazahmed0/currency-api@1/latest/currencies/usd/cny.json'
    _, body_b = http_request('GET', url)
    data = json.loads(body_b)
    with open(rate_path, 'w') as f:
        json.dump(data, f)
    return data['cny']



################
# Main Process #
################

def main():
    # https://docs.lemonsqueezy.com/api/stores#retrieve-a-store
    url = f'https://api.lemonsqueezy.com/v1/stores/{STORE_ID}'
    headers = {
        'Accept': 'application/vnd.api+json',
        'Content-Type': 'application/vnd.api+json',
        'Authorization': f'Bearer {API_KEY}'
    }
    _, body_b = http_request('GET', url, headers=headers)
    data = json.loads(body_b)
    attrs = data['data']['attributes']
    def format_money(n):
        v = n * get_usd_cny_rate() / 100
        return f'{v:.0f}'
    text = f'{attrs["name"]}: {format_money(attrs["total_revenue"])} {attrs["currency"]}'
    render(text)
    print('---')
    submenu_keys = ['total_sales', 'thirty_day_sales', 'thirty_day_revenue', 'updated_at']
    for key in submenu_keys:
        value = attrs[key]
        if key.endswith('revenue'):
            value = format_money(value)
        render(f'{key}: {value}')

main()
