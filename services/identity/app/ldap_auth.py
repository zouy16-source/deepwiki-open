"""LDAP/AD 认证（FR-ADM-01）：search-then-bind。

平台唯一认证源，无本地回退（已决策）：目录不可达时登录不可用，接口返回 503。

流程与安全约束：
1. 服务账号 bind 后按用户名搜索用户 DN（不依赖匿名搜索，生产目录通常禁匿名）；
2. 用户 DN + 密码二次 bind 完成认证；
3. 空/全空白密码前置拦截——LDAP simple bind 对空密码按匿名 bind 处理并"成功"；
4. 用户名经 RFC 4515 转义后才拼入过滤器，防 LDAP 注入；
5. 搜索命中 0 条（用户不存在）或多条（目录数据异常）一律视为认证失败，不猜测。
"""

import ssl
from dataclasses import dataclass

from ldap3 import Connection, Server, Tls
from ldap3.core.exceptions import LDAPException
from ldap3.utils.conv import escape_filter_chars

from .config import settings


@dataclass
class LdapUser:
    username: str
    display_name: str
    email: str


class LdapUnavailableError(Exception):
    """目录不可达或服务账号配置错误——属部署问题而非用户凭据问题，登录接口应回 503。"""


def _server() -> Server:
    tls = None
    if settings.ldap_url.startswith("ldaps"):
        tls = Tls(
            validate=ssl.CERT_REQUIRED,
            ca_certs_file=settings.ldap_ca_cert_file or None,
        )
    return Server(settings.ldap_url, connect_timeout=settings.ldap_timeout, tls=tls)


def _safe_unbind(conn: Connection) -> None:
    try:
        conn.unbind()
    except LDAPException:
        pass


def _entry_attr(entry, name: str) -> str:
    if not name:
        return ""
    try:
        value = entry[name].value
    except (LDAPException, KeyError, AttributeError):
        return ""
    if value is None:
        return ""
    # 多值属性取第一个
    if isinstance(value, (list, tuple)):
        return str(value[0]) if value else ""
    return str(value)


def authenticate(username: str, password: str) -> LdapUser | None:
    """认证成功返回用户档案；用户名/密码错误返回 None；目录不可用抛 LdapUnavailableError。"""
    if not settings.ldap_url:
        raise LdapUnavailableError("LDAP_URL not configured")
    if not username or not password or not password.strip():
        return None

    search_filter = settings.ldap_user_filter.format(
        username=escape_filter_chars(username)
    )
    server = _server()

    # ① 服务账号搜索用户 DN
    conn = Connection(
        server,
        user=settings.ldap_bind_dn or None,
        password=settings.ldap_bind_password or None,
        receive_timeout=settings.ldap_timeout,
    )
    try:
        if not conn.bind():
            # 服务账号 bind 失败 = 部署配置错误，不能与用户凭据错误混淆
            raise LdapUnavailableError(f"service account bind failed: {conn.result}")
        conn.search(
            settings.ldap_base_dn,
            search_filter,
            attributes=[
                a
                for a in (settings.ldap_attr_display, settings.ldap_attr_email)
                if a
            ],
        )
        entries = list(conn.entries)
    except LdapUnavailableError:
        raise
    except LDAPException as e:
        raise LdapUnavailableError(str(e)) from e
    finally:
        _safe_unbind(conn)

    if len(entries) != 1:
        return None
    entry = entries[0]

    # ② 用户 DN + 密码 bind 验证
    user_conn = Connection(
        server,
        user=entry.entry_dn,
        password=password,
        receive_timeout=settings.ldap_timeout,
    )
    try:
        if not user_conn.bind():
            return None
    except LDAPException as e:
        raise LdapUnavailableError(str(e)) from e
    finally:
        _safe_unbind(user_conn)

    display_name = _entry_attr(entry, settings.ldap_attr_display)
    email = _entry_attr(entry, settings.ldap_attr_email)
    return LdapUser(
        username=username,
        display_name=display_name or username,
        email=email,
    )
