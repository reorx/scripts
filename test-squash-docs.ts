#!/usr/bin/env node
// 运行：node test-squash-docs.ts（Node >=22.18）
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, type TestContext } from 'node:test';
import {
  buildPlan,
  parseArgs,
  readHistory,
  rewrittenCommits,
  type Commit,
} from './skills/squash-docs/scripts/squash-docs.ts';

const script = fileURLToPath(new URL('./skills/squash-docs/scripts/squash-docs.ts', import.meta.url));
const docs = parseArgs([]);
const commit = (id: string, subject: string, files = ['README.md'], body = ''): Commit => ({
  hash: id.repeat(40),
  parents: id === '1' ? [] : [String(Number(id) - 1).repeat(40)],
  message: `${subject}\n${body}`,
  files,
});
interface Report {
  before: string;
  after: string;
  backup: string;
  groups: { original: string[]; rewritten: string; removedHeaders: number }[];
}

function fixture(t: TestContext) {
  const repo = mkdtempSync(join(tmpdir(), 'squash-docs-repo-'));
  t.after(() => rmSync(repo, { recursive: true, force: true }));
  const git = (...args: string[]) =>
    execFileSync('git', args, { cwd: repo, encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'] }).trim();
  git('init', '-q', '-b', 'main');
  git('config', 'user.email', 'test@example.invalid');
  git('config', 'user.name', 'Test');
  git('config', 'commit.gpgsign', 'false');
  git('config', 'core.hooksPath', '/dev/null');
  const add = (file: string, text: string, message = text) => {
    writeFileSync(join(repo, file), text);
    git('add', '--', file);
    git('commit', '-qm', message);
    return git('rev-parse', 'HEAD');
  };
  const run = (...args: string[]) =>
    spawnSync(process.execPath, [script, '--repo', repo, ...args], { encoding: 'utf8' });
  return { repo, git, add, run };
}

function verify(s: ReturnType<typeof fixture>, before: string, result: ReturnType<typeof s.run>) {
  assert.equal(result.status, 0, result.stderr);
  const match = result.stdout.match(/校验报告：(.+)/);
  assert.ok(match, result.stdout);
  const report: Report = JSON.parse(readFileSync(match[1]!, 'utf8'));
  assert.equal(report.before, before);
  assert.equal(s.git('rev-parse', report.backup), before);
  assert.equal(s.git('rev-parse', 'HEAD'), report.after);
  assert.equal(s.git('rev-parse', 'HEAD^{tree}'), s.git('rev-parse', `${before}^{tree}`));
  const mapping = new Map<string, string>();
  for (const entry of report.groups) for (const hash of entry.original) mapping.set(hash, entry.rewritten);
  for (const entry of report.groups) {
    const first = entry.original[0]!;
    const last = entry.original.at(-1)!;
    assert.equal(s.git('rev-parse', `${entry.rewritten}^{tree}`), s.git('rev-parse', `${last}^{tree}`));
    const parents = s
      .git('show', '-s', '--format=%P', first)
      .split(' ')
      .filter(Boolean)
      .map((p) => mapping.get(p) ?? p);
    assert.deepEqual(s.git('show', '-s', '--format=%P', entry.rewritten).split(' ').filter(Boolean), parents);
    if (entry.original.length === 1) {
      assert.equal(s.git('show', '-s', '--format=%B', entry.rewritten), s.git('show', '-s', '--format=%B', first));
      assert.equal(
        s.git('show', '-s', '--format=%an <%ae> %at %cn <%ce> %ct', entry.rewritten),
        s.git('show', '-s', '--format=%an <%ae> %at %cn <%ce> %ct', first),
      );
    }
  }
  assert.equal(
    s.git('rev-list', '--count', '--min-parents=2', 'HEAD'),
    s.git('rev-list', '--count', '--min-parents=2', before),
  );
  assert.equal(s.git('status', '--porcelain'), '');
  return report;
}

// 参数与计划

test('默认选最近 50 条，支持作用域 docs 和自定义正则、仓库路径', () => {
  assert.equal(docs.count, 50);
  assert.equal(docs.apply, false);
  assert.ok(docs.pattern.test('docs: plain'));
  assert.ok(docs.pattern.test('docs(kb): scoped'));
  assert.ok(!docs.pattern.test('fix: docs: mentioned'));
  const options = parseArgs(['--count', '12', '--pattern', '^notes:', '--repo', '/some repo', '--apply']);
  assert.equal(options.count, 12);
  assert.equal(options.repo, '/some repo');
  assert.equal(options.apply, true);
  assert.ok(options.pattern.test('notes: note'));
  assert.ok(!options.pattern.test('docs: doc'));
});

test('--all 显式选全部历史，与 --count 互斥', () => {
  assert.equal(parseArgs(['--all']).all, true);
  assert.throws(() => parseArgs(['--all', '--count', '10']), /互斥/);
  assert.throws(() => parseArgs(['--count', '10', '--all']), /互斥/);
});

test('无效数量、无效正则、缺少参数、未知选项均拒绝', () => {
  for (const args of [
    ['--count', '0'],
    ['--count', '-1'],
    ['--count', '1.5'],
    ['--count', '2junk'],
    ['--count', '9007199254740992'],
    ['--pattern', '['],
    ['--repo'],
    ['--count'],
    ['--pattern'],
    ['--title'],
    ['--unknown'],
  ]) {
    assert.throws(() => parseArgs(args));
  }
});

test('只压缩连续的多条匹配，保持代码、单条 docs 和提交顺序', () => {
  const commits = [
    commit('1', 'docs: first'),
    commit('2', 'docs(kb): second'),
    commit('3', 'fix: separator'),
    commit('4', 'docs: alone'),
    commit('5', 'feat: separator'),
    commit('6', 'docs: third'),
    commit('7', 'docs: fourth'),
  ];
  const plan = buildPlan(commits, docs);
  assert.deepEqual(
    plan.map((group) => group.commits.map((item) => item.hash[0])),
    [['1', '2'], ['3'], ['4'], ['5'], ['6', '7']],
  );
  assert.equal(plan[1]!.message, null);
  assert.equal(plan[2]!.message, null);
  assert.equal(plan[4]!.message, 'update docs for README.md\n\ndocs: third\n\ndocs: fourth\n');
});

test('标题用去重排序的完整文件路径，正文保留每条完整消息和空白', () => {
  const plan = buildPlan(
    [
      commit('1', 'docs: first', ['kb/a.md', 'AGENTS.md'], '\n  original text  \n\n'),
      commit('2', 'docs: second', ['kb/a.md', 'apps/web/AGENTS.md'], '\nsecond body\n'),
    ],
    { pattern: /^docs:/ },
  );
  assert.equal(
    plan[0]!.message,
    'update docs for AGENTS.md, apps/web/AGENTS.md, kb/a.md\n\n' +
      'docs: first\n\n  original text  \n\n\n' +
      'docs: second\n\nsecond body\n',
  );
});

test('文件名中的换行不会进入标题，空提交有明确标题', () => {
  assert.equal(
    buildPlan([commit('1', 'docs: a', ['a\nb.md']), commit('2', 'docs: b', [])], { pattern: /^docs:/ })[0]!.message,
    'update docs for "a\\nb.md"\n\ndocs: a\n\ndocs: b\n',
  );
  assert.match(
    buildPlan([commit('1', 'docs: a', []), commit('2', 'docs: b', [])], { pattern: /^docs:/ })[0]!.message!,
    /^update docs for \(no files\)\n/,
  );
});

test('--title 自定义合并标题，{files} 每处都按字面替换，多行标题拒绝', () => {
  assert.equal(docs.title, 'update docs for {files}');
  const options = parseArgs(['--pattern', '^chore:', '--title', 'chore: squash {files} ({files})']);
  const plan = buildPlan([commit('1', 'chore: a', ['$&.md']), commit('2', 'chore: b', ['b.md'])], options);
  assert.equal(plan[0]!.message, 'chore: squash $&.md, b.md ($&.md, b.md)\n\nchore: a\n\nchore: b\n');
  assert.equal(
    buildPlan([commit('1', 'wip'), commit('2', 'wip')], parseArgs(['--pattern', '^wip$', '--title', 'wip']))[0]!
      .message,
    'wip\n\nwip\n\nwip\n',
  );
  assert.throws(() => parseArgs(['--title', 'a\nb']), /一行/);
});

test('自定义匹配规则只考察首行，不因正文里的 docs 误合并', () => {
  const commits = [
    commit('1', 'notes: a'),
    commit('2', 'notes: b'),
    commit('3', 'fix: c', [], '\ndocs: body'),
    commit('4', 'docs: d'),
  ];
  assert.deepEqual(
    buildPlan(commits, { pattern: /^notes:/ }).map((group) => group.commits.length),
    [2, 1, 1],
  );
});

test('有状态的正则不会漏匹配，没有连续匹配时计划不改消息', () => {
  assert.equal(buildPlan([commit('1', 'docs: a'), commit('2', 'docs: b')], { pattern: /^docs:/g }).length, 1);
  assert.equal(buildPlan([], docs).length, 0);
  assert.ok(buildPlan([commit('1', 'docs: a'), commit('2', 'fix: b')], docs).every((group) => group.message === null));
});

test('可选路径筛选要求全部路径匹配，含代码的 docs 提交隔开两侧文档', () => {
  const options = parseArgs(['--files-pattern', '(?:\\.md$|^kb/)']);
  const commits = [
    commit('1', 'docs: a'),
    commit('2', 'docs: b'),
    commit('3', 'docs: mixed', ['README.md', 'src/code.ts']),
    commit('4', 'docs: c', ['kb/review.html']),
    commit('5', 'docs: d'),
  ];
  assert.deepEqual(
    buildPlan(commits, options).map((g) => g.commits.length),
    [2, 1, 2],
  );
  assert.equal(buildPlan(commits, docs).length, 1);
  assert.throws(() => parseArgs(['--files-pattern', '[']));
  assert.throws(() => parseArgs(['--files-pattern']));
});

test('改写范围是合并组及其之后的全部后代，之前的提交哈希不变', () => {
  const plan = buildPlan(
    [commit('1', 'feat: a'), commit('2', 'docs: b'), commit('3', 'docs: c'), commit('4', 'feat: d')],
    docs,
  );
  assert.deepEqual(
    [...rewrittenCommits(plan)].map((hash) => hash[0]),
    ['2', '3', '4'],
  );
  assert.equal(rewrittenCommits(buildPlan([commit('1', 'docs: a'), commit('2', 'feat: b')], docs)).size, 0);
});

// 读取与预览

test('读取窗口的边界不包含第 N+1 条，含新增/删除/重命名文件，预览不改历史', (t) => {
  const s = fixture(t);
  const base = s.add('old.md', 'docs: outside');
  const first = s.add('new.md', 'docs: first\n\nbody');
  s.git('mv', 'old.md', 'renamed.md');
  s.git('rm', 'new.md');
  s.git('commit', '-qm', 'docs: second');
  const head = s.git('rev-parse', 'HEAD');
  const history = readHistory(s.repo, 2);
  assert.equal(history.commits[0]!.parents[0], base);
  assert.deepEqual(
    history.commits.map((item) => item.hash),
    [first, head],
  );
  assert.deepEqual(history.commits[1]!.files.sort(), ['new.md', 'old.md', 'renamed.md']);
  assert.equal(history.commits[0]!.message, 'docs: first\n\nbody\n');
  const beforeRefs = s.git('show-ref');
  const result = s.run('--count', '2');
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /update docs for new.md, old.md, renamed.md/);
  assert.equal(s.git('rev-parse', 'HEAD'), head);
  assert.equal(s.git('show-ref'), beforeRefs);
  assert.equal(s.git('status', '--porcelain'), '');
  assert.deepEqual(readHistory(s.repo, 50).commits[0]!.parents, []);
});

test('无匹配的预览不改变仓库，merge 历史可以读取', (t) => {
  const s = fixture(t);
  s.add('README.md', 'feat: root');
  const head = s.git('rev-parse', 'HEAD');
  const result = s.run();
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /没有连续匹配/);
  assert.equal(s.git('rev-parse', 'HEAD'), head);
  s.git('checkout', '-qb', 'side');
  s.add('side.md', 'docs: side');
  s.git('checkout', '-q', 'main');
  s.add('main.md', 'docs: main');
  s.git('merge', '--no-ff', '-qm', 'merge', 'side');
  assert.equal(readHistory(s.repo, 50).commits.at(-1)!.parents.length, 2);
});

