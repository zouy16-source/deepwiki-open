# services/ — AI研发管理平台后端服务

后端按模块拆分服务（见 [docs/admin-phase1-plan.md](../docs/admin-phase1-plan.md) §3.1 工程结构）：

| 服务 | 模块 | 端口 | 存储 |
| --- | --- | --- | --- |
| [requirement](./requirement/) | 模块一（需求管理中心）+ 模块三（评审协作）+ TAPD 同步 | 8002 | MySQL `requirement_db` |
| [identity](./identity/) | 模块十一（SSO/RBAC/项目空间/审计） | 8003 | MySQL `identity_db` |
| `../api/`（存量演进） | 模块二（AI 可行性分析）+ 模块八（代码知识库） | 8001 | LocalDB + FAISS 本地索引 |

统一约定：

- 前端只面向 `web/` 的 Nitro BFF 单入口；BFF 将会话换成内部 JWT（HS256，`INTERNAL_JWT_SECRET`）下发给各服务
- 登录链路：BFF `/api/auth/login` → identity `/internal/auth/verify`（LDAP search-then-bind，**唯一认证源，无本地回退**）→ BFF 写 httpOnly 会话 cookie；`INTERNAL_JWT_SECRET` 为空 = 本地开发免鉴权
- 平台 API 代理：BFF `/api/{requirements,users,projects,audit-logs}/**` 同路径转发至对应服务（`web/server/utils/platformProxy.ts`），转发时校验会话并以会话用户为 sub 即签短时内部 JWT；会话 cookie 不透传给内部服务
- 每服务独立 MySQL schema 与 alembic 迁移，**禁止跨库 join**，跨域数据经 API 聚合
- **schema 变更一律走 alembic**（init 迁移已就位，现网库已 stamp 到 head）：改 models → `alembic revision --autogenerate -m "..."` → 审查生成的迁移（新增 NOT NULL 列必须带 server_default 或回填）→ `alembic upgrade head`；`DB_AUTO_CREATE` 仅用于本地 SQLite 快速起步，它不会 ALTER 已存在的表
- requirement 调用 api 服务发起分析任务，结果经事件/回调回写，避免双向强耦合
- **TAPD 同步**（单向只读镜像，过渡期）：`POST /api/tapd/sync {project_id}` 用企业凭证按当前用户 tapd_nick(owner) 拉 TAPD 需求，按 `(source='tapd', external_id)` 幂等 upsert；镜像需求 `status='synced'` 不进平台状态机（只读，不可流转/编辑），但可发起 AI 分析（增值）。凭证配置 `TAPD_API_USER`/`TAPD_API_PASSWORD`（`TAPD_FAKE=true` 用内置样例离线验证）。用户 TAPD 账号（identity `user.tapd_nick`）、项目 workspace 映射（identity `project.tapd_workspace_id`）
- 新服务复制 requirement 的目录结构与约定（config/db/auth/models/schemas/routers + alembic）

本地一键起后端：仓库根目录 `docker-compose up mysql requirement identity`（api 服务见根 README）。
