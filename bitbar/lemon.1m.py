#!/usr/bin/env PYTHONIOENCODING=UTF-8 python3

# Read before Use:
# 1. Please change the absolute path of Python 3 executable in the first line
# 2. Python version should be of 3.7+

# <bitbar.title>Lemon Revenue Indicator</bitbar.title>
# <bitbar.version>v1.0</bitbar.version>
# <bitbar.author>Reorx</bitbar.author>
# <bitbar.author.github>reorx</bitbar.author.github>
# <bitbar.desc>Displays your store revenue from Lemon Squeezy</bitbar.desc>
# <bitbar.dependencies>python</bitbar.dependencies>

import os
import json
from pathlib import Path
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


def get_usd_currency_rate(currency: str):
    currency_lower = currency.lower()
    rate_path = xbar_config_dir.joinpath(f'{default_currency}_{currency}.json')
    if rate_path.exists():
        with open(rate_path, 'r') as f:
            rate_data = json.load(f)
            today = datetime.datetime.now().strftime('%Y-%m-%d')
            if rate_data['date'] == today:
                return rate_data[currency_lower]
    url = f'https://cdn.jsdelivr.net/gh/fawazahmed0/currency-api@1/latest/currencies/{default_currency.lower()}/{currency_lower}.json'
    _, body_b = http_request('GET', url)
    data = json.loads(body_b)
    with open(rate_path, 'w') as f:
        json.dump(data, f)
    return data[currency_lower]


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

def format_money(n, currency):
    v = n
    if currency != default_currency:
        v = n * get_usd_currency_rate(currency)
    return f'{currency_symbol_map.get(currency, "")}{v/100:.0f}'


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
    text = f'{attrs["name"]}: {format_money(attrs["total_revenue"], DISPLAY_CURRENCY)}'
    render(text)
    print('---')
    submenu_keys = ['total_sales', 'thirty_day_revenue', 'thirty_day_sales']
    for key in submenu_keys:
        value = attrs[key]
        if key.endswith('revenue'):
            value = format_money(value, DISPLAY_CURRENCY)
        render(f'{key}: {value}')

main()
