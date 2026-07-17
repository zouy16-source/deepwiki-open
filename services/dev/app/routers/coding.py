"""编码任务分发 + 进度 SSE(内部端点,requirement 服务 / BFF 调用)。

模式对齐 requirement 的 analysis:重异步任务在本服务后台跑,终态经 callback_url 回写。
    POST /internal/coding/dispatch          → 202,后台 RuntimeDispatcher.dispatch,完成回调 callback_url
    GET  /internal/coding/runs/{id}/events   → SSE 实时进度(前端经 BFF 订阅,让 PM 点一下就看到跑)

进度存进程内 RunChannel(run_id → 事件列表 + 终态),SSE 游标式读取。起步 Claude Code(直连
Claude API,需 ANTHROPIC_API_KEY);开 MR 走 GitLab(需 GITLAB_TOKEN)。
"""

import asyncio
import json
import logging

import httpx
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..coding import (
    ClaudeCodeWorker,
    CodingTask,
    GitLabGitOps,
    ProgressEvent,
    RuntimeDispatcher,
    WorkerStatus,
)
from ..config import settings

logger = logging.getLogger(__name__)

internal_router = APIRouter()  # /internal/**:仅服务间直连 / BFF 代理

_MAX_RUNS = 200  # 进程内保留的运行数上限(简单 GC,防内存无界)


class _Channel:
    __slots__ = ("events", "done", "result")

    def __init__(self) -> None:
        self.events: list[dict] = []       # 进度事件(线程内 append,SSE 协程读——GIL 下安全)
        self.done: bool = False
        self.result: dict | None = None    # 终态 payload


_runs: dict[int, _Channel] = {}


def _channel(run_id: int) -> _Channel:
    ch = _runs.get(run_id)
    if ch is None:
        ch = _Channel()
        _runs[run_id] = ch
        if len(_runs) > _MAX_RUNS:  # 删最旧
            for k in list(_runs)[: len(_runs) - _MAX_RUNS]:
                _runs.pop(k, None)
    return ch


class DispatchTask(BaseModel):
    task_id: str
    repo_url: str
    title: str
    description: str
    base_branch: str = "main"
    extra_context: str = ""
    test_cmd: str | None = None
    model: str | None = None


class DispatchIn(BaseModel):
    run_id: int
    callback_url: str
    open_pr: bool = True
    task: DispatchTask


def _run_and_callback(body: DispatchIn) -> None:
    ch = _channel(body.run_id)
    t = body.task
    task = CodingTask(
        task_id=t.task_id, repo_url=t.repo_url, title=t.title, description=t.description,
        base_branch=t.base_branch, extra_context=t.extra_context, test_cmd=t.test_cmd,
        model=t.model,
    )
    dispatcher = RuntimeDispatcher(
        workers={"claude-code": ClaudeCodeWorker()},
        workspace_root=settings.workspace_root,
        git_ops=GitLabGitOps() if body.open_pr else None,
        clone_depth=settings.clone_depth,
    )

    def on_progress(e: ProgressEvent) -> None:
        ch.events.append({"kind": e.kind, "message": e.message[:500]})
        logger.info("[coding run=%s] %s: %s", body.run_id, e.kind, e.message[:200])

    try:
        result = dispatcher.dispatch(task, "claude-code", on_progress=on_progress)
        ok = result.status is WorkerStatus.SUCCESS
        error = result.error or ("" if ok else f"未产生可提交改动({result.status.value})")
        payload = {
            "run_id": body.run_id,
            "status": "succeeded" if ok else "failed",
            "branch": result.branch or "",
            "mr_url": result.pr_url or "",
            "summary": result.summary or "",
            "error": error,
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("coding run %s crashed", body.run_id)
        payload = {"run_id": body.run_id, "status": "failed", "branch": "",
                   "mr_url": "", "summary": "", "error": str(e)}

    ch.result = payload
    ch.done = True
    try:
        httpx.post(body.callback_url, json=payload, timeout=15)
    except Exception as e:  # noqa: BLE001
        logger.error("coding run %s callback to %s failed: %s", body.run_id, body.callback_url, e)


@internal_router.post("/internal/coding/dispatch", status_code=202)
def dispatch_coding(body: DispatchIn, bg: BackgroundTasks):
    _channel(body.run_id)  # 预建通道,SSE 可立即连接(不丢早期事件)
    # 后台执行(Starlette 在线程池跑 sync task,阻塞子进程 OK),立即 202 返回
    bg.add_task(_run_and_callback, body)
    return {"accepted": True, "run_id": body.run_id}


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@internal_router.get("/internal/coding/runs/{run_id}/events")
async def stream_events(run_id: int):
    async def gen():
        ch = _runs.get(run_id)
        waited = 0
        while ch is None and waited < 20:  # 极早连接:等通道建立(最多 ~6s)
            await asyncio.sleep(0.3)
            waited += 1
            ch = _runs.get(run_id)
        if ch is None:
            yield _sse({"kind": "error", "message": "run not found"})
            return
        cursor = 0
        while True:
            while cursor < len(ch.events):
                yield _sse(ch.events[cursor])
                cursor += 1
            if ch.done:
                yield _sse({"kind": "done", **(ch.result or {})})
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
    })
