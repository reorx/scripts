#!/bin/bash
# deck-paste — 把 Mac 剪贴板（或命令行传入的文本）送进 Steam Deck 游戏模式并粘贴
#
# 用法:
#   deck-paste                      # 把 Mac 剪贴板同步到 Deck 剪贴板（默认，只同步）
#   deck-paste "要发的文本"          # 直接发文本，不动 Mac 剪贴板
#   cmd | deck-paste -              # 从管道读（必须显式加 -）
#   deck-paste --paste              # 同步之后再触发一次 Ctrl+V 粘贴
#   deck-paste --type               # 逐字模拟打字（游戏不支持粘贴时用）
#   deck-paste --display :1         # 手动指定目标 X display
#   deck-paste --setup              # 在 Deck 上安装/修复依赖（xclip + gpaste）
#   deck-paste --selftest           # 跑一遍行为自检（SteamOS 更新后建议复验）
#
# 环境变量:
#   DECK_HOST   Deck 的 ssh 目标，默认 deck@steamdeck.local
#
# 前置条件: Mac 能免密 ssh 到 Deck；Deck 处于游戏模式且已聚焦一个输入框。
set -euo pipefail

DECK_HOST="${DECK_HOST:-deck@steamdeck.local}"
REMOTE_GPASTE='$HOME/.local/bin/gpaste'
SSH_OPTS=(-o ConnectTimeout=8 -o BatchMode=yes)

die(){ echo "deck-paste: $*" >&2; exit 1; }

# ---- --setup: 在 Deck 上装依赖（纯用户态，不需要 sudo，不动 steamos-readonly）----
do_setup(){
  echo "==> 检查 Deck 连通性 ($DECK_HOST)"
  ssh "${SSH_OPTS[@]}" "$DECK_HOST" true || die "ssh 连不上 $DECK_HOST"

  echo "==> 安装 xclip 到 ~/.local/bin（免 sudo）"
  ssh "${SSH_OPTS[@]}" "$DECK_HOST" 'bash -se' <<'REMOTE'
set -euo pipefail
mkdir -p ~/.local/bin
if [ -x ~/.local/bin/xclip ]; then echo "    xclip 已存在，跳过"; else
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT; cd "$tmp"
  curl -sSfL --max-time 20 https://archlinux.org/packages/extra/x86_64/xclip/json/ > m.json
  ver=$(python3 -c "import json;d=json.load(open('m.json'));print(d['pkgver']+'-'+d['pkgrel'])")
  curl -sSfL --max-time 60 -o p.tar.zst \
    "https://geo.mirror.pkgbuild.com/extra/os/x86_64/xclip-${ver}-x86_64.pkg.tar.zst"
  tar --use-compress-program=unzstd -xf p.tar.zst usr/bin/xclip
  install -m755 usr/bin/xclip ~/.local/bin/xclip
  echo "    装好 xclip $ver"
fi
command -v xdotool >/dev/null || echo "    !! 系统缺 xdotool，自动粘贴不可用（--no-key 仍可用）"
REMOTE

  echo "==> 部署 gpaste 到 Deck"
  # gpaste 正文内嵌在本脚本末尾的 __GPASTE__ 段里，保持单文件自包含
  sed -n '/^# ---8<--- GPASTE BEGIN/,/^# ---8<--- GPASTE END/p' "${BASH_SOURCE[0]}" \
    | sed '1d;$d' | sed 's/^#GP//' \
    | ssh "${SSH_OPTS[@]}" "$DECK_HOST" \
        'mkdir -p ~/.local/bin && cat > ~/.local/bin/gpaste && chmod +x ~/.local/bin/gpaste'
  echo "==> 完成。试一下:  deck-paste   (只同步剪贴板)"
}

