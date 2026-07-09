"""TAPD 需求同步（单向只读镜像，手动触发）。

流程：当前用户点同步 → 查其 TAPD nick（identity）+ project 绑定的 tapd_workspace_id →
用企业凭证按 owner=nick 拉 TAPD 需求 → 按 (source='tapd', external_id) 幂等 upsert。
平台侧增值数据（AI 分析、评审）通过 requirement_id 外挂，同步覆盖不影响它们。

用户/项目档案在 identity 服务，跨服务经 HTTP 读取（不建外键）。
"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_subject
from ..config import settings
from ..db import get_db
from ..models import Requirement, utcnow
from ..tapd_client import TapdError, fetch_stories
from ..tapd_mapping import map_story

logger = logging.getLogger(__name__)

router = APIRouter()

# story 映射后可被同步覆盖的字段（平台增值字段如 complexity 不在此列，同步不动它们）
_SYNC_FIELDS = (
    "external_url", "external_status", "title", "description",
    "priority", "assignee", "status", "req_type", "external_extra", "project_id",
)


class SyncRequest(BaseModel):
    project_id: int


class SyncResult(BaseModel):
    created: int
    updated: int
    total: int
    workspace_id: str
    owner: str


def _identity_get(path: str) -> dict | None:
    try:
        resp = httpx.get(f"{settings.identity_base_url.rstrip('/')}{path}", timeout=5)
        if resp.status_code == 200:
            return resp.json()
        logger.warning("identity GET %s -> %s", path, resp.status_code)
    except Exception as e:  # noqa: BLE001
        logger.warning("identity GET %s failed: %s", path, e)
    return None


def _resolve_tapd_nick(username: str) -> str:
    """平台 username → TAPD nick。用户列表在 identity；找不到映射则回退用 username。"""
    users = _identity_get("/api/users?limit=200") or []
    for u in users:
        if u.get("username") == username:
            return (u.get("tapd_nick") or "").strip()
    return ""


def _nick_map() -> dict[str, str]:
    """TAPD nick → 平台 username 反查表（回写 assignee 时用）。"""
    users = _identity_get("/api/users?limit=200") or []
    return {u["tapd_nick"]: u["username"] for u in users if u.get("tapd_nick")}


@router.post("/tapd/sync", response_model=SyncResult)
def sync_tapd(
    body: SyncRequest,
    db: Session = Depends(get_db),
    subject: str = Depends(current_subject),
):
    # 1. project 必须绑定了 TAPD workspace
    project = _identity_get(f"/api/projects/{body.project_id}")
    if project is None:
        raise HTTPException(404, "project not found")
    workspace_id = (project.get("tapd_workspace_id") or "").strip()
    if not workspace_id:
        raise HTTPException(400, "该项目未绑定 TAPD workspace（先在项目空间配置 tapd_workspace_id）")

    # 2. 当前用户必须绑定了 TAPD nick（“按当前用户同步”的过滤依据）
    nick = _resolve_tapd_nick(subject) if subject != "dev" else ""
    if subject != "dev" and not nick:
        raise HTTPException(400, "当前用户未绑定 TAPD 账号（先在个人设置绑定 tapd_nick）")
    # dev 免鉴权模式下 nick 空 = 不按 owner 过滤，便于本地/fake 验证

    # 3. 拉取 TAPD 需求
    try:
        stories = fetch_stories(workspace_id, nick)
    except TapdError as e:
        raise HTTPException(502, str(e))

    # 4. 幂等 upsert（按 source='tapd' + external_id）
    nick2user = _nick_map()
    created = updated = 0
    for story in stories:
        sid = str(story.get("id") or "")
        if not sid:
            continue
        owner_nick = (story.get("owner") or "").strip()
        assignee = nick2user.get(owner_nick, owner_nick)  # 映射不到存原 nick
        fields = map_story(story, body.project_id, assignee, creator=subject)

        existing = db.scalar(
            select(Requirement).where(
                Requirement.source == "tapd", Requirement.external_id == sid
            )
        )
        if existing is None:
            db.add(Requirement(**fields, synced_at=utcnow()))
            created += 1
        else:
            for f in _SYNC_FIELDS:
                setattr(existing, f, fields[f])
            existing.synced_at = utcnow()
            updated += 1

    db.commit()
    return SyncResult(
        created=created, updated=updated, total=len(stories),
        workspace_id=workspace_id, owner=nick,
    )
