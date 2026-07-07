"""ldap_auth 单元测试：用假 Server/Connection 覆盖 search-then-bind 的全部分支。

重点是两条安全回归（对应历史 Java 实现的漏洞）：
- 空/空白密码必须在发起 bind 前拒绝（LDAP 匿名 bind 会"成功"）；
- 用户名必须经 RFC 4515 转义后才进过滤器（防注入）。
"""

from types import SimpleNamespace

import pytest
from ldap3.core.exceptions import LDAPSocketOpenError

from app import ldap_auth
from app.ldap_auth import LdapUnavailableError, authenticate


class FakeEntry:
    def __init__(self, dn: str, attrs: dict):
        self.entry_dn = dn
        self._attrs = attrs

    def __getitem__(self, name):
        if name not in self._attrs:
            raise KeyError(name)
        return SimpleNamespace(value=self._attrs[name])


class LdapScript:
    """每个用例配置的假目录行为。第一条连接视为服务账号，第二条视为用户 bind。"""

    def __init__(self):
        self.service_bind_ok = True
        self.user_bind_ok = True
        self.bind_raises = None  # 从 bind() 抛出的异常（模拟目录不可达）
        self.entries = []
        self.searches = []  # (base_dn, filter)
        self.connections = []


@pytest.fixture()
def ldap(monkeypatch):
    script = LdapScript()

    class FakeConnection:
        def __init__(self, server, user=None, password=None, **kwargs):
            self.user = user
            self.password = password
            self.entries = []
            script.connections.append(self)
            self._is_service = len(script.connections) == 1

        def bind(self):
            if script.bind_raises is not None:
                raise script.bind_raises
            if self._is_service:
                return script.service_bind_ok
            return script.user_bind_ok

        def search(self, base_dn, search_filter, attributes=None):
            script.searches.append((base_dn, search_filter))
            self.entries = list(script.entries)
            return bool(self.entries)

        @property
        def result(self):
            return {"description": "fake"}

        def unbind(self):
            return True

    monkeypatch.setattr(ldap_auth, "Server", lambda *a, **kw: object())
    monkeypatch.setattr(ldap_auth, "Connection", FakeConnection)
    monkeypatch.setattr(ldap_auth.settings, "ldap_url", "ldap://fake:389")
    monkeypatch.setattr(ldap_auth.settings, "ldap_base_dn", "dc=test,dc=local")
    monkeypatch.setattr(ldap_auth.settings, "ldap_bind_dn", "cn=svc,dc=test,dc=local")
    monkeypatch.setattr(ldap_auth.settings, "ldap_bind_password", "svcpass")
    return script


def entry(dn="uid=alice,ou=users,dc=test,dc=local", **attrs):
    return FakeEntry(dn, attrs)


def test_success_returns_profile_and_binds_with_user_dn(ldap):
    ldap.entries = [entry(displayName="Alice A", mail="alice@test.local")]

    user = authenticate("alice", "goodpass")

    assert user == ldap_auth.LdapUser(
        username="alice", display_name="Alice A", email="alice@test.local"
    )
    # 第二条连接必须用搜索到的 DN + 用户密码 bind
    assert ldap.connections[1].user == "uid=alice,ou=users,dc=test,dc=local"
    assert ldap.connections[1].password == "goodpass"


def test_empty_and_whitespace_password_rejected_before_any_bind(ldap):
    assert authenticate("alice", "") is None
    assert authenticate("alice", "   ") is None
    assert ldap.connections == []  # 未发起任何 LDAP 连接


def test_username_is_escaped_in_search_filter(ldap):
    ldap.entries = []

    authenticate("admin)(uid=*", "x")

    _, search_filter = ldap.searches[0]
    assert search_filter == r"(uid=admin\29\28uid=\2a)"


def test_wrong_password_returns_none(ldap):
    ldap.entries = [entry(displayName="Alice", mail="a@t")]
    ldap.user_bind_ok = False
    assert authenticate("alice", "badpass") is None


def test_unknown_user_returns_none(ldap):
    ldap.entries = []
    assert authenticate("nobody", "pass") is None


def test_multiple_matches_rejected(ldap):
    ldap.entries = [entry(), entry(dn="uid=alice,ou=other,dc=test,dc=local")]
    assert authenticate("alice", "pass") is None


def test_service_account_bind_failure_raises_unavailable(ldap):
    ldap.service_bind_ok = False
    with pytest.raises(LdapUnavailableError):
        authenticate("alice", "pass")


def test_directory_unreachable_raises_unavailable(ldap):
    ldap.bind_raises = LDAPSocketOpenError("connection refused")
    with pytest.raises(LdapUnavailableError):
        authenticate("alice", "pass")


def test_missing_ldap_url_raises_unavailable(monkeypatch):
    monkeypatch.setattr(ldap_auth.settings, "ldap_url", "")
    with pytest.raises(LdapUnavailableError):
        authenticate("alice", "pass")


def test_missing_attributes_fall_back(ldap):
    ldap.entries = [entry()]  # 目录里没有 displayName/mail

    user = authenticate("alice", "pass")

    assert user.display_name == "alice"
    assert user.email == ""
