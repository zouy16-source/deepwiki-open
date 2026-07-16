# Phase 3 编码执行引擎选型 + POC 方案

> 面向 **FR-DEV-01**(AI 编码 Agent / 云端开发工作台)。目标:为"由平台后端**无头调用**的底层**编码执行引擎**"做一次**证据化**选型,并给出一条 `TAPD 任务 → PR` 的**最小验证(POC)**方案。
>
> - 场景管线:`TAPD 任务 → 平台后端触发 → git clone → 理解需求 → 改代码 → 跑测试 → 开 PR → Jenkins CI → 人工 Code Review`。开发者**不直接操作**引擎,平台后端把引擎当"执行引擎"调用。
> - 硬约束:① 接**国产模型**(DeepSeek / 智谱 GLM / Kimi-Moonshot / 通义 Qwen),代码/数据**不出海**;② **开源可嵌入**、可自托管;③ **无头/可编程**调用,能拿回 patch/PR。
> - 事实核实基准日:**2026-07-16**(联网核实至官方 repo / docs / GitHub API;所有关键事实带来源。因外部项目迭代快,行内标注了"post-cutoff / 需自测"的不确定点)。

---

## 1. 选型判据(为什么是这几维)

按"能否当**后端执行引擎**"从硬到软排:

| # | 判据 | 为什么是它 |
|---|------|-----------|
| A | **无头 / 可编程调用** | 第一门槛。开发者不进终端,平台后端必须能非交互驱动、并**拿回 patch/PR + 成败信号**。做不到就出局。 |
| B | **接国产模型(不出海)** | 硬合规约束。看是否走 LiteLLM / OpenAI 兼容、能否自定义 `base_url` 指向域内端点。 |
| C | **沙箱执行隔离** | 引擎要在容器里跑命令/测试,多租户 + 跑不可信代码,必须隔离。 |
| D | **Git & PR 工作流** | 产出 branch/commit,并能开 PR(引擎自带,或平台补这一段)。 |
| E | **SWE 能力信号** | SWE-bench Verified 作**相对**能力参考(注意:榜单分数都用前沿美国模型,不等于国产模型下的表现)。 |
| F | **许可证** | 二次开发 / 商用 / 嵌入自由度。 |
| G | **成熟度 / 维护方** | 多年期企业底座,怕单人维护 / 研究定位 / 停更。 |
| H | **中国部署要点** | 镜像拉取、遥测、气隙。 |

---

## 2. 横评对比表(全部带来源,基准日 2026-07-16)

维度为行、四引擎为列。

