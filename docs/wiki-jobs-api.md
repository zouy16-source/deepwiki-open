# Wiki 生成任务系统 — 接口契约 & 状态机(草案 v0.1)

把"生成 wiki"从前端编排迁到**后端后台任务**。前端退化为瘦客户端:发起任务 → 轮询进度 → 完成查看。本文定义 API 契约、Job 对象、状态机、阶段/进度/ETA 语义。

> 状态:**草案,待评审**。带 ⚠️ 的是需要拍板的开放问题。

---

## 0. 设计原则

1. **按缓存 key 幂等 + 去重**:同一个 `(repo_type, owner, repo, language, comprehensive)` 同时只跑一个任务;重复发起返回同一个 job(多个客户端订阅同一进度)。
2. **非阻塞**:`POST /generate` 立即返回 job(202),实际生成在后台 asyncio 任务里跑。
3. **轮询优先**:列表轮询 `GET /jobs`(2–3s);需要更实时再加 SSE。
4. **并发受控**:全局信号量上限(配置),超出排队。
5. **缓存是事实来源**:"已生成"以缓存/`processed_projects` 为准;job 只表达"正在生成/刚结束"。

---

## 1. Job 对象

```jsonc
{
  "id": "job_8f3a2c…",                 // UUID
  "key": {                             // 身份 = 缓存 key
    "owner": "cargo",
    "repo": "brazil_backend_api",      // 嵌套组已扁平化(/→_)
    "repo_type": "gitlab",
    "language": "zh",
    "comprehensive": true
  },
  "repo_url": "http://git.ymdd.tech/cargo/brazil/backend/api",  // 真实地址(克隆用)
  "status": "running",                 // queued|running|succeeded|partial|failed|canceled
  "phase": "generating",               // fetching_repo|indexing|planning|generating|saving|null
  "progress": {
    "percent": 62,                     // 0..100 总进度
    "total_pages": 11,                 // planning 完成前为 null
    "done_pages": 6,
    "failed_pages": 0,
    "current_page": "数据流与状态管理"    // 正在生成的页标题,空闲为 null
  },
  "timing": {
    "created_at": "2026-06-30T08:00:00Z",
    "started_at": "2026-06-30T08:00:03Z",  // 拿到并发槽、真正开跑
    "updated_at": "2026-06-30T08:04:10Z",
    "finished_at": null,
    "elapsed_seconds": 247,
    "eta_seconds": 150                 // 预计剩余秒;未知为 null
  },
  "queue_position": null,              // status=queued 时 ≥1
  "model": { "provider": "openai", "model": "qwen-plus", "is_custom": false },
  "cache_ready": false,               // 缓存已就绪可查看(saving 完成后 true)
  "error": null                       // 失败时 { "code": "...", "message": "..." }
}
```

**字段说明**

| 字段 | 含义 |
|---|---|
| `id` | 任务唯一 ID(UUID)。后端另维护 `key → id` 索引做去重 |
| `key` | 身份,等于 wiki 缓存 key;规范串 `gitlab:cargo:brazil_backend_api:zh:true` |
| `status` | 生命周期(见状态机) |
| `phase` | running 期间的子阶段;非 running 为 null |
| `progress.percent` | 总进度(阶段加权,见 §4) |
| `progress.total_pages` | planning 完成后才知道(LLM 决定 4–12 页) |
| `eta_seconds` | 预计剩余;generating 期 `剩余页 × 每页均值`,之前用历史/启发式 |
| `cache_ready` | true 后前端可直接「查看」 |
| `error.code` | 见 §5 错误码 |

---

## 2. 接口契约

### 2.1 `POST /api/wiki/generate` — 发起(或加入)生成

**Request**
```jsonc
{
  "repo_url": "http://git.ymdd.tech/cargo/brazil/backend/api",
  "repo_type": "gitlab",
  "owner": "cargo",
  "repo": "brazil_backend_api",
  "language": "zh",
  "comprehensive": true,
  "provider": "openai",
  "model": "qwen-plus",
  "is_custom_model": false,
  "custom_model": "",
  "token": "",                         // 私有库可选 token
  "excluded_dirs": "", "excluded_files": "",
  "included_dirs": "", "included_files": "",
  "force": false                       // true=即使有缓存/在跑也重生成
}
```

