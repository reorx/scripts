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

from typing import Optional
import sys
import json
import time
import subprocess
from urllib.request import urlopen
from http.client import HTTPResponse, HTTPException
from dataclasses import dataclass, field


t0 = time.time()


#################
# Configuration #
#################

class SymbolType:
    spot = 'SPOT'
    future = 'FUTURE'
    # margin = 'MARGIN'


# configure symbols to monitor
symbol_configs = [
    {
        'symbol': 'BTCUSDT',
        'type': SymbolType.spot,
        #'acronym': 'B',
        'link': 'https://www.tradingview.com/symbols/BTCUSDT/?exchange=BINANCE',
    },
    {
        'symbol': 'ETHUSDT',
        'type': SymbolType.future,
        'acronym': 'E(F)',
        'link': 'https://www.tradingview.com/symbols/ETHUSDT/?exchange=BINANCE',
    },
    {
        'symbol': 'ETHUSDT',
        'type': SymbolType.spot,
        #'acronym': 'E',
        'link': 'https://www.tradingview.com/symbols/ETHUSDT/?exchange=BINANCE',
    },
]


api_urls = {
    SymbolType.spot: 'https://api.binance.com/api/v3/ticker/price?symbol={symbol}',
    SymbolType.future: 'https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}',
}


#####################
# Utility Functions #
#####################

# ref: https://stackoverflow.com/a/11511419/596206
def get_screen_status(debug=False) -> Optional[dict]:
    system_python = '/usr/bin/python'
    code = """\
import Quartz, json
d = {'is_screen_active': False, 'data': None}
_d = Quartz.CGSessionCopyCurrentDictionary()
if _d and not _d.get('CGSSessionScreenIsLocked') and _d.get('kCGSSessionOnConsoleKey', 0):
    d['is_screen_active'] = True
    d['data'] = dict(_d.items())
print(json.dumps(d))
"""
    p = subprocess.Popen([system_python], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate(code.encode())
    if debug:
        print(f'returncode={p.returncode}\nout={out.decode()}\nerr={err.decode()}')
    if p.returncode != 0:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


style = '|font=Hack size=11'


def render(s, extra_style=''):
    print(s + style + extra_style)


@dataclass
class State:
    symbol: str
    type: str
    link: str
    acronym: str = field(default='')
    price: float = field(default=0.0)
    price_str: str = field(default='⚠')
    error: str = field(default='')

    @property
    def id(self):
        return f'{self.symbol}-{self.type}'


@dataclass
class Store:
    timestamp: int
    prices: dict
    # h24_prices, h4_prices


################
# Main Process #
################

screen = get_screen_status()
if screen and not screen['is_screen_active']:
    print('** NO SCREEN **')
    sys.exit(0)


coin_states = []


for config in symbol_configs:
    state = State(**config)
    coin_states.append(state)
    symbol = state.symbol

    url = api_urls[state.type].format(symbol=symbol)
    try:
        resp: HTTPResponse = urlopen(url)
        # read earily to trigger exceptions
        resp_content: str = resp.read().decode()
    except HTTPException as e:
        state.error = f'Get {symbol} error: {e.__class__}: {e}'
        continue

    if resp.status != 200:
        state.error = f'Get {symbol} error: {resp.status} {resp_content}'
        continue

    try:
        data = json.loads(resp_content)
    except ValueError as e:
        state.error = f'{symbol} decode json error: {e}, {resp_content}'
        continue
    state.price = float(data['price'])
    state.price_str = f'{state.price:.2f}'

summary = ' '.join([f'{s.acronym}:{s.price_str}' for s in coin_states if s.acronym])
render(summary + style)
print('---')

for s in coin_states:
    render(f'{s.symbol} ({s.type})', ' color=blue')
    if s.error:
        render(f'- Error: {s.error}')
    else:
        render(f'- Last Price: ${s.price_str}', ' color=#555')
    render('- View Chart', f' href={s.link}')

duration = int((time.time() - t0) * 1000)
print(f'Duration: {duration}ms')
