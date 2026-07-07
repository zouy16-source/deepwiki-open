"""极简 MCP server（Streamable HTTP / JSON-RPC，无状态）。

把字段追溯的三个代码检索工具（trace_tools.py）+ list_repos 暴露给开发者的
Cursor / Claude Code 等 MCP 客户端，直连后端即可检索服务器上的本地 clone：

    claude mcp add --transport http deepwiki-trace http://<host>:8001/mcp

刻意不引入官方 mcp SDK：协议面只需 initialize / tools/list / tools/call 三个方法，
无状态 JSON 响应即为规范允许的最小实现（不提供 SSE 流，GET 返回 405）；
省一个依赖 = 不动 poetry.lock、不加 Docker 构建变数。
"""

import logging
import os

from fastapi import APIRouter, Request, Response

from api import trace_tools

logger = logging.getLogger(__name__)
router = APIRouter()

PROTOCOL_VERSION = "2025-03-26"
SERVER_INFO = {"name": "deepwiki-trace", "version": "2.0.0"}

# tools/list 返回的工具定义：在 TOOLS_SPEC 基础上加 repo 参数（MCP 客户端跨仓库使用）
_REPO_PARAM = {"repo": {"type": "string", "description": "仓库 clone 名（owner_repo 形式），先用 list_repos 查看可选值"}}
MCP_TOOLS = [{
    "name": "list_repos",
    "description": "列出服务器上可检索的仓库（本地 clone）。其余工具的 repo 参数取这里返回的名字。",
    "inputSchema": {"type": "object", "properties": {}, "required": []},
}] + [{
    "name": t["function"]["name"],
    "description": t["function"]["description"],
    "inputSchema": {
        "type": "object",
        "properties": {**_REPO_PARAM, **t["function"]["parameters"]["properties"]},
        "required": ["repo"] + t["function"]["parameters"].get("required", []),
    },
} for t in trace_tools.TOOLS_SPEC]


def _call_tool(name: str, args: dict) -> str:
    if name == "list_repos":
        repos = trace_tools.list_repos()
        return "\n".join(repos) or "（服务器上没有任何 clone）"
    root = os.path.join(trace_tools.repos_root(), os.path.basename(str(args.get("repo") or "")))
    if not os.path.isdir(root):
        return f"（错误：仓库不存在 {args.get('repo')}，用 list_repos 查看可选值）"
    return trace_tools.dispatch(root, name, args)


def _handle_rpc(body: dict):
    """处理单条 JSON-RPC 消息；通知（无 id）返回 None。"""
    method, msg_id, params = body.get("method", ""), body.get("id"), body.get("params") or {}
    if msg_id is None:  # notification（如 notifications/initialized）
        return None
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": MCP_TOOLS}}
    if method == "tools/call":
        name, args = params.get("name", ""), params.get("arguments") or {}
        try:
            text = _call_tool(name, args)
            is_err = text.startswith("（错误")
        except Exception as e:  # noqa: BLE001
            logger.exception(f"MCP 工具执行失败: {name}")
            text, is_err = f"（错误：{e}）", True
        return {"jsonrpc": "2.0", "id": msg_id, "result": {
            "content": [{"type": "text", "text": text}], "isError": is_err}}
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}}


@router.post("/mcp")
async def mcp_endpoint(request: Request, response: Response):
    try:
        body = await request.json()
    except Exception:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
    # 兼容 2025-03-26 的 batch 形式
    if isinstance(body, list):
        results = [r for r in (_handle_rpc(m) for m in body if isinstance(m, dict)) if r]
        if not results:
            response.status_code = 202
            return Response(status_code=202)
        return results
    result = _handle_rpc(body if isinstance(body, dict) else {})
    if result is None:
        return Response(status_code=202)
    return result


@router.get("/mcp")
async def mcp_get():
    # 不提供服务端主动 SSE 流（规范允许）
    return Response(status_code=405)