# ---- --selftest: 行为自检 ----
do_selftest(){
  set +e; trap 'set -e' RETURN        # 自检里有预期失败的用例，不能让 errexit 打断
  local G='$HOME/.local/bin/gpaste' X='$HOME/.local/bin/xclip'
  local pass=0 faile=0 T r b a rc st el
  local saved; saved=$(pbpaste 2>/dev/null || true)
  ok(){ echo "  ✓ $1"; pass=$((pass+1)); }
  ng(){ echo "  ✗ $1 — 实际: $2"; faile=$((faile+1)); }
  rb(){ ssh "${SSH_OPTS[@]}" "$DECK_HOST" "DISPLAY=${1:-:0} $X -selection clipboard -o" 2>/dev/null; }
  ctr(){ ssh "${SSH_OPTS[@]}" "$DECK_HOST" 'DISPLAY=:0 xprop -root GAMESCOPE_INPUT_COUNTER' 2>/dev/null | grep -oE '[0-9]+$'; }

  echo "== 剪贴板同步 =="
  T="st-$RANDOM"; printf '%s' "$T" | ssh "${SSH_OPTS[@]}" "$DECK_HOST" "$G -q" >/dev/null 2>&1
  r=$(rb :0); [ "$r" = "$T" ] && ok "写入后 :0 可读回" || ng "写入后 :0 可读回" "$r"
  r=$(rb :1); [ "$r" = "$T" ] && ok ":1 同步（游戏所在 display）" || ng ":1 同步" "$r"

  echo "== 编码 =="
  T='中文 émoji 🎮 CODE-123'
  printf '%s' "$T" | ssh "${SSH_OPTS[@]}" "$DECK_HOST" "$G -q" >/dev/null 2>&1
  r=$(rb :0); [ "$r" = "$T" ] && ok "中文/emoji 不乱码" || ng "中文/emoji" "$r"
  T=$(printf 'l1\nl2\tTAB')
  printf '%s' "$T" | ssh "${SSH_OPTS[@]}" "$DECK_HOST" "$G -q" >/dev/null 2>&1
  r=$(rb :0); [ "$r" = "$T" ] && ok "多行/制表符保持原样" || ng "多行" "$(printf '%s' "$r" | od -c | head -1)"

  echo "== 健壮性 =="
  st=$(date +%s)
  printf 'x' | ssh "${SSH_OPTS[@]}" "$DECK_HOST" "$G -q" >/dev/null 2>&1 &
  local pid=$! i=0
  while [ $i -lt 50 ] && kill -0 $pid 2>/dev/null; do sleep 0.2; i=$((i+1)); done
  if kill -0 $pid 2>/dev/null; then kill $pid 2>/dev/null; el=10; else wait $pid; el=$(( $(date +%s) - st )); fi
  [ $el -lt 5 ] && ok "SSH 不挂起 (${el}s)" || ng "SSH 挂起" "${el}s"
  printf '' | ssh "${SSH_OPTS[@]}" "$DECK_HOST" "$G -q" >/dev/null 2>&1
  [ $? -ne 0 ] && ok "空输入报错退出" || ng "空输入" "却返回 0"
  T="st-persist-$RANDOM"
  printf '%s' "$T" | ssh "${SSH_OPTS[@]}" "$DECK_HOST" "$G -q" >/dev/null 2>&1
  ssh "${SSH_OPTS[@]}" "$DECK_HOST" 'pkill -u deck -x xclip' 2>/dev/null; sleep 1
  r=$(rb :0); [ "$r" = "$T" ] && ok "xclip 退出后内容仍在（无常驻进程）" || ng "内容丢失" "$r"

  echo "== 按键投递 =="
  b=$(ctr); printf 'k' | ssh "${SSH_OPTS[@]}" "$DECK_HOST" "$G -q" >/dev/null 2>&1; sleep 0.6; a=$(ctr)
  [ "$a" = "$b" ] && ok "默认模式零按键 (counter=$b)" || ng "默认模式误发按键" "$b -> $a"
  b=$(ctr); printf 'k' | ssh "${SSH_OPTS[@]}" "$DECK_HOST" "$G -q --paste" >/dev/null 2>&1; sleep 0.6; a=$(ctr)
  { [ -n "$b" ] && [ -n "$a" ] && [ "$a" -gt "$b" ]; } && ok "--paste 确实发出按键 ($b -> $a)" || ng "--paste 未发按键" "$b -> $a"

  echo "== Mac 端入口 =="
  T="st-arg-$RANDOM"; "${BASH_SOURCE[0]}" -q -- "$T" >/dev/null 2>&1
  r=$(rb :0); [ "$r" = "$T" ] && ok "命令行传参" || ng "命令行传参" "$r"
  T="st-pb-$RANDOM"; printf '%s' "$T" | pbcopy; "${BASH_SOURCE[0]}" -q >/dev/null 2>&1
  r=$(rb :0); [ "$r" = "$T" ] && ok "默认读 pbpaste" || ng "默认读 pbpaste" "$r"
  T="st-pipe-$RANDOM"; printf '%s' "$T" | "${BASH_SOURCE[0]}" -q - >/dev/null 2>&1
  r=$(rb :0); [ "$r" = "$T" ] && ok "显式管道 -" || ng "管道 -" "$r"

  [ -n "$saved" ] && printf '%s' "$saved" | pbcopy
  echo; echo "结果: $pass 通过, $faile 失败"
  [ $faile -eq 0 ]
}

