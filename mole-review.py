#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.10"
# dependencies = ["textual>=8.0"]
# ///
"""
mole-review - review Mole's cleanup preview (clean-list.txt) in a TUI

Reads the list written by `mo clean --dry-run`, shows it by category sorted
by size, and lets you mark entries and delete them in one go.

A separate whitelist (~/.config/mole-review/whitelist) hides entries you have
already reviewed and decided to keep. mole never reads it; the syntax and
matching rules are the same as ~/.config/mole/whitelist, so lines can be
copied over when you want mole itself to skip them too.

With --rescan it first runs `mo clean --dry-run` on the terminal, exactly as
if typed in the shell, then opens the fresh list.
"""

import argparse
import fnmatch
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from rich.cells import cell_len
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

HOME = os.path.expanduser('~')
DEFAULT_LIST = Path(HOME, '.config/mole/clean-list.txt')
DEFAULT_WHITELIST = Path(HOME, '.config/mole-review/whitelist')
# mo always writes its preview to DEFAULT_LIST
RESCAN_CMD = ['mo', 'clean', '--dry-run']

WHITELIST_HEADER = (
    '# mole-review whitelist: entries matching these patterns are hidden from review.\n'
    '# Same syntax as ~/.config/mole/whitelist (one path or glob per line), but mole never reads this file.\n'
)

KEYS_HELP = """\
keys:
  space   mark / unmark row             a      mark / unmark all shown rows
  d       delete marked (or current)    x      whitelist current/marked, or un-whitelist
  w       show / hide whitelisted       s      cycle sort: size desc, size asc, path
  1-9     show one category             0      show all categories
  enter   (in sidebar) show category    tab    switch sidebar / table
  /       filter by path                esc    clear filter
  o       reveal in Finder              e      edit whitelist in $EDITOR
  c       copy full path                r      reload list and whitelist
  q       quit
"""

UNITS = {'B': 1, 'KB': 1000, 'MB': 1000**2, 'GB': 1000**3, 'TB': 1000**4}
SIZE_RE = re.compile(r'^([\d.]+)([KMGT]?B)$')
# PATH  # SIZE[, N items][, counted under PARENT], SIZE may be `size unknown`
ITEM_RE = re.compile(
    r'^(?P<path>/.*?)  # (?P<size>[\d.]+[KMGT]?B|size unknown)'
    r'(?:, (?P<count>\d+) items)?(?:, counted under (?P<under>/.*?))?\s*$'
)
HEADER_RE = re.compile(r'^# Mole Cleanup Preview - (.+)$')
POTENTIAL_RE = re.compile(r'^# Potential cleanup: (.+)$')
CATEGORY_RE = re.compile(r'^=== (.+) ===$')

SORT_MODES = ['size_desc', 'size_asc', 'path']
SORT_LABELS = {'size_desc': 'size ↓', 'size_asc': 'size ↑', 'path': 'path'}

SHOW_ALL_LABEL = 'Show All Categories'
CATEGORY_HINT = '1-9 select · 0 all'
# background of a category row, filled for the category's share of all bytes
BAR_STYLE = 'on #5a4a1e'


@dataclass(frozen=True)
class Item:
    path: str
    size: int
    size_text: str
    category: str
    count: int = 1
    # set when mole already counted this row's bytes in a listed ancestor
    counted_under: str | None = None


@dataclass
class CleanList:
    generated_at: str = ''
    potential: str = ''
    categories: list[str] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)


# --- sizes -------------------------------------------------------------------


def parse_size(text: str) -> int:
    m = SIZE_RE.match(text.strip())
    if not m:
        raise ValueError(f'bad size: {text!r}')
    return round(float(m.group(1)) * UNITS[m.group(2)])


def format_size(n: int) -> str:
    """Same decimal units and precision as mole's bytes_to_human."""
    if n >= 1000**3:
        return f'{n / 1000**3:.2f}GB'
    if n >= 1000**2:
        return f'{n / 1000**2:.1f}MB'
    if n >= 1000:
        return f'{round(n / 1000)}KB'
    return f'{n}B'


