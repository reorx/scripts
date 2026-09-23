#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.10"
# dependencies = ["textual>=8.0"]
# ///
"""
Behavior tests for mole-review.py

Run: uv run test_mole_review.py
"""

import asyncio
import importlib.util
import os
import re
import tempfile
import unittest
from pathlib import Path

from textual import events

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('mole_review', HERE / 'mole-review.py')
mr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mr)


SAMPLE = """\
# Mole Cleanup Preview - 2026-09-23 11:29:28
#
# How to protect files:
# 1. Copy any path below to ~/.config/mole/whitelist
#

=== User essentials ===
{root}/Caches/Google  # 2.11GB
{root}/Caches/pip  # 9.4MB
{root}/Logs/Fork.log  # 1.0MB

=== Browsers ===
{root}/Caches/Google/Chrome/Default  # 2.11GB, counted under {root}/Caches/Google
{root}/Support/Chrome/Service Worker/CacheStorage  # 250.7MB

=== Developer tools ===
{root}/npm/_cacache/content-v2  # 11.82GB
{root}/npm/weird # name  # 381KB
{root}/npm/empty  # 0B

# ============================================
# Summary
# ============================================
# Potential cleanup: At least 14.29GB
# Items: 8
# Categories: 3
"""


class TestParseSize(unittest.TestCase):
    def test_units_are_decimal_like_mole(self):
        self.assertEqual(mr.parse_size('0B'), 0)
        self.assertEqual(mr.parse_size('381KB'), 381_000)
        self.assertEqual(mr.parse_size('289.2MB'), 289_200_000)
        self.assertEqual(mr.parse_size('20.99GB'), 20_990_000_000)

    def test_format_size_round_trips_mole_style(self):
        self.assertEqual(mr.format_size(20_990_000_000), '20.99GB')
        self.assertEqual(mr.format_size(289_200_000), '289.2MB')
        self.assertEqual(mr.format_size(381_000), '381KB')
        self.assertEqual(mr.format_size(12), '12B')


class TestParseCleanList(unittest.TestCase):
    def setUp(self):
        self.cl = mr.parse_clean_list(SAMPLE.format(root='/r'))

    def test_header_and_summary(self):
        self.assertEqual(self.cl.generated_at, '2026-09-23 11:29:28')
        self.assertEqual(self.cl.potential, 'At least 14.29GB')

    def test_categories_in_file_order(self):
        self.assertEqual(self.cl.categories, ['User essentials', 'Browsers', 'Developer tools'])

    def test_items_carry_category_and_size(self):
        self.assertEqual(len(self.cl.items), 8)
        first = self.cl.items[0]
        self.assertEqual(first.path, '/r/Caches/Google')
        self.assertEqual(first.category, 'User essentials')
        self.assertEqual(first.size, 2_110_000_000)
        self.assertEqual(first.size_text, '2.11GB')

    def test_path_with_spaces_and_hash_uses_last_separator(self):
        paths = [i.path for i in self.cl.items]
        self.assertIn('/r/Support/Chrome/Service Worker/CacheStorage', paths)
        self.assertIn('/r/npm/weird # name', paths)

    def test_new_mole_annotations(self):
        text = '\n'.join([
            '=== Developer tools ===',
            '/r/a  # 1.0MB, 12 items',
            '/r/a/b  # 51.2MB, counted under /r/a',
            '/r/c  # size unknown',
            '/r/d  # size unknown, 3 items, counted under /r/a',
        ])
        a, b, c, d = mr.parse_clean_list(text).items
        self.assertEqual((a.path, a.size, a.count, a.counted_under), ('/r/a', 1_000_000, 12, None))
        self.assertEqual((b.path, b.size, b.count, b.counted_under), ('/r/a/b', 51_200_000, 1, '/r/a'))
        self.assertEqual((c.path, c.size, c.size_text), ('/r/c', 0, '?'))
        self.assertEqual((d.path, d.count, d.counted_under), ('/r/d', 3, '/r/a'))

    def test_repeated_category_header_is_one_category(self):
        text = '=== A ===\n/r/1  # 1B\n=== B ===\n/r/2  # 1B\n=== A ===\n/r/3  # 1B\n'
        cl = mr.parse_clean_list(text)
        self.assertEqual(cl.categories, ['A', 'B'])
        self.assertEqual([i.category for i in cl.items], ['A', 'B', 'A'])

    def test_real_mole_file_parses_if_present(self):
        real = Path('~/.config/mole/clean-list.txt').expanduser()
        if not real.exists():
            self.skipTest('no real clean-list.txt')
        text = real.read_text()
        m = re.search(r'^# Items: (\d+)$', text, re.M)
        if not m:
            self.skipTest('clean-list.txt is incomplete (mole may be rewriting it)')
        cl = mr.parse_clean_list(text)
        # mole's Items total counts top-level rows only, each weighted by its "N items"
        self.assertEqual(sum(i.count for i in cl.items if not i.counted_under), int(m.group(1)))
        self.assertGreater(len(cl.categories), 0)
        paths = {i.path for i in cl.items}
        self.assertTrue(all(i.counted_under in paths for i in cl.items if i.counted_under))


