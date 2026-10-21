#!/usr/bin/env node
/**
 * 合并 Git 历史中连续匹配的提交（默认 docs:）。
 * 独立工具，Node >=22.18（原生类型剥离）/ Git >=2.38，无依赖，可复制到任意位置。
 * squash-docs.ts --repo /path/to/repo --count 50
 * squash-docs.ts --all --apply
 * 只收缩单链上的匹配提交，复用原 tree，不检出文件、不重新执行 merge。
 */
import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, realpathSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

export interface Commit {
  hash: string;
  parents: string[];
  message: string;
  files: string[];
}
export interface History {
  commits: Commit[];
  head: string;
}
export interface Group {
  commits: Commit[];
  message: string | null;
}
export interface PlanOptions {
  pattern: RegExp;
  filesPattern?: RegExp;
  title?: string;
}
interface CommitObject {
  raw: Buffer;
  headers: string[];
  message: Buffer;
  tree: string;
  parents: string[];
}

const DEFAULT_TITLE = 'update docs for {files}';

const HELP = `用法：squash-docs.ts [选项]
  --repo <路径>     Git 仓库或其中的目录，默认当前目录
  --count <数量>    拓扑顺序最近的提交数量，默认 50
  --all             当前 HEAD 可达的全部历史，与 --count 互斥
  --pattern <正则>  匹配提交消息首行，默认 ^docs(?:\\([^)]*\\))?:
  --files-pattern <正则>  可选，要求提交的全部变更路径匹配；空提交仍可匹配
  --title <模板>    合并后的标题，{files} 替换为变更路径，默认 '${DEFAULT_TITLE}'
  --apply           执行历史改写；不加此选项只预览
  --help            显示帮助

只合并单链上连续匹配的两条或更多提交，不跨窗口、分叉点或 merge。
默认不限制文件类型；可用 --files-pattern '(?:\\.md$|^kb/)' 保留混合代码提交。
标题按模板汇总变更路径，正文保留完整原消息。
预览列出改写范围，并提示其中已推送到远程或仍被其他分支、标签引用的提交。
分叉点和 merge 各自保留；保留父提交顺序，复用原 tree，不重算冲突解决。
合并提交使用组内首条的作者和提交者元数据、末条的 tree；不改写时间。
改写对象会移除失效的 gpgsig/mergetag；原对象通过备份引用保留。
要求当前分支、干净工作区、完整克隆且无进行中的 Git 操作或 replace/graft。
全部新对象校验通过后，原子更新当前分支和 refs/squash-docs-backup/ 备份。
不检出历史文件、不更新其他分支或标签、不自动推送。报告保存在 Git 目录。
`;

export function parseArgs(args: string[]) {
  let count = 50;
  let countSpecified = false;
  let all = false;
  let source = '^docs(?:\\([^)]*\\))?:';
  let filesSource: string | undefined;
  let title = DEFAULT_TITLE;
  let repo = process.cwd();
  let apply = false;
  let help = false;
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg === '--apply') apply = true;
    else if (arg === '--all') all = true;
    else if (arg === '--help' || arg === '-h') help = true;
    else if (
      arg === '--count' ||
      arg === '--pattern' ||
      arg === '--files-pattern' ||
      arg === '--title' ||
      arg === '--repo'
    ) {
      const value = args[++i];
      if (value === undefined || value.startsWith('--')) throw new Error(`${arg} 缺少参数`);
      if (arg === '--count') {
        countSpecified = true;
        count = Number(value);
        if (!/^\d+$/.test(value) || !Number.isSafeInteger(count) || count < 1) {
          throw new Error('--count 必须是正整数');
        }
      } else if (arg === '--pattern') source = value;
      else if (arg === '--files-pattern') filesSource = value;
      else if (arg === '--title') {
        if (/[\r\n]/.test(value)) throw new Error('--title 只能是一行');
        title = value;
      } else repo = value;
    } else throw new Error(`未知选项：${arg}`);
  }
  if (all && countSpecified) throw new Error('--all 与 --count 互斥');
  return {
    count,
    all,
    pattern: new RegExp(source),
    filesPattern: filesSource === undefined ? undefined : new RegExp(filesSource),
    title,
    repo,
    apply,
    help,
  };
}

function gitBytes(repo: string, args: string[], input?: Buffer | string) {
  return execFileSync('git', ['--no-replace-objects', ...args], {
    cwd: repo,
    input,
    stdio: ['pipe', 'pipe', 'pipe'],
    maxBuffer: 64 * 1024 * 1024,
  });
}

