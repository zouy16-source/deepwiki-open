"""可行性分析任务（FR-ANA-01~05 的任务框架，admin-phase1-plan §5 W5）。

沿用 wiki_jobs 的思路做轻量版：内存 store + asyncio 后台任务 + 并发信号量 +
可插拔分析函数。requirement 服务 POST /api/analysis/tasks 创建任务；任务到达
终态时本服务回调 requirement 的 /internal/analysis/callback（内部 JWT 用 stdlib
HS256 手工签名，不给 api 服务新增依赖）。

v2 分析器（agentic 检索版）：项目空间绑定了代码库时，逐仓库跑 grep/read_file/
list_dir 工具循环（复用 trace_agent.run_tool_loop，直读 ~/.adalflow/repos 本地
clone 的最新代码），产出带 `文件:行号` 真实引用的调查纪要，再综合为四维可行性
报告；未绑定仓库或 clone 缺失时自动降级为 v1 纯需求文本分析（报告标注局限）。
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
    # 需求源自对话创建时的对话快照——作为分析 agent 的已知线索（seed），少走盲搜
    source_context: str = ""


class AnalysisTaskRequest(BaseModel):
    run_id: int                # requirement 服务侧 AnalysisRun 主键，回调时原样带回
    callback_url: str = ""     # 留空 = 不回调（调试用）
    requirement: AnalysisRequirement
    repos: list[str] = []      # 项目空间绑定的本地 clone 目录名（如 eopl_galaxy-waybill）


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


# --- 分析器 --------------------------------------------------------------------
# v2：agentic 检索（有绑定仓库时）；v1：纯需求文本（降级路径）。
# 输出契约相同：{summary, complexity, report_md}，标签解析见 _parse_tags。

_TAG_FOOTER = """
报告末尾追加两行标签（供系统解析，不要放进正文小节）：
<summary>一句话结论（不超过 60 字）</summary>
<complexity>S|M|L|XL 其中之一</complexity>"""

_REQ_BLOCK = """- 编号：#{id} · 类型：{req_type} · 优先级：{priority} · 期望上线：{expected}
- 标题：{title}
- 描述：
{description}"""


def _req_block(req: "AnalysisRequirement") -> str:
    return _REQ_BLOCK.format(
        id=req.id, req_type=req.req_type, priority=req.priority,
        expected=req.expected_online_date or "未设定",
        title=req.title, description=(req.description or "（未填写）")[:6000],
    )


def _parse_tags(text: str) -> dict:
    def _tag(name: str) -> str:
        m = re.search(rf"<{name}>([\s\S]*?)</{name}>", text)
        return m.group(1).strip() if m else ""

    summary = _tag("summary") or "分析完成（未解析出摘要）"
    complexity = _tag("complexity").upper()
    if complexity not in ("S", "M", "L", "XL"):
        complexity = ""
    report_md = re.sub(r"<(summary|complexity)>[\s\S]*?</\1>", "", text).strip()
    return {"summary": summary, "complexity": complexity, "report_md": report_md}


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


def _make_llm():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 未配置，AI 分析不可用（可走人工降级流转）")
    from openai import AsyncOpenAI

    llm = AsyncOpenAI(api_key=api_key, base_url=os.environ.get("OPENAI_BASE_URL"))
    return llm, os.environ.get("ANALYSIS_MODEL", "qwen-plus")


async def _analyze_text_only(req: AnalysisRequirement) -> dict:
    """v1（降级路径）：仅需求文本的单轮分析。"""
    llm, model = _make_llm()
    prompt = _PROMPT.format(
        id=req.id, req_type=req.req_type, priority=req.priority,
        expected=req.expected_online_date or "未设定",
        title=req.title, description=(req.description or "（未填写）")[:6000],
    )
    if (req.source_context or "").strip():
        prompt += f"\n\n【前期对话线索】（产品经理与代码库 AI 的对话结论，可作为分析参考）\n{req.source_context[:4000]}"
    resp = await llm.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}], temperature=0.2,
    )
    return _parse_tags(resp.choices[0].message.content or "")


_REPO_AGENT_SYSTEM = """你是资深架构师，正在仓库 {repo}（服务器本地最新工作树）中调查一条业务需求的落地可行性。