test('预览提示改写范围，以及其中已推送到远程或被其他分支、标签引用的提交', (t) => {
  const s = fixture(t);
  const remote = mkdtempSync(join(tmpdir(), 'squash-docs-remote-'));
  t.after(() => rmSync(remote, { recursive: true, force: true }));
  s.add('a.md', '1', 'feat: base');
  s.add('a.md', '2', 'docs: one');
  const local = s.run();
  assert.equal(local.status, 0, local.stderr);
  assert.doesNotMatch(local.stdout, /改写范围/);
  s.add('a.md', '3', 'docs: two');
  const unpushed = s.run();
  assert.match(unpushed.stdout, /改写范围：2 条原提交/);
  assert.doesNotMatch(unpushed.stdout, /已推送到远程|其他本地分支或标签/);
  s.git('init', '-q', '--bare', remote);
  s.git('remote', 'add', 'origin', remote);
  s.git('push', '-q', 'origin', 'HEAD~1:refs/heads/main');
  s.git('fetch', '-q', 'origin');
  const pushed = s.run();
  assert.match(pushed.stdout, /其中 1 条已推送到远程/);
  assert.doesNotMatch(pushed.stdout, /其他本地分支或标签/);
  s.git('tag', 'v1');
  const tagged = s.run();
  assert.match(tagged.stdout, /其中 2 条仍被其他本地分支或标签引用/);
});

