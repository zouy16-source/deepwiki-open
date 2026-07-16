#!/usr/bin/env bash
# 列出网关对外暴露的模型(证明网关起来了、配置被加载)。
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

say "GET $GATEWAY_URL/v1/models"
curl -fsS "$GATEWAY_URL/v1/models" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  || die "网关无响应——先 docker compose up -d,再看 docker logs poc-coding-gateway"
echo
ok "网关在线,上面是可用 model_name 列表"
