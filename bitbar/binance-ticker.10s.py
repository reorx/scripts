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
# - [x] ansi color for price up/down
# - [ ] ratio for last n hours
# - [ ] margin symbol

from typing import Optional
import os
import sys
import json
import time
import subprocess
from multiprocessing import Pool
from urllib.request import urlopen
from http.client import HTTPResponse, HTTPException, IncompleteRead
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
        'acronym': 'B',
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

store_file_path = os.path.expanduser('~/.bitbar.binance-ticker.json')


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
    duration: int = field(default=0)

    @property
    def id(self):
        return f'{self.symbol}-{self.type}'


@dataclass
class Store:
    timestamp: float
    prices: dict  # {'ETHUSDT-SPOT': 223.24}
    # h24_prices, h4_prices

    @classmethod
    def new(cls) -> 'Store':
        return cls(timestamp=t0, prices={})

    @classmethod
    def load(cls) -> 'Store':
        if not os.path.exists(store_file_path):
            return cls.new()

        with open(store_file_path, 'r') as f:
            d = json.loads(f.read())
        return cls(**d)

    def save(self):
        with open(store_file_path, 'w') as f:
            f.write(json.dumps(self.__dict__))


def make_color(code):
    def color_func(s):
        tpl = '\x1b[{}m{}\x1b[0m'
        return tpl.format(code, s)
    return color_func


black = make_color(30)
red = make_color(31)
green = make_color(32)
yellow = make_color(33)
blue = make_color(34)
magenta = make_color(35)
cyan = make_color(36)
white = make_color(37)


def cal_duration(t_s):
    return int((time.time() - t_s) * 1000)


################
# Main Process #
################

screen = get_screen_status()
if screen and not screen['is_screen_active']:
    print('** NO SCREEN **')
    sys.exit(0)


store = Store.load()
new_store = Store.new()


def process_symbol(config):
    state = State(**config)
    symbol = state.symbol

    url = api_urls[state.type].format(symbol=symbol)
    t00 = time.time()
    try:
        resp: HTTPResponse = urlopen(url)
        # read earily to trigger exceptions
        try:
            resp_content: str = resp.read().decode()
        except IncompleteRead as e:
            resp_content: str = e.partial.decode()
    except HTTPException as e:
        state.error = f'Get {symbol} error:\n{e.__class__}: {e}'
        return state
    finally:
        state.duration = cal_duration(t00)

    if resp.status != 200:
        state.error = f'Get {symbol} error:\n{resp.status} {resp_content}'
        return state

    try:
        data = json.loads(resp_content)
    except ValueError as e:
        state.error = f'{symbol} decode json error:\n{e}, {resp_content}'
        return state
    state.price = float(data['price'])
    price_str = f'{state.price:.2f}'

    last_price = store.prices.get(state.id)
    if last_price is not None:
        if state.price > last_price:
            #price_str += green('↾')
            price_str += green('↑')
        else:
            #price_str += red('⇂')
            price_str += red('↓')
    state.price_str = price_str
    return state


coin_states: list
with Pool() as pool:
    coin_states = pool.map(process_symbol, symbol_configs)


summary_items = []
for s in coin_states:
    new_store.prices[s.id] = s.price

    if not s.acronym:
        continue
    summary_items.append(f'{s.acronym}:{s.price_str}')

summary = ' '.join(summary_items)
render(summary + style)
print('---')

for s in coin_states:
    render(f'{s.symbol} ({s.type})', ' color=blue')
    if s.error:
        render(f'- Error: {s.error}')
    else:
        render(black(f'- Price: ${s.price_str}') + f', Last: ${store.prices.get(s.id, "")}')
    render('- View Chart', f' href={s.link}')

duration = cal_duration(t0)
print(f'Duration: {duration}ms ({", ".join(str(s.duration) for s in coin_states)})|font=Helvtica size=11')


# save new store
new_store.save()
