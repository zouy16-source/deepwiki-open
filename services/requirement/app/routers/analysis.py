"""可行性分析对接（FR-ANA，W5）：发起任务 → api 服务执行 → 回调驱动流转。

- 发起：需求须处于「待分析」，同一需求同时只允许一个进行中的分析；
- 回调：succeeded → 回写报告 + 需求复杂度 + 驱动 analysis_done（artifact analysis/<run_id>）；
  需求已被人工流转走时（InvalidTransition）报告照存、流转跳过——人工降级路径优先（NFR-02）。
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
from ..models import AnalysisRun, Requirement
from ..schemas import AnalysisCallbackIn, AnalysisRunOut
from ..state_machine import InvalidTransition

logger = logging.getLogger(__name__)

router = APIRouter()            # /api/**：经 BFF 暴露给前端
internal_router = APIRouter()   # /internal/**：仅服务间直连（api 服务回调）

ACTIVE = ("queued", "running")


def _project_repos(project_id: int) -> list[str]:
    """项目空间绑定的代码库（identity FR-ADM-02）。取不到不阻塞——分析会降级为纯文本模式。"""
    try:
        resp = httpx.get(
            f"{settings.identity_base_url.rstrip('/')}/api/projects/{project_id}",
            timeout=5,
        )
        if resp.status_code == 200:
            repos = resp.json().get("repos")
            return repos if isinstance(repos, list) else []
        logger.warning("fetch project %s repos -> %s", project_id, resp.status_code)
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch project %s repos failed: %s", project_id, e)
    return []


@router.post("/requirements/{req_id}/analysis", response_model=AnalysisRunOut, status_code=202)
def start_analysis(
    req_id: int,
    db: Session = Depends(get_db),
    subject: str = Depends(current_subject),
):
    req = db.get(Requirement, req_id)
    if req is None:
        raise HTTPException(404, "requirement not found")
    # TAPD 镜像需求（source!=native）允许直接发起分析（增值）；平台原生需求须处于待分析
    if req.source == "native" and req.status != "pending_analysis":
        raise HTTPException(409, f"analysis requires status 'pending_analysis', current: '{req.status}'")
    active = db.scalar(
        select(AnalysisRun).where(
            AnalysisRun.requirement_id == req_id, AnalysisRun.status.in_(ACTIVE)
        )
    )
    if active is not None:
        raise HTTPException(409, f"analysis run {active.id} is still in progress")

    run = AnalysisRun(requirement_id=req_id, created_by=subject)
    db.add(run)
    db.flush()

    payload = {
        "run_id": run.id,
        "callback_url": f"{settings.callback_base_url.rstrip('/')}/internal/analysis/callback",
        "repos": _project_repos(req.project_id),
        "requirement": {
            "id": req.id,
            "title": req.title,
            "description": req.description,
            "req_type": req.req_type,
            "priority": req.priority,
            "project_id": req.project_id,
            "expected_online_date": req.expected_online_date.isoformat()
            if req.expected_online_date else None,
            "source_context": (req.source_context or "")[:8000],
        },
    }
    try:
        resp = httpx.post(
            f"{settings.analysis_base_url.rstrip('/')}/api/analysis/tasks",
            json=payload, timeout=10,
        )
        resp.raise_for_status()
        run.task_id = resp.json().get("id")
    except Exception as e:  # noqa: BLE001
        logger.warning("failed to submit analysis task for run %s: %s", run.id, e)
        run.status = "failed"
        run.error = f"无法提交分析任务（api 服务不可达）：{e}"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(run)
        raise HTTPException(502, run.error)

    db.commit()
    db.refresh(run)
    return run


@router.get("/requirements/{req_id}/analysis", response_model=list[AnalysisRunOut])
def list_analysis_runs(req_id: int, db: Session = Depends(get_db)):
    if db.get(Requirement, req_id) is None:
        raise HTTPException(404, "requirement not found")
    return db.scalars(
        select(AnalysisRun)
        .where(AnalysisRun.requirement_id == req_id)
        .order_by(AnalysisRun.id.desc())
    ).all()


@router.get("/analysis-runs/{run_id}", response_model=AnalysisRunOut)
def get_analysis_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(AnalysisRun, run_id)
    if run is None:
        raise HTTPException(404, "analysis run not found")
    return run


@internal_router.post("/internal/analysis/callback", response_model=AnalysisRunOut)
def analysis_callback(
    body: AnalysisCallbackIn,
    db: Session = Depends(get_db),
    subject: str = Depends(current_subject),
):
    run = db.get(AnalysisRun, body.run_id)
    if run is None:
        raise HTTPException(404, "analysis run not found")
    if run.status not in ACTIVE:
        return run  # 回调重试导致的重复投递：幂等返回

    run.status = body.status
    run.summary = body.summary
    run.complexity = body.complexity or None
    run.report_md = body.report_md
    run.error = body.error
    run.task_id = body.task_id or run.task_id
    run.finished_at = datetime.now(timezone.utc)

    if body.status == "succeeded":
        req = db.get(Requirement, run.requirement_id)
        if body.complexity in ("S", "M", "L", "XL"):
            req.complexity = body.complexity
        try:
            apply_transition(
                db, req, "analysis_done", "ai-analysis",
                comment=body.summary[:500],
                artifact_type="analysis_report", artifact_ref=f"analysis/{run.id}",
            )
        except InvalidTransition as e:
            # 需求已被人工流转（降级路径），报告照存、流转跳过
            logger.info("analysis_done skipped for req %s: %s", run.requirement_id, e)

    db.commit()
    db.refresh(run)
    return run
