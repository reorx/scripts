---
created: 2026-10-22
tags:
  - skills
  - hnread
  - hacker-news
  - scraping
---

# hnread：查清 HN 返回 419 的原因，加上 curl → requests → Algolia 自动回退，并修正评论树

## 概要

一个 agent 反馈 hnread 的脚本被 HN 拒绝（HTTP 419），而 curl 正常。对照测试表明，原因不是 Python 本身：python-requests 带浏览器 User-Agent 时 HN 才返回 419；requests 用自己的 UA、或者 curl 带任意 UA，都能正常拿到页面。用户的方案是加 curl 模式并设为默认，后来又要求脚本自己处理失败。最终 `hn_flat.py` 默认用 `--fetcher auto`，依次尝试 curl、requests、Algolia HN API。HN 返回 200 但页面里没有帖子，也算失败。Algolia 返回整棵评论树，但顺序按 id；再发一次 Firebase 请求，恢复 HN 的顶层排名。在一个 3000 多条评论的帖子上对比两条路径时，发现 HN 页面路径原有两个问题：已删除评论的回复会挂到上一条无关评论下；低分评论只过滤了一档灰色。按用户“低分要过滤掉”的决定，两个都修了。修复后，HN 页面路径和 HN 默认视图一致；它显示的评论，除 1 条外 Algolia 都有。SKILL.md 也加上了批量调用的约束：一次只抓一个帖子，间隔至少 30 秒。

## 修改的文件

- `skills/hnread/scripts/hn_flat.py`：
  - 新增 `--fetcher {auto,curl,requests,algolia}`，auto 依次回退，全部失败时给出提示并以退出码 1 结束；
  - requests 不再伪造浏览器 UA；连接超时设为 10 秒；
  - 新增 Algolia 加 Firebase 排名的抓取；Algolia 的结果缓存为 `.json`；
  - `parse_comments` 和 `build_comment_tree` 改为保留被删、低分评论的占位，让它们的回复顶替原位置；`noshow` 行直接丢弃；
  - `is_flagged_comment` 改为 `is_low_score_comment`，匹配所有非 `c00` 的灰度 class。
- `skills/hnread/scripts/test_hn_flat.py`（新建）：14 个 CLI 行为测试，用本地服务器分别模拟 HN 页面、Algolia 和 Firebase。
- `skills/hnread/SKILL.md`：说明自动回退、内容来自 Algolia 时怎么理解，以及批量调用的间隔和 `--cache-dir`。
- `AGENTS.md`：新增 Hacker News threads 一节，写明 UA 的坑、两条路径的过滤规则和测试命令。
- `kb/known-issues.md`：先登记、后删除两条 hnread 条目。

## 注意事项

- HN 的 robots.txt 写着 `Crawl-delay: 30`，批量抓取的间隔以此为准。
- HN 会把被 flag 或 dead 的评论折叠（行上带 `coll`），它下面的回复带 `noshow`，浏览器默认不显示。3000 条评论的帖子里有 425 行属于这种情况。评论被踩时，HN 会给 `commtext` 加灰度 class（实测有 `c73`、`c88`），这类评论不会折叠，回复照常显示。
- Algolia 的评论没有分数（`points` 为 null），也没有 flag 信息（`options` 为空），所以 Algolia 路径无法过滤低分评论，还会带上一部分 HN 隐藏的回复。脚本会在 stderr 提示这一点。
- Firebase 根节点的 `kids` 去掉 dead 评论后，和 HN 页面的顶层顺序完全一致，一次请求就能恢复排名。嵌套回复要恢复排名得每条评论发一次请求，所以没做。
- HN 的大帖子不分页：3000 多条评论都在一个 4.6MB 的页面里。
- `~/.agents` 下的副本是 hardlink。Edit 工具和 cc-format 写文件时会换 inode，`skm install` 随后会把副本判成非托管。先确认副本和改动前的版本一致，再删掉副本、重跑 `skm install`。

## 遗留问题

- `skm install` 仍然卡在 `~/.agents/skills/herdr-coordinator` 的覆盖确认上，与本次改动无关，需要用户在终端里处理。
- `fetch_from_algolia()` 里用 try/except 包住了 Firebase 排名请求：排名失败时只打印警告，保留时间顺序。这偏离了“只在顶层处理错误”的约定，属于有意为之。

## 已解决的已知问题

- **hnread：已删除评论的回复会被挂到上一条无关评论下面（HN 页面路径）**：被删和低分的评论现在以占位形式参与建树，它们的回复顶替原来的位置；HN 默认隐藏的 `noshow` 行直接丢弃。有测试覆盖。大帖子实测：@kcb 那条挂错的回复已不在输出里，HN 页面路径和 Algolia 的差异从 194 条降到 1 条。
- **hnread：被踩灰的评论只跳过 `c73` 一档，更灰的 `c88` 反而保留**：按用户决定过滤所有低分评论，改为匹配所有非 `c00` 的灰度 class，有测试覆盖（`c5a`、`c73`、`c88`）。
