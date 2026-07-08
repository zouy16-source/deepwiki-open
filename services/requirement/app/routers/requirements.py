from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_subject
from ..db import get_db
from ..flow import apply_transition
from ..models import FlowEvent, Requirement
from ..schemas import FlowEventOut, RequirementCreate, RequirementOut, TransitionIn
from ..state_machine import InvalidTransition

router = APIRouter()


@router.post("", response_model=RequirementOut, status_code=201)
def create_requirement(
    body: RequirementCreate,
    db: Session = Depends(get_db),
    subject: str = Depends(current_subject),
):
    if body.parent_id is not None and db.get(Requirement, body.parent_id) is None:
        raise HTTPException(422, f"parent requirement {body.parent_id} not found")
    req = Requirement(creator=subject, **body.model_dump())
    db.add(req)
    db.flush()
    db.add(
        FlowEvent(
            requirement_id=req.id,
            from_status=None,
            to_status=req.status,
            action="create",
            operator=subject,
            # 对话式创建：把对话快照绑定为需求的第一个 AI 产物
            artifact_type="chat" if body.source_context.strip() else None,
            artifact_ref=f"chat/req-{req.id}" if body.source_context.strip() else None,
        )
    )
    db.commit()
    db.refresh(req)
    return req


@router.get("", response_model=list[RequirementOut])
def list_requirements(
    project_id: int | None = None,
    status: str | None = None,
    parent_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    stmt = select(Requirement).order_by(Requirement.id.desc())
    if project_id is not None:
        stmt = stmt.where(Requirement.project_id == project_id)
    if status is not None:
        stmt = stmt.where(Requirement.status == status)
    if parent_id is not None:
        stmt = stmt.where(Requirement.parent_id == parent_id)
    return db.scalars(stmt.limit(min(limit, 200)).offset(offset)).all()


@router.get("/{req_id}", response_model=RequirementOut)
def get_requirement(req_id: int, db: Session = Depends(get_db)):
    req = db.get(Requirement, req_id)
    if req is None:
        raise HTTPException(404, "requirement not found")
    return req


@router.post("/{req_id}/transitions", response_model=RequirementOut)
def transition(
    req_id: int,
    body: TransitionIn,
    db: Session = Depends(get_db),
    subject: str = Depends(current_subject),
):
    req = db.get(Requirement, req_id)
    if req is None:
        raise HTTPException(404, "requirement not found")
    try:
        apply_transition(
            db, req, body.action, subject,
            comment=body.comment,
            artifact_type=body.artifact_type,
            artifact_ref=body.artifact_ref,
        )
    except InvalidTransition as e:
        raise HTTPException(409, str(e))
    db.commit()
    db.refresh(req)
    return req


@router.get("/{req_id}/events", response_model=list[FlowEventOut])
def list_events(req_id: int, db: Session = Depends(get_db)):
    if db.get(Requirement, req_id) is None:
        raise HTTPException(404, "requirement not found")
    return db.scalars(
        select(FlowEvent)
        .where(FlowEvent.requirement_id == req_id)
        .order_by(FlowEvent.id)
    ).all()
