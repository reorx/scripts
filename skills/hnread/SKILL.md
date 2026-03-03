---
name: hnread
description: >-
  Read and analyze Hacker News discussion threads. Fetches an HN thread URL, converts it to
  flat markdown using hn_flat.py, then extracts and presents the most valuable discussion
  insights — critical rebuttals, personal anecdotes, technical corrections, and notable debates.
  Use when the user provides an HN URL and wants a curated summary of the discussion.
---

# HNRead - Hacker News Discussion Analyzer

Fetch a Hacker News discussion thread and extract the most valuable insights from the comments.

## Available Scripts

- **`scripts/hn_flat.py`** — Fetches an HN thread and converts it to flat markdown with nested comment structure.

## Workflow

1. **Receive the HN URL** from the user (e.g., `https://news.ycombinator.com/item?id=12345`)

2. **Fetch and convert** the discussion to markdown:
   ```bash
   uv run scripts/hn_flat.py "<URL>" --no-frontmatter --stdout
   ```
   If the output is very long (large threads), use condensing to reduce noise:
   ```bash
   uv run scripts/hn_flat.py "<URL>" --no-frontmatter --stdout --condense 0.6
   ```

3. **Read the markdown output** and analyze the comments to extract valuable insights.

4. **Present findings** organized into the following categories (skip any category that has no relevant content):

   ### Output Format

   Start with the post title and a one-line summary of what the linked article/post is about (infer from comments if needed).

   Then list insights by category:

   **Critical Rebuttals / Counterarguments**
   — Comments that challenge, critique, or offer counterpoints to the article's claims.

   **Personal Experiences & Anecdotes**
   — First-hand stories or real-world experiences shared by commenters that add context.

   **Technical Insights & Corrections**
   — Technical details, corrections of misconceptions, or deeper explanations.

   **Notable Debates**
   — Back-and-forth exchanges between commenters that surface interesting perspectives.

   **Other Noteworthy Points**
   — Anything else that stands out as valuable, surprising, or thought-provoking.

   For each insight:
   - Write a short summary line describing the point
   - Quote the relevant comment text (use `>` blockquote), attribute it to the author (`@username`)
   - If it's a debate, quote both sides

   Example:

   ```
   **Critical Rebuttals / Counterarguments**

   1. The article's claim about X is misleading — the actual situation is Y.
      > @someuser: "The article completely ignores the fact that..."

   **Notable Debates**

   1. Whether approach A or B is better for large-scale systems.
      > @user1: "In my experience with distributed systems..."
      > @user2: "That's true for small clusters, but at scale..."
   ```

5. **Language**: Present the analysis in the same language the user used when invoking the skill. If the user wrote in Chinese, respond in Chinese. If in English, respond in English.

## Notes

- Focus on quality over quantity — surface 5-15 truly valuable insights rather than listing everything.
- Prefer comments with substance: data, experience, expertise. Skip low-effort reactions.
- When a comment thread builds on itself (A replies to B replies to C), capture the full arc if it's insightful.
- If the thread is very large, use `--condense 0.5` to reduce noise before analysis.