| 维度 | **Claude Code Runtime**（Claude Agent SDK） | **OpenHands** | **Aider** | **SWE-agent**（→ mini-swe-agent） |
|---|---|---|---|---|
| **定位/类别** | 编码 agent **harness/运行时**(库 + CLI),Claude Code 打包成库 | 可自托管的 agent **平台**:Python SDK + REST Agent Server + 无头 CLI + GitHub Action + SaaS | 交互式 CLI **结对编程器**(非自主 agent,非库) | **研究级** agent 框架(ACI 概念,NeurIPS 2024) |
| **为 SWE 专造** | ✅ 正是为编码工作流造的行业参照 | ✅ 平台级 SWE agent | ⚠️ 编辑器,不自主 | ✅ `issue→patch/PR` 天生贴 TAPD→PR |
| **A. 无头调用** | ✅ `claude -p` + `--output-format json/stream-json` + `--permission-mode`;Python/TS SDK | ✅ 三条路:`openhands --headless -t`;REST `POST /conversations`;`openhands-sdk` 进程内嵌入 | ✅ `-m/--message`、`-f/--message-file`、`--yes-always`(注意**没有** `--yes`);全量 `AIDER_*` 环境变量。**Python API 官方标注"不支持/不稳定"→ 走子进程** | ✅ `sweagent run …`;`sweagent run-batch --num_workers`(批处理→`preds.json`);Python `Agent`/`Environment` API |
| **拿回结果方式** | stdout JSON / SDK 消息流;Bash 工具产出 diff/PR | `GET /git/diff` 取 patch;或读 `events.jsonl`+workspace;或 GitHub Action 直接开 PR | 就地改文件 + 默认 `git commit`;**无退出码成败契约 → 靠 commit/测试结果自判**(gap) | 写出 `.patch`+`.traj`;`--actions.apply_patch_locally` / `--actions.open_pr` |
| **F. 许可证** | CLI = Apache-2.0;**Agent SDK 壳 MIT,但受 Anthropic 商业条款约束**,且驱动**闭源 Claude Code 引擎 + 闭源模型** | **核心 MIT**;但 `enterprise/` 目录是 **PolyForm Free Trial**(受限 source-available)→ GitHub 报 `NOASSERTION`。生产只用 MIT 核心 | **Apache-2.0**(带专利授权,最企业友好) | **MIT**(mini-swe-agent 亦 MIT) |
| **B. 接国产模型** | ⚠️ **Anthropic 协议原生**(Anthropic API/Bedrock/Vertex/Foundry)。非 Claude 模型需**翻译网关**(LiteLLM 经 `ANTHROPIC_BASE_URL`)或用国产模型的 `/anthropic` 兼容端点。**Anthropic 官方"不支持"非 Claude 路由 → 战略依赖风险** | ✅ **LiteLLM**(`litellm==1.84.1` 硬钉)。任意 OpenAI 兼容 `base_url`。Kimi 有专页、DeepSeek 是 UI 选项、Qwen/GLM 走 `base_url`。**Qwen 团队用 OpenHands 做 harness 报 71.3% SWE-bench Verified** | ✅ **LiteLLM**。OpenAI 兼容经 `OPENAI_API_BASE`。**DeepSeek 有专页**;Kimi/Qwen 走域内 `base_url`;GLM 经 `zai/` 或 OpenAI 兼容(需自测) | ✅ **LiteLLM**(`api_base/api_key`)。任意 OpenAI 兼容。国产经 LiteLLM 的 `deepseek/`、`dashscope/`、`moonshot/`、GLM(docs 未点名国产,**需自测 tool-calling**) |
| **C. 沙箱隔离** | ⚠️ 自带 Bash 工具跑命令 + 权限系统 + hooks,但**容器隔离要你自己套**(它跑在你给的容器里) | ✅ **Docker 沙箱**(V1 镜像 `ghcr.io/openhands/agent-server`);另有 Process(无隔离/快)、Remote、SDK Local/Apptainer、Enterprise K8s-Helm。**E2B/Modal/Daytona 运行时已于 2025-06 移除** | ❌ **无沙箱**,直接在工作目录以当前权限跑 → **容器要你自己提供**(正好契合你 Docker 部署) | ✅ **SWE-ReX**(MIT):Docker/local/AWS/Modal/Fargate,跑任意 shell |
| **跑测试/命令** | ✅ Bash 工具 | ✅ TerminalTool | ✅ `--test-cmd`+`--auto-test`(失败回灌修复)、`--lint-cmd`+`--auto-lint`(默认开) | ✅ SWE-ReX 任意命令 |
| **D. Git 分支/提交** | ✅ 经 Bash(git/gh 全能,但非专门封装) | ✅ 原生 git 操作 + `GET /git/diff /commits` | ✅ **每次编辑自动 commit(LLM 写 message)**;⚠️ **不建分支、不推、不开 PR → 平台补这段** | ✅ 产出 patch;`--actions.open_pr` 建分支+PR |
| **E. issue→PR 一体化** | ⚠️ 无专门 resolver,但 Bash+gh 可拼 | ✅ **一等公民**:GitHub Action / Resolver(`fix-me` 标签 / `@openhands-agent`)真·API 开 PR;**GitLab MR、Bitbucket、Azure DevOps、Jira 均一等公民** | ❌ 无 | ✅ `--actions.open_pr`;⚠️ **无维护中的官方 GitHub Action**(`usage/github/` 404);勿与 LangChain "Open SWE" 混淆 |
| **SWE-bench(能力信号)** | 编码 agent 标杆(配 Claude 模型达前沿);**国产模型下未验证** | **开源第一** scaffold;2025-05 "开源唯一进前十";~72%(2026 中,二手聚合) | ❌ **从未发过 SWE-bench Verified**;自有榜(polyglot Exercism);旧 2024 Lite 26.3%/full 18.9% | SWE-bench 作者出品;1.0(2025-02)开源 SoTA;mini 自报 Verified >74% |
| **G. 成熟度/活跃** | Anthropic 官方,海量使用,headless/权限/hooks/子 agent/MCP 成熟 | **~80.9k★**,2024-03 建,**日更**(`cloud-1.46.2` 2026-07-15) | ~47.4k★,但**准单人维护**(Paul Gauthier ~96%),2026 明显放缓(约半年空档,最后 push 2026-05-22) | ~19.8k★,最后 commit 2026-07-07,但**tag 停在 v1.1.0(2025-05)**;官方明说**维护重心转向 mini-swe-agent**(~5.8k★) |
| **维护方** | Anthropic(闭源引擎+闭源模型) | All Hands AI(风投) | 个人(Aider-AI 社区组) | Princeton NLP → SWE-agent 组(学术) |
| **H. 中国部署** | 闭源模型;走第三方路由属"官方不支持"+商业条款;遥测走 Anthropic(`DISABLE_TELEMETRY=1`) | 完全自托管(docker-compose);**需把 `ghcr.io` 镜像同步进域内 registry(Harbor/ACR)**;遥测 PostHog 需关 | 无强依赖;pip 安装即可 | 需同步 SWE-ReX 的 Docker 镜像 |
| **关键短板** | 闭源+商业条款+**Anthropic 官方不支持非 Claude 路由**(战略风险) | 镜像域内化;避开 PolyForm `enterprise/`;国产模型 tool-calling 需自测 | **不自主**(不自己找文件/建分支/开 PR/无沙箱)+准单人维护 | **研究定位 + 维护转向 mini**;无官方 Action |

