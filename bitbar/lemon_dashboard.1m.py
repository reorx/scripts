#!/usr/bin/env PYTHONIOENCODING=UTF-8 python3

# Read before Use:
# 1. Please ensure that python3 is installed on your MacOS
# 2. Please create the file `~/.config/xbar/lemonsqueezy.json` and put "api_key" and "store_id" in it before using the script
# 3. The script should be put at `~/Library/Application Support/xbar/plugins`. See xbar documentation: https://github.com/matryer/xbar#the-plugin-directory
#
# <bitbar.title>Lemon Revenue Indicator</bitbar.title>
# <bitbar.version>v1.0</bitbar.version>
# <bitbar.author>Reorx</bitbar.author>
# <bitbar.author.github>reorx</bitbar.author.github>
# <bitbar.desc>Displays your store revenue from Lemon Squeezy</bitbar.desc>
# <bitbar.dependencies>python</bitbar.dependencies>

import os
import json
from pathlib import Path
import subprocess
import datetime
from typing import Optional, Tuple, Union
from urllib import request, parse
from http.client import HTTPResponse, IncompleteRead



#################
# Configuration #
#################


xbar_config_dir = Path(os.path.expanduser('~/.config/xbar'))
config_path = xbar_config_dir.joinpath('lemonsqueezy.json')

with open(config_path, 'r') as f:
    config = json.loads(f.read())

API_KEY = config['api_key']
STORE_ID = config['store_id']
DISPLAY_CURRENCY = config.get('display_currency', 'USD')


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


def run_curl_script():
    result = subprocess.run(['bash', xbar_config_dir.joinpath('lemon_dashboard.curl.sh')], capture_output=True)
    return result


default_currency = 'USD'
currency_symbol_map = {
  "USD": "$",
  "EUR": "€",
  "JPY": "¥",
  "GBP": "£",
  "AUD": "$",
  "CAD": "$",
  "CHF": "CHF",
  "CNY": "¥",
  "HKD": "$",
  "NZD": "$"
}

def format_money_of_currency(n, currency):
    return f'{currency_symbol_map.get(currency, "")}{n/100:.0f}'


################
# Main Process #
################

def main():
    r = run_curl_script()
    if r.returncode != 0:
        render(f'curl returns {r.returncode}')
        raise Exception(r.stderr)
    data = json.loads(r.stdout)

    total = data['props']['overview']['charts'][0]['total']
    currency = data['props']['overview']['charts'][0]['currency']

    text = f'🍋 {format_money_of_currency(total, currency)}'
    render(text)

main()
