from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

# MySQL 用 BIGINT 主键；SQLite（本地快速验证/单测）退化为 INTEGER 以支持自增
PK = BigInteger().with_variant(Integer, "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(64), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    source: Mapped[str] = mapped_column(String(16), default="sso")  # sso | local
    # TAPD 账号（nick）：按当前用户同步 TAPD 需求时用作 owner 过滤（用企业凭证 + 此 nick 过滤）
    tapd_nick: Mapped[str] = mapped_column(String(64), default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Role(Base):
    __tablename__ = "role"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # biz/pm/dev/qa/lead/admin
    name: Mapped[str] = mapped_column(String(64))


class UserRole(Base):
    """RBAC：用户-角色绑定；project_id 为空表示全局角色（如平台管理员）。"""

    __tablename__ = "user_role"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(PK, ForeignKey("user.id"), index=True)
    role_id: Mapped[int] = mapped_column(PK, ForeignKey("role.id"))
    project_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)


class Project(Base):
    """项目空间：权限与代码知识库授权的隔离边界（FR-ADM-02）。"""

    __tablename__ = "project"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    # 绑定的代码库（FR-KB-01/FR-ADM-02）：本地 clone 目录名 JSON 数组（如 ["eopl_galaxy-waybill"]），
    # 可行性分析 Agent 据此确定检索范围
    repos: Mapped[str] = mapped_column(Text, default="[]")
    # 代码库补充元数据（FR-DEV-01）：名字 → {git_url, default_branch} 的 JSON 映射。
    # 与 repos（名字）解耦——名字给分析 Agent 读本地 clone 用，git_url 给编码 Worker fresh clone 用。
    # 名字在 repos 里但此处无条目 = 该库没配 git 地址（编码需手填/走别的库）。TEXT 不能 server_default 故 nullable。
    repo_meta: Mapped[str | None] = mapped_column(Text, nullable=True, default="{}")
    # TAPD workspace（项目）id：同步 TAPD 需求时映射到本 project；空 = 未接入 TAPD
    tapd_workspace_id: Mapped[str] = mapped_column(String(32), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    """操作审计（FR-ADM-04），含 AI 调用记录归集（模型/Token 摘要放 detail JSON）。"""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(32), index=True)
    resource_id: Mapped[str] = mapped_column(String(64), default="")
    detail: Mapped[str] = mapped_column(Text, default="")  # JSON 文本；高频查询字段再抽实体列
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