**行为(幂等/去重)**
- 由 `(repo_type, owner, repo, language, comprehensive)` 算 key。
- `force=false`:
  - 已有缓存 → `200`,返回合成 job `{status:"succeeded", cache_ready:true}`(前端直接查看)。
  - 已有 `queued`/`running` 任务 → `200`,返回那个 job(去重,客户端去订阅)。
  - 否则 → 新建,`202 Accepted` + Job。
- `force=true`:取消同 key 在跑任务 + 删缓存 → 新建。

**Response**:`202`(新建)/ `200`(命中已有)+ Job
**错误**:`400` 参数错;`401` 鉴权(⚠️ 见开放问题);`503` 不可用。

### 2.2 `GET /api/wiki/jobs` — 列表(给项目列表轮询)

**Query**:`?status=queued,running&owner=&repo=&limit=100`(默认返回 active + 近 N 分钟已结束)
**Response**
```jsonc
{
  "jobs": [ /* Job[] */ ],
  "active": 3,            // running + queued 数
  "capacity": 3          // 全局并发上限
}
```
> 已结束的 job 保留一个 TTL(如 10 min)让列表能显示"刚完成",之后丢弃(以缓存为准)。

### 2.3 `GET /api/wiki/jobs/{id}` — 单个详情
**Response**:Job。`404` 未知/已过期。

### 2.4 `DELETE /api/wiki/jobs/{id}` — 取消
取消 `queued`/`running` 任务。**Response**:Job(status=canceled)。`409` 已结束;`404` 未知。

### 2.5 `GET /api/wiki/jobs/{id}/events` — SSE 进度流(可选,二期)
```
event: progress
data: { /* Job 快照 */ }
```
终态后 `event: done` 并关闭。⚠️ 一期可只做轮询,SSE 后补。

---

## 3. 状态机(status 生命周期)

```
                    ┌───────────── cancel ─────────────┐
                    │                                  ▼
 create ──> queued ───(拿到并发槽)──> running ───────> succeeded   (全部页 OK + 已存缓存)
              │                          │     └──────> partial     (已存缓存,但 ≥1 页失败,仍可看)
              │                          ├────────────> failed       (出错且无可用缓存)
              └──────── cancel ──────────┴─ cancel ───> canceled
```

| status | 含义 | 终态? |
|---|---|---|
| `queued` | 等并发槽(信号量满) | 否 |
| `running` | 正在跑,phase 推进 | 否 |
| `succeeded` | 全部页生成 + 缓存已存 | ✅ |
| `partial` | 缓存已存,但有页失败(可查看,带告警) | ✅ |
| `failed` | 在产出可用缓存前中止(拉取/索引/planning 失败,或全页失败) | ✅ |
| `canceled` | 用户/force 取消 | ✅ |

> 终态 job 保留 TTL 后清理。`cache_ready=true` 的(succeeded/partial)前端转「查看」。

---

## 4. 阶段(phase)+ 进度/ETA 语义

**phase 顺序(仅 running)**

| phase | 做什么 | 备注 |
|---|---|---|
| `fetching_repo` | 克隆 + 文件树 + README | gitlab file_tree / github API / 本地 |
| `indexing` | 建 embedding / RAG 索引 | **首次最久**,随仓库大小波动;当前后端是首条 chat 时惰性建,任务化建议显式成一阶段 |
| `planning` | 出结构 XML → 解析 | 完成后 `total_pages` 才已知 |
| `generating` | 逐页生成 1..N | `done_pages/total_pages` 驱动进度 |
| `saving` | 写缓存 | 完成 `cache_ready=true` |

**进度加权(建议,可调)**

| phase | percent 区间 |
|---|---|
| fetching_repo | 0 → 5 |
| indexing | 5 → 25(粗略,可不确定) |
| planning | 25 → 35 |
| generating | 35 → 95(按 `done_pages/total_pages` 线性) |
| saving | 95 → 100 |

