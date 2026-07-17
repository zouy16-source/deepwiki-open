# services/dev —— AI 编码执行(Worker / Runtime Dispatcher)

Phase-3(FR-DEV-01)的执行层。落地决策见 [`docs/admin-phase3-coding-engine.md`](../../docs/admin-phase3-coding-engine.md) §5。

**架构(K8s 式)**:平台控制面把一个编码任务派给一个 **Worker(Pod)**;Worker 只管在一份 clone 上把代码改对,**换引擎只动 Worker,控制面零改动**。

```
控制面(平台后端) → RuntimeDispatcher → CodingWorker(Pod)
                         │                    └─ ClaudeCodeWorker(第一个,直连 Claude API)
                         │                    └─ (将来) OpenHandsWorker / MiniSweWorker …
   workspace 生命周期 ────┘  clone·切分支·commit·算 diff·(seam)push+PR
```

## 现在能跑什么(S1 核)

`clone → Claude Code 自主改 → 统一 commit → 出 diff`,本地可跑通:

```bash
npm i -g @anthropic-ai/claude-code      # 装 claude CLI(一次)
export ANTHROPIC_API_KEY=sk-ant-...      # 起步直连 Claude API(数据出海,已知情)

python services/dev/run_worker.py \
  --repo /path/to/a/git/repo \
  --title "给 README 顶部加一行标题" \
  --desc  "在 README.md 第一行加 '# Hello from AI Worker'" \
  --base  main
```

输出:分支名、引擎总结、统一 diff。`--repo` 可以是远程 URL 或本地仓库路径(本地路径作 clone 源,**原仓库不受影响**)。

> 将来接国产模型:给 `ClaudeCodeWorker` 的运行环境设 `ANTHROPIC_BASE_URL` 指向 [`poc/coding-engine/`](../../poc/coding-engine/) 网关即可,本 adapter 不用改。

### 一路跑到 GitLab MR(git.ymdd.tech)

`git.ymdd.tech` = 自建 **GitLab**,故 PR = **Merge Request**。加 `--open-pr` 即在 `commit` 后 push 分支并开 MR:

```bash
export GITLAB_TOKEN=glpat-...     # Personal/Project Access Token,scope: api + 可 push,角色 ≥ Developer
# 自签证书内网:export GITLAB_INSECURE=1
python services/dev/run_worker.py \
  --repo https://git.ymdd.tech/galaxy/waybill.git \
  --title "..." --desc "..." --base main \
  --open-pr            # 若服务端拒绝浅克隆 push,再加 --full-clone
```

产出从 `branch+diff` 变成 **MR URL**。token 只用于 push URL 与 API 头,**不写进任何进度事件/日志**(有 `_redact`)。

## 代码结构

| 文件 | 作用 |
|---|---|
| `app/coding/models.py` | 契约:`CodingTask` / `WorkerResult` / `ProgressEvent`(零外部依赖) |
| `app/coding/worker.py` | `CodingWorker` 抽象 + `RuntimeDispatcher`(workspace/git 生命周期)+ `GitOps` 钩子协议 |
| `app/coding/claude_code_worker.py` | Claude Code 适配器(`claude -p --output-format stream-json` 无头子进程 + 事件解析) |
| `app/coding/gitlab_ops.py` | **GitLab GitOps**:push 分支 + 建 MR(git.ymdd.tech,纯 stdlib) |
| `run_worker.py` | 本地跑通器(CLI) |

## seam 状态

- ✅ **出口 · push + 开 PR(GitLab MR)** —— `GitLabGitOps` 已实现,`--open-pr` 可用。
- ⬜ **入口 · TAPD 触发**:平台在需求/任务进入"开发"态时,组一个 `CodingTask`(repo/base/描述 + 复用已有 agentic 调查/术语表结论作 `extra_context`)投给 `RuntimeDispatcher`。可复用 `services/requirement` 的 flow / `api` 的 agentic 调查。
- ⬜ **CI · Jenkins**:MR 开出后触发 Jenkins;结果回写任务状态(可挂回调)。
- ⬜ **服务化**:把 Dispatcher 包成 FastAPI 服务(`services/dev`,:8004),进度用 SSE 推(照 `api/agentic_chat.py` 的 on_step/on_think 模式)。

## 加一个新 Worker(将来横评/切换)

实现 `CodingWorker.run(task, workdir, on_progress) -> WorkerResult`(只改文件、不 commit),注册进 `RuntimeDispatcher(workers={...})`。控制面、入口、出口全部复用——这就是"引擎可换可逆"。