function git(repo: string, args: string[]) {
  return gitBytes(repo, args).toString('utf8');
}

function readObject(repo: string, hash: string): CommitObject {
  const raw = gitBytes(repo, ['cat-file', 'commit', hash]);
  const boundary = raw.indexOf('\n\n');
  if (boundary < 0) throw new Error(`无效 commit：${hash}`);
  // latin1 可逐字节还原 header；保留作者、时间、encoding 和未知的多行 header。
  const headers = raw
    .subarray(0, boundary)
    .toString('latin1')
    .split(/\n(?! )/);
  const tree = headers.find((header) => header.startsWith('tree '))?.slice(5);
  if (!tree) throw new Error(`commit 缺少 tree：${hash}`);
  return {
    raw,
    headers,
    tree,
    message: raw.subarray(boundary + 2),
    parents: headers.filter((header) => header.startsWith('parent ')).map((header) => header.slice(7)),
  };
}

function assertOriginalHistory(repo: string) {
  if (git(repo, ['rev-parse', '--is-shallow-repository']).trim() === 'true') {
    throw new Error('浅克隆不能整理历史，请先获取完整历史。');
  }
  const grafts = git(repo, ['rev-parse', '--path-format=absolute', '--git-path', 'info/grafts']).trim();
  if (existsSync(grafts) || git(repo, ['for-each-ref', '--format=%(refname)', 'refs/replace/']).trim()) {
    throw new Error('存在 replace/graft，不能将替换后的视图写入原历史。');
  }
}

export function readHistory(repo: string, count: number | null): History {
  assertOriginalHistory(repo);
  const head = git(repo, ['rev-parse', '--verify', 'HEAD']).trim();
  // 子节点在父节点前的前缀再倒序，保证窗口内每个父节点先于子节点。
  const args = ['rev-list', '--topo-order', ...(count === null ? [] : [`--max-count=${count}`]), head];
  const hashes = git(repo, args).trim().split('\n').reverse();
  const commits = hashes.map((hash) => {
    const object = readObject(repo, hash);
    const files =
      object.parents.length > 1
        ? []
        : git(repo, ['diff-tree', '--root', '--no-commit-id', '--no-renames', '-r', '--name-only', '-z', hash])
            .split('\0')
            .filter(Boolean);
    return { hash, parents: object.parents, message: object.message.toString('utf8'), files };
  });
  return { head, commits };
}

function combinedMessage(commits: Commit[], title: string) {
  const files = [...new Set(commits.flatMap((commit) => commit.files))]
    .sort()
    .map((file) => (/[\r\n\u2028\u2029]/.test(file) ? JSON.stringify(file) : file));
  const body = commits
    .map((commit) => (commit.message.endsWith('\n') ? commit.message : `${commit.message}\n`))
    .join('\n');
  const list = files.join(', ') || '(no files)';
  // \u51fd\u6570\u5f62\u5f0f\u7684\u66ff\u6362\u503c\u4e0d\u89e3\u6790 $& \u7b49\u7279\u6b8a\u5e8f\u5217\uff0c\u8def\u5f84\u6309\u5b57\u9762\u5199\u5165\u3002
  return `${title.replaceAll('{files}', () => list)}\n\n${body}`;
}

export function buildPlan(commits: Commit[], { pattern, filesPattern, title = DEFAULT_TITLE }: PlanOptions): Group[] {
  const children = new Map<string, number>();
  for (const commit of commits) {
    for (const parent of commit.parents) children.set(parent, (children.get(parent) ?? 0) + 1);
  }
  const groups: Group[] = [];
  const eligible = new Map<string, Group>();
  for (const commit of commits) {
    pattern.lastIndex = 0;
    const matches =
      commit.parents.length <= 1 &&
      (children.get(commit.hash) ?? 0) <= 1 &&
      pattern.test(commit.message.split('\n', 1)[0]!) &&
      (!filesPattern ||
        commit.files.every((file) => {
          filesPattern.lastIndex = 0;
          return filesPattern.test(file);
        }));
    const parentGroup = matches ? eligible.get(commit.parents[0]!) : undefined;
    if (parentGroup) {
      parentGroup.commits.push(commit);
      eligible.set(commit.hash, parentGroup);
    } else {
      const group: Group = { commits: [commit], message: null };
      groups.push(group);
      if (matches) eligible.set(commit.hash, group);
    }
  }
  for (const group of groups) if (group.commits.length > 1) group.message = combinedMessage(group.commits, title);
  return groups;
}