**ETA**
- `generating` 期:`eta = 剩余页 × 每页均值`,均值优先取**本任务已完成页的实测**,回退**该 model 的历史滚动均值**,再回退常量(~40s/页)。
- `generating` 之前:粗估(历史 / 仓库规模)或 `null`。
- 实测每页耗时应落库(stats),持续优化全局 ETA。

---

## 5. 错误码(error.code)

| code | 触发 | 一般后果 |
|---|---|---|
| `repo_fetch_failed` | 克隆 / 取文件树失败 | failed |
| `embedding_failed` | embedding provider key 缺失 / 报错(OPENAI/GOOGLE key) | failed |
| `embedding_model_not_found` | Ollama embedding 模型未找到 | failed |
| `planning_failed` | 无有效 XML / 结构 LLM 出错 | failed |
| `page_generation_failed` | 单页失败 | 计入 `failed_pages`,任务继续 |
| `all_pages_failed` | 所有页失败 | failed |
| `auth_required` / `auth_invalid` | 鉴权模式下缺/错授权码 | failed(401 起手) |
| `canceled` | 被取消 | canceled |
| `internal_error` | 其它 | failed |

---

## 6. 并发 / 去重 / 持久化

- **全局并发**:`MAX_CONCURRENT_JOBS`(默认 3)信号量;超出 → `queued` + `queue_position`。
- **单任务内逐页并发**:默认 1(顺序),可配小并发,避免打爆 LLM 限流。
- **去重**:一个 key 一个任务;`key → job_id` 索引。
- **持久化**(⚠️ 拍板):
  - 一期 **内存 dict** 最简:后端重启 → 在跑任务丢失(前端再轮询发现无 job,缓存有则可看、无则重发起)。
  - 产品级 **Redis / SQLite**:任务表 + 队列持久,重启可恢复 / 多 worker。

---

## 7. 前端集成草图

- **项目列表**:进页 `GET /jobs` 按 key 建索引;每行——有 job → 显示**进度条 + 阶段 + ETA(+ 取消)**;无 job → `查看`(缓存/processed_projects 命中)或 `生成`。有 active 时每 2–3s 轮询。
- **生成按钮** → `POST /generate` → 乐观插入 job → 轮询。
- **详情页**:订阅 `/jobs/{id}/events` 或轮询 `/jobs/{id}`;`succeeded/partial` 后读缓存渲染。
- **取消** → `DELETE /jobs/{id}`。

---

## 8. 已定决策 ✅(2026-06-30 拍板)

| # | 决策点 | 结论 |
|---|---|---|
| 1 | 持久化 | 一期 **内存 dict**;产品化再上 Redis |
| 2 | 进度通道 | 一期 **只轮询**;SSE 二期补 |
| 3 | 鉴权 | 复用现有 `DEEPWIKI_AUTH_MODE` / `DEEPWIKI_AUTH_CODE` |
| 4 | partial 策略 | 沿用现状:**存部分内容 + 占位**,可查看 |
| 5 | 失败页重试 | **自动重试 1 次** |
| 6 | indexing 阶段 | **显式成独立阶段**(进度更准) |
| 7 | job_id 方案 | **UUID + `key → job_id` 索引** |
| 8 | 已结束 job TTL | **10 分钟** |

> 缓存 key 实为 `(repo_type, owner, repo, language)`(后端缓存文件名不含 comprehensive)。job 的 key **额外带 comprehensive** 用于任务去重粒度(comprehensive/concise 视为不同任务),但"是否已有缓存"按 `(repo_type, owner, repo, language)` 判断。

---

## 9. 移植对照(从现有前端编排 → 后端)

| 现前端(TS) | 迁到后端(Python) |
|---|---|
| `useWikiData.fetchRepositoryStructure` | `fetching_repo` 阶段 |
| 首条 `/ws/chat` 惰性建索引 | `indexing` 阶段(可显式化) |
| `determineWikiStructure`(XML 解析) | `planning` 阶段 |
| 逐页 `generatePageContent` 循环 | `generating` 阶段 + 信号量 |
| `wikiPrompts.ts` 提示词 | 移植成 Python 常量/模板 |
| `saveCache`(POST /api/wiki_cache) | `saving` 阶段(后端直接写) |
| 前端进度 state | Job.progress(轮询/SSE 暴露) |