【需求】
{req_block}

你有三个工具：grep（全仓搜索）、read_file（带行号读片段）、list_dir（看目录结构）。调查目标：
1. 定位与需求相关的现有模块/页面/接口/服务（先 list_dir 看结构，再用业务词、接口路径、表名等多个标识符变体 grep）；
2. 找出可复用的相似实现（如已有的导出/打印/批量/校验等同类逻辑）；
3. 评估改动面：需要新增/修改哪些文件或模块；
4. 识别冲突与风险：与现有逻辑的耦合点、数据结构约束。

结束时直接输出「仓库调查纪要」（不再调用工具），要求：
- 每条结论标注来源 `完整相对路径:行号`（如 `galaxy-waybill-service/src/main/java/.../WaybillQueryServiceImpl.java:42`），
  路径与行号必须逐字复制自 grep/read_file 的真实返回——系统会逐条机器核验，对不上的引用会被标记为不可信；
- 按「相关现状 / 可复用实现 / 预计改动面 / 冲突与风险」组织；
- 某方面确实无相关实现时明确写"未发现相关实现"，不要硬凑。"""

_SYNTHESIS_PROMPT = """你是资深研发负责人。以下是对一条业务需求的逐仓库代码调查纪要（由代码检索 agent 产出，
引用的 文件:行号 均来自真实代码），请综合为评审会可用的可行性分析报告。

【需求信息】
{req_block}

【逐仓库调查纪要】
{findings}

【输出要求】
1. 中文 Markdown，按以下小节组织（标题层级 ##）：业务可行性 / 代码可行性 / 复杂度评估 / 系统范围 / 风险与建议 / 结论
2. 代码可行性与系统范围必须基于调查纪要，保留关键结论的代码引用；**引用必须从纪要中逐字复制
   （完整相对路径:行号），禁止改写文件名、简化路径或凭理解生成新引用**——系统会逐条机器核验，
   编造的引用会被标记并降低报告可信度；纪要中没有证据支撑的结论不要写；
