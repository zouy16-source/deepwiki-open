# requirement-service（需求域服务）

AI研发管理平台的需求域服务，承载 **模块一（需求管理中心）+ 模块三（评审协作）**：
需求 CRUD、全生命周期状态机与留痕、主/子需求树、业务↔系统需求关联、评审、通知。
详见 [docs/admin.md](../../docs/admin.md) 与 [docs/admin-phase1-plan.md](../../docs/admin-phase1-plan.md) §3.1。

## 本地运行

```bash
cd services/requirement
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
# SQLite 快速起步（无需 MySQL）：
DATABASE_URL=sqlite:///./dev.db DB_AUTO_CREATE=true .venv/bin/uvicorn app.main:app --port 8002 --reload
```

MySQL（与 docker-compose 一致）：`DATABASE_URL=mysql+pymysql://root:devroot@localhost:3306/requirement_db`

## 环境变量

| 变量 | 说明 | 默认 |
| --- | --- | --- |
| `DATABASE_URL` | SQLAlchemy 连接串 | 本地 MySQL requirement_db |
| `DB_AUTO_CREATE` | 启动时建表（仅开发；生产用 alembic） | false |
| `INTERNAL_JWT_SECRET` | BFF 下发的内部 JWT 密钥；留空 = 关闭鉴权（仅本地） | 空 |

## 迁移

```bash
.venv/bin/alembic revision --autogenerate -m "init tables"
.venv/bin/alembic upgrade head
```

## API 骨架

- `GET /health`
- `POST /api/requirements` 创建需求（草稿态，写 create 留痕）
- `GET /api/requirements?project_id=&status=&parent_id=` 列表
- `GET /api/requirements/{id}` / `GET /api/requirements/{id}/events`
- `POST /api/requirements/{id}/transitions` 状态流转 `{action, comment, artifact_type, artifact_ref}`
  —— 动作合法性由 `app/state_machine.py` 表驱动校验，AI 产物经 artifact 字段绑定到流转节点

## 待办（一期内）

- [ ] 评审（FR-REV-01/02）：评审单模型 + 结论驱动 approve/reject 流转
- [ ] 通知（IM/邮件）出站适配
- [ ] 调用 api 服务发起可行性分析任务，结果回调后 analysis_done 流转
- [ ] 业务↔系统需求 link 表（当前仅 parent_id 树）