class TestWhitelist(unittest.TestCase):
    def test_load_skips_comments_blanks_and_expands_home(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'whitelist'
            f.write_text('# comment\n\n  ~/Library/Caches/pip  \n/abs/path\n')
            patterns = mr.load_whitelist(f)
        self.assertEqual(patterns, [os.path.expanduser('~/Library/Caches/pip'), '/abs/path'])

    def test_load_missing_file_is_empty(self):
        self.assertEqual(mr.load_whitelist(Path('/nonexistent/whitelist')), [])

    def test_exact_match(self):
        self.assertTrue(mr.is_whitelisted('/a/b', ['/a/b']))
        self.assertTrue(mr.is_whitelisted('/a/b/', ['/a/b/']))
        self.assertFalse(mr.is_whitelisted('/a/bc', ['/a/b']))

    def test_glob_star_crosses_slashes_like_bash(self):
        self.assertTrue(mr.is_whitelisted('/Users/x/Library/Caches/foo', ['/Users/*/Library/Caches/foo']))
        self.assertTrue(mr.is_whitelisted('/a/b/c/d', ['/a/*/d']))

    def test_child_of_plain_directory_pattern(self):
        self.assertTrue(mr.is_whitelisted('/a/b/c', ['/a/b']))

    def test_child_of_glob_pattern_is_not_whitelisted(self):
        self.assertFalse(mr.is_whitelisted('/a/bx/c', ['/a/b?']))

    def test_parent_of_whitelisted_path_is_protected(self):
        # deleting the parent would take the protected child with it
        self.assertTrue(mr.is_whitelisted('/a', ['/a/b/c']))

    def test_matching_patterns_reports_which_lines_hit(self):
        self.assertEqual(mr.matching_patterns('/a/b/c', ['/x', '/a/b', '/a/*/c']), ['/a/b', '/a/*/c'])

    def test_add_creates_file_and_skips_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'sub' / 'whitelist'
            mr.add_to_whitelist(f, ['/a/b', '/c'])
            mr.add_to_whitelist(f, ['/a/b'])
            self.assertEqual(mr.load_whitelist(f), ['/a/b', '/c'])

    def test_remove_only_drops_exact_lines(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'whitelist'
            f.write_text('# keep me\n/a/b\n/a/*\n')
            mr.remove_from_whitelist(f, ['/a/b'])
            self.assertEqual(f.read_text(), '# keep me\n/a/*\n')


class TestTotals(unittest.TestCase):
    def test_nested_items_are_counted_once(self):
        cl = mr.parse_clean_list(SAMPLE.format(root='/r'))
        google = [i for i in cl.items if 'Google' in i.path]
        self.assertEqual(len(google), 2)
        self.assertEqual(mr.total_size(google), 2_110_000_000)

    def test_sibling_prefix_is_not_nesting(self):
        items = [mr.Item('/a/b', 1, '1B', 'c'), mr.Item('/a/bc', 2, '2B', 'c')]
        self.assertEqual(mr.total_size(items), 3)


class TestView(unittest.TestCase):
    def setUp(self):
        self.cl = mr.parse_clean_list(SAMPLE.format(root='/r'))
        self.all_cats = set(self.cl.categories)

    def view(self, **kw):
        args = dict(categories=self.all_cats, patterns=[], show_whitelisted=False, query='', sort_mode='size_desc')
        args.update(kw)
        return mr.filter_items(self.cl.items, **args)

    def test_default_sort_is_size_descending(self):
        sizes = [i.size for i in self.view()]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertEqual(self.view()[0].path, '/r/npm/_cacache/content-v2')

    def test_size_ascending_and_path_sort(self):
        self.assertEqual(self.view(sort_mode='size_asc')[0].path, '/r/npm/empty')
        paths = [i.path for i in self.view(sort_mode='path')]
        self.assertEqual(paths, sorted(paths))

    def test_filter_by_one_or_many_categories(self):
        self.assertEqual({i.category for i in self.view(categories={'Browsers'})}, {'Browsers'})
        got = {i.category for i in self.view(categories={'Browsers', 'Developer tools'})}
        self.assertEqual(got, {'Browsers', 'Developer tools'})

    def test_whitelisted_hidden_by_default_and_shown_on_request(self):
        patterns = ['/r/npm']
        self.assertFalse(any('/npm/' in i.path for i in self.view(patterns=patterns)))
        shown = self.view(patterns=patterns, show_whitelisted=True)
        self.assertEqual(sum('/npm/' in i.path for i in shown), 3)

    def test_query_is_case_insensitive_substring(self):
        self.assertEqual([i.path for i in self.view(query='FORK')], ['/r/Logs/Fork.log'])


class TestDeletePath(unittest.TestCase):
    def test_deletes_dirs_files_and_symlinks_without_following(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'dir' / 'sub').mkdir(parents=True)
            (root / 'dir' / 'sub' / 'f').write_text('x')
            (root / 'file').write_text('x')
            (root / 'target').mkdir()
            (root / 'target' / 'keep').write_text('x')
            (root / 'link').symlink_to(root / 'target')
            for name in ('dir', 'file', 'link'):
                mr.delete_path(str(root / name))
            self.assertFalse((root / 'dir').exists())
            self.assertFalse((root / 'file').exists())
            self.assertFalse((root / 'link').is_symlink())
            self.assertTrue((root / 'target' / 'keep').exists())

    def test_refuses_unsafe_paths(self):
        for bad in ('/', '/Users', os.path.expanduser('~'), 'relative/path', '/a/../b'):
            with self.assertRaises(ValueError, msg=bad):
                mr.delete_path(bad)


class AppTestCase(unittest.IsolatedAsyncioTestCase):
    """Drives the real TUI with textual's pilot against a temp file tree."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        text = SAMPLE.format(root=self.root)
        for item in mr.parse_clean_list(text).items:
            p = Path(item.path)
            if p.name == 'Fork.log':
                continue  # simulate an entry mole listed but that is already gone
            p.mkdir(parents=True, exist_ok=True)
            (p / 'data').write_text('x')
        self.list_path = self.root / 'clean-list.txt'
        self.list_path.write_text(text)
        self.wl_path = self.root / 'config' / 'whitelist'

    def tearDown(self):
        self.tmp.cleanup()

    def make_app(self):
        return mr.MoleReviewApp(list_path=self.list_path, whitelist_path=self.wl_path)

    def p(self, rel):
        return str(self.root / rel)

    async def settle(self, app, pilot):
        await app.workers.wait_for_complete()
        await pilot.pause()


class TestAppBrowse(AppTestCase):
    async def test_starts_sorted_by_size_and_drops_missing_entries(self):
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            table = app.query_one(mr.ItemTable)
            self.assertEqual(table.row_count, 7)
            self.assertEqual(app.shown[0].path, self.p('npm/_cacache/content-v2'))
            self.assertNotIn(self.p('Logs/Fork.log'), [i.path for i in app.shown])

    async def test_number_keys_toggle_categories_and_zero_shows_all(self):
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.press('3')  # Developer tools off
            await pilot.pause()
            self.assertEqual({i.category for i in app.shown}, {'User essentials', 'Browsers'})
            await pilot.press('1')  # User essentials off
            await pilot.pause()
            self.assertEqual({i.category for i in app.shown}, {'Browsers'})
            await pilot.press('0')
            await pilot.pause()
            self.assertEqual(len(app.shown), 7)

    async def test_sort_key_cycles_modes(self):
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.press('s')
            await pilot.pause()
            self.assertEqual(app.sort_mode, 'size_asc')
            self.assertEqual(app.shown[0].size, 0)
            await pilot.press('s')
            await pilot.pause()
            self.assertEqual(app.sort_mode, 'path')

    async def test_search_filters_rows(self):
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.press('slash')
            await pilot.press(*'pip')
            await pilot.pause()
            self.assertEqual([i.path for i in app.shown], [self.p('Caches/pip')])
            await pilot.press('escape')
            await pilot.pause()
            self.assertEqual(len(app.shown), 7)

    async def test_typing_in_filter_does_not_trigger_shortcuts(self):
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.press('slash', *'dwsx')
            await pilot.pause()
            self.assertEqual(app.query_one(mr.SearchInput).value, 'dwsx')
            self.assertFalse(isinstance(app.screen, mr.ConfirmDelete))
            self.assertFalse(app.show_whitelisted)
            self.assertEqual(app.sort_mode, 'size_desc')
            self.assertFalse(self.wl_path.exists())

    async def test_keys_right_after_slash_go_to_filter_even_when_batched(self):
        # a terminal can deliver '/' and the next keys in one read, before a deferred focus lands
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            for ch in '/dx':
                key = events.Key('slash' if ch == '/' else ch, ch)
                key.set_sender(app)
                app._driver.send_message(key)  # what the terminal driver does, without pilot's idle waits
            await pilot.pause()
            await pilot.pause()
            self.assertEqual(app.query_one(mr.SearchInput).value, 'dx')
            self.assertFalse(isinstance(app.screen, mr.ConfirmDelete))
            self.assertFalse(self.wl_path.exists())

    async def test_slash_inside_filter_types_a_slash(self):
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.press('slash', *'Caches', 'slash', *'pip')
            await pilot.pause()
            self.assertEqual(app.query_one(mr.SearchInput).value, 'Caches/pip')
            self.assertEqual([i.path for i in app.shown], [self.p('Caches/pip')])

    async def test_enter_in_sidebar_shows_only_that_category(self):
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            app.query_one(mr.CategoryList).focus()
            await pilot.press('down', 'enter')
            await pilot.pause()
            self.assertEqual({i.category for i in app.shown}, {'Browsers'})


class TestAppWhitelist(AppTestCase):
    async def test_whitelisted_rows_hidden_then_shown_dimmed(self):
        mr.add_to_whitelist(self.wl_path, [self.p('npm')])
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            self.assertEqual(len(app.shown), 4)
            await pilot.press('w')
            await pilot.pause()
            self.assertEqual(len(app.shown), 7)
            table = app.query_one(mr.ItemTable)
            row = table.get_row(self.p('npm/empty'))
            self.assertIn('dim', str(row[-1].style))
            normal = table.get_row(self.p('Caches/pip'))
            self.assertNotIn('dim', str(normal[-1].style))

    async def test_x_adds_current_row_to_whitelist_and_hides_it(self):
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            top = app.shown[0].path
            await pilot.press('x')
            await pilot.pause()
            self.assertEqual(mr.load_whitelist(self.wl_path), [top])
            self.assertNotIn(top, [i.path for i in app.shown])

    async def test_x_on_whitelisted_row_removes_it_from_whitelist(self):
        target = self.p('npm/_cacache/content-v2')
        mr.add_to_whitelist(self.wl_path, [target])
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.press('w')
            await pilot.pause()
            # cursor stays on the previously focused row, move to the whitelisted one
            self.assertEqual(app.shown[0].path, target)
            app.query_one(mr.ItemTable).move_cursor(row=0)
            await pilot.press('x')
            await pilot.pause()
            self.assertEqual(mr.load_whitelist(self.wl_path), [])

    async def test_whitelisted_rows_cannot_be_marked(self):
        target = self.p('npm/_cacache/content-v2')
        mr.add_to_whitelist(self.wl_path, [target])
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.press('w')
            await pilot.pause()
            app.query_one(mr.ItemTable).move_cursor(row=0)
            await pilot.press('space')
            await pilot.pause()
            self.assertEqual(app.marked, set())


class TestAppDelete(AppTestCase):
    async def test_mark_rows_then_confirm_deletes_them(self):
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            first, second = app.shown[0].path, app.shown[1].path
            await pilot.press('space', 'space')
            await pilot.pause()
            self.assertEqual(app.marked, {first, second})
            await pilot.press('d')
            await pilot.pause()
            await pilot.press('y')
            await self.settle(app, pilot)
            self.assertFalse(os.path.exists(first))
            self.assertFalse(os.path.exists(second))
            self.assertEqual(app.marked, set())
            # second row is Caches/Google, its nested Chrome/Default child goes with it
            self.assertEqual(second, self.p('Caches/Google'))
            self.assertEqual(len(app.shown), 4)

    async def test_cancel_keeps_everything(self):
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            first = app.shown[0].path
            await pilot.press('space', 'd')
            await pilot.pause()
            await pilot.press('n')
            await self.settle(app, pilot)
            self.assertTrue(os.path.exists(first))
            self.assertEqual(app.marked, {first})

    async def test_deleting_parent_also_drops_nested_children(self):
        parent = self.p('Caches/Google')
        child = self.p('Caches/Google/Chrome/Default')
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            app.marked = {parent}
            await pilot.press('d')
            await pilot.pause()
            await pilot.press('y')
            await self.settle(app, pilot)
            paths = [i.path for i in app.shown]
            self.assertNotIn(parent, paths)
            self.assertNotIn(child, paths)

    async def test_mark_all_visible_toggles(self):
        app = self.make_app()
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.press('a')
            await pilot.pause()
            self.assertEqual(len(app.marked), 7)
            await pilot.press('a')
            await pilot.pause()
            self.assertEqual(app.marked, set())


if __name__ == '__main__':
    unittest.main(verbosity=2)
