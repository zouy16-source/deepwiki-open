"""可行性分析任务（FR-ANA-01~05 的任务框架，admin-phase1-plan §5 W5）。

沿用 wiki_jobs 的思路做轻量版：内存 store + asyncio 后台任务 + 并发信号量 +
可插拔分析函数。requirement 服务 POST /api/analysis/tasks 创建任务；任务到达
终态时本服务回调 requirement 的 /internal/analysis/callback（内部 JWT 用 stdlib
HS256 手工签名，不给 api 服务新增依赖）。

v1 分析器：仅以需求文本为上下文的单轮 LLM 分析（OpenAI 兼容端点，qwen 系），
报告中明确标注"未接入代码库检索"的局限。AI 线的 agentic 检索版（trace 工具循环
直读仓库）就位后替换 run_feasibility_analysis 即可——任务框架与回调协议不变。
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import aiohttp
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

ANALYSIS_TERMINAL = {"succeeded", "failed"}
_FINISHED_TTL_S = 3600


# --- 请求/存储 ---------------------------------------------------------------

class AnalysisRequirement(BaseModel):
    id: int
    title: str
    description: str = ""
    req_type: str = "business"
    priority: str = "P1"
    project_id: Optional[int] = None
    expected_online_date: Optional[str] = None


class AnalysisTaskRequest(BaseModel):
    run_id: int                # requirement 服务侧 AnalysisRun 主键，回调时原样带回
    callback_url: str = ""     # 留空 = 不回调（调试用）
    requirement: AnalysisRequirement


_tasks: dict[str, dict] = {}
_sem = asyncio.Semaphore(int(os.environ.get("MAX_CONCURRENT_ANALYSIS", "3")))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gc() -> None:
    cutoff = time.time() - _FINISHED_TTL_S
    for tid in list(_tasks):
        t = _tasks[tid]
        if t["status"] in ANALYSIS_TERMINAL and t.get("finished_ts", 0) < cutoff:
            _tasks.pop(tid, None)


def _view(t: dict) -> dict:
    return {k: t[k] for k in (
        "id", "run_id", "status", "summary", "complexity", "report_md", "error",
        "created_at", "started_at", "finished_at",
    )}


# --- 内部 JWT（stdlib HS256，与 BFF/requirement 共享 INTERNAL_JWT_SECRET）------

def _sign_internal_jwt(sub: str = "svc:api", ttl: int = 300) -> str:
    secret = os.environ.get("INTERNAL_JWT_SECRET", "")
    if not secret:
        return ""  # 本地免鉴权模式，与其余服务约定一致

    def b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    payload = b64(json.dumps({"sub": sub, "iat": now, "exp": now + ttl}).encode())
    sig = b64(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


# --- v1 分析器 ----------------------------------------------------------------

_PROMPT = """你是资深研发负责人，对下面这条业务需求做可行性预分析，产出评审会可用的报告。

【需求信息】
- 编号：#{id} · 类型：{req_type} · 优先级：{priority} · 期望上线：{expected}
- 标题：{title}
- 描述：
{description}

【输出要求】
1. 用中文 Markdown 输出，按以下小节组织（保持标题层级为 ##）：
   业务可行性 / 代码可行性 / 复杂度评估 / 系统范围 / 风险与建议 / 结论
2. 本次分析**尚未接入代码库检索**：「代码可行性」与「系统范围」只能基于需求文本推断，
   必须在这两节开头明确标注"（基于需求文本推断，待接入代码库检索后复核）"，不得编造具体文件/接口。