---

## 3. 逐引擎点评(对本场景)

**OpenHands** — 最贴"后端无头调用的执行引擎":MIT 核心、平台级(REST Agent Server + SDK + CLI + Docker 沙箱 + 多平台 PR resolver)、LiteLLM 接国产模型、SWE-bench 开源第一、~81k★ 日更、可完全自托管。你的 `TAPD→clone→改→测→PR→Jenkins` 能干净地映射到 **Agent Server(`POST /conversations` + `GET /git/diff`)** 或 **SDK**,平台负责建 PR(或直接用 resolver)。要注意:① 生产组件避开 PolyForm 的 `enterprise/`;② `ghcr.io` 镜像同步进域内;③ 榜单分是前沿模型跑的,**国产模型下的真实成功率要自测**,优先选 function-calling 强、非 thinking 的变体。

**Claude Code Runtime** — 编码能力标杆、headless/权限/hooks 打磨最成熟,但:闭源引擎 + 闭源模型 + **Anthropic 官方"不支持"非 Claude 路由** + Agent SDK 受商业条款约束。接国产模型要经 LiteLLM 翻译成 Anthropic 协议(能做,但依赖"官方不支持"的路径)。→ **作为"能力上限对照组"评估,不作不出海默认底座。**

**Aider** — `编辑+测试+提交`这一段最稳、Apache-2.0 最干净、接国产模型顺(DeepSeek 有专页)。但它是**组件不是 turnkey agent**:不自主探索选文件、不建分支、不推、不开 PR、无沙箱、无退出码契约,且准单人维护 2026 放缓。→ 适合"**平台已切好上下文文件、只要一个稳的 apply-edit 子环节**",不适合当自主主引擎。

**SWE-agent / mini-swe-agent** — `issue→patch/PR` 语义天然贴 `TAPD→PR`、MIT、SWE-ReX 沙箱、`run-batch` 无头批处理。但研究定位,且**官方明说"今后请用 mini-swe-agent"**。→ 若走这条线,**直接评 mini-swe-agent**(约百行、bash-only、`subprocess.run`→`docker exec`、干净 Python API、同样 LiteLLM/`base_url`、SWE-bench 分相当,且是维护所在)。

