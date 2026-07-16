#!/usr/bin/env bash
# OpenAI 兼容端点连通验证 —— 覆盖 OpenHands / Aider / SWE-agent 的传输协议。
# 让模型对一段代码做个 hello-world 级"改动",顺带看它能否按指令产出 diff。
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_common.sh"

say "POST $GATEWAY_URL/v1/chat/completions   (model=$POC_MODEL)"

payload=$(cat <<JSON
{
  "model": "$POC_MODEL",
  "messages": [
    {"role": "system", "content": "你是编码助手。只输出统一 diff(unified diff),不要解释。"},
    {"role": "user", "content": "给 hello.py 增加一个 main 保护:\n\n    def hello():\n        print(\"hi\")\n\n请输出把它改成 `if __name__ == \"__main__\": hello()` 的 diff。"}
  ],
  "temperature": 0
}
JSON
)

resp=$(curl -fsS "$GATEWAY_URL/v1/chat/completions" \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d "$payload") || die "OpenAI 端点调用失败——检查 KEY / model_name / 网关日志"

echo "$resp"
echo
# 粗略判定:返回里应有 choices/content
echo "$resp" | grep -q '"content"' && ok "OpenAI 兼容端点连通(OpenHands/Aider/SWE-agent 走这条)" \
  || die "响应异常,未见 content 字段"
