"""对话式创建需求的 agentic 聊天通道（多仓库自主路由，SSE）。

一个业务系统常横跨多个仓库（如银河开单 = 后端 + 前端）。本通道把项目绑定的全部仓库
交给 agent，grep/read_file/list_dir 都带 repo 参数，system prompt 注入各仓库简介
（自动识别前端/后端）——agent 自己判断该查哪个仓库（问接口去后端、问交互去前端），
无需用户预选。工具循环复用 trace_agent.run_tool_loop，回答中的 文件:行号 引用经机器核验。

SSE 事件：step（工具调用进度，含 repo）/ answer（最终回答）/ error。
RAG 语义检索对精确标识符失效（consigneeArea 事件），故不用 RAG；wiki Ask 仍走 RAG。
"""

import asyncio
import copy
import json
import logging
import os

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api import trace_tools
from api.analysis_jobs import _make_llm, _verify_citations
from api.trace_agent import run_tool_loop
from api.trace_tools import TOOLS_SPEC, repos_root

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class AgenticChatRequest(BaseModel):
    repos: list[str]               # 项目绑定的本地 clone 目录名集合（agent 自主在其间路由）
    messages: list[ChatMessage]    # 完整对话历史，最后一条为本轮提问


# 识别标志文件 → 仓库类型简介（让 agent 一眼看出前端/后端，无需额外探测轮次）
def _repo_brief(root: str) -> str:
    try:
        entries = set(os.listdir(root))
    except OSError:
        return "（无法读取）"
    has = lambda *fs: any(f in entries for f in fs)  # noqa: E731
    if has("pom.xml") or has("build.gradle", "settings.gradle"):
        return "Java/JVM 后端（Maven/Gradle 多模块）"
    if has("nuxt.config.js", "nuxt.config.ts"):
        return "Nuxt 前端"
    if has("next.config.js", "next.config.ts", "next.config.mjs"):
        return "Next.js 前端"
    if has("go.mod"):
        return "Go 后端"
    if has("pyproject.toml", "requirements.txt", "setup.py"):
        return "Python 服务"
    if has("package.json"):
        return "Node/前端"
    # 兜底：列几个顶层目录帮助判断
    dirs = sorted(d for d in entries if os.path.isdir(os.path.join(root, d)) and not d.startswith("."))[:6]
    return "结构：" + "、".join(dirs) if dirs else "（空/未知）"


def _resolve_repos(repo_names: list[str]) -> dict[str, str]:
    """clone 目录名 → 绝对路径（仅保留本地存在的），防路径逃逸。"""
    root = repos_root()
    out: dict[str, str] = {}
    for name in repo_names:
        base = os.path.basename(str(name).strip())
        if not base:
            continue
        p = os.path.join(root, base)
        if os.path.isdir(p):
            out[base] = p
    return out


def _build_tools_spec(repo_names: list[str]) -> list[dict]:
    """在单仓库 TOOLS_SPEC 基础上，给每个工具加必填 repo 参数（自主路由的关键）。"""
    spec = copy.deepcopy(TOOLS_SPEC)
    for tool in spec:
        fn = tool["function"]
        props = fn["parameters"]["properties"]
        props["repo"] = {
            "type": "string",
            "enum": repo_names,
            "description": "在哪个仓库执行（必填）。按问题选择：接口/存储/业务逻辑通常在后端仓库，页面/交互/样式在前端仓库。",
        }
        fn["parameters"]["required"] = ["repo"] + fn["parameters"].get("required", [])
    return spec


def _make_dispatch(roots: dict[str, str]):
    """多仓库分发：按 args.repo 定位 root，转调单仓库 dispatch；repo 非法则回可读错误让 agent 自纠。"""
    def dispatch(name: str, args: dict) -> str:
        # 用 get 不 pop：保留 repo 供进度轨迹展示；trace_tools.dispatch 只读特定键、无视 repo
        repo = os.path.basename(str(args.get("repo", "")).strip())
        root = roots.get(repo)
        if root is None:
            return f"（错误：仓库 '{repo}' 不可用；可用仓库：{'、'.join(roots)}）"
        return trace_tools.dispatch(root, name, args)
    return dispatch


def _system_prompt(roots: dict[str, str]) -> str:
    lines = [f"- {name}：{_repo_brief(root)}" for name, root in roots.items()]
    return f"""你是「{'、'.join(roots)}」这一业务系统的代码调查助手，正在与产品经理对话，
帮其确认代码事实、评估改动可行性，以便立项需求。该系统包含以下仓库（服务器本地最新工作树）：

{chr(10).join(lines)}

你有三个工具：grep、read_file、list_dir——每次调用都要指定 repo（在哪个仓库操作）。回答规则：
1. **自主路由**：按问题性质选仓库——接口/服务/存储/业务逻辑查后端仓库，页面/组件/交互/样式查前端仓库；
   涉及前后端联动（如"某字段前端怎么展示、后端怎么存"）就分别在两个仓库检索；
2. 涉及代码事实的问题**必须先用工具查证再回答**，禁止凭印象；标识符（camelCase 字段、接口路径、表名）优先精确 grep，无命中换变体多试；
3. 结论标注来源 `完整相对路径:行号`（并注明所在仓库），路径与行号逐字来自工具返回——系统会机器核验，编造会被标记；
4. 确实查不到时明确说"未找到"并列出尝试过的搜索词，不编造；
5. 中文回答，面向产品经理：先给结论、再给依据，避免过度铺陈技术细节。"""


@router.post("/api/chat/agentic")
async def agentic_chat(body: AgenticChatRequest):
    roots = _resolve_repos(body.repos)

    async def gen():
        if not roots:
            yield _sse({"type": "error", "message": "项目未绑定可用的本地代码库"})
            return
        if not body.messages or body.messages[-1].role != "user":
            yield _sse({"type": "error", "message": "最后一条消息必须是用户提问"})
            return

        queue: asyncio.Queue = asyncio.Queue()

        async def on_step(step: dict):
            await queue.put({"type": "step", **step})

        async def produce():
            try:
                llm, model = _make_llm()
                model = os.environ.get("CHAT_AGENT_MODEL", model)
                messages = [{"role": "system", "content": _system_prompt(roots)}] + [
                    {"role": m.role, "content": m.content[:6000]} for m in body.messages[-12:]
                ]
                iters = int(os.environ.get("CHAT_AGENT_ITERS", "10"))
                deadline = int(os.environ.get("CHAT_AGENT_DEADLINE_S", "120"))
                answer, steps = await run_tool_loop(
                    llm, model, root="", messages=messages,
                    max_iters=iters, deadline_s=deadline,
                    on_step=on_step, log_label=f"chat:{'+'.join(roots)}",
                    tools_spec=_build_tools_spec(list(roots)),
                    dispatch_fn=_make_dispatch(roots),
                )
                # 引用核验：对项目全部仓库的并集校验 文件:行号
                verified, ok, bad = _verify_citations(answer, list(roots.items()))
                await queue.put({
                    "type": "answer", "content": verified,
                    "tool_calls": len(steps), "cites_ok": ok, "cites_bad": bad,
                })
            except Exception as e:  # noqa: BLE001
                logger.exception("agentic chat failed [%s]", "+".join(roots))
                await queue.put({"type": "error", "message": str(e)})
            finally:
                await queue.put(None)

        task = asyncio.create_task(produce())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield _sse(item)
        finally:
            task.cancel()

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
    })


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"
