from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog
from ..schemas import AuditLogCreate, AuditLogOut

router = APIRouter()


@router.post("", response_model=AuditLogOut, status_code=201)
def create_audit_log(body: AuditLogCreate, db: Session = Depends(get_db)):
    log = AuditLog(**body.model_dump())
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


@router.get("", response_model=list[AuditLogOut])
def list_audit_logs(
    actor: str | None = None,
    resource_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if actor is not None:
        stmt = stmt.where(AuditLog.actor == actor)
    if resource_type is not None:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    return db.scalars(stmt.limit(min(limit, 200)).offset(offset)).all()
