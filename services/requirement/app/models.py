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


class AnalysisRun(Base):
    """可行性分析执行记录（FR-ANA，W5 对接）。

    任务在 api 服务执行（task_id 为其任务号）；终态经 /internal/analysis/callback
    回写本表，succeeded 时驱动 analysis_done 流转并绑定 artifact analysis/<run_id>。
    """

    __tablename__ = "analysis_run"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    requirement_id: Mapped[int] = mapped_column(
        PK, ForeignKey("requirement.id"), index=True
    )
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued/running/succeeded/failed
    summary: Mapped[str] = mapped_column(Text, default="")
    complexity: Mapped[str | None] = mapped_column(String(8), nullable=True)
    report_md: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Review(Base):
    """评审单（FR-REV-01/02）：发起时驱动 start_review 流转，结论驱动 approve/reject。

    participants 存用户名 JSON 数组（用户档案在 identity 服务，跨服务不建外键）。
    conclusion 为空 = 评审中；approved / conditional（有条件通过，同样进入排期）/ rejected。
    """

    __tablename__ = "review"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    requirement_id: Mapped[int] = mapped_column(
        PK, ForeignKey("requirement.id"), index=True
    )
    initiator: Mapped[str] = mapped_column(String(64))
    agenda: Mapped[str] = mapped_column(Text, default="")
    participants: Mapped[str] = mapped_column(Text, default="[]")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    conclusion: Mapped[str | None] = mapped_column(String(16), nullable=True)
    conclusion_comment: Mapped[str] = mapped_column(Text, default="")
    concluded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    concluded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


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