args=(); text=""; use_stdin_text=0; read_stdin=0
while [ $# -gt 0 ]; do
  case "$1" in
    --setup) do_setup; exit 0 ;;
    --selftest) do_selftest; exit $? ;;
    --paste|--no-key|--type|--quiet|-q) args+=("$1") ;;
    --display) args+=("$1" "$2"); shift ;;
    --display=*) args+=("$1") ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -|--stdin) read_stdin=1 ;;
    --) shift; text="$*"; use_stdin_text=1; break ;;
    -*) die "未知选项 $1" ;;
    *)  text="$*"; use_stdin_text=1; break ;;
  esac
  shift
done

# 输入来源是显式约定，不靠猜 stdin 是不是 tty（那在脚本/cron 里会静默取到空）
if [ "$use_stdin_text" = 1 ]; then
  payload(){ printf '%s' "$text"; }
elif [ "$read_stdin" = 1 ]; then
  payload(){ cat; }                 # 显式: echo x | deck-paste -
else
  payload(){ pbpaste; }             # 默认: Mac 剪贴板
fi

out=$(payload | ssh "${SSH_OPTS[@]}" "$DECK_HOST" "$REMOTE_GPASTE ${args[*]:-}" 2>&1) || {
  echo "$out" >&2
  case "$out" in
    *"找不到 xclip"*|*"No such file"*) echo "deck-paste: 依赖没装好，跑一次: deck-paste --setup" >&2 ;;
  esac
  exit 1
}
[ -n "$out" ] && echo "$out" >&2
exit 0