3. 复杂度按 S/M/L/XL 分级并给出依据与人天区间参考。
4. 报告末尾追加两行标签（供系统解析，不要放进正文小节）：
<summary>一句话结论（不超过 60 字）</summary>
<complexity>S|M|L|XL 其中之一</complexity>"""


async def run_feasibility_analysis(req: AnalysisRequirement) -> dict:
    """v1：单轮 LLM 分析。返回 {summary, complexity, report_md}；失败抛异常。"""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 未配置，AI 分析不可用（可走人工降级流转）")

    from openai import AsyncOpenAI

    llm = AsyncOpenAI(api_key=api_key, base_url=os.environ.get("OPENAI_BASE_URL"))
    model = os.environ.get("ANALYSIS_MODEL", "qwen-plus")
    prompt = _PROMPT.format(
        id=req.id, req_type=req.req_type, priority=req.priority,
        expected=req.expected_online_date or "未设定",
        title=req.title, description=(req.description or "（未填写）")[:6000],
    )
    resp = await llm.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}], temperature=0.2,
    )
    text = resp.choices[0].message.content or ""

    def _tag(name: str) -> str:
        m = re.search(rf"<{name}>([\s\S]*?)</{name}>", text)
        return m.group(1).strip() if m else ""

    summary = _tag("summary") or "分析完成（未解析出摘要）"
    complexity = _tag("complexity").upper()
    if complexity not in ("S", "M", "L", "XL"):
        complexity = ""
    report_md = re.sub(r"<(summary|complexity)>[\s\S]*?</\1>", "", text).strip()
    return {"summary": summary, "complexity": complexity, "report_md": report_md}


# --- 任务执行与回调 ------------------------------------------------------------

async def _send_callback(t: dict) -> None:
    url = t.get("callback_url") or ""
    if not url:
        return
    payload = {
        "run_id": t["run_id"], "task_id": t["id"], "status": t["status"],
        "summary": t["summary"], "complexity": t["complexity"],
        "report_md": t["report_md"], "error": t["error"],
    }
    headers = {"Content-Type": "application/json"}
    token = _sign_internal_jwt()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status < 300:
                        return
                    body = (await resp.text())[:200]
                    logger.warning("analysis callback %s -> %s: %s", url, resp.status, body)
        except Exception as e:  # noqa: BLE001
            logger.warning("analysis callback attempt %d failed: %s", attempt + 1, e)
        await asyncio.sleep(2 * (attempt + 1))
    logger.error("analysis callback gave up: task=%s run=%s", t["id"], t["run_id"])


async def _run_task(task_id: str, req: AnalysisRequirement) -> None:
    t = _tasks[task_id]
    async with _sem:
        t["status"] = "running"
        t["started_at"] = _now_iso()
        try:
            timeout_s = int(os.environ.get("ANALYSIS_TIMEOUT_S", "300"))
            result = await asyncio.wait_for(run_feasibility_analysis(req), timeout=timeout_s)
            t.update(result)
            t["status"] = "succeeded"
        except asyncio.TimeoutError:
            t["status"] = "failed"
            t["error"] = "analysis timed out"
        except Exception as e:  # noqa: BLE001
            logger.exception("analysis task %s failed", task_id)
            t["status"] = "failed"
            t["error"] = str(e)
        t["finished_at"] = _now_iso()
        t["finished_ts"] = time.time()
    await _send_callback(t)


# --- API ----------------------------------------------------------------------

@router.post("/api/analysis/tasks", status_code=202)
async def create_analysis_task(body: AnalysisTaskRequest):
    _gc()
    task_id = f"ana_{uuid.uuid4().hex[:12]}"
    _tasks[task_id] = {
        "id": task_id, "run_id": body.run_id, "callback_url": body.callback_url,
        "status": "queued", "summary": "", "complexity": "", "report_md": "", "error": "",
        "created_at": _now_iso(), "started_at": None, "finished_at": None,
    }
    asyncio.create_task(_run_task(task_id, body.requirement))
    return _view(_tasks[task_id])


@router.get("/api/analysis/tasks/{task_id}")
async def get_analysis_task(task_id: str):
    _gc()
    t = _tasks.get(task_id)
    if t is None:
        raise HTTPException(404, "analysis task not found")
    return _view(t)
