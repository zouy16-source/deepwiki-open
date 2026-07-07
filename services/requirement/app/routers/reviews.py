"""评审协作（FR-REV-01/02）。

评审与状态机的耦合关系（评审是流转的驱动者，不是旁挂的记录）：
- 发起评审：需求必须处于「分析完成」，创建评审单并驱动 start_review → 评审中；
- 录入结论：approved / conditional（有条件通过）→ approve → 已排期；rejected → reject → 已打回。
每次驱动的 FlowEvent 都绑定 artifact（review/<id>），从流转记录可回溯到评审单。
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_subject
from ..db import get_db
from ..flow import apply_transition
from ..models import Requirement, Review
from ..schemas import ReviewConclude, ReviewCreate, ReviewOut
from ..state_machine import InvalidTransition

router = APIRouter()

CONCLUSION_LABELS = {"approved": "通过", "conditional": "有条件通过", "rejected": "打回"}
_TYPE_LABELS = {"business": "业务需求", "system": "系统需求"}


def build_agenda(req: Requirement) -> str:
    """自动生成评审议程（FR-REV-01）。W5 接入分析任务后，「AI 分析结论」段自动附报告摘要。"""
    desc = (req.description or "").strip() or "（未填写）"
    if len(desc) > 800:
        desc = desc[:800] + "…"
    expected = req.expected_online_date.isoformat() if req.expected_online_date else "未设定"
    return f"""# 评审会议程：{req.title}

## 需求摘要
- 编号：#{req.id} · {_TYPE_LABELS.get(req.req_type, req.req_type)} · 优先级 {req.priority}
- 提出人：{req.creator} · 期望上线：{expected}

{desc}

## AI 分析结论
> 待接入分析任务（一期 W5）：此处将自动附可行性分析报告摘要（业务可行性 / 代码可行性 / 复杂度 / 系统范围）。

## 待决议项
1. 需求是否可行，是否通过评审进入排期
2. 需求如何拆分：涉及哪些系统需求（子需求）与团队
3. 初步排期与开发/测试负责人
"""


def _get_requirement(db: Session, req_id: int) -> Requirement:
    req = db.get(Requirement, req_id)
    if req is None:
        raise HTTPException(404, "requirement not found")
    return req


@router.post("/requirements/{req_id}/reviews", response_model=ReviewOut, status_code=201)
def create_review(
    req_id: int,
    body: ReviewCreate,
    db: Session = Depends(get_db),
    subject: str = Depends(current_subject),
):
    req = _get_requirement(db, req_id)
    open_review = db.scalar(
        select(Review).where(Review.requirement_id == req_id, Review.conclusion.is_(None))
    )
    if open_review is not None:
        raise HTTPException(409, f"review {open_review.id} is still open for this requirement")

    review = Review(
        requirement_id=req_id,
        initiator=subject,
        participants=json.dumps(body.participants, ensure_ascii=False),
        scheduled_at=body.scheduled_at,
        agenda=body.agenda or build_agenda(req),
    )
    db.add(review)
    db.flush()

    try:
        apply_transition(
            db, req, "start_review", subject,
            comment="发起评审",
            artifact_type="review", artifact_ref=f"review/{review.id}",
        )
    except InvalidTransition as e:
        raise HTTPException(409, str(e))

    db.commit()
    db.refresh(review)
    return review


@router.get("/requirements/{req_id}/reviews", response_model=list[ReviewOut])
def list_reviews(req_id: int, db: Session = Depends(get_db)):
    _get_requirement(db, req_id)
    return db.scalars(
        select(Review).where(Review.requirement_id == req_id).order_by(Review.id.desc())
    ).all()


@router.get("/reviews/{review_id}", response_model=ReviewOut)
def get_review(review_id: int, db: Session = Depends(get_db)):
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(404, "review not found")
    return review


@router.post("/reviews/{review_id}/conclude", response_model=ReviewOut)
def conclude_review(
    review_id: int,
    body: ReviewConclude,
    db: Session = Depends(get_db),
    subject: str = Depends(current_subject),
):
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(404, "review not found")
    if review.conclusion is not None:
        raise HTTPException(409, f"review already concluded: {review.conclusion}")

    req = _get_requirement(db, review.requirement_id)
    action = "reject" if body.conclusion == "rejected" else "approve"
    label = CONCLUSION_LABELS[body.conclusion]
    comment = f"[评审结论：{label}]" + (f" {body.comment}" if body.comment else "")

    try:
        apply_transition(
            db, req, action, subject,
            comment=comment,
            artifact_type="review", artifact_ref=f"review/{review.id}",
        )
    except InvalidTransition as e:
        raise HTTPException(409, str(e))

    review.conclusion = body.conclusion
    review.conclusion_comment = body.comment
    review.concluded_by = subject
    review.concluded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(review)
    return review