# ---8<--- GPASTE BEGIN
#GP#!/bin/bash
#GP# gpaste — 把 stdin 的文本送进 Steam Deck 游戏模式的剪贴板并粘贴
#GP#
#GP# 用法:  echo "文本" | ~/.local/bin/gpaste [选项]
#GP#   (无选项)        只把内容写进 Deck 剪贴板（安全默认，不碰任何按键）
#GP#   --paste         写完剪贴板后，额外发一次 Ctrl+V 触发粘贴
#GP#   --type          不用剪贴板，用 xdotool 逐字模拟打字（适合不支持粘贴的游戏）
#GP#   --display :N    手动指定按键发往哪个 X display（默认自动判断）
#GP#   --quiet         不输出诊断信息
#GP#
#GP# 设计要点（都经实测验证）:
#GP#   * gamescope 在 :0 / :1 两个 Xwayland 之间会同步剪贴板，写一边两边都有
#GP#   * gamescope 会接管 selection，xclip 退出后内容仍在，所以不留常驻进程，SSH 不会挂
#GP#   * 不需要 XAUTHORITY，gamescope 的 Xwayland 不校验 auth
#GPset -uo pipefail
#GP
#GPXCLIP="${XCLIP:-$HOME/.local/bin/xclip}"
#GPcommand -v "$XCLIP" >/dev/null 2>&1 || XCLIP=$(command -v xclip 2>/dev/null)
#GP
#GPmode=clip; want_display=""; quiet=0
#GPwhile [ $# -gt 0 ]; do
#GP  case "$1" in
#GP    --paste)   mode=paste ;;
#GP    --no-key)  mode=clip ;;          # 兼容旧写法，等同默认
#GP    --type)    mode=type ;;
#GP    --display) want_display="$2"; shift ;;
#GP    --display=*) want_display="${1#*=}" ;;
#GP    --quiet|-q) quiet=1 ;;
#GP    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
#GP    *) echo "gpaste: 未知选项 $1" >&2; exit 2 ;;
#GP  esac
#GP  shift
#GPdone
#GPlog(){ [ "$quiet" = 1 ] || echo "gpaste: $*" >&2; }
#GP
#GP# ---- 读输入 ----
#GPtext=$(cat)
#GP[ -n "$text" ] || { echo "gpaste: 输入为空" >&2; exit 1; }
#GP
#GP# ---- 选择目标 display ----
#GP# 游戏跑在 :1，Steam UI 在 :0。:1 上只有 steamcompmgr 说明没游戏在前台。
#GPpick_display(){
#GP  [ -n "$want_display" ] && { echo "$want_display"; return; }
#GP  local n
#GP  n=$(DISPLAY=:1 xdotool search --onlyvisible --name '.' 2>/dev/null \
#GP      | while read -r w; do DISPLAY=:1 xdotool getwindowname "$w" 2>/dev/null; done \
#GP      | grep -vc '^steamcompmgr$')
#GP  if [ "${n:-0}" -gt 0 ]; then echo ":1"; else echo ":0"; fi
#GP}
#GPD=$(pick_display)
#GPlog "目标 display = $D"
#GP
#GP# ---- 打字模式：不碰剪贴板 ----
#GPif [ "$mode" = type ]; then
#GP  command -v xdotool >/dev/null || { echo "gpaste: 缺 xdotool" >&2; exit 1; }
#GP  DISPLAY=$D xdotool type --clearmodifiers --delay 30 -- "$text" || exit 1
#GP  log "已模拟输入 ${#text} 字符"
#GP  exit 0
#GPfi
#GP
#GP# ---- 写剪贴板 ----
#GP[ -n "$XCLIP" ] || { echo "gpaste: 找不到 xclip" >&2; exit 1; }
#GPfor sel in clipboard primary; do            # primary 一并写，兼容中键粘贴的程序
#GP  printf '%s' "$text" | DISPLAY=$D $XCLIP -selection "$sel" >/dev/null 2>&1 &
#GPdone
#GPsleep 0.3
#GP
#GP# 读回校验（gamescope 已接管 selection，此时 xclip 可以退场）
#GPgot=$(DISPLAY=$D timeout 3 "$XCLIP" -selection clipboard -o 2>/dev/null)
#GPif [ "$got" != "$text" ]; then
#GP  echo "gpaste: 剪贴板校验失败" >&2
#GP  exit 1
#GPfi
#GPlog "剪贴板已写入 ${#text} 字符 ✓"
#GP
#GP[ "$mode" = paste ] || exit 0       # 默认到此为止，只写剪贴板
#GP
#GP# ---- 发送 Ctrl+V（仅 --paste）----
#GPcommand -v xdotool >/dev/null || { echo "gpaste: 缺 xdotool，无法自动粘贴（去掉 --paste 仍可写剪贴板）" >&2; exit 1; }
#GPDISPLAY=$D xdotool key --clearmodifiers ctrl+v || exit 1
#GPlog "已发送 Ctrl+V 到 $D"
# ---8<--- GPASTE END
