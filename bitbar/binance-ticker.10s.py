#!/usr/bin/env PYTHONIOENCODING=UTF-8 /Users/reorx/.pyenv/versions/3.7.1/bin/python

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
# - [ ] ansi color for price up/down
# - [ ] ratio for last n hours

import json
from urllib.request import urlopen
from http.client import HTTPResponse, HTTPException
from dataclasses import dataclass, field


style = '|font=Hack size=11'


def render(s, extra_style=''):
    print(s + style + extra_style)


symbol_configs = {
    'BTCUSDT': {
        'acronym': 'B',
        'link': 'https://www.tradingview.com/symbols/BTCUSDT/?exchange=BINANCE',
    },
    'ETHUSDT': {
        'acronym': 'E',
        'link': 'https://www.tradingview.com/symbols/ETHUSDT/?exchange=BINANCE',
    },
}


@dataclass
class State:
    symbol: str
    acronym: str
    link: str
    price: float = field(default=0.0)
    price_str: str = field(default='⚠')
    error: str = field(default='')


symbol_states = {}


symbols = ['BTCUSDT', 'ETHUSDT']


for symbol in symbols:
    state = State(symbol=symbol, **symbol_configs[symbol])
    symbol_states[symbol] = state

    url = f'https://api.binance.com/api/v3/ticker/price?symbol={symbol}'
    try:
        resp: HTTPResponse = urlopen(url)
    except HTTPException as e:
        state.error = f'Get {symbol} error: {e.__class__}: {e}'
        continue

    if resp.status != 200:
        state.error = f'Get {symbol} error: {resp.status} {resp.read().decode()}'
        continue

    data = json.load(resp)
    state.price = float(data['price'])
    state.price_str = f'{state.price:.2f}'

summary = ' '.join([f'{symbol_states[s].acronym}:{symbol_states[s].price_str}' for s in symbols])
render(summary + style)
print('---')

for s in symbols:
    state = symbol_states[s]
    render(f'{s}', ' color=blue')
    if state.error:
        render(f'- Error: {state.error}')
    else:
        render(f'- Last Price: ${state.price_str}', ' color=#555')
    render('- View Chart', f' href={state.link}')