// 合并组本身和父链上有改写的组都会得到新哈希，即合并组及其全部后代。
export function rewrittenCommits(plan: Group[]) {
  const changed = new Set<string>();
  for (const group of plan) {
    if (group.message === null && !group.commits[0]!.parents.some((parent) => changed.has(parent))) continue;
    for (const commit of group.commits) changed.add(commit.hash);
  }
  return changed;
}

// 统计 changed 中能从 refArgs 所列引用到达的提交；只有 HEAD 能到达的不计入。
function reachableFrom(repo: string, head: string, changed: Set<string>, refArgs: string[]) {
  const own = new Set(git(repo, ['rev-list', head, '--not', ...refArgs]).split('\n'));
  return [...changed].filter((hash) => !own.has(hash)).length;
}

function assertReady(repo: string, head: string, branch: string) {
  if (!branch.startsWith('refs/heads/')) throw new Error('不能在 detached HEAD 上执行。');
  for (const name of [
    'rebase-merge',
    'rebase-apply',
    'MERGE_HEAD',
    'CHERRY_PICK_HEAD',
    'REVERT_HEAD',
    'sequencer',
    'index.lock',
  ]) {
    const path = git(repo, ['rev-parse', '--path-format=absolute', '--git-path', name]).trim();
    if (existsSync(path)) throw new Error(`有进行中的 Git 操作：${name}，请先完成或中止。`);
  }
  if (git(repo, ['status', '--porcelain', '--untracked-files=all']).length > 0) {
    throw new Error('工作区不干净，请先提交或 stash 改动（包括未跟踪文件）。');
  }
  if (
    git(repo, ['rev-parse', 'HEAD']).trim() !== head ||
    git(repo, ['rev-parse', '--symbolic-full-name', 'HEAD']).trim() !== branch
  ) {
    throw new Error('HEAD 或当前分支已改变，请重新运行预览。');
  }
}

function rewriteObject(first: CommitObject, last: CommitObject, parents: string[], message: string | null) {
  const body = message === null ? first.message : Buffer.from(message);
  const changed = message !== null || first.parents.some((parent, i) => parent !== parents[i]);
  if (!changed) return { raw: first.raw, removedHeaders: 0 };
  let removedHeaders = 0;
  const headers = [`tree ${last.tree}`, ...parents.map((parent) => `parent ${parent}`)];
  for (const header of first.headers) {
    const key = header.split(' ', 1)[0];
    if (key === 'tree' || key === 'parent') continue;
    // 签名覆盖旧 commit，mergetag 引用旧父对象；不能冒充仍然有效。
    if (key === 'gpgsig' || key === 'gpgsig-sha256' || key === 'mergetag') {
      removedHeaders++;
      continue;
    }
    headers.push(header);
  }
  return { raw: Buffer.concat([Buffer.from(`${headers.join('\n')}\n\n`, 'latin1'), body]), removedHeaders };
}

function writeHistory(repo: string, history: History, plan: Group[]) {
  const mapping = new Map<string, string>();
  const selected = new Set(history.commits.map((commit) => commit.hash));
  const rewritten = new Set<string>();
  const groups = [];
  for (const group of plan) {
    const first = readObject(repo, group.commits[0]!.hash);
    const last = readObject(repo, group.commits.at(-1)!.hash);
    if (group.message !== null) {
      for (const commit of group.commits) {
        const object = readObject(repo, commit.hash);
        const encoding = object.headers.find((header) => header.startsWith('encoding '));
        if (!Buffer.from(commit.message).equals(object.message) || (encoding && !/^encoding utf-?8$/i.test(encoding))) {
          throw new Error(`不能合并非 UTF-8 消息：${commit.hash}`);
        }
      }
    }
    const parents = first.parents.map((parent) => {
      if (selected.has(parent) && !mapping.has(parent)) throw new Error(`父节点未先处理：${parent}`);
      return mapping.get(parent) ?? parent;
    });
    if (new Set(parents).size !== parents.length) throw new Error('改写会折叠 merge 的父节点，已停止。');
    const object = rewriteObject(first, last, parents, group.message);
    const hash = gitBytes(repo, ['hash-object', '-t', 'commit', '-w', '--stdin'], object.raw).toString('utf8').trim();
    const actual = readObject(repo, hash);
    if (
      !actual.raw.equals(object.raw) ||
      actual.tree !== last.tree ||
      JSON.stringify(actual.parents) !== JSON.stringify(parents) ||
      rewritten.has(hash)
    ) {
      throw new Error(`提交内容或拓扑校验失败：${hash}`);
    }
    rewritten.add(hash);
    for (const commit of group.commits) mapping.set(commit.hash, hash);
    groups.push({
      original: group.commits.map((commit) => commit.hash),
      rewritten: hash,
      tree: last.tree,
      parents,
      removedHeaders: object.removedHeaders,
    });
  }
  const after = mapping.get(history.head)!;
  if (readObject(repo, after).tree !== readObject(repo, history.head).tree)
    throw new Error('最终 tree 不一致，未更新分支。');
  return { after, groups };
}