# --- clean-list.txt ----------------------------------------------------------


def parse_item(line: str, category: str) -> Item:
    m = ITEM_RE.match(line)
    if not m:
        return Item(line.strip(), 0, '?', category)
    known = m['size'] != 'size unknown'
    return Item(
        m['path'],
        parse_size(m['size']) if known else 0,
        m['size'] if known else '?',
        category,
        int(m['count'] or 1),
        m['under'],
    )


def parse_clean_list(text: str) -> CleanList:
    cl = CleanList()
    category = 'Uncategorized'
    for raw in text.splitlines():
        line = raw.rstrip()
        if m := CATEGORY_RE.match(line):
            category = m.group(1)
        elif line.startswith('/'):
            cl.items.append(parse_item(line, category))
        elif m := HEADER_RE.match(line):
            cl.generated_at = m.group(1)
            continue
        elif m := POTENTIAL_RE.match(line):
            cl.potential = m.group(1)
            continue
        else:
            continue
        if category not in cl.categories:
            cl.categories.append(category)
    return cl


# --- whitelist ---------------------------------------------------------------


def expand_pattern(line: str) -> str:
    return os.path.expanduser(line.replace('${HOME}', HOME).replace('$HOME', HOME))


def normalize_path(p: str) -> str:
    while '//' in p:
        p = p.replace('//', '/')
    return p.rstrip('/') or '/'


def load_whitelist(path: Path) -> list[str]:
    if not path.exists():
        return []
    patterns = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            patterns.append(expand_pattern(line))
    return patterns


def pattern_hits(path: str, pattern: str) -> bool:
    """Mirror of mole's is_path_whitelisted (lib/core/app_protection.sh)."""
    target, pat = normalize_path(path), normalize_path(pattern)
    has_glob = any(c in pat for c in '*?[')
    return (
        target == pat
        # bash [[ == ]] globbing: `*` also matches `/`, same as fnmatch
        or fnmatch.fnmatchcase(target, pat)
        # target is a parent of a protected path, deleting it would take the child too
        or pat.startswith(target + '/')
        # target lives inside a protected directory
        or (not has_glob and target.startswith(pat + '/'))
    )


def matching_patterns(path: str, patterns: list[str]) -> list[str]:
    return [p for p in patterns if pattern_hits(path, p)]


def is_whitelisted(path: str, patterns: list[str]) -> bool:
    return any(pattern_hits(path, p) for p in patterns)


def add_to_whitelist(path: Path, entries: list[str]) -> None:
    existing = set(load_whitelist(path))
    new = [e for e in dict.fromkeys(entries) if e not in existing]
    if not new:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text() if path.exists() else WHITELIST_HEADER
    if text and not text.endswith('\n'):
        text += '\n'
    path.write_text(text + ''.join(f'{e}\n' for e in new))


def remove_from_whitelist(path: Path, entries: list[str]) -> None:
    targets = set(entries)
    lines = path.read_text().splitlines(keepends=True)
    path.write_text(''.join(line for line in lines if expand_pattern(line.strip()) not in targets))


# --- views -------------------------------------------------------------------


def listed_ancestor(path: str, paths: set[str]) -> str | None:
    parent = os.path.dirname(path)
    while parent not in ('/', ''):
        if parent in paths:
            return parent
        parent = os.path.dirname(parent)
    return None


def top_level(items: list[Item]) -> list[Item]:
    """Drop items that sit inside another listed item."""
    paths = {i.path for i in items}
    return [i for i in items if listed_ancestor(i.path, paths) is None]


def total_size(items: list[Item]) -> int:
    return sum(i.size for i in top_level(items))


def filter_items(
    items: list[Item],
    categories: set[str],
    patterns: list[str],
    show_whitelisted: bool,
    query: str,
    sort_mode: str,
) -> list[Item]:
    q = os.path.expanduser(query).lower()
    shown = [
        i
        for i in items
        if i.category in categories
        and (not q or q in i.path.lower())
        and (show_whitelisted or not is_whitelisted(i.path, patterns))
    ]
    if sort_mode == 'path':
        shown.sort(key=lambda i: i.path)
    elif sort_mode == 'size_asc':
        shown.sort(key=lambda i: (i.size, i.path))
    else:
        shown.sort(key=lambda i: (-i.size, i.path))
    return shown