// 改写

test('从根压缩，保留代码提交、空提交、消息、元数据和文件内容，不检出历史文件，可按提示撤销', (t) => {
  const s = fixture(t);
  s.add('a.md', '1', 'docs: first');
  s.add('a.md', '2', 'docs: second');
  s.add('code.ts', 'export const code = 42;', 'feat: code');
  s.git('commit', '--allow-empty', '-qm', 'docs: empty first');
  s.git('commit', '--allow-empty', '-qm', 'docs: empty second');
  const before = s.git('rev-parse', 'HEAD');
  const hooks = join(s.repo, '.git/audit-hooks');
  mkdirSync(hooks);
  for (const name of ['pre-rebase', 'pre-commit', 'post-checkout']) {
    writeFileSync(join(hooks, name), '#!/bin/sh\nexit 99\n', { mode: 0o755 });
  }
  s.git('config', 'core.hooksPath', hooks);
  const result = s.run('--all', '--apply');
  const report = verify(s, before, result);
  assert.equal(report.groups.length, 3);
  assert.match(s.git('log', '--format=%B'), /docs: first\n\ndocs: second/);
  const undo = result.stdout.match(/撤销：git (reset --keep \S+)/);
  assert.ok(undo, result.stdout);
  s.git(...undo[1]!.split(' '));
  assert.equal(s.git('rev-parse', 'HEAD'), before);
});

