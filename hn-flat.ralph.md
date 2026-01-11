write a script called hn-flat.py, it should be called by uv to run. if it needs external deps like bs4, define them in metadata comment.

this script should fetch the html of a given hacker news url, parse it, and convert the discussions in a structured data (a comments tree).

the goal is to generate formatted text in markdown list format easy for human to read the discussions. by default write to `hn.<id>.md`, use `-o` to specify out file path. a sample is like this:

<example>
- @alam [+2]: Kind of wild that a private company has that kind of power, both in terms of being one of the few that can offer this service and they can make threats at this level.
  I'm pretty sure if you tried that here (Canada) it would do the latter.
  - @dan: Would a regulating body in Canada do this, though?
  - @will: Also I feel like threatening to take your toys and go home when they don't play fair is a totally valid response.
- @bobby: It's a great description of one of the main tactics the administration he is asking for help uses though. Which again goes to Cloudflare
entirely abandoning the moral high ground here.
</example>

`[+2]` means the comment has two children. it only shows when the amount of children >= 1.

if a div.comment has direct child <div class="commtext c73">, it means its a comment flagged as inappropriate, they (and their children comments) should be omitted when generating markdown list.

`--condense <rate>`: this option is for condense the comments if the whole thread is too large. `<rate>` is the goal of the length of the condensed result divides the length of the original result. the logic is like this: in a while true loop, remove comment that has least weight (weight = children_count * comment_length / 10), then calculate the rate = modified comments tree result length / original comments tree result length, break if the rate >= target rate.


you should test the script with this url https://news.ycombinator.com/item?id=46555760