def display_path(path: str) -> str:
    return '~' + path[len(HOME) :] if path.startswith(HOME + '/') else path


# --- deletion ----------------------------------------------------------------


def check_deletable(path: str) -> None:
    parts = path.split('/')
    if (
        not path.startswith('/')
        or '..' in parts
        or '.' in parts
        or len([p for p in parts if p]) < 3
        or normalize_path(path) == HOME
    ):
        raise ValueError(f'refusing to delete unsafe path: {path}')


def delete_path(path: str) -> None:
    check_deletable(path)
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)


# --- clipboard ---------------------------------------------------------------


def copy_text(text: str) -> bool:
    """Put text on the macOS clipboard, False when pbcopy is not available."""
    if not shutil.which('pbcopy'):
        return False
    subprocess.run(['pbcopy'], input=text, text=True, check=True)
    return True


# --- TUI ---------------------------------------------------------------------


class ItemTable(DataTable):
    BINDINGS = [Binding('space', 'app.toggle_mark', 'Mark')]


class CategoryList(OptionList):
    """Single-select: enter or a click picks the category (OptionSelected)."""


class SearchInput(Input):
    BINDINGS = [Binding('escape', 'app.clear_search', 'Clear', show=False)]


class ConfirmDelete(ModalScreen[bool]):
    BINDINGS = [
        Binding('y', 'confirm', 'Delete'),
        Binding('n,escape', 'cancel', 'Cancel'),
    ]

    def __init__(self, items: list[Item]):
        super().__init__()
        self.items = sorted(items, key=lambda i: -i.size)

    def compose(self) -> ComposeResult:
        listing = Text()
        for n, item in enumerate(self.items):
            listing.append(('\n' if n else '') + f'{item.size_text:>9}  ', style='bold')
            listing.append(display_path(item.path))
        with Vertical(id='dialog'):
            yield Label(
                Text.assemble(
                    'Delete ',
                    (str(len(self.items)), 'bold'),
                    ' entries, ',
                    (format_size(total_size(self.items)), 'bold red'),
                    '?',
                )
            )
            with VerticalScroll(id='listing'):
                yield Static(listing)
            yield Label('Deleted permanently, not moved to Trash.', classes='warn')
            with Horizontal(id='buttons'):
                yield Button('Delete (y)', variant='error', id='yes')
                yield Button('Cancel (n)', variant='primary', id='no')

    def on_mount(self) -> None:
        self.query_one('#no').focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == 'yes')

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


# actions defined here, disabled while a modal is open so keys don't leak through it
APP_ACTIONS = {
    'toggle_mark', 'mark_all', 'delete', 'toggle_whitelist', 'toggle_show_whitelisted',
    'cycle_sort', 'select_category', 'all_categories', 'focus_search',
    'clear_search', 'reveal', 'copy_path', 'edit_whitelist', 'reload',
}  # fmt: skip
BUSY_ACTIONS = {'delete', 'toggle_whitelist', 'edit_whitelist', 'reload'}