test('嵌套 no-ff merge 和分叉点保留，已解决冲突的 merge tree 不重算，其他分支标签不变', (t) => {
  const s = fixture(t);
  s.add('root.md', '0', 'docs: root');
  const fork = s.add('shared.ts', 'base\n', 'docs: fork');
  s.git('checkout', '-qb', 'side');
  s.add('side.md', 'a', 'docs: side one');
  s.add('side.md', 'b', 'docs: side two');
  s.add('shared.ts', 'side\n', 'feat: side code');
  s.git('checkout', '-q', 'main');
  s.add('main.md', 'a', 'docs: main one');
  s.add('main.md', 'b', 'docs: main two');
  s.add('shared.ts', 'main\n', 'feat: main code');
  s.git('checkout', '-q', 'side');
  const conflict = spawnSync('git', ['merge', '--no-ff', '-m', 'docs: nested merge', 'main'], { cwd: s.repo });
  assert.equal(conflict.status, 1);
  s.add('shared.ts', 'manual conflict resolution\n', 'docs: nested merge');
  s.add('side.md', 'c', 'docs: after merge one');
  s.add('side.md', 'd', 'docs: after merge two');
  const side = s.git('rev-parse', 'side');
  s.git('tag', 'keep', side);
  s.git('checkout', '-q', 'main');
  s.git('merge', '--no-ff', '-qm', 'docs: outer merge', 'side');
  s.add('main.md', 'c', 'docs: tail one');
  s.add('main.md', 'd', 'docs: tail two');
  const before = s.git('rev-parse', 'HEAD');
  const refs = s.git('show-ref');
  const preview = s.run('--all');
  assert.equal(preview.status, 0, preview.stderr);
  assert.equal(s.git('show-ref'), refs);
  const report = verify(s, before, s.run('--all', '--apply'));
  assert.ok(report.groups.some((g) => g.original.length > 1));
  assert.equal(report.groups.find((g) => g.original.includes(fork))!.original.length, 1);
  assert.equal(s.git('rev-parse', 'side'), side);
  assert.equal(s.git('rev-parse', 'keep'), side);
  assert.equal(readFileSync(join(s.repo, 'shared.ts'), 'utf8'), 'manual conflict resolution\n');
  assert.equal(s.git('rev-list', '--count', '--min-parents=2', 'HEAD'), '2');
});