---

## 4. 关键架构点:统一模型网关(让横评"只比引擎、不比模型")

四引擎里三个(OpenHands/Aider/SWE-agent)原生 LiteLLM / OpenAI 兼容,Claude Code 走 Anthropic 协议。**用一个统一模型网关(LiteLLM proxy)同时对外提供两种端点、都路由到同一国产模型后端**:

```
                         ┌───────────────────────────────────────────┐
  OpenHands  ─OpenAI兼容─▶│                                           │
  Aider      ─OpenAI兼容─▶│   统一模型网关(LiteLLM proxy)            │─▶ DeepSeek
  SWE-agent  ─OpenAI兼容─▶│   · 出海管控 / 脱敏 / 审计 / 限流 / 计费   │─▶ 智谱 GLM
  Claude Code ─Anthropic─▶│   · 同一后端模型喂给四引擎                 │─▶ 通义 Qwen
                         └───────────────────────────────────────────┘   Kimi …
```

价值:① 横评时**同一模型后端**喂四引擎,差异只归因于**引擎**;② 集中做**不出海管控 + 脱敏 + 审计 + 限流**——正是 `admin.md` M1.1 的"脱敏网关"落点(即便不出海,代码仍出本地到模型 API,脱敏/审计仍需要);③ 换模型/换引擎互不影响,降耦合。

---

## 5. 决策(2026-07-16 locked)

### 5.1 架构:K8s 式控制面 + 可换 Worker(Pod)
不让 Spring Boot 去"控制 Claude",也不让 Claude 去"管流程";而是分层:

```
                    AI 研发平台
                         │
                 Spring Boot 控制面(事件 / 调度 / 权限 / 审计 / 状态)
                         │
                 Runtime Dispatcher
                         │
     ┌───────────────────┼───────────────────┐
  Worker(需求实现)   Worker(Code Review)  Worker(测试修复)   ← Pod,一次一具体任务
     │                   │                   │
        Git / MCP / Jenkins / Docker …
```

- Spring Boot = K8s 控制面;**Worker = Pod**,专注完成一次软件工程任务;将来加 Qwen Code / Codex / Gemini CLI 只是**新增 Worker 类型**,不推翻平台。
- **"定底层"的真正内容 = 定 `Worker` 抽象接口 + Runtime Dispatcher**(输入:仓库+任务;输出:分支/patch/PR + 进度事件),引擎因此**可换、可逆**。

### 5.2 引擎决策
- **第一个 / 默认 Worker = Claude Code Runtime**(首个 adapter)。起步阶段**直连 Claude API + Claude 模型**,数据出海在小公司起步阶段**可接受**。
  - 理由:此配置下 Claude Code 处于**最佳状态**(Claude 模型 + 成熟 harness 打包),编码质量天花板。此前"国产模型下丢优势"的反对**在这里不成立**——因为没有拆包。
  - 起步**无需 LiteLLM 网关**:Claude Code 直接 `ANTHROPIC_API_KEY` 打 Anthropic。§4 的统一网关**留给未来接国产 Worker** 时再用。
- **可插拔备选 Worker(为将来不出海 / 国产模型 / 规模化保留)**:
  - **OpenHands-core(headless)** / **mini-swe-agent** —— 开源、model-agnostic、可自托管;当合规收紧或要跑敏感仓库时,换 adapter 即可,上层零改动。
  - **Aider** —— 平台切好文件后的稳定 apply-edit 子环节。

### 5.3 睁眼上路(已知情、非否决)
- **数据出海**:银河开单代码(含业务逻辑)会到 Anthropic。**建议划线**:哪些仓库可出海、哪些将来必须切回不出海 Worker。
- **Agent SDK 商业条款**:面向客户的平台用 Claude Agent SDK 受 Anthropic Commercial ToS 约束,规模化前需复核。
- **保险**:Worker 做成 adapter(见 5.1),Claude Code 是第一个而非唯一——这是几乎零成本的退路。

