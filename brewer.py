#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.12"
# dependencies = ["textual>=8.0"]
# ///
"""
brewer - upgrade Homebrew formulae by how far behind they are

Only formulae installed on request are looked at; the ones pulled in purely as
dependencies are left out. An update's level comes from the first version
segment that differs: the 1st is major, the 2nd is minor, anything later (or
only the brew revision `_N`) is patch.

  brewer outdated     brew update, then list the major and minor updates
  brewer upgrade      brew update, upgrade whitelisted formulae, review the
                      remaining major/minor updates in a TUI (upgrade,
                      whitelist or uninstall each), carry that out, then
                      print a summary; --no-review stops after the whitelist
  brewer whitelist    show the whitelist, or add / rm formulae

Whitelisted formulae (~/.config/brewer/whitelist, one name per line) are
upgraded without asking, patch updates included.
"""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import webbrowser
from collections import Counter
from dataclasses import dataclass, field
from itertools import zip_longest
from pathlib import Path

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Static

WHITELIST_PATH = Path.home() / '.config/brewer/whitelist'
WHITELIST_HEADER = (
    '# brewer whitelist: `brewer upgrade` upgrades these formulae without asking, patch updates included.\n'
    '# One formula per line, short name or full tap name (user/tap/name).\n'
)
LEVELS = ('major', 'minor', 'patch')
LEVEL_STYLE = {'major': 'bold red', 'minor': 'yellow', 'patch': 'dim'}
ARROW = '→'
DESC_WIDTH = 60

BOLD, RED, YELLOW, STAGE = '1', '31', '33', '1;36'


# --- output ------------------------------------------------------------------


def paint(text: str, style: str, stream=None) -> str:
    stream = stream or sys.stdout
    if not stream.isatty() or 'NO_COLOR' in os.environ:
        return text
    return f'\033[{style}m{text}\033[0m'


def stage(title: str) -> None:
    print(paint(f'▶ {title}', STAGE))


def warn(message: str) -> None:
    print(paint(f'brewer: {message}', YELLOW, sys.stderr), file=sys.stderr)


# --- versions ----------------------------------------------------------------


def version_tokens(version: str) -> list[int | str]:
    # `_N` is the brew revision: the formula was rebuilt, the software did not change
    core = re.sub(r'_\d+$', '', version)
    tokens = [int(t) if t.isdigit() else t for t in re.findall(r'\d+|[A-Za-z]+', core)]
    # prefixes such as `v` and `RELEASE.` are not part of the version
    while tokens and isinstance(tokens[0], str):
        tokens.pop(0)
    return tokens


def version_level(installed: str, latest: str) -> str:
    old, new = version_tokens(installed), version_tokens(latest)
    if not old or not new:
        # cannot tell how far apart they are, so ask rather than skip
        return 'major'
    for i, (a, b) in enumerate(zip_longest(old, new)):
        if a != b:
            return LEVELS[min(i, 2)]
    return 'patch'


# --- brew --------------------------------------------------------------------


@dataclass
class Formula:
    name: str  # as `brew outdated` reports it, the full name for tap formulae
    installed: str
    latest: str
    level: str
    pinned: bool
    desc: str
    homepage: str
    required_by: list[str] = field(default_factory=list)  # installed formulae depending on it, full names


def brew_json(*args: str) -> dict:
    return json.loads(subprocess.run(['brew', *args], capture_output=True, text=True, check=True).stdout)


def brew_run(*args: str) -> int:
    """Run brew on the terminal, its output shown live."""
    sys.stdout.flush()
    # brewer runs `brew update` itself (or was told not to), upgrades must not trigger another one;
    # the review TUI already is the confirmation, so brew 7's default "proceed? [y/n]" must not ask again
    env = {**os.environ, 'HOMEBREW_NO_AUTO_UPDATE': '1', 'HOMEBREW_NO_ASK': '1'}
    return subprocess.run(['brew', *args], env=env).returncode