test('跨 merge 的有限窗口不改窗口外对象，merge 的父提交有序且不折叠', (t) => {
  const s = fixture(t);
  const root = s.add('root.md', 'r', 'feat: root');
  s.git('checkout', '-qb', 'side');
  s.add('side.md', 's1', 'docs: side one');
  s.add('side.md', 's2', 'docs: side two');
  s.git('checkout', '-q', 'main');
  s.git('merge', '--no-ff', '-qm', 'merge', 'side');
  s.add('tail.md', 't1', 'docs: tail one');
  s.add('tail.md', 't2', 'docs: tail two');
  const before = s.git('rev-parse', 'HEAD');
  const report = verify(s, before, s.run('--count', '5', '--apply'));
  assert.ok(!report.groups.some((g) => g.original.includes(root)));
  assert.equal(s.git('rev-list', '--max-parents=0', 'HEAD'), root);
});

test('octopus merge 的三个父节点和无共同祖先的根均保留', (t) => {
  const s = fixture(t);
  s.add('a.md', 'a1', 'docs: a1');
  s.add('a.md', 'a2', 'docs: a2');
  const a = s.git('rev-parse', 'HEAD');
  s.git('checkout', '--orphan', 'other');
  s.git('rm', '-rf', '.');
  s.add('b.md', 'b1', 'docs: b1');
  s.add('b.md', 'b2', 'docs: b2');
  const b = s.git('rev-parse', 'HEAD');
  s.git('checkout', '-q', 'main');
  const c = s.add('c.md', 'c', 'feat: c');
  const merge = execFileSync(
    'git',
    ['commit-tree', 'HEAD^{tree}', '-p', c, '-p', b, '-p', a, '-m', 'merge three parents'],
    { cwd: s.repo, encoding: 'utf8' },
  ).trim();
  s.git('update-ref', 'refs/heads/main', merge, c);
  verify(s, merge, s.run('--all', '--apply'));
  assert.equal(s.git('show', '-s', '--format=%P', 'HEAD').split(' ').length, 3);
  assert.equal(s.git('rev-list', '--max-parents=0', 'HEAD').split('\n').length, 2);
});

test('压缩保留二进制、符号链接、可执行位，工作区和 index 字节及文件时间都不变', (t) => {
  const s = fixture(t);
  s.add('a.md', 'one', 'docs: one');
  writeFileSync(join(s.repo, 'blob.bin'), Buffer.from([0, 255, 128, 3]));
  writeFileSync(join(s.repo, 'run.sh'), '#!/bin/sh\nexit 0\n', { mode: 0o755 });
  symlinkSync('a.md', join(s.repo, 'link'));
  s.git('add', '.');
  s.git('commit', '-qm', 'feat: binary and modes');
  s.add('a.md', 'two', 'docs: two');
  s.add('a.md', 'three', 'docs: three');
  const before = s.git('rev-parse', 'HEAD');
  const index = readFileSync(join(s.repo, '.git/index'));
  const mtime = statSync(join(s.repo, 'a.md')).mtimeMs;
  verify(s, before, s.run('--all', '--apply'));
  assert.deepEqual(readFileSync(join(s.repo, '.git/index')), index);
  assert.equal(statSync(join(s.repo, 'a.md')).mtimeMs, mtime);
});

test('只移除改写对象的失效签名，保留未知多行 header 和未改写的签名对象', (t) => {
  const s = fixture(t);
  const root = s.add('root.md', 'root', 'feat: root');
  const raw =
    s
      .git('cat-file', 'commit', root)
      .replace('\n\n', '\ngpgsig root signature\n continued\nx-extra retained\n continuation\n\n') + '\n';
  const signedRoot = execFileSync('git', ['hash-object', '-t', 'commit', '-w', '--stdin'], {
    cwd: s.repo,
    input: raw,
    encoding: 'utf8',
  }).trim();
  s.git('update-ref', 'refs/heads/main', signedRoot, root);
  s.add('a.md', 'one', 'docs: one');
  s.add('a.md', 'two', 'docs: two');
  const tip = s.add('code.ts', 'code', 'feat: tail');
  const signedRaw =
    s
      .git('cat-file', 'commit', tip)
      .replace(
        '\n\n',
        '\ngpgsig old signature\n continued\nmergetag old tag\n continued\nx-extra retained\n continuation\n\n',
      ) + '\n';
  const signedTip = execFileSync('git', ['hash-object', '-t', 'commit', '-w', '--stdin'], {
    cwd: s.repo,
    input: signedRaw,
    encoding: 'utf8',
  }).trim();
  s.git('update-ref', 'refs/heads/main', signedTip, tip);
  const report = verify(s, signedTip, s.run('--all', '--apply'));
  assert.equal(s.git('rev-list', '--max-parents=0', 'HEAD'), signedRoot);
  assert.match(s.git('cat-file', 'commit', signedRoot), /gpgsig root signature/);
  const current = s.git('cat-file', 'commit', 'HEAD');
  assert.doesNotMatch(current, /gpgsig|mergetag/);
  assert.match(current, /x-extra retained\n continuation/);
  assert.equal(report.groups.at(-1)!.removedHeaders, 2);
});