3. 复杂度按 S/M/L/XL 分级，依据涉及仓库数、改动模块数、数据变更给出人天区间参考；
4. 若某仓库纪要显示与需求无关，在「系统范围」中如实说明。
{tag_footer}"""


# --- 引用核验（报告可信三件套之"出处必须真实"）--------------------------------

_CITE_RE = re.compile(
    r"`?([\w\-./]+\.(?:java|kt|go|vue|jsx?|tsx?|xml|jsp|sql|py|yml|yaml|properties|gradle|sh))"
    r"\s*[:：]\s*(\d+)`?"
)

# 代码标识符提取：只保留带 camelCase / PascalCase / snake_case 信号的 token（长度≥4），
# 过滤掉 field/class/list 这类纯小写歧义词与中文，降低误判。
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
_CODEY_RE = re.compile(r"[a-z][A-Z]|[A-Z][a-z].*[A-Z]|_")


def _code_identifiers(text: str) -> set:
    return {t for t in _IDENT_RE.findall(text or "") if _CODEY_RE.search(t)}


def _build_file_index(roots: list) -> dict:
    """basename -> [绝对路径]。走一遍仓库树（跳过噪声目录），供引用核验。"""
    from api.trace_tools import SKIP_DIRS

    index: dict = {}
    for _base, root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                index.setdefault(fn, []).append(os.path.join(dirpath, fn))
    return index


def _read_window(path: str, line_no: int, ctx: int = 3) -> str:
    """读引用行 ±ctx 行的实际代码（内容级核验用）。"""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except OSError:
        return ""
    lo, hi = max(0, line_no - 1 - ctx), min(len(lines), line_no + ctx)
    return "".join(lines[lo:hi])


def _verify_citations(md: str, roots: list) -> tuple:
    """逐条机器核验 `文件:行号`，两级：
      1) 位置核验：文件存在（路径后缀匹配）且行号不超行数；
      2) 内容核验：引用前文若提到代码标识符，则该标识符须出现在引用行 ±3 行内。
    位置不过 → ⚠️引用未通过核验；位置过但内容不符 → ⚠️引用内容存疑（均计入未通过）。
    返回 (标注后的 md, 通过数, 未通过数)。"""
    index = _build_file_index(roots)
    line_counts: dict = {}
    ok = bad = 0

    def _lines(path: str) -> int:
        if path not in line_counts:
            try:
                with open(path, "rb") as f:
                    line_counts[path] = sum(1 for _ in f)
            except OSError:
                line_counts[path] = -1
        return line_counts[path]

    def _check(m: re.Match) -> str:
        nonlocal ok, bad
        cited_path, line_no = m.group(1), int(m.group(2))
        candidates = index.get(os.path.basename(cited_path), [])
        suffix = cited_path.lstrip("./")
        target = next(
            (c for c in candidates if c.replace(os.sep, "/").endswith(suffix)), None
        )
        if target is None and len(candidates) == 1:
            target = candidates[0]  # 只写了文件名且全仓唯一：可定位
        # 位置核验
        if target is None or not (0 < line_no <= _lines(target)):
            bad += 1
            return m.group(0) + "（⚠️引用未通过核验）"
        # 内容核验：取引用前文里的代码标识符，看是否真的在引用行附近出现。
        # 窗口限制在**当前行内**（回退到上一个换行）——否则逐条列表里会把上一条的标识符带进来，造成假阳性。
        line_start = m.string.rfind("\n", 0, m.start()) + 1
        pre = m.string[max(line_start, m.start() - 120):m.start()]
        idents = _code_identifiers(pre)
        if idents:
            window = _read_window(target, line_no)
            if not any(idt in window for idt in idents):
                bad += 1
                return m.group(0) + "（⚠️引用内容存疑：该行未见所述标识符）"
        ok += 1
        return m.group(0)

    return _CITE_RE.sub(_check, md), ok, bad


# --- 否定结论对抗验证（打击"漏查→假阴性"：grep 一次没命中就下"不存在"结论）------

_NEG_RE = re.compile(
    r"(未找到|未发现|未定位|不存在|没有找到|没有发现|未定义|查不到|未命中|无相关实现|未见)"
)


def _ident_variants(ident: str) -> set:
    """标识符多变体：原样 / camel↔snake / 去 get·set·is·has 前缀。"""
    v = {ident, ident.lower()}
    snake = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", ident).lower()
    v.add(snake)
    if "_" in ident:
        parts = [p for p in ident.split("_") if p]
        if parts:
            v.add(parts[0] + "".join(p.capitalize() for p in parts[1:]))
    for p in ("get", "set", "is", "has"):
        if ident.startswith(p) and len(ident) > len(p) + 2:
            rest = ident[len(p):]
            v.add(rest[0].lower() + rest[1:])
    return {x for x in v if len(x) >= 4}


def adversarial_negation_check(answer: str, roots: list, max_claims: int = 6) -> tuple:
    """对回答里的否定结论做确定性对抗验证：提取被否定的代码标识符，多变体跨仓库重新 grep。
    命中即为假阴性反证（原结论可能错），在回答末尾追加「对抗验证」段。纯 grep、无 LLM 调用。
    返回 (标注后的回答, 反证数)。"""
    from api.trace_tools import grep

    # 收集否定句里的候选标识符
    claims: list[str] = []
    seen: set = set()
    for line in answer.splitlines():
        if not _NEG_RE.search(line):
            continue
        for idt in _code_identifiers(line):
            if idt not in seen:
                seen.add(idt)
                claims.append(idt)
    claims = claims[:max_claims]
    if not claims:
        return answer, 0

    refutations = []
    for idt in claims:
        hit_line = None
        for variant in sorted(_ident_variants(idt), key=len, reverse=True):
            for name, root in roots:
                out = grep(root, variant, max_hits=3)
                if out and not out.startswith("（无命中"):
                    first = out.splitlines()[0]  # rel:line: 内容
                    parts = first.split(":", 2)
                    if len(parts) >= 2 and parts[1].strip().isdigit():
                        hit_line = f"{name}/{parts[0]}:{parts[1].strip()}"
                        break
            if hit_line:
                break
        if hit_line:
            refutations.append((idt, hit_line))

    if not refutations:
        return answer, 0

    lines = ["", "---", "### ⚠️ 对抗验证（对否定结论的多变体二次检索）"]
    for idt, loc in refutations:
        lines.append(f"- `{idt}`：原结论称未找到，但二次检索在 `{loc}` 命中——原结论可能为**假阴性**，请复核。")
    return answer + "\n".join(lines) + "\n", len(refutations)


async def run_feasibility_analysis(
    req: AnalysisRequirement, repos: Optional[list] = None
) -> dict:
    """v2：绑定了代码库 → 逐仓库 agentic 调查 + 综合报告；否则降级为 v1 文本分析。"""
    from api.trace_tools import repos_root

    max_repos = int(os.environ.get("ANALYSIS_MAX_REPOS", "2"))
    roots: list[tuple[str, str]] = []
    missing: list[str] = []
    for name in (repos or [])[:max_repos]:
        base = os.path.basename(str(name).strip())  # 防路径逃逸
        if not base:
            continue
        root = os.path.join(repos_root(), base)
        if os.path.isdir(root):
            roots.append((base, root))
        else:
            missing.append(base)

    if not roots:
        result = await _analyze_text_only(req)
        reason = "本地 clone 缺失：" + "、".join(missing) if missing else "项目空间未绑定代码库"
        result["report_md"] = (
            f"> ⚠️ 本报告未接入代码库检索（{reason}），代码可行性与系统范围为基于需求文本的推断。\n\n"
            + result["report_md"]
        )
        return result

    from api.trace_agent import run_tool_loop

    llm, model = _make_llm()
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    req_block = _req_block(req)
    iters = int(os.environ.get("ANALYSIS_AGENT_ITERS", "10"))
    per_repo_deadline = int(os.environ.get("ANALYSIS_AGENT_DEADLINE_S", "150"))

    seed = (req.source_context or "").strip()
    user_msg = "开始调查。"
    if seed:
        user_msg += (
            "\n\n已知线索（产品经理与代码库 AI 的前期对话，其中的代码结论可参考，但引用前仍须用工具核实）：\n"
            + seed[:4000]
        )

    findings = []
    tool_calls = 0
    for base, root in roots:
        messages = [
            {"role": "system", "content": _REPO_AGENT_SYSTEM.format(repo=base, req_block=req_block)},
            {"role": "user", "content": user_msg},
        ]
        text, steps = await run_tool_loop(
            llm, model, root, messages,
            max_iters=iters, deadline_s=per_repo_deadline, log_label=f"analysis:{base}",
        )
        tool_calls += len(steps)
        findings.append(f"### 仓库 {base}（工具调用 {len(steps)} 次）\n{text}")

    prompt = _SYNTHESIS_PROMPT.format(
        req_block=req_block, findings="\n\n".join(findings), tag_footer=_TAG_FOOTER,
    )
    resp = await llm.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}], temperature=0.2,
    )
    result = _parse_tags(resp.choices[0].message.content or "")

    # 对抗验证否定结论（假阴性反证）→ 再逐条核验全部引用（含对抗验证追加的真实出处）
    checked, refuted = adversarial_negation_check(result["report_md"], roots)
    verified_md, cites_ok, cites_bad = _verify_citations(checked, roots)
    trust = ""
    if cites_ok + cites_bad > 0:
        trust = f" · 引用核验：{cites_ok} 通过 / {cites_bad} 未通过"
        if cites_bad > cites_ok:
            trust += "（⚠️多数引用未通过核验，结论请人工复核）"
    if refuted:
        trust += f" · 对抗验证驳回 {refuted} 条否定结论（疑似假阴性）"
    header = (
        f"> 检索时间：{started} · 检索仓库：{'、'.join(b for b, _ in roots)}"
        + (f"（缺失 clone：{'、'.join(missing)}）" if missing else "")
        + f" · 代码检索 {tool_calls} 次（agentic 直读最新工作树）{trust}\n\n"
    )
    result["report_md"] = header + verified_md
    return result


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


async def _run_task(task_id: str, req: AnalysisRequirement, repos: list) -> None:
    t = _tasks[task_id]
    async with _sem:
        t["status"] = "running"
        t["started_at"] = _now_iso()
        try:
            # agentic 检索版预算更大：逐仓库工具循环 + 综合各一段
            timeout_s = int(os.environ.get("ANALYSIS_TIMEOUT_S", "600"))
            result = await asyncio.wait_for(run_feasibility_analysis(req, repos), timeout=timeout_s)
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
    asyncio.create_task(_run_task(task_id, body.requirement, body.repos))
    return _view(_tasks[task_id])


@router.get("/api/analysis/tasks/{task_id}")
async def get_analysis_task(task_id: str):
    _gc()
    t = _tasks.get(task_id)
    if t is None:
        raise HTTPException(404, "analysis task not found")
    return _view(t)


# --- 对话 → 需求草稿（对话式创建需求，BFF /api/analysis/draft 转发到此）---------

class DraftFromChatRequest(BaseModel):
    messages: list = []       # [{role, content}] 产品经理与代码库 AI 的对话
    project_name: str = ""


_DRAFT_PROMPT = """你是资深产品经理助手。根据下面「产品经理与代码库 AI 助手」的对话记录，提炼一条结构化业务需求草稿{project_hint}。

