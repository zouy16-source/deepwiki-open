# S0 —— 统一模型网关 + 四引擎连通验证

Phase-3 编码引擎选型 POC 的第 0 步(见 [`docs/admin-phase3-coding-engine.md`](../../docs/admin-phase3-coding-engine.md) §6.5)。

**目标**:一个统一模型网关(LiteLLM proxy)同时对外供 **OpenAI** + **Anthropic** 两种协议、都路由到**同一国产模型**后端;并证明 **Claude Code Runtime / OpenHands / Aider / SWE-agent 四引擎 × 国产模型均可连通**。

> 刻意与现网 DeepWiki 的 LiteLLM(`docker-compose-litellm.yml`,:4000 + postgres)**隔离**:本 POC 独立端口 **:4100**、无状态、随起随拆,不影响正在跑的服务。

---

## 一、起网关(2 分钟)

```bash
cd poc/coding-engine
cp .env.example .env
#  编辑 .env:填「你要用的那一家」KEY(默认演示 DeepSeek);已有 DashScope 就填它并把 POC_MODEL 改成 qwen3-coder
docker compose --env-file .env up -d
docker logs -f poc-coding-gateway     # 看到 "Uvicorn running on ... 4000" 即就绪
```

## 二、连通验证(证明网关↔国产模型,双协议)

```bash
chmod +x smoke/*.sh
./smoke/models.sh           # 列出网关暴露的 model_name
./smoke/openai_ping.sh      # OpenAI 端点 → 覆盖 OpenHands / Aider / SWE-agent 的协议
./smoke/anthropic_ping.sh   # Anthropic /v1/messages → 覆盖 Claude Code 的协议
```

两个 ping 都 `OK`,就说明**网关到国产模型的双协议链路通了**——这已覆盖四引擎的全部传输面。

> ⚠️ 这两个 ping 需要你在 `.env` 里填了真实国产模型 KEY 才能跑通(我没有你的 KEY,没法替你打真实模型)。脚本本身已做 `bash -n` 语法校验、配置已做 YAML 校验。

---

## 三、把每个引擎指向网关(各跑一个 hello-world)

网关地址:宿主机上用 `http://localhost:4100`;**引擎跑在别的容器里**(OpenHands/SWE-agent 的 Docker 沙箱)时用 `http://host.docker.internal:4100`。下面 `<KEY>` = 你的 `LITELLM_MASTER_KEY`,`<M>` = `POC_MODEL`(如 `deepseek-chat`)。

### OpenHands(走 OpenAI 协议)
`config.toml` 或环境变量:
```toml
[llm]
model    = "litellm_proxy/<M>"                     # 也可写 openai/<M>
base_url = "http://host.docker.internal:4100/v1"
api_key  = "<KEY>"
```
```bash
# 无头单任务(示意):在某工作区仓库上跑一个最小改动
openhands --headless -t "在 README 顶部加一行标题 '# hello'"
```
拿回结果:`GET /git/diff`(Agent Server)或读 workspace。

### Aider(走 OpenAI 协议)
```bash
export OPENAI_API_BASE="http://localhost:4100/v1"
export OPENAI_API_KEY="<KEY>"
cd /some/git/repo
aider --model "openai/<M>" -m "在 README 顶部加一行 '# hello'" \
      --yes-always --no-stream --no-pretty --no-check-update --no-auto-commits
```
产出:就地改文件(+可选 commit)。分支/推送/开 PR 由平台补。

### SWE-agent(走 OpenAI 协议)
```bash
sweagent run \
  --agent.model.name="openai/<M>" \
  --agent.model.api_base="http://localhost:4100/v1" \
  --agent.model.api_key="<KEY>" \
  --env.repo.path=/some/git/repo \
  --problem_statement.text="在 README 顶部加一行 '# hello'"
# 产出 .patch;加 --actions.open_pr 可直接开 PR
```
> 继任版 **mini-swe-agent** 同理(LiteLLM,`--model openai/<M>` + 同样 `api_base`),更简、更适合嵌入。

### Claude Code Runtime(走 Anthropic 协议 —— **对照组**)
```bash
export ANTHROPIC_BASE_URL="http://localhost:4100"
export ANTHROPIC_AUTH_TOKEN="<KEY>"
export ANTHROPIC_MODEL="<M>"                 # 顶掉硬编码的 claude-* 名
export ANTHROPIC_SMALL_FAST_MODEL="<M>"
export DISABLE_TELEMETRY=1 DISABLE_AUTOUPDATER=1
claude -p "只回一个词:pong" --output-format json
```
> 提醒:Claude Code 走非 Claude 模型是 **Anthropic 官方不支持** 的路径(+ Agent SDK 商业条款)。本 POC 仅作**能力上限对照**,不作不出海默认底座。若日志报 `model not found: claude-xxx`,把该名字照抄进 `litellm-config.yaml` 的别名段。

---

## 四、连通矩阵(把结果记这)

| 引擎 | 协议 | 端点 | 连通 | 备注 |
|---|---|---|---|---|
| OpenHands | OpenAI | `/v1` | ☐ | 沙箱内用 host.docker.internal |
| Aider | OpenAI | `/v1` | ☐ | 宿主直跑 |
| SWE-agent / mini | OpenAI | `/v1` | ☐ | 沙箱内用 host.docker.internal |
| Claude Code | Anthropic | `/v1/messages` | ☐ | 对照组 |

四行都 ✅ → **S0 达成**,进 S1(用 OpenHands 打通一条 `TAPD→clone→改→测→PR→Jenkins` 最小闭环)。

---

## 文件

- `litellm-config.yaml` —— 网关:四家国产模型 + Claude Code 别名,双协议
- `docker-compose.yml` —— 独立无状态网关(:4100)
- `.env.example` —— KEY / 模型选择
- `smoke/` —— `models.sh` · `openai_ping.sh` · `anthropic_ping.sh`(+ `_common.sh`)
