"""状态流转的唯一入口：校验合法性 + 写留痕（可绑定 AI 产物/评审等 artifact）。

requirements 路由的手动流转与 reviews 路由的评审驱动流转都走这里，
保证"每次状态变更必有 FlowEvent"这一审计不变量。
"""

from sqlalchemy.orm import Session

from .models import FlowEvent, Requirement
from .state_machine import next_status


def apply_transition(
    db: Session,
    req: Requirement,
    action: str,
    operator: str,
    comment: str = "",
    artifact_type: str | None = None,
    artifact_ref: str | None = None,
) -> str:
    """执行一次流转，返回新状态。非法流转抛 InvalidTransition（调用方转 409）。"""
    to = next_status(req.status, action)
    db.add(
        FlowEvent(
            requirement_id=req.id,
            from_status=req.status,
            to_status=to,
            action=action,
            operator=operator,
            comment=comment,
            artifact_type=artifact_type,
            artifact_ref=artifact_ref,
        )
    )
    req.status = to
    return to