【对话记录】
{transcript}

【输出要求】只输出一个 JSON 对象（不要任何其它文字或代码块标记）：
{{
  "title": "需求标题，一句话说清要做什么，不超过 50 字",
  "req_type": "business 或 system",
  "priority": "P0 / P1 / P2（按对话中体现的紧迫性判断，默认 P1）",
  "description": "按模板组织，用 \\n 换行：【背景】…\\n【目标】…\\n【涉及业务域】…（对话中确认过的系统/模块/代码结论）\\n【验收期望】…",
  "gaps": ["对话中缺失、创建需求前应向业务方补充确认的信息点；没有则为空数组"]
}}
对话中没有依据的内容不要编造，缺什么如实写进 gaps。"""


def _extract_json(text: str) -> dict:
    """容错解析：剥掉 ```json 围栏，取第一个 { 到最后一个 } 之间的内容。"""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in model output")
    return json.loads(cleaned[start:end + 1])


@router.post("/api/analysis/requirement-draft")
async def requirement_draft(body: DraftFromChatRequest):
    msgs = [m for m in body.messages if isinstance(m, dict) and (m.get("content") or "").strip()]
    if len(msgs) < 2:
        raise HTTPException(422, "对话内容不足，先与 AI 聊几轮再生成草稿")
    try:
        llm, model = _make_llm()
    except RuntimeError as e:
        raise HTTPException(503, str(e))

    transcript = "\n\n".join(
        f"[{'产品' if m.get('role') == 'user' else 'AI'}] {str(m.get('content'))[:2500]}"
        for m in msgs[-20:]
    )
    hint = f"（所属项目：{body.project_name}）" if body.project_name else ""
    resp = await llm.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": _DRAFT_PROMPT.format(project_hint=hint, transcript=transcript)}],
        temperature=0.2,
    )
    text = resp.choices[0].message.content or ""
    try:
        data = _extract_json(text)
    except (ValueError, json.JSONDecodeError):
        logger.warning("requirement draft parse failed: %s", text[:300])
        raise HTTPException(502, "草稿解析失败，请重试")

    return {
        "title": str(data.get("title") or "")[:255],
        "req_type": data.get("req_type") if data.get("req_type") in ("business", "system") else "business",
        "priority": data.get("priority") if data.get("priority") in ("P0", "P1", "P2") else "P1",
        "description": str(data.get("description") or ""),
        "gaps": [str(g) for g in data.get("gaps") or [] if str(g).strip()][:8],
    }
