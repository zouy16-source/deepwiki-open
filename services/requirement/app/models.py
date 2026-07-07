from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

# MySQL 用 BIGINT 主键；SQLite（本地快速验证/单测）退化为 INTEGER 以支持自增
PK = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Requirement(Base):
    __tablename__ = "requirement"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(BigInteger, index=True)
    # 主/子需求树：业务需求（business）可拆多个系统需求（system）
    parent_id: Mapped[int | None] = mapped_column(
        PK, ForeignKey("requirement.id"), nullable=True, index=True
    )
    req_type: Mapped[str] = mapped_column(String(16), default="business")
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    priority: Mapped[str] = mapped_column(String(8), default="P1")
    complexity: Mapped[str | None] = mapped_column(String(8), nullable=True)  # S/M/L/XL
    expected_online_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    creator: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class FlowEvent(Base):
    """状态流转留痕：操作人/时间/意见 + 关联 AI 产物（分析报告、文档、MR、测试结果）。"""

    __tablename__ = "flow_event"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    requirement_id: Mapped[int] = mapped_column(
        PK, ForeignKey("requirement.id"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(32))
    operator: Mapped[str] = mapped_column(String(64))
    comment: Mapped[str] = mapped_column(Text, default="")
    artifact_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    artifact_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
