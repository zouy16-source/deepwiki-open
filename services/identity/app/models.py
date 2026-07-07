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