class MoleReviewApp(App):
    TITLE = 'mole-review'
    CSS = """
    #sidebar { width: 24; border-right: solid $panel-lighten-2; }
    #sidebar .section { padding: 0 1; }
    #categories { height: auto; max-height: 70%; }
    /* bold marks the selection; a cursor left behind when unfocused would read as a size bar */
    #categories > .option-list--option-highlighted { background: transparent; }
    #categories:focus > .option-list--option-highlighted { background: $block-cursor-background; }
    #show-all { width: 1fr; margin: 1 0 0 0; }
    #summary { padding: 1 1; color: $text-muted; }
    #main { width: 1fr; }
    #category-bar { height: 1; padding: 0 1; background: $boost; }
    #table { height: 1fr; }
    #detail {
        height: auto; padding: 0 1;
        border-top: solid $primary 60%; border-bottom: solid $primary 60%;
    }
    #detail-path { height: auto; min-height: 1; max-height: 2; }
    #detail-row { height: auto; }
    #detail-kv { width: 1fr; height: auto; min-height: 1; max-height: 2; }
    #copy-path { margin-left: 2; }
    #status { height: 1; padding: 0 1; background: $boost; }
    ConfirmDelete { align: center middle; }
    #dialog { width: 100; max-width: 95%; height: auto; max-height: 85%; border: thick $error; background: $surface; padding: 1 2; }
    #listing { height: auto; max-height: 20; margin: 1 0; }
    #listing Static { text-wrap: nowrap; text-overflow: ellipsis; }
    #dialog .warn { color: $warning; }
    #buttons { height: auto; align-horizontal: right; margin-top: 1; }
    #buttons Button { margin-left: 2; }
    """
    BINDINGS = [
        Binding('d', 'delete', 'Delete'),
        Binding('a', 'mark_all', 'Mark all'),
        Binding('x', 'toggle_whitelist', 'Whitelist ±'),
        Binding('w', 'toggle_show_whitelisted', 'Show WL'),
        Binding('s', 'cycle_sort', 'Sort'),
        # priority: handled in the app's queue so the keys right after it already reach the filter
        Binding('slash', 'focus_search', 'Filter', priority=True),
        Binding('o', 'reveal', 'Finder'),
        Binding('c', 'copy_path', 'Copy path', show=False),
        Binding('e', 'edit_whitelist', 'Edit WL'),
        Binding('r', 'reload', 'Reload'),
        Binding('q', 'quit', 'Quit'),
        Binding('0', 'all_categories', 'All cats', show=False),
        *[Binding(str(n), f'select_category({n - 1})', show=False) for n in range(1, 10)],
    ]

    def __init__(self, list_path: Path, whitelist_path: Path):
        super().__init__()
        self.list_path = list_path
        self.whitelist_path = whitelist_path
        self.log_path = whitelist_path.parent / 'deleted.log'
        self.clean_list = CleanList()
        self.items: list[Item] = []
        self.gone = 0
        self.patterns: list[str] = []
        self.wl_paths: set[str] = set()
        self.marked: set[str] = set()
        self.shown: list[Item] = []
        self.show_whitelisted = False
        self.sort_mode = 'size_desc'
        self.category: str | None = None  # None shows all categories
        self.deleting = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id='sidebar'):
                yield Label(Text.assemble(('Categories', 'bold'), '\n', (CATEGORY_HINT, 'dim')), classes='section')
                yield CategoryList(id='categories', compact=True)
                yield Button(SHOW_ALL_LABEL, id='show-all', compact=True)
                yield Static(id='summary')
            with Vertical(id='main'):
                yield Static(id='category-bar')
                yield SearchInput(placeholder='/ filter by path', id='search', compact=True)
                yield ItemTable(id='table', cursor_type='row', zebra_stripes=True)
                with Vertical(id='detail'):
                    yield Static(id='detail-path')
                    with Horizontal(id='detail-row'):
                        yield Static(id='detail-kv')
                        yield Button('Copy Path', id='copy-path', compact=True)
                yield Static(id='status')
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(ItemTable)
        table.add_column(' ', key='mark', width=1)
        table.add_column(Text('Size', justify='right'), key='size', width=9)
        table.add_column('Path', key='path')
        # clicking it must not pull focus away from the file list
        self.query_one('#copy-path', Button).can_focus = False
        self.load_data()
        table.focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in APP_ACTIONS and isinstance(self.screen, ModalScreen):
            return False
        if action in BUSY_ACTIONS and self.deleting:
            return False
        return True

    # --- state -------------------------------------------------------------

    def load_data(self) -> None:
        self.clean_list = parse_clean_list(self.list_path.read_text())
        self.items = [i for i in self.clean_list.items if os.path.lexists(i.path)]
        self.gone = len(self.clean_list.items) - len(self.items)
        self.sub_title = f'{display_path(str(self.list_path))} · {self.clean_list.generated_at}'
        self.load_patterns()

    def load_patterns(self) -> None:
        self.patterns = load_whitelist(self.whitelist_path)
        self.wl_paths = {i.path for i in self.items if is_whitelisted(i.path, self.patterns)}
        paths = {i.path for i in self.items}
        self.marked = {p for p in self.marked if p in paths and p not in self.wl_paths}
        self.rebuild_categories()
        self.refresh_table()

    def selected_categories(self) -> set[str]:
        if self.category is None:
            return set(self.clean_list.categories)
        return {self.category}

    def current_item(self) -> Item | None:
        if not self.shown:
            return None
        return self.shown[self.query_one(ItemTable).cursor_row]

    # --- rendering ---------------------------------------------------------

    def category_prompt(self, n: int, category: str, width: int, share: float) -> Text:
        text = Text(f' {n} {category}', style='bold' if self.category in (None, category) else 'dim')
        text.pad_right(width - text.cell_len)
        bar = max(1, round(width * share)) if share > 0 else 0
        text.stylize(BAR_STYLE, 0, bar)
        return text

    def fit_sidebar(self, summary: Text) -> int:
        """Size the sidebar to its longest text, return the width of a category row."""
        rows = [f' {n} {c} ' for n, c in enumerate(self.clean_list.categories, 1)]
        width = max(
            [cell_len(row) for row in rows]
            + [cell_len(CATEGORY_HINT) + 2, cell_len(SHOW_ALL_LABEL) + 2]
            + [cell_len(line) + 2 for line in summary.plain.splitlines()]
        )
        self.query_one('#sidebar').styles.width = width + 1  # border-right
        return width

    def rebuild_categories(self) -> None:
        cl = self.query_one(CategoryList)
        cats = self.clean_list.categories
        if self.category not in cats:
            self.category = None
        groups = {c: filter_items(self.items, {c}, self.patterns, self.show_whitelisted, '', 'path') for c in cats}
        sizes = {c: total_size(items) for c, items in groups.items()}
        grand = sum(sizes.values())
        summary = self.summary_text()
        width = self.fit_sidebar(summary)
        prompts = [self.category_prompt(n, c, width, sizes[c] / grand if grand else 0) for n, c in enumerate(cats, 1)]
        if [cl.get_option_at_index(i).id for i in range(cl.option_count)] != cats:
            cl.clear_options()
            cl.add_options([Option(prompt, id=c) for prompt, c in zip(prompts, cats)])
            cl.highlighted = 0 if cats else None
        else:
            for idx, prompt in enumerate(prompts):
                cl.replace_option_prompt_at_index(idx, prompt)
        self.query_one('#show-all', Button).variant = 'primary' if self.category is None else 'default'
        self.query_one('#summary', Static).update(summary)
        self.update_category_bar(groups, sizes)

    def update_category_bar(self, groups: dict[str, list[Item]], sizes: dict[str, int]) -> None:
        if self.category is None:
            name = 'All Categories'
            items = [i for group in groups.values() for i in group]
            size = total_size(items)  # nested paths across categories counted once
        else:
            name, items, size = self.category, groups[self.category], sizes[self.category]
        text = Text.assemble(
            (name, 'bold'),
            f'  {len(items)} item{"" if len(items) == 1 else "s"} · ',
            (format_size(size), 'bold yellow'),
        )
        grand = sum(sizes.values())
        if self.category is not None and grand:
            share = size / grand
            text.append(f'  {share:.0%} of all' if share >= 0.01 or not size else '  <1% of all', style='dim')
        self.query_one('#category-bar', Static).update(text)

    def show_category(self, category: str | None) -> None:
        """Show one category (None for all), then hand the arrow keys to the file list."""
        self.category = category
        self.rebuild_categories()
        if category is not None:
            self.query_one(CategoryList).highlighted = self.clean_list.categories.index(category)
        self.refresh_table()
        table = self.query_one(ItemTable)
        table.move_cursor(row=0)
        self.focus_now(table)

    def render_row(self, item: Item) -> list[Text]:
        if item.path in self.wl_paths:
            return [
                Text('◦', style='dim'),
                Text(item.size_text, style='dim', justify='right'),
                Text(display_path(item.path), style='dim'),
            ]
        marked = item.path in self.marked
        if item.size >= 1000**3:
            size_style = 'bold red'
        elif item.size >= 100 * 1000**2:
            size_style = 'yellow'
        else:
            size_style = ''
        return [
            Text('●' if marked else ' ', style='bold red'),
            Text(item.size_text, style=size_style, justify='right'),
            Text(display_path(item.path), style='bold' if marked else ''),
        ]

    def refresh_table(self) -> None:
        table = self.query_one(ItemTable)
        current = self.current_item()
        self.shown = filter_items(
            self.items,
            self.selected_categories(),
            self.patterns,
            self.show_whitelisted,
            self.query_one(SearchInput).value,
            self.sort_mode,
        )
        table.clear()
        for item in self.shown:
            table.add_row(*self.render_row(item), key=item.path)
        if current:
            index = {i.path: n for n, i in enumerate(self.shown)}
            if current.path in index:
                table.move_cursor(row=index[current.path])
        self.update_status()
        self.update_detail()

    def update_row(self, item: Item) -> None:
        table = self.query_one(ItemTable)
        for key, value in zip(('mark', 'size', 'path'), self.render_row(item)):
            table.update_cell(item.path, key, value)

    def summary_text(self) -> Text:
        wl_items = [i for i in self.items if i.path in self.wl_paths]
        rows = [
            ('mole says', self.clean_list.potential.replace('At least ', '≥')),
            ('dedup', format_size(total_size(self.items))),  # nested paths counted once
            ('entries', str(len(self.items))),
            ('gone', str(self.gone)),  # listed but no longer on disk
            ('whitelist', f'{len(wl_items)} · {format_size(total_size(wl_items))}'),
            ('patterns', str(len(self.patterns))),
        ]
        text = Text()
        for n, (label, value) in enumerate(rows):
            text.append(('\n' if n else '') + f'{label:<10}', style='bold')
            text.append(value)
        return text

    def update_status(self, message: str = '') -> None:
        if message:
            self.query_one('#status', Static).update(Text(message, style='bold yellow'))
            return
        marked = [i for i in self.items if i.path in self.marked]
        text = Text()
        text.append(f'{len(self.shown)} shown · {format_size(total_size(self.shown))}')
        text.append('  │  ', style='dim')
        text.append(f'marked {len(marked)} · {format_size(total_size(marked))}', style='bold red' if marked else '')
        text.append('  │  ', style='dim')
        text.append(f'sort {SORT_LABELS[self.sort_mode]}')
        text.append('  │  ', style='dim')
        text.append(f'whitelisted {"shown (dim)" if self.show_whitelisted else "hidden"}')
        self.query_one('#status', Static).update(text)

    def update_detail(self) -> None:
        item = self.current_item()
        path, kv = Text(), Text()
        if item:
            path.append(display_path(item.path), style='bold')
            fields = [('Category', item.category, 'cyan'), ('Size', item.size_text, 'yellow')]
            if item.count > 1:
                fields.append(('Items', str(item.count), ''))
            hits = matching_patterns(item.path, self.patterns) if item.path in self.wl_paths else []
            if hits:
                fields.append(('Whitelisted by', ', '.join(display_path(h) for h in hits), 'yellow'))
            parent = item.counted_under or listed_ancestor(item.path, {i.path for i in self.items})
            if parent:
                fields.append(('Counted under', display_path(parent), 'cyan'))
            for n, (label, value, style) in enumerate(fields):
                kv.append(('   ' if n else '') + f'{label}: ', style='dim')
                kv.append(value, style=style)
        self.query_one('#detail-path', Static).update(path)
        self.query_one('#detail-kv', Static).update(kv)
        self.query_one('#copy-path', Button).disabled = item is None

    # --- events ------------------------------------------------------------

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if isinstance(event.option_list, CategoryList):
            self.show_category(event.option_id)

    @on(Button.Pressed, '#show-all')
    def on_show_all_pressed(self) -> None:
        self.show_category(None)

    @on(Button.Pressed, '#copy-path')
    def on_copy_path_pressed(self) -> None:
        self.action_copy_path()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.refresh_table()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.focus_now(self.query_one(ItemTable))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.update_detail()

    # --- actions -----------------------------------------------------------

    def action_toggle_mark(self) -> None:
        item = self.current_item()
        if item is None:
            return
        if item.path in self.wl_paths:
            self.notify('Whitelisted entries cannot be marked, press x to un-whitelist first', severity='warning')
            return
        self.marked ^= {item.path}
        self.update_row(item)
        self.update_status()
        self.query_one(ItemTable).action_cursor_down()

    def action_mark_all(self) -> None:
        markable = {i.path for i in self.shown if i.path not in self.wl_paths}
        if markable and markable <= self.marked:
            self.marked -= markable
        else:
            self.marked |= markable
        self.refresh_table()

    def action_cycle_sort(self) -> None:
        self.sort_mode = SORT_MODES[(SORT_MODES.index(self.sort_mode) + 1) % len(SORT_MODES)]
        self.refresh_table()

    def action_select_category(self, index: int) -> None:
        cats = self.clean_list.categories
        if index < len(cats):
            self.show_category(cats[index])

    def action_all_categories(self) -> None:
        self.show_category(None)

    def focus_now(self, widget: Widget) -> None:
        # Widget.focus() is deferred, keys the terminal delivers in the same read
        # (e.g. "/dx" typed fast) would still reach the old focus and fire shortcuts
        self.screen.set_focus(widget)

    def action_focus_search(self) -> None:
        search = self.query_one(SearchInput)
        if self.focused is search:
            search.insert_text_at_cursor('/')
        else:
            self.focus_now(search)

    def action_clear_search(self) -> None:
        self.query_one(SearchInput).value = ''
        self.focus_now(self.query_one(ItemTable))

    def action_toggle_show_whitelisted(self) -> None:
        self.show_whitelisted = not self.show_whitelisted
        self.rebuild_categories()
        self.refresh_table()

    def action_toggle_whitelist(self) -> None:
        item = self.current_item()
        if self.marked:
            add_to_whitelist(self.whitelist_path, sorted(self.marked))
            self.notify(f'Whitelisted {len(self.marked)} marked entries')
        elif item is None:
            return
        elif item.path in self.wl_paths:
            self.unwhitelist(item)
        else:
            add_to_whitelist(self.whitelist_path, [item.path])
            self.notify(f'Whitelisted {display_path(item.path)}')
        self.load_patterns()

    def unwhitelist(self, item: Item) -> None:
        hits = matching_patterns(item.path, self.patterns)
        exact = [h for h in hits if normalize_path(h) == normalize_path(item.path)]
        if exact:
            remove_from_whitelist(self.whitelist_path, exact)
        rest = [h for h in hits if h not in exact]
        if rest:
            self.notify(
                f'Still whitelisted by: {", ".join(display_path(h) for h in rest)} (press e to edit)',
                severity='warning',
            )
        else:
            self.notify(f'Removed {display_path(item.path)} from whitelist')

    def action_reveal(self) -> None:
        item = self.current_item()
        if item:
            subprocess.run(['open', '-R', item.path], check=False)

    def action_copy_path(self) -> None:
        item = self.current_item()
        if item is None:
            return
        try:
            copied = copy_text(item.path)
        except (OSError, subprocess.CalledProcessError) as e:
            self.notify(f'Copy failed: {e}', severity='error')
            return
        if not copied:
            self.copy_to_clipboard(item.path)  # OSC 52, needs terminal support
        self.notify(f'Copied {item.path}')

    def action_edit_whitelist(self) -> None:
        if not self.whitelist_path.exists():
            self.whitelist_path.parent.mkdir(parents=True, exist_ok=True)
            self.whitelist_path.write_text(WHITELIST_HEADER)
        editor = os.environ.get('VISUAL') or os.environ.get('EDITOR') or 'vi'
        with self.suspend():
            subprocess.run([*shlex.split(editor), str(self.whitelist_path)], check=False)
        self.load_patterns()

    def action_reload(self) -> None:
        self.load_data()
        self.notify('Reloaded')

    def action_delete(self) -> None:
        targets = [i for i in self.items if i.path in self.marked]
        if not targets:
            item = self.current_item()
            if item is None or item.path in self.wl_paths:
                return
            targets = [item]
        self.push_screen(ConfirmDelete(targets), lambda ok: self.start_delete(targets) if ok else None)

    def start_delete(self, targets: list[Item]) -> None:
        self.deleting = True
        self.run_delete(top_level(targets))

    @work(thread=True, exclusive=True, group='delete')
    def run_delete(self, targets: list[Item]) -> None:
        removed: list[Item] = []
        failed: list[tuple[Item, str]] = []
        for n, item in enumerate(targets, 1):
            self.call_from_thread(self.update_status, f'Deleting {n}/{len(targets)}: {display_path(item.path)}')
            try:
                delete_path(item.path)
            except FileNotFoundError:
                pass
            except (OSError, ValueError) as e:
                failed.append((item, str(e)))
                continue
            removed.append(item)
        self.call_from_thread(self.finish_delete, removed, failed)

    def finish_delete(self, removed: list[Item], failed: list[tuple[Item, str]]) -> None:
        self.deleting = False
        self.write_delete_log(removed, failed)
        roots = {i.path for i in removed}

        def is_gone(path: str) -> bool:
            return path in roots or listed_ancestor(path, roots) is not None

        self.items = [i for i in self.items if not is_gone(i.path)]
        self.marked = {p for p in self.marked if not is_gone(p)}
        self.rebuild_categories()
        self.refresh_table()
        self.notify(f'Deleted {len(removed)} entries, freed about {format_size(total_size(removed))}')
        if failed:
            lines = '\n'.join(f'{display_path(i.path)}: {err}' for i, err in failed[:5])
            self.notify(f'{len(failed)} failed (still marked):\n{lines}', severity='error', timeout=15)

    def write_delete_log(self, removed: list[Item], failed: list[tuple[Item, str]]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().isoformat(timespec='seconds')
        with self.log_path.open('a') as f:
            for i in removed:
                f.write(f'{stamp}\tdeleted\t{i.size_text}\t{i.path}\n')
            for i, err in failed:
                f.write(f'{stamp}\tfailed\t{i.size_text}\t{i.path}\t{err}\n')


def rescan() -> int:
    """Run mole's dry run in the foreground on the inherited terminal, return its exit code."""
    proc = subprocess.Popen(RESCAN_CMD)
    # like a shell waiting on a foreground job, Ctrl+C is mo's to handle so its traps can
    # clean up. Ignored only after the spawn, a child started with SIGINT ignored can't trap it.
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        return proc.wait()
    finally:
        signal.signal(signal.SIGINT, previous)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog='mole-review',
        description="Review mole's cleanup preview in a TUI: sort by size, filter by category, batch delete.",
        epilog=KEYS_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'list', nargs='?', type=Path, default=DEFAULT_LIST, help=f'clean list file (default: {DEFAULT_LIST})'
    )
    parser.add_argument(
        '--whitelist', type=Path, default=DEFAULT_WHITELIST, help=f'review whitelist (default: {DEFAULT_WHITELIST})'
    )
    parser.add_argument(
        '--rescan', action='store_true', help=f'run `{shlex.join(RESCAN_CMD)}` first to regenerate the list'
    )
    args = parser.parse_args()
    if args.rescan:
        if args.list != DEFAULT_LIST:
            parser.error(f'--rescan regenerates {DEFAULT_LIST}, it cannot be combined with another list path')
        try:
            code = rescan()
        except FileNotFoundError:
            sys.exit(f'{RESCAN_CMD[0]} not found in PATH, install mole first: brew install mole')
        if code != 0:
            print(f'{RESCAN_CMD[0]} exited with {code}, not opening the review', file=sys.stderr)
            # killed by a signal shows as -N, report it the way a shell does
            sys.exit(code if code > 0 else 128 - code)
    if not args.list.exists():
        sys.exit(f'{args.list} not found, generate it with: mo clean --dry-run')
    MoleReviewApp(args.list, args.whitelist).run()


if __name__ == '__main__':
    main()
