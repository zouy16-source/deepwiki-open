#!/usr/bin/env bash
# Anthropic 兼容端点连通验证 —— 覆盖 Claude Code Runtime 的传输协议。
# LiteLLM proxy 原生暴露 POST /v1/messages(Anthropic 格式),把请求翻译到国产后端。
# 这正是 Claude Code 设 ANTHROPIC_BASE_URL 后打的那个端点。
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

say "POST $GATEWAY_URL/v1/messages   (model=$POC_MODEL, Anthropic 格式)"

payload=$(cat <<JSON
{
  "model": "$POC_MODEL",
  "max_tokens": 512,
  "messages": [
    {"role": "user", "content": "只回一个词:pong"}
  ]
}
JSON
)

resp=$(curl -fsS "$GATEWAY_URL/v1/messages" \
  -H "x-api-key: $LITELLM_MASTER_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d "$payload") || die "Anthropic 端点调用失败——确认 model_name 存在于配置,且 Claude Code 侧 ANTHROPIC_MODEL 指向它"

echo "$resp"
echo
# Anthropic 响应体应含 "type":"message" 与 content 块
echo "$resp" | grep -q '"content"' && ok "Anthropic 兼容端点连通(Claude Code 走这条)" \
  || die "响应异常,未见 content——若报 model not found: claude-xxx,把该名字加成配置里的别名"
