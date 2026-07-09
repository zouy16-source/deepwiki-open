from datetime import date, datetime, timezone

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

# MySQL 用 BIGINT 主键；SQLite（本地快速验证/单测）退化为 INTEGER 以支持自增
PK = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Requirement(Base):
    __tablename__ = "requirement"
    # 外部来源需求（TAPD）幂等键：同一来源同一外部 id 唯一。native 需求 external_id 为 NULL，
    # MySQL 唯一约束允许多个 NULL，不影响平台原生需求。
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_requirement_source_external"),
    )

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
    # 对话式创建时的对话快照（产品×代码库 AI）；作为可行性分析 agent 的种子线索
    source_context: Mapped[str] = mapped_column(Text, default="")
    creator: Mapped[str] = mapped_column(String(64))

    # --- 外部来源（TAPD 同步镜像，单向只读；native = 平台原生）---
    # 新增 NOT NULL 列带 server_default，保证对已有行的 ALTER TABLE 安全（迁移教训）
    source: Mapped[str] = mapped_column(String(16), default="native", server_default="native", index=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_url: Mapped[str] = mapped_column(String(512), default="", server_default="")
    external_status: Mapped[str] = mapped_column(String(64), default="", server_default="")  # TAPD 原始状态（v_status 中文）
    assignee: Mapped[str] = mapped_column(String(255), default="", server_default="")  # 处理人（映射后 username，映射不到存原 nick）
    # TEXT 在 MySQL 不能有 server_default，故置 nullable；读写侧按空串/"{}" 兜底
    external_extra: Mapped[str | None] = mapped_column(Text, nullable=True, default="{}")  # TAPD 全量字段兜底（JSON）：迭代/自定义字段/附件链接/工时等
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

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