def on_request_formulae(info: dict) -> dict[str, dict]:
    """Formulae with any keg installed on request, by full name."""
    return {f['full_name']: f for f in info['formulae'] if any(k['installed_on_request'] for k in f['installed'])}


def dependents(info: dict) -> dict[str, list[str]]:
    """Installed formulae that depend on each formula, all by full name."""
    users: dict[str, set[str]] = {}
    for f in info['formulae']:
        for keg in f['installed']:
            # what the keg was built against, recursively: the same record brew checks before an uninstall;
            # kegs from old brew versions may have none
            for dep in keg.get('runtime_dependencies') or []:
                users.setdefault(dep['full_name'], set()).add(f['full_name'])
    return {name: sorted(names) for name, names in users.items()}


def parse_scan(info: dict, outdated: dict) -> list[Formula]:
    wanted = on_request_formulae(info)
    users = dependents(info)
    found = []
    for o in outdated['formulae']:
        f = wanted.get(o['name'])
        if f is None:
            continue
        # brew lists the installed versions oldest first
        installed, latest = o['installed_versions'][-1], o['current_version']
        level = version_level(installed, latest)
        found.append(
            Formula(
                o['name'],
                installed,
                latest,
                level,
                o['pinned'],
                f['desc'] or '',
                f['homepage'] or '',
                users.get(o['name'], []),
            )
        )
    return found


def scan() -> list[Formula]:
    """Outdated formulae installed on request."""
    return parse_scan(brew_json('info', '--json=v2', '--installed'), brew_json('outdated', '--json=v2', '--formula'))


def update_homebrew() -> None:
    stage('Updating Homebrew')
    if brew_run('update') != 0:
        warn('brew update failed, going on with the formula data already on disk')


def brew_change(command: str, name: str, dry_run: bool) -> int:
    """`brew upgrade` or `brew uninstall` one formula."""
    # --formula keeps a same-named cask (docker) out of it
    args = [command, '--formula', name]
    if dry_run:
        print(f'would run: brew {shlex.join(args)}')
        return 0
    return brew_run(*args)


# --- whitelist ---------------------------------------------------------------


def short_name(name: str) -> str:
    return name.rsplit('/', 1)[-1]


def same_formula(a: str, b: str) -> bool:
    """`stripe` and `stripe/stripe-cli/stripe` name the same formula."""
    return a == b or short_name(a) == b or a == short_name(b)


def is_entry(line: str) -> bool:
    line = line.strip()
    return bool(line) and not line.startswith('#')


def load_whitelist(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text().splitlines() if is_entry(line)]


def in_whitelist(name: str, entries: list[str]) -> bool:
    return any(same_formula(name, e) for e in entries)


def add_to_whitelist(path: Path, names: list[str]) -> list[str]:
    """Append the names not listed yet, return them."""
    entries = load_whitelist(path)
    new = []
    for name in names:
        if not in_whitelist(name, entries + new):
            new.append(name)
    if not new:
        return []
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text() if path.exists() else WHITELIST_HEADER
    if text and not text.endswith('\n'):
        text += '\n'
    path.write_text(text + ''.join(f'{n}\n' for n in new))
    return new


def remove_from_whitelist(path: Path, names: list[str]) -> list[str]:
    """Drop the lines naming any of `names`, keep every other line, return the names that matched."""
    lines = path.read_text().splitlines(keepends=True) if path.exists() else []

    def names_hit(line: str) -> list[str]:
        return [n for n in names if is_entry(line) and same_formula(n, line.strip())]

    removed = [n for n in names if any(n in names_hit(line) for line in lines)]
    if removed:
        path.write_text(''.join(line for line in lines if not names_hit(line)))
    return removed


# --- plan --------------------------------------------------------------------


@dataclass
class Plan:
    auto: list[Formula]  # whitelisted, upgraded without asking whatever the level
    review: list[Formula]  # major and minor updates to confirm, major first
    ignored: list[Formula]  # patch-only updates outside the whitelist
    pinned: list[Formula]  # never upgraded


