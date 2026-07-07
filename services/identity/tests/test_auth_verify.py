"""POST /internal/auth/verify 接口测试（LDAP 层 mock 掉，见 test_ldap_auth.py）。"""

import json

import jwt as pyjwt
import pytest
from sqlalchemy import select

from app import ldap_auth
from app.auth import settings as auth_settings
from app.ldap_auth import LdapUnavailableError, LdapUser
from app.models import AuditLog, Role, User, UserRole

VERIFY = "/internal/auth/verify"


@pytest.fixture()
def ldap_ok(monkeypatch):
    def fake_auth(username, password):
        if password == "goodpass":
            return LdapUser(
                username=username, display_name=f"{username} 显示名", email=f"{username}@corp.local"
            )
        return None

    monkeypatch.setattr(ldap_auth, "authenticate", fake_auth)


def last_audit(db):
    return db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()


def test_first_login_jit_provisions_user(client, db, ldap_ok):
    resp = client.post(VERIFY, json={"username": "alice", "password": "goodpass"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["username"] == "alice"
    assert body["user"]["display_name"] == "alice 显示名"
    assert body["user"]["source"] == "sso"
    assert body["roles"] == []
    assert body["project_ids"] == []

    user = db.scalar(select(User).where(User.username == "alice"))
    assert user is not None and user.is_active

    audit = last_audit(db)
    assert audit.action == "login" and audit.actor == "alice"
    assert json.loads(audit.detail)["success"] is True


def test_relogin_refreshes_profile_not_duplicates(client, db, ldap_ok, monkeypatch):
    client.post(VERIFY, json={"username": "alice", "password": "goodpass"})

    def updated(username, password):
        return LdapUser(username=username, display_name="Alice 新名字", email="new@corp.local")

    monkeypatch.setattr(ldap_auth, "authenticate", updated)
    resp = client.post(VERIFY, json={"username": "alice", "password": "goodpass"})

    assert resp.status_code == 200
    users = db.scalars(select(User).where(User.username == "alice")).all()
    assert len(users) == 1
    assert users[0].display_name == "Alice 新名字"
    assert users[0].email == "new@corp.local"


def test_wrong_password_generic_401(client, db, ldap_ok):
    resp = client.post(VERIFY, json={"username": "alice", "password": "badpass"})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid username or password"
    assert db.scalar(select(User).where(User.username == "alice")) is None  # 失败不建档
    assert json.loads(last_audit(db).detail)["reason"] == "invalid_credentials"


def test_ldap_unavailable_returns_503(client, db, monkeypatch):
    def boom(username, password):
        raise LdapUnavailableError("connection refused")

    monkeypatch.setattr(ldap_auth, "authenticate", boom)
    resp = client.post(VERIFY, json={"username": "alice", "password": "goodpass"})

    assert resp.status_code == 503
    assert json.loads(last_audit(db).detail)["reason"].startswith("ldap_unavailable")


def test_inactive_user_rejected_with_generic_401(client, db, ldap_ok):
    db.add(User(username="alice", source="sso", is_active=False))
    db.commit()

    resp = client.post(VERIFY, json={"username": "alice", "password": "goodpass"})

    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid username or password"
    assert json.loads(last_audit(db).detail)["reason"] == "inactive_user"


def test_roles_and_projects_aggregated(client, db, ldap_ok):
    user = User(username="alice", source="sso")
    admin = Role(code="admin", name="平台管理员")
    dev = Role(code="dev", name="开发")
    db.add_all([user, admin, dev])
    db.flush()
    db.add_all(
        [
            UserRole(user_id=user.id, role_id=admin.id, project_id=None),  # 全局角色
            UserRole(user_id=user.id, role_id=dev.id, project_id=7),
            UserRole(user_id=user.id, role_id=dev.id, project_id=3),
        ]
    )
    db.commit()

    body = client.post(VERIFY, json={"username": "alice", "password": "goodpass"}).json()

    assert {(r["role"], r["project_id"]) for r in body["roles"]} == {
        ("admin", None),
        ("dev", 7),
        ("dev", 3),
    }
    assert body["project_ids"] == [3, 7]


def test_empty_password_rejected_by_schema(client, ldap_ok):
    resp = client.post(VERIFY, json={"username": "alice", "password": ""})
    assert resp.status_code == 422


def test_requires_service_jwt_when_auth_enabled(client, ldap_ok, monkeypatch):
    monkeypatch.setattr(auth_settings, "internal_jwt_secret", "test-secret")

    no_token = client.post(VERIFY, json={"username": "alice", "password": "goodpass"})
    assert no_token.status_code == 401

    token = pyjwt.encode({"sub": "svc:bff"}, "test-secret", algorithm="HS256")
    ok = client.post(
        VERIFY,
        json={"username": "alice", "password": "goodpass"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert ok.status_code == 200
