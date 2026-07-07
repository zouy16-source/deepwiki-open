# identity-service（身份与系统管理服务）

AI研发管理平台的身份与系统管理服务，承载 **模块十一**：SSO/LDAP 接入、用户/角色 RBAC、
项目空间（权限与知识库授权的隔离边界）、审计日志（含 AI 调用记录归集）。
详见 [docs/admin.md](../../docs/admin.md) 与 [docs/admin-phase1-plan.md](../../docs/admin-phase1-plan.md) §3.1。

## 本地运行

```bash
cd services/identity
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
DATABASE_URL=sqlite:///./dev.db DB_AUTO_CREATE=true .venv/bin/uvicorn app.main:app --port 8003 --reload
```

MySQL（与 docker-compose 一致）：`DATABASE_URL=mysql+pymysql://root:devroot@localhost:3306/identity_db`

环境变量与迁移命令同 [requirement-service](../requirement/README.md)（`DATABASE_URL` / `DB_AUTO_CREATE` / `INTERNAL_JWT_SECRET`）。

## LDAP/AD 登录（FR-ADM-01）

LDAP 是平台**唯一认证源**（已决策不做本地回退：目录不可达 = 登录不可用，接口回 503）。
认证流程为 search-then-bind：服务账号搜索用户 DN → 用户 DN + 密码二次 bind；
空密码前置拦截（防匿名 bind 绕过）、用户名 RFC 4515 转义（防过滤器注入）。实现见 `app/ldap_auth.py`。

| 环境变量 | 说明 | 示例 |
| --- | --- | --- |
| `LDAP_URL` | 目录地址，生产用 ldaps；留空则登录一律 503 | `ldaps://ldap.corp.com:636` |
| `LDAP_BASE_DN` | 搜索起点 | `dc=corp,dc=com` |
| `LDAP_BIND_DN` / `LDAP_BIND_PASSWORD` | 搜索用服务账号（不依赖匿名搜索） | `cn=svc-devflow,ou=svc,dc=corp,dc=com` |
| `LDAP_USER_FILTER` | 用户过滤器模板；AD 域用 sAMAccountName | `(uid={username})` |
| `LDAP_ATTR_DISPLAY` / `LDAP_ATTR_EMAIL` | 档案属性映射 | `displayName` / `mail` |
| `LDAP_CA_CERT_FILE` | ldaps 证书校验 CA（留空用系统信任库） | `/etc/ssl/corp-ca.pem` |

本地开发**直接对接企业 LDAP/AD**（不起本地目录容器）：在仓库根目录 `.env` 配置上表 `LDAP_*` 变量即可。
不想连目录调试时，把 `INTERNAL_JWT_SECRET` 留空 = 免鉴权模式（BFF 不强制登录，服务端主体为 `dev`），不影响其他功能开发。

## API 骨架

- `GET /health`
- `POST /internal/auth/verify` — BFF 登录调用：LDAP 认证 + JIT 建档 + 角色聚合 + 登录审计（200/401/503）
- `POST | GET /api/users`；`GET /api/users/me`（内部 JWT 主体）
- `POST | GET /api/projects`；`GET /api/projects/{id}`
- `POST | GET /api/audit-logs`

## 待办（一期内）

- [x] SSO/LDAP 登录流程（BFF 侧对接，本服务提供用户建档与校验）
- [ ] 角色种子数据（biz/pm/dev/qa/lead/admin）与授权校验 API
- [ ] 项目空间成员管理与代码库绑定授权
- [ ] AI 调用审计的批量写入接口（api 服务上报）