def make_plan(formulae: list[Formula], whitelist: list[str]) -> Plan:
    plan = Plan([], [], [], [])
    for f in formulae:
        if f.pinned:
            plan.pinned.append(f)
        elif in_whitelist(f.name, whitelist):
            plan.auto.append(f)
        elif f.level == 'patch':
            plan.ignored.append(f)
        else:
            plan.review.append(f)
    plan.review.sort(key=lambda f: (LEVELS.index(f.level), f.name))
    return plan


def removal_order(formulae: list[Formula]) -> list[Formula]:
    """Dependents first: brew refuses to uninstall a formula another installed one still needs."""
    names = {f.name for f in formulae}
    # dependency lists are recursive, so whatever needs X also needs everything X needs and counts higher
    return sorted(formulae, key=lambda f: len(names.intersection(f.required_by)))


def formula_lines(formulae: list[Formula], whitelist: list[str] = ()) -> list[str]:
    """Aligned `name  installed  → latest  tags` lines."""
    w_name = max(len(f.name) for f in formulae)
    w_installed = max(len(f.installed) for f in formulae)
    w_latest = max(len(f.latest) for f in formulae)
    lines = []
    for f in formulae:
        tags = [t for t, on in (('whitelist', in_whitelist(f.name, whitelist)), ('pinned', f.pinned)) if on]
        line = f'  {f.name:<{w_name}}  {f.installed:<{w_installed}}  {ARROW} {f.latest:<{w_latest}}  {" ".join(tags)}'
        lines.append(line.rstrip())
    return lines


def versions(f: Formula) -> str:
    return f'{f.name} {f.installed} {ARROW} {f.latest}'


# --- review TUI --------------------------------------------------------------


@dataclass
class Choice:
    upgrade: list[str]
    whitelist: list[str]
    uninstall: list[str] = field(default_factory=list)


def name_list(names: list[str], limit: int = 3) -> str:
    shown = ', '.join(names[:limit])
    return shown if len(names) <= limit else f'{shown} and {len(names) - limit} more'


def formula_info(f: Formula) -> Group:
    facts = Table.grid(padding=(0, 2))
    facts.add_column(style='bold')
    facts.add_column()
    facts.add_row('Homepage', f.homepage or 'none')
    facts.add_row('Required by', ', '.join(f.required_by) or 'none')
    level = Text.assemble((f.level.capitalize(), LEVEL_STYLE[f.level]), f'  {f.installed} {ARROW} {f.latest}')
    return Group(level, Text(), Text(f.desc or 'No description.'), Text(), facts)


class ReviewTable(DataTable):
    BINDINGS = [
        Binding('j', 'cursor_down', show=False),
        Binding('k', 'cursor_up', show=False),
    ]


class InfoScreen(ModalScreen[None]):
    """One formula in full, over the review list."""

    CSS = """
    InfoScreen { align: center middle; }
    #info { width: 80%; max-width: 100; height: auto; padding: 1 2; border: round $accent; background: $surface; }
    """
    BINDINGS = [
        # the cursor stays on this formula's row, so the app opens the right homepage
        Binding('o', 'app.open_homepage', 'Homepage'),
        Binding('i,escape,q', 'dismiss', 'Close'),
    ]

    def __init__(self, formula: Formula):
        super().__init__()
        self.formula = formula

    def compose(self) -> ComposeResult:
        info = Static(formula_info(self.formula), id='info')
        info.border_title = self.formula.name
        yield info
        yield Footer()