> 保留提醒:各引擎 SWE-bench 分都用**前沿模型**跑,harness 质量与模型质量是两回事;POC 的价值在于用**真实任务**量出你选定配置(Claude API 起步 / 将来国产 Worker)的真实一次成功率。

---

## 6. POC 方案:跑通一条 TAPD → PR 的最小验证

### 6.1 目标与成功标准
- **目标**:证据化选出 Phase 3 主编码引擎(+ 备选),而非凭感觉。
- **P0 成功标准(必须达成)**:银河开单某仓库上,由平台后端**无头**驱动 **Claude Code Runtime(第一个 Worker)**,针对一个真实 TAPD 小任务,完成 `clone → 改 → 测 → 推分支 → 开 PR → Jenkins 绿`。起步**直连 Claude API**(数据出海可接受),经 `Worker` adapter 调用。
- **(后续)横评成功标准**:在 `Worker` 抽象下把 OpenHands-core / mini-swe-agent 等作为可插拔 adapter 插入,同一任务集下产出可比的**一次成功率 + 人工评审信号**,为"将来是否需要国产 Worker"提供数据。

### 6.2 架构(POC 最小闭环)
```
TAPD 任务(已有 tapd_sync 可复用,新增 dev-task 触发)
  → 平台后端(requirement/新 dev 服务)
    → 编码执行引擎(容器内:clone→理解→改→测)
        ↕ 统一模型网关(LiteLLM proxy → 国产模型;脱敏+审计+限流)
    → git push 新分支 → 开 PR(引擎自带 or 平台用 git+平台 API)
      → Jenkins CI → 人工 Code Review
```

### 6.3 最小任务集(真实任务,非合成 benchmark)
从**银河开单 TAPD 历史**挑 **5–10 个已完成、已合并 PR** 的真实小任务,**用其真实 PR 作 ground truth**:
- 难度梯度:纯文本/配置改动 → 单文件逻辑修复 → 跨文件小功能。
- 避开:需大量业务上下文、外部依赖联调、大重构的任务(留到后续)。
- **为什么用真实历史任务而非造 eval set**:呼应 `admin.md` owner note(用户不会给你 eval,他们直接离开)——用**已合并 PR** 当天然 ground truth,既真实又零额外标注成本。

### 6.4 评测指标
**客观**(每引擎 × 每任务 × N 次):
- **一次成功率**:patch 生成 ✅ + 编译/测试通过 ✅ + Jenkins 绿 ✅
- **PR 可合并率**:人工 approve 且无需大改
- 平均迭代轮次 / 墙钟耗时 / token 成本

**人工评审信号**(复用现有 passive-signal 理念):
- diff 可读性(1–5)
- review 需改动量(改多少行才能合)
- 是否越界过改(over-edit / 偏离任务)

**嵌入工程性**(这决定"能不能当引擎"):
- 后端无头调用顺手度 / 拿回 patch/PR 的清晰度 / 沙箱隔离与多租户 / 失败可观测(退出码 or 事件流)

### 6.5 分阶段计划
| 阶段 | 时长 | 内容 | 产出 |
|---|---|---|---|
| **S0 网关(已建,当前可缓)** | — | 统一模型网关(`poc/coding-engine/`,双协议→国产模型)。**起步直连 Claude API 用不到**,留给将来接国产 Worker | 脚手架已就绪、待用 |
| **S1 P0 闭环** | 3–5 天 | 定 **`Worker` 接口 + Runtime Dispatcher**,写 **Claude Code Runtime adapter**(直连 Claude API),打通 `TAPD→clone→改→测→push→PR→Jenkins` 最小闭环 | Worker 抽象落地 + 一条真实 TAPD→PR 端到端跑通 |
| **S2 补 Worker(按需)** | 1 周 | 当出现不出海 / 国产模型 / 规模化诉求时,插 OpenHands-core / mini-swe adapter,同任务集横评,填 6.4 指标 | 对比数据 + "是否引入国产 Worker"结论 |
| **S3 决策** | 1–2 天 | 按数据决定默认 Worker 与各仓库 Worker 分配;结论沉淀进 `admin.md` Phase 3 | 选型结论 + 后续工程计划 |

