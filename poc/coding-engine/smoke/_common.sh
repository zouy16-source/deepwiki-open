#!/usr/bin/env bash
# 被各 smoke 脚本 source:载入 .env、设默认值、提供小工具。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$HERE/../.env"
if [ -f "$ENV_FILE" ]; then
  # 只导出简单 KEY=VALUE 行
  set -a; . "$ENV_FILE"; set +a
fi

GATEWAY_URL="${GATEWAY_URL:-http://localhost:4100}"
LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-sk-poc-1234}"
POC_MODEL="${POC_MODEL:-deepseek-chat}"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
ok()  { printf '\033[1;32m OK\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mERR\033[0m %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null || die "需要 curl"
