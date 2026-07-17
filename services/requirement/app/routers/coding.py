"""AI 编码对接(FR-DEV-01):发起编码 → dev 服务执行 → 回调绑 MR 产物。

模式对齐 analysis:
- 发起(/api/requirements/{id}/coding):native 需求须处于 scheduled/in_dev(scheduled 自动 start_dev);
  TAPD 镜像需求不受状态机约束,直接可发起;同一需求同时只允许一个进行中的编码;
  种子上下文复用最近一次成功分析的报告(agentic 调查/术语表结论已沉淀其中)。
- 回调(/internal/coding/callback):succeeded → 绑 artifact mr/<url> 并写 coding_done 留痕
  (in_dev 自环,不改变生命周期状态);需求已被人工流转走时(InvalidTransition)MR 照存、流转跳过。
"""

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_subject
from ..config import settings
from ..db import get_db
from ..flow import apply_transition
from ..models import AnalysisRun, CodingRun, Requirement
from ..schemas import CodingCallbackIn, CodingRunOut, CodingStartIn
from ..state_machine import InvalidTransition

logger = logging.getLogger(__name__)

router = APIRouter()            # /api/**:经 BFF 暴露给前端
internal_router = APIRouter()   # /internal/**:仅服务间直连(dev 服务回调)

ACTIVE = ("queued", "running")


def _looks_like_git_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "ssh://", "git@")) or s.endswith(".git")


def _fetch_project(project_id: int) -> dict:
    """取项目详情(含 repos 名字 + repo_meta 的 git 地址,identity FR-ADM-02)。取不到返回空 dict。"""
    try:
        resp = httpx.get(
            f"{settings.identity_base_url.rstrip('/')}/api/projects/{project_id}", timeout=5,
        )
        if resp.status_code == 200:
            return resp.json()
        logger.warning("fetch project %s -> %s", project_id, resp.status_code)
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch project %s failed: %s", project_id, e)
    return {}


def _resolve_repo(project_id: int, given_url: str | None, given_branch: str | None) -> tuple[str, str]:
    """确定编码目标仓库 (git_url, base_branch)。

    优先级:显式传入 > 项目 repo_meta(git_url + default_branch,由 wiki 缓存 backfill 而来)。
    分支:显式 given_branch > repo_meta.default_branch(如 master)> main。
    走向自动化的关键——repo_meta 由 wiki 生成时就已知的真实地址/分支自动回填,人不再手填。
    多仓库的自动选择由「从分析结果推导目标仓库」那一步接手(下一步)。
    """
    if given_url and _looks_like_git_url(given_url):
        return given_url, (given_branch or "main")
    if given_url:
        raise HTTPException(400, f"repo_url 不像 git 地址:{given_url}")
    meta = _fetch_project(project_id).get("repo_meta") or {}
    entries = [(str(m["git_url"]), str(m.get("default_branch") or "main"))
               for m in meta.values()
               if isinstance(m, dict) and _looks_like_git_url(str(m.get("git_url") or ""))]
    if len(entries) == 1:
        url, branch = entries[0]
        return url, (given_branch or branch)
    if not entries:
        raise HTTPException(400, "未指定 repo_url,且项目绑定的代码库尚未配置 git 地址(repo_meta);"
                                 "请先跑 backfill 从 wiki 缓存回填,或本次直接传 repo_url")
    raise HTTPException(400, f"项目绑定了多个带 git 地址的代码库,请用 repo_url 指定其一:"
                            f"{[u for u, _ in entries]}")


def _analysis_seed(db: Session, req_id: int) -> str:
    """最近一次成功分析的报告作为编码种子上下文(agentic 调查/术语表结论已沉淀其中)。"""
    run = db.scalar(
        select(AnalysisRun)
        .where(AnalysisRun.requirement_id == req_id, AnalysisRun.status == "succeeded")
        .order_by(AnalysisRun.id.desc())
    )
    return (run.report_md or "")[:6000] if run else ""


