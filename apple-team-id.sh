#!/bin/bash
# apple-team-id — 从钥匙串的 Apple 签名证书里提取开发者 Team ID
# （新版 Xcode 的 Accounts 界面不显示 Team ID，用这个脚本查）
#
# 用法：
#   apple-team-id        # 列出所有团队：Team ID、团队名、证书类型
#   apple-team-id -q     # 只输出 Team ID（每行一个），便于 TEAM_ID=$(apple-team-id -q)
#
# 原理：`security find-identity` 找出钥匙串里有私钥、可用于签名的证书，
# 再用 openssl 读证书 subject —— OU 字段就是 Team ID，O 字段是团队名。
set -euo pipefail

quiet=0
if [[ "${1:-}" == "-q" ]]; then
  quiet=1
elif [[ -n "${1:-}" ]]; then
  sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
fi

# 可用签名身份的证书 CN，形如 "Apple Development: xx@yy.com (XXXXXXXXXX)"
cns=$(security find-identity -v -p codesigning 2>/dev/null \
  | sed -n 's/^ *[0-9][0-9]*) [0-9A-F]* "\(.*\)"$/\1/p' | sort -u)

if [[ -z "$cns" ]]; then
  echo "error: 钥匙串里没有可用的 Apple 签名证书。" >&2
  echo "       先在 Xcode → Settings → Accounts 登录 Apple ID，再到" >&2
  echo "       Manage Certificates… 创建一张 Apple Development 证书。" >&2
  exit 1
fi

# 每行：TeamID <TAB> 团队名 <TAB> 证书类型
rows=$(while IFS= read -r cn; do
  subject=$(security find-certificate -c "$cn" -p 2>/dev/null \
    | openssl x509 -noout -subject -nameopt multiline 2>/dev/null) || continue
  ou=$(sed -n 's/^ *organizationalUnitName *= *//p' <<<"$subject" | head -1)
  o=$(sed -n 's/^ *organizationName *= *//p' <<<"$subject" | head -1)
  # Team ID 固定为 10 位大写字母数字；不匹配的（如自签证书）跳过
  [[ "$ou" =~ ^[A-Z0-9]{10}$ ]] || continue
  printf '%s\t%s\t%s\n' "$ou" "$o" "${cn%%:*}"
done <<<"$cns" | sort -u)

if [[ -z "$rows" ]]; then
  echo "error: 找到了签名证书，但没有一张带 Team ID（OU 字段）。" >&2
  exit 1
fi

if [[ $quiet == 1 ]]; then
  cut -f1 <<<"$rows" | sort -u
else
  awk -F'\t' '
    !($1 in name) { order[++n] = $1; name[$1] = $2 }
    certs[$1] !~ $3 { certs[$1] = certs[$1] ? certs[$1] ", " $3 : $3 }
    END {
      printf "%s\t%s\t%s\n", "TEAM ID", "TEAM NAME", "CERTIFICATES"
      for (i = 1; i <= n; i++) {
        t = order[i]
        printf "%s\t%s\t%s\n", t, name[t], certs[t]
      }
    }' <<<"$rows" | column -t -s $'\t'
fi