function applyHistory(repo: string, history: History, plan: Group[]) {
  const branch = git(repo, ['rev-parse', '--symbolic-full-name', 'HEAD']).trim();
  assertReady(repo, history.head, branch);
  const result = writeHistory(repo, history, plan);
  const id = `${new Date().toISOString().replace(/[:.]/g, '-')}-${randomUUID()}`;
  const backup = `refs/squash-docs-backup/${id}`;
  const directory = git(repo, ['rev-parse', '--path-format=absolute', '--git-path', 'squash-docs']).trim();
  mkdirSync(directory, { recursive: true });
  const report = join(directory, `${id}.json`);
  // 先落盘映射，再原子更新引用；中途失败不会留下半改写的当前分支。
  writeFileSync(report, `${JSON.stringify({ before: history.head, branch, backup, ...result }, null, 2)}\n`);
  assertOriginalHistory(repo);
  assertReady(repo, history.head, branch);
  gitBytes(
    repo,
    ['update-ref', '-m', 'squash-docs: preserve trees and merge topology', '--stdin'],
    `start\noption no-deref\ncreate ${backup} ${history.head}\nupdate ${branch} ${result.after} ${history.head}\nprepare\ncommit\n`,
  );
  console.log(`备份引用：${backup}\n校验报告：${report}`);
  const removed = result.groups.reduce((sum, group) => sum + group.removedHeaders, 0);
  console.log(`整理完成：${history.commits.length} → ${plan.length}；逐组 tree、父节点顺序和最终 tree 校验通过。`);
  if (removed) console.log(`移除 ${removed} 个失效签名/mergetag header，原对象保留在备份中。`);
  console.log(`撤销：git reset --keep ${backup}`);
}

function main(args: string[]) {
  const options = parseArgs(args);
  if (options.help) {
    console.log(HELP);
    return;
  }
  const repo = git(options.repo, ['rev-parse', '--show-toplevel']).trim();
  const history = readHistory(repo, options.all ? null : options.count);
  const plan = buildPlan(history.commits, options);
  const combined = plan.filter((group) => group.message !== null);
  console.log(
    `仓库：${repo}\nHEAD：${history.head}\n窗口：${history.commits.length} 条；merge：${history.commits.filter((c) => c.parents.length > 1).length}；匹配规则：${options.pattern.source}`,
  );
  if (options.filesPattern) console.log(`全部路径需匹配：${options.filesPattern.source}`);
  if (combined.length === 0) {
    console.log('没有连续匹配的提交，无需改写。');
    return;
  }
  console.log(`计划合并 ${combined.length} 组，提交数 ${history.commits.length} → ${plan.length}：`);
  for (const group of combined) {
    console.log(`\n${group.commits.map((commit) => commit.hash.slice(0, 12)).join(' + ')}\n${group.message}`);
  }
  const changed = rewrittenCommits(plan);
  const branch = git(repo, ['rev-parse', '--symbolic-full-name', 'HEAD']).trim();
  const exclude = branch.startsWith('refs/heads/') ? [`--exclude=${branch.slice('refs/heads/'.length)}`] : [];
  const published = reachableFrom(repo, history.head, changed, ['--remotes']);
  const shared = reachableFrom(repo, history.head, changed, [...exclude, '--branches', '--tags']);
  console.log(`改写范围：${changed.size} 条原提交（合并组及其后代）将获得新哈希。`);
  if (published) {
    console.log(
      `注意：其中 ${published} 条已推送到远程，改写后推送需要 git push --force-with-lease，协作者需重新同步。`,
    );
  }
  if (shared) {
    console.log(`注意：其中 ${shared} 条仍被其他本地分支或标签引用，这些引用不会更新，将继续指向旧历史。`);
  }
  if (options.apply) applyHistory(repo, history, plan);
  else console.log('仅预览，未修改仓库。确认后使用相同参数加 --apply 执行。');
}

if (process.argv[1] && realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url))) {
  try {
    main(process.argv.slice(2));
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
