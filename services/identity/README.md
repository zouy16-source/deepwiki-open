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

## API 骨架

- `GET /health`
- `POST | GET /api/users`；`GET /api/users/me`（内部 JWT 主体）
- `POST | GET /api/projects`；`GET /api/projects/{id}`
- `POST | GET /api/audit-logs`

## 待办（一期内）

- [ ] SSO/LDAP 登录流程（BFF 侧对接，本服务提供用户建档与校验）
- [ ] 角色种子数据（biz/pm/dev/qa/lead/admin）与授权校验 API
- [ ] 项目空间成员管理与代码库绑定授权
- [ ] AI 调用审计的批量写入接口（api 服务上报）
