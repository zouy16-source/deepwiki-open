"""对话式创建需求的 agentic 聊天通道（替代 RAG 通道，SSE）。

RAG 语义检索对精确标识符（camelCase 字段、接口路径）先天失效——consigneeArea 事件的根因。
本通道每轮回答前跑 grep/read_file/list_dir 工具循环（复用 trace_agent.run_tool_loop），
直读本地 clone 最新代码；回答中的 `文件:行号` 引用经 analysis_jobs._verify_citations
机器核验后才下发。SSE 事件：step（工具调用进度）/ answer（最终回答）/ error。
"""

import asyncio
import json
import logging
import os

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.analysis_jobs import _make_llm, _verify_citations
from api.trace_agent import run_tool_loop
from api.trace_tools import repos_root

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatMessage(BaseModel):
    role: str
    content: str


class AgenticChatRequest(BaseModel):
    repo: str                      # 本地 clone 目录名（如 eopl_galaxy-waybill）
    messages: list[ChatMessage]    # 完整对话历史，最后一条为本轮提问


_SYSTEM = """你是仓库 {repo}（服务器本地最新工作树）的代码调查助手，正在与产品经理对话，
帮其确认代码事实、评估改动可行性，以便立项需求。

你有三个工具：grep（全仓搜索）、read_file（带行号读片段）、list_dir（看目录结构）。回答规则：
1. 涉及代码事实的问题（字段/接口/类/逻辑是否存在、在哪、如何实现）**必须先用工具查证再回答**，禁止凭印象；
   标识符类线索（camelCase 字段名、接口路径片段、表名）优先 grep 精确检索，无命中就换变体（驼峰/下划线/去前缀）多试几次；
2. 结论标注来源 `完整相对路径:行号`，路径与行号逐字来自工具返回——系统会逐条机器核验，编造会被标记；
3. 确实查不到时明确说"未找到"，并列出尝试过的搜索词，不要编造；
4. 中文回答，简洁分点，面向产品经理：先给结论，再给依据，避免过度展开技术细节。"""


@router.post("/api/chat/agentic")
async def agentic_chat(body: AgenticChatRequest):
    base = os.path.basename(body.repo.strip())
    root = os.path.join(repos_root(), base)

    async def gen():
        if not base or not os.path.isdir(root):
            yield _sse({"type": "error", "message": f"仓库 {base or '(空)'} 的本地 clone 不存在"})
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
                messages = [{"role": "system", "content": _SYSTEM.format(repo=base)}] + [
                    {"role": m.role, "content": m.content[:6000]} for m in body.messages[-12:]
                ]
                iters = int(os.environ.get("CHAT_AGENT_ITERS", "8"))
                deadline = int(os.environ.get("CHAT_AGENT_DEADLINE_S", "90"))
                answer, steps = await run_tool_loop(
                    llm, model, root, messages,
                    max_iters=iters, deadline_s=deadline,
                    on_step=on_step, log_label=f"chat:{base}",
                )
                verified, ok, bad = _verify_citations(answer, [(base, root)])
                await queue.put({
                    "type": "answer", "content": verified,
                    "tool_calls": len(steps), "cites_ok": ok, "cites_bad": bad,
                })
            except Exception as e:  # noqa: BLE001
                logger.exception("agentic chat failed [%s]", base)
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