// 拒绝条件

test('工作区不干净时 --apply 在改写前拒绝，不创建备份', (t) => {
  const s = fixture(t);
  s.add('README.md', 'docs: a');
  s.add('b.md', 'docs: b');
  writeFileSync(join(s.repo, 'untracked'), 'keep');
  const refs = s.git('show-ref');
  const result = s.run('--apply');
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /工作区/);
  assert.equal(s.git('show-ref'), refs);
  assert.equal(readFileSync(join(s.repo, 'untracked'), 'utf8'), 'keep');
});

test('detached HEAD 和进行中的 Git 操作在改写前拒绝', (t) => {
  const s = fixture(t);
  s.add('README.md', 'docs: a');
  s.add('b.md', 'docs: b');
  s.git('checkout', '--detach', '-q');
  const detached = s.run('--apply');
  assert.notEqual(detached.status, 0);
  assert.match(detached.stderr, /detached HEAD/);
  s.git('checkout', '-q', 'main');
  writeFileSync(join(s.repo, '.git', 'CHERRY_PICK_HEAD'), s.git('rev-parse', 'HEAD'));
  const refs = s.git('show-ref');
  const pending = s.run('--apply');
  assert.notEqual(pending.status, 0);
  assert.match(pending.stderr, /进行中的 Git 操作/);
  assert.equal(s.git('show-ref'), refs);
});

test('浅克隆缺少窗口父对象时拒绝，不能误当成根提交', (t) => {
  const s = fixture(t);
  s.add('README.md', 'docs: root');
  s.add('b.md', 'docs: a');
  s.add('c.md', 'docs: b');
  const clone = join(s.repo, 'shallow');
  s.git('clone', '-q', '--depth', '2', `file://${s.repo}`, clone);
  assert.throws(() => readHistory(clone, 2));
});

test('replace refs 拒绝处理，不把替换对象误写进原历史', (t) => {
  const s = fixture(t);
  const a = s.add('a.md', 'a1', 'docs: a1');
  const b = s.add('a.md', 'a2', 'docs: a2');
  s.git('replace', a, b);
  const before = s.git('show-ref');
  const result = s.run('--all', '--apply');
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /replace/);
  assert.equal(s.git('show-ref'), before);
});

test('引用事务被拒绝时当前分支和备份引用均不改变', (t) => {
  const s = fixture(t);
  s.add('a.md', 'a1', 'docs: a1');
  s.add('a.md', 'a2', 'docs: a2');
  const before = s.git('show-ref');
  const hook = join(s.repo, '.git/hooks/reference-transaction');
  writeFileSync(hook, '#!/bin/sh\nif [ "$1" = prepared ]; then exit 1; fi\n');
  chmodSync(hook, 0o755);
  s.git('config', 'core.hooksPath', join(s.repo, '.git/hooks'));
  const result = s.run('--all', '--apply');
  assert.notEqual(result.status, 0);
  assert.equal(s.git('show-ref'), before);
  assert.equal(s.git('status', '--porcelain'), '');
});

test('非 UTF-8 docs 消息拒绝压缩，不悄悄替换原消息字节', (t) => {
  const s = fixture(t);
  const root = s.add('a.md', 'one', 'docs: one');
  const raw = execFileSync('git', ['cat-file', 'commit', root], { cwd: s.repo });
  const custom = Buffer.concat([
    raw.subarray(0, raw.indexOf('\n\n') + 2),
    Buffer.from('docs: '),
    Buffer.from([0xe9, 0x0a]),
  ]);
  const nonUtf8 = execFileSync('git', ['hash-object', '-t', 'commit', '-w', '--stdin'], {
    cwd: s.repo,
    input: custom,
    encoding: 'utf8',
  }).trim();
  s.git('update-ref', 'refs/heads/main', nonUtf8, root);
  s.add('a.md', 'two', 'docs: two');
  const refs = s.git('show-ref');
  const result = s.run('--all', '--apply');
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /非 UTF-8/);
  assert.equal(s.git('show-ref'), refs);
});