@router.post("/requirements/{req_id}/coding", response_model=CodingRunOut, status_code=202)
def start_coding(
    req_id: int,
    body: CodingStartIn,
    db: Session = Depends(get_db),
    subject: str = Depends(current_subject),
):
    req = db.get(Requirement, req_id)
    if req is None:
        raise HTTPException(404, "requirement not found")
    # 状态校验:native 需求须在 scheduled(自动 start_dev)或 in_dev;TAPD 镜像不受约束
    if req.source == "native":
        if req.status == "scheduled":
            apply_transition(db, req, "start_dev", subject, comment="AI 编码启动")
        elif req.status != "in_dev":
            raise HTTPException(409, f"coding requires status 'scheduled' or 'in_dev', current: '{req.status}'")

    active = db.scalar(
        select(CodingRun).where(CodingRun.requirement_id == req_id, CodingRun.status.in_(ACTIVE))
    )
    if active is not None:
        raise HTTPException(409, f"coding run {active.id} is still in progress")

    repo_url, base_branch = _resolve_repo(req.project_id, body.repo_url, body.base_branch)
    run = CodingRun(requirement_id=req_id, repo=repo_url, created_by=subject, status="queued")
    db.add(run)
    db.flush()

    payload = {
        "run_id": run.id,
        "callback_url": f"{settings.callback_base_url.rstrip('/')}/internal/coding/callback",
        "open_pr": True,
        "task": {
            "task_id": f"req-{req_id}",
            "repo_url": repo_url,
            "base_branch": base_branch,
            "title": req.title,
            "description": req.description,
            "extra_context": _analysis_seed(db, req_id),
            "test_cmd": body.test_cmd,
        },
    }
    try:
        resp = httpx.post(
            f"{settings.dev_base_url.rstrip('/')}/internal/coding/dispatch",
            json=payload, timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:  # noqa: BLE001
        logger.warning("failed to submit coding task for run %s: %s", run.id, e)
        run.status = "failed"
        run.error = f"无法提交编码任务(dev 服务不可达):{e}"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
        raise HTTPException(502, run.error)

    run.status = "running"
    db.commit()
    db.refresh(run)
    return run


@router.get("/requirements/{req_id}/coding", response_model=list[CodingRunOut])
def list_coding_runs(req_id: int, db: Session = Depends(get_db)):
    if db.get(Requirement, req_id) is None:
        raise HTTPException(404, "requirement not found")
    return db.scalars(
        select(CodingRun).where(CodingRun.requirement_id == req_id).order_by(CodingRun.id.desc())
    ).all()


@router.get("/coding-runs/{run_id}", response_model=CodingRunOut)
def get_coding_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(CodingRun, run_id)
    if run is None:
        raise HTTPException(404, "coding run not found")
    return run


@internal_router.post("/internal/coding/callback", response_model=CodingRunOut)
def coding_callback(
    body: CodingCallbackIn,
    db: Session = Depends(get_db),
    subject: str = Depends(current_subject),
):
    run = db.get(CodingRun, body.run_id)
    if run is None:
        raise HTTPException(404, "coding run not found")
    if run.status not in ACTIVE:
        return run  # 回调重试导致的重复投递:幂等返回

    run.status = body.status
    run.branch = body.branch or run.branch
    run.mr_url = body.mr_url or None
    run.summary = body.summary
    run.error = body.error
    run.finished_at = datetime.now(timezone.utc)

    if body.status == "succeeded":
        req = db.get(Requirement, run.requirement_id)
        try:
            apply_transition(
                db, req, "coding_done", "ai-coding",
                comment=(body.summary or "")[:500],
                artifact_type="mr", artifact_ref=(body.mr_url or run.branch or "")[:255] or None,
            )
        except InvalidTransition as e:
            # 需求已被人工流转(降级路径),MR 照存、流转跳过
            logger.info("coding_done skipped for req %s: %s", run.requirement_id, e)

    db.commit()
    db.refresh(run)
    return run