### 6.6 风险与降级
- **国产模型 tool-calling 保真度不足 → autonomy 掉档**:降级为"平台切文件 + Aider 单步编辑",或人工补上下文,或换 function-calling 更强的模型;优先非 thinking 变体。
- **镜像拉取受阻**(OpenHands `ghcr.io/openhands/*`、SWE-ReX 镜像):同步进域内 registry(Harbor/ACR),CI 里改指向。
- **Claude Code 第三方路由的战略风险**(Anthropic 官方不支持 + 商业条款):只作对照,不作默认底座。
- **单人维护/研究定位**(Aider / SWE-agent):长期主引擎倾向 OpenHands;另两者作特定子环节补充。
- **脱敏合规**:即便不出海,代码仍出本地到模型 API → 统一网关做脱敏 + 审计(`admin.md` M1.1 前置)。
- **许可证**:OpenHands 生产组件避开 PolyForm 的 `enterprise/`,只用 MIT 核心。

---

## 附:核实来源(基准日 2026-07-16,联网核实至官方一手源)

- **Claude Agent SDK / Claude Code**:code.claude.com/docs/en/agent-sdk/overview、/headless;claude.com/blog/building-agents-with-the-claude-agent-sdk;github.com/anthropics/claude-agent-sdk-python(MIT 壳);LiteLLM 网关经 `ANTHROPIC_BASE_URL`(docs.litellm.ai)。
- **OpenHands**(org 已 `All-Hands-AI`→`OpenHands`,docs `docs.all-hands.dev`→`docs.openhands.dev` 308):github.com/OpenHands/OpenHands(README/LICENSE/`pyproject.toml` 钉 `litellm==1.84.1`/`enterprise/` PolyForm/`integrations/*/service/prs.py` 真·API 开 PR);docs.openhands.dev(headless、sandboxes、github-action、gitlab/bitbucket install);SWE-bench 博客(openhands.dev/blog)+ Qwen 71.3% 报告;GitHub API(~80.9k★,`cloud-1.46.2` 2026-07-15);V1 沙箱镜像 `ghcr.io/openhands/agent-server`、runtime `ghcr.io/openhands/runtime`;官方 SDK 论文 arXiv 2511.03690。
- **Aider**:github.com/Aider-AI/aider(Apache-2.0,`args.py` 证 `-m/-f/--yes-always`、无 `--yes`、无分支/推/PR 选项);aider.chat/docs(scripting/llms/openai-compat/deepseek/git/lint-test);自有榜非 SWE-bench;GitHub/PyPI API(~47.4k★,v0.86.2 2026-02-12,单人 ~96%);headless 单跑可出坏码 issue #4923。
- **SWE-agent**(`princeton-nlp`→`SWE-agent/SWE-agent`):github.com/SWE-agent/SWE-agent(MIT,`models.py` 走 LiteLLM,`cl_tutorial`/`batch_mode`/`--actions.open_pr`);SWE-ReX(github.com/SWE-agent/SWE-ReX,Docker 沙箱);mini-swe-agent(MIT,~5.8k★,官方指定继任);arXiv 2405.15793(NeurIPS 2024);`usage/github/` 404(无维护中的官方 Action)。
- **国产模型 via LiteLLM**:docs.litellm.ai/docs/providers 之 deepseek / dashscope(Qwen)/ moonshot(Kimi)/ zai(GLM),均可自定义域内 `base_url`。

> 不确定点(需 POC 自测/复核):国产模型在各引擎下的真实 tool-calling 保真度与一次成功率;当前 SWE-bench Verified 绝对榜首(网络内容农场噪声,未采信);GLM 在 Aider 的 `zai/` 路径(推断,需测)。
