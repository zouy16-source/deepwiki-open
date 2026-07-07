"""登录认证接口（FR-ADM-01）。

BFF 的 /api/auth/login 调 POST /internal/auth/verify 完成 LDAP 认证；
会话与内部 JWT 签发在 BFF，本服务只负责"验证凭据 + JIT 建档 + 角色聚合 + 审计"。

对客户端只区分三种结果：200 成功 / 401 用户名或密码错误 / 503 目录不可用。
失败细节（用户不存在/密码错误/账号停用）只进审计日志，不回传，避免用户枚举。
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ldap_auth
from ..auth import current_subject
from ..db import get_db
from ..models import AuditLog, Role, User, UserRole
from ..schemas import LoginVerifyRequest, LoginVerifyResponse, RoleGrant, UserOut

router = APIRouter()


def _audit_login(db: Session, username: str, success: bool, reason: str = "") -> None:
    db.add(
        AuditLog(
            actor=username,
            action="login",
            resource_type="auth",
            detail=json.dumps(
                {"success": success, "reason": reason}, ensure_ascii=False
            ),
        )
    )
    db.commit()


@router.post("/verify", response_model=LoginVerifyResponse)
def verify(
    body: LoginVerifyRequest,
    db: Session = Depends(get_db),
    _subject: str = Depends(current_subject),
):
    try:
        ldap_user = ldap_auth.authenticate(body.username, body.password)
    except ldap_auth.LdapUnavailableError as e:
        _audit_login(db, body.username, False, f"ldap_unavailable: {e}")
        raise HTTPException(503, "authentication service unavailable")

    if ldap_user is None:
        _audit_login(db, body.username, False, "invalid_credentials")
        raise HTTPException(401, "invalid username or password")

    user = db.scalar(select(User).where(User.username == ldap_user.username))
    if user is None:
        # JIT 建档：目录只回答"你是谁"，角色由管理员在平台内授予（RBAC 留在平台库）
        user = User(
            username=ldap_user.username,
            display_name=ldap_user.display_name,
            email=ldap_user.email,
            source="sso",
        )
        db.add(user)
        db.flush()
    else:
        if not user.is_active:
            _audit_login(db, body.username, False, "inactive_user")
            raise HTTPException(401, "invalid username or password")
        # 目录是档案权威源：每次登录刷新展示名/邮箱
        user.display_name = ldap_user.display_name or user.display_name
        user.email = ldap_user.email or user.email

    grants = db.execute(
        select(Role.code, UserRole.project_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    ).all()

    _audit_login(db, body.username, True)  # 同一事务提交建档/刷新与审计
    db.refresh(user)

    return LoginVerifyResponse(
        user=UserOut.model_validate(user),
        roles=[RoleGrant(role=code, project_id=pid) for code, pid in grants],
        project_ids=sorted({pid for _, pid in grants if pid is not None}),
    )