class ReviewApp(App[Choice | None]):
    """Pick which formulae to upgrade, whitelist or uninstall; exits with a Choice, or None when cancelled."""

    TITLE = 'brewer'
    CSS = """
    #status { height: 1; padding: 0 1; background: $boost; }
    ReviewTable { height: 1fr; }
    """
    BINDINGS = [
        Binding('space', 'toggle_upgrade', 'Upgrade'),
        Binding('d', 'toggle_whitelist', 'Whitelist'),
        Binding('x', 'toggle_uninstall', 'Uninstall'),
        Binding('i', 'show_info', 'Info'),
        Binding('o', 'open_homepage', 'Homepage'),
        # DataTable binds enter itself
        Binding('enter', 'confirm', 'Confirm', priority=True),
        Binding('q,escape', 'cancel', 'Cancel'),
        Binding('ctrl+c', 'cancel', show=False, priority=True),
    ]

    def __init__(self, formulae: list[Formula]):
        super().__init__()
        self.formulae = formulae
        self.to_upgrade: set[str] = set()
        self.to_whitelist: set[str] = set()
        self.to_uninstall: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Static(id='status')
        yield ReviewTable(cursor_type='row', zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(ReviewTable)
        # fixed widths: the marks start out empty and update_cell does not widen a column
        table.add_column('Up', key='upgrade', width=2)
        table.add_column('WL', key='whitelist', width=2)
        table.add_column('Rm', key='uninstall', width=2)
        for label in ('Level', 'Formula', 'Installed', 'Latest', 'Description'):
            table.add_column(label)
        for f in self.formulae:
            desc = f.desc if len(f.desc) <= DESC_WIDTH else f.desc[: DESC_WIDTH - 1] + '…'
            level = Text(f.level.capitalize(), style=LEVEL_STYLE[f.level])
            table.add_row(*self.marks(f), level, f.name, f.installed, f.latest, desc, key=f.name)
        self.update_status()

    def marks(self, f: Formula) -> tuple[Text, Text, Text]:
        return (
            Text('✓' if f.name in self.to_upgrade else '', style='bold green'),
            Text('★' if f.name in self.to_whitelist else '', style='bold yellow'),
            Text('✗' if f.name in self.to_uninstall else '', style='bold red'),
        )

    def status_text(self) -> str:
        levels = Counter(f.level for f in self.formulae)
        return (
            f'{levels["major"]} major · {levels["minor"]} minor'
            f'    {len(self.to_upgrade)} selected · {len(self.to_whitelist)} to whitelist'
            f' · {len(self.to_uninstall)} to uninstall'
        )

    def update_status(self) -> None:
        self.query_one('#status', Static).update(self.status_text())

    def current(self) -> Formula:
        return self.formulae[self.query_one(ReviewTable).cursor_row]

    def redraw(self, f: Formula) -> None:
        table = self.query_one(ReviewTable)
        for key, mark in zip(('upgrade', 'whitelist', 'uninstall'), self.marks(f)):
            table.update_cell(f.name, key, mark)
        self.update_status()

    def action_toggle_upgrade(self) -> None:
        f = self.current()
        if f.name in self.to_upgrade:
            self.to_upgrade.discard(f.name)
            # whitelisting means "always upgrade", it cannot stay on a formula left behind
            self.to_whitelist.discard(f.name)
        else:
            self.to_upgrade.add(f.name)
            self.to_uninstall.discard(f.name)
        self.redraw(f)

    def action_toggle_whitelist(self) -> None:
        f = self.current()
        if f.name in self.to_whitelist:
            self.to_whitelist.discard(f.name)
        else:
            self.to_whitelist.add(f.name)
            self.to_upgrade.add(f.name)
            self.to_uninstall.discard(f.name)
        self.redraw(f)

    def action_toggle_uninstall(self) -> None:
        f = self.current()
        if f.name in self.to_uninstall:
            self.to_uninstall.discard(f.name)
        else:
            self.to_uninstall.add(f.name)
            self.to_upgrade.discard(f.name)
            self.to_whitelist.discard(f.name)
            # marking them too makes it work: dependents are uninstalled first
            if needed_by := [n for n in f.required_by if n not in self.to_uninstall]:
                self.notify(
                    f'{f.name} is required by {name_list(needed_by)}: '
                    'Homebrew refuses to uninstall it unless those go too',
                    severity='warning',
                )
        self.redraw(f)

    def action_show_info(self) -> None:
        self.push_screen(InfoScreen(self.current()))

    def action_open_homepage(self) -> None:
        f = self.current()
        if not f.homepage:
            self.notify(f'{f.name} has no homepage', severity='warning')
            return
        webbrowser.open(f.homepage)
        self.notify(f'Opened {f.homepage}')

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # priority bindings reach through the info panel; enter there must not confirm the whole review
        return not (action == 'confirm' and isinstance(self.screen, InfoScreen))

    def action_confirm(self) -> None:
        names = [f.name for f in self.formulae]

        def picked(marked: set[str]) -> list[str]:
            return [n for n in names if n in marked]

        self.exit(Choice(picked(self.to_upgrade), picked(self.to_whitelist), picked(self.to_uninstall)))

    def action_cancel(self) -> None:
        self.exit(None)


# --- upgrade -----------------------------------------------------------------


PHASES = ('whitelist', 'selected', 'uninstall')


@dataclass
class Attempt:
    formula: Formula
    phase: str  # one of PHASES: upgraded from the whitelist, upgraded as selected, or uninstalled
    code: int | None = None  # stays None when Ctrl-C hit before brew returned


@dataclass
class Report:
    """What one `brewer upgrade` run did, filled in stage by stage."""

    before: list[Formula]
    plan: Plan
    dry_run: bool
    attempts: list[Attempt] = field(default_factory=list)
    review: list[Formula] = field(default_factory=list)
    chosen: list[str] = field(default_factory=list)
    uninstall: list[str] = field(default_factory=list)
    whitelisted: list[str] = field(default_factory=list)
    skipped_review: bool = False
    after: list[Formula] = field(default_factory=list)


def is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def subject(f: Formula, phase: str) -> str:
    """The formula and the version an upgrade or an uninstall is about."""
    return f'{f.name} {f.installed}' if phase == 'uninstall' else versions(f)


def run_each(formulae: list[Formula], phase: str, report: Report) -> None:
    command = 'uninstall' if phase == 'uninstall' else 'upgrade'
    for i, f in enumerate(formulae, 1):
        print(paint(f'[{i}/{len(formulae)}] {subject(f, phase)}', BOLD))
        attempt = Attempt(f, phase)
        report.attempts.append(attempt)
        attempt.code = brew_change(command, f.name, report.dry_run)


def still_to_review(report: Report) -> list[Formula]:
    if not report.plan.auto or report.dry_run:
        return report.plan.review
    stage('Rescanning')
    # whitelisted upgrades may have taken some of the others along as outdated dependents
    outdated = {f.name for f in scan()}
    return [f for f in report.plan.review if f.name in outdated]


def run_stages(report: Report, whitelist_path: Path, no_review: bool) -> None:
    auto = report.plan.auto
    if auto:
        stage(f'Upgrading whitelisted formulae ({len(auto)})')
        run_each(auto, 'whitelist', report)
    else:
        print('No whitelisted formula to upgrade.')

    report.review = review = still_to_review(report)
    if not review:
        print('No major or minor update left to review.')
        return
    if no_review or not is_interactive():
        report.skipped_review = True
        stage(f'Needs review ({len(review)}), skipped: {"--no-review" if no_review else "not a terminal"}')
        print('\n'.join(formula_lines(review)))
        return

    stage(f'Review ({len(review)})')
    choice = ReviewApp(review).run()
    if choice is None:
        print('Review cancelled, nothing selected.')
        return
    carry_out(choice, report, whitelist_path)


def carry_out(choice: Choice, report: Report, whitelist_path: Path) -> None:
    report.chosen, report.uninstall = choice.upgrade, choice.uninstall
    if choice.whitelist:
        # saved right away, a long upgrade cut short by Ctrl-C keeps the marks
        report.whitelisted = choice.whitelist if report.dry_run else add_to_whitelist(whitelist_path, choice.whitelist)
        print(f'{"Would whitelist" if report.dry_run else "Whitelisted"}: {", ".join(choice.whitelist)}')
    if not choice.upgrade and not choice.uninstall:
        print('Nothing selected.')
        return
    if choice.uninstall:
        print(f'To uninstall: {", ".join(choice.uninstall)}')
    if choice.upgrade:
        print(f'Selected: {", ".join(choice.upgrade)}')

    by_name = {f.name: f for f in report.review}
    if choice.uninstall:
        # first: upgrading a formula also upgrades its outdated dependents, one of them may be on its way out
        stage(f'Uninstalling ({len(choice.uninstall)})')
        run_each(removal_order([by_name[n] for n in choice.uninstall]), 'uninstall', report)
    if choice.upgrade:
        stage(f'Upgrading selected formulae ({len(choice.upgrade)})')
        run_each([by_name[n] for n in choice.upgrade], 'selected', report)


def summary_groups(r: Report) -> list[tuple[str, list[str]]]:
    if r.dry_run:
        planned = {phase: [subject(a.formula, phase) for a in r.attempts if a.phase == phase] for phase in PHASES}
        return [
            ('Would upgrade (whitelist)', planned['whitelist']),
            ('Would upgrade (selected)', planned['selected']),
            ('Would uninstall', planned['uninstall']),
            ('Would add to whitelist', r.whitelisted),
        ]
    outdated = {f.name for f in r.after}
    done = {phase: [] for phase in PHASES}
    failed = []
    for a in r.attempts:
        name = a.formula.name
        what = 'uninstall ' if a.phase == 'uninstall' else ''
        if a.code is None:
            failed.append(f'{name} ({what}interrupted)')
        elif a.code != 0:
            failed.append(f'{name} ({what}exit {a.code})')
        elif a.phase != 'uninstall' and name in outdated:
            failed.append(f'{name} (still outdated)')
        else:
            done[a.phase].append(subject(a.formula, a.phase))
    # uninstalled formulae leave `brew outdated` too, being attempted keeps them out of this group
    attempted = {a.formula.name for a in r.attempts}
    also = [versions(f) for f in r.before if f.name not in outdated and f.name not in attempted]
    return [
        ('Upgraded (whitelist)', done['whitelist']),
        ('Upgraded (selected)', done['selected']),
        ('Also upgraded by Homebrew', also),
        ('Uninstalled', done['uninstall']),
        ('Failed', failed),
        ('Added to whitelist', r.whitelisted),
    ]


def print_summary(r: Report, groups: list[tuple[str, list[str]]]) -> None:
    for title, items in groups:
        if not items:
            continue
        print(paint(f'{title}:', RED if title == 'Failed' else BOLD))
        for item in items:
            print(f'  {item}')
    left = len(r.review) - len(r.chosen) - len(r.uninstall)
    counts = (
        (left, 'left to review' if r.skipped_review else 'not selected'),
        (len(r.plan.ignored), 'patch-only ignored'),
        (len(r.plan.pinned), 'pinned'),
    )
    tail = ' · '.join(f'{n} {label}' for n, label in counts if n)
    if tail:
        print(tail)


# --- commands ----------------------------------------------------------------


def cmd_outdated(args: argparse.Namespace) -> int:
    if not args.no_update:
        update_homebrew()
    formulae = scan()
    if not formulae:
        print('All formulae are up to date.')
        return 0
    whitelist = load_whitelist(args.whitelist)
    listed = sorted((f for f in formulae if f.level != 'patch'), key=lambda f: (LEVELS.index(f.level), f.name))
    # one table for both groups, so the columns line up across them
    lines = formula_lines(listed, whitelist) if listed else []
    for level in ('major', 'minor'):
        group = [line for f, line in zip(listed, lines) if f.level == level]
        if group:
            print(paint(f'{level.capitalize()} ({len(group)})', BOLD))
            print('\n'.join(group))
    plan = make_plan(formulae, whitelist)
    counts = ((len(plan.ignored), 'patch-only ignored'), (len(plan.auto), 'whitelisted to auto-upgrade'))
    tail = ' · '.join(f'{n} {label}' for n, label in counts if n)
    if tail:
        print(tail)
    return 0


def cmd_upgrade(args: argparse.Namespace) -> int:
    if not args.no_update:
        update_homebrew()
    before = scan()
    if not before:
        print('All formulae are up to date.')
        return 0
    report = Report(before, make_plan(before, load_whitelist(args.whitelist)), args.dry_run)
    interrupted = False
    try:
        run_stages(report, args.whitelist, args.no_review)
    except KeyboardInterrupt:
        interrupted = True
        print()
    if not args.dry_run:
        report.after = scan()
    stage('Summary')
    groups = summary_groups(report)
    print_summary(report, groups)
    if interrupted:
        return 130
    return 1 if dict(groups).get('Failed') else 0


def cmd_whitelist(args: argparse.Namespace) -> int:
    path = args.whitelist
    if args.action == 'list':
        print(path)
        entries = load_whitelist(path)
        print('\n'.join(entries) if entries else '(empty)')
        return 0
    names = list(dict.fromkeys(args.names))
    if args.action == 'add':
        installed = on_request_formulae(brew_json('info', '--json=v2', '--installed'))
        for name in names:
            if not any(same_formula(name, full) for full in installed):
                warn(f'{name} is not a formula installed on request, adding it anyway')
        added = add_to_whitelist(path, names)
        if added:
            print(f'Added: {", ".join(added)}')
        if present := [n for n in names if n not in added]:
            print(f'Already in whitelist: {", ".join(present)}')
        return 0
    removed = remove_from_whitelist(path, names)
    if removed:
        print(f'Removed: {", ".join(removed)}')
    for name in names:
        if name not in removed:
            warn(f'Not in whitelist: {name}')
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        '--whitelist', type=Path, default=WHITELIST_PATH, help=f'whitelist file (default: {WHITELIST_PATH})'
    )
    no_update = argparse.ArgumentParser(add_help=False)
    no_update.add_argument('--no-update', action='store_true', help='skip `brew update`, use the local formula data')

    parser = argparse.ArgumentParser(
        prog='brewer',
        description='Upgrade Homebrew formulae by how far behind they are, with a whitelist and a review TUI.',
        epilog=(
            'review keys: up/down (j/k) move, space upgrade, d whitelist (+ upgrade), x uninstall, '
            'i details, o homepage, enter confirm, q cancel'
        ),
    )
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('outdated', parents=[common, no_update], help='brew update, then list major and minor updates')
    p.set_defaults(func=cmd_outdated)
    p = sub.add_parser(
        'upgrade',
        parents=[common, no_update],
        help='upgrade whitelisted formulae, then review the remaining major/minor updates',
    )
    p.add_argument(
        '--dry-run', action='store_true', help='go through every step but change nothing, keep the whitelist'
    )
    p.add_argument(
        '--no-review', action='store_true', help='upgrade the whitelist only, list what needs review without the TUI'
    )
    p.set_defaults(func=cmd_upgrade)
    p = sub.add_parser('whitelist', parents=[common], help='show the whitelist, or add / rm formulae')
    p.add_argument('action', nargs='?', choices=['list', 'add', 'rm'], default='list')
    p.add_argument('names', nargs='*', metavar='formula')
    p.set_defaults(func=cmd_whitelist)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == 'whitelist' and (args.action == 'list') == bool(args.names):
        parser.error('whitelist add/rm take formula names, plain `whitelist` takes none')
    needs_brew = args.command != 'whitelist' or args.action == 'add'
    if needs_brew and not shutil.which('brew'):
        print('brewer: brew not found in PATH', file=sys.stderr)
        return 1
    try:
        return args.func(args)
    except subprocess.CalledProcessError as e:
        print(f'brewer: `{shlex.join(e.cmd)}` exited with {e.returncode}\n{e.stderr or ""}'.rstrip(), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
