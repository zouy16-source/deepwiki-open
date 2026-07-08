"""字段追溯 v2：单仓库 agent tool-loop。

替代 v1 的单次 RAG probe —— 给 LLM grep / read_file / list_dir 三个工具（trace_tools.py），
让它在本地 clone 上自主深挖：顺着 grep 命中读上下文、追调用链、猜错路径后自我纠错。
混合检索（术语表别名 + grep windows）仍作为第一跳种子上下文注入，省掉前几轮盲搜。

qwen-plus function calling 走 OpenAI 兼容端点（DashScope compatible-mode）。
迭代上限 + 软时间预算双保险：到限后收走工具、强制基于已有证据收敛出结论。
"""

import asyncio
import json
import logging
import os
import time

from api.trace_tools import TOOLS_SPEC, dispatch

logger = logging.getLogger(__name__)

MAX_ITERS = 12          # 工具轮次上限（每轮可含多个并行工具调用）
DEADLINE_S = 210        # 单仓库软时间预算（秒）——前端整体超时 280s，须留出综合阶段
MAX_TOOL_RESULT = 16_000  # 单个工具结果注入上下文的字符上限


def _system_prompt(repo_label: str, layer: str, query: str, variants: list) -> str:
    return f"""你是资深代码考古工程师，正在仓库 {repo_label}（{layer or '层次未知'}）中调查业务字段/术语「{query}」（相关标识符：{'、'.join(variants)}）。

你有三个工具：grep（全仓搜索）、read_file（带行号读片段）、list_dir（看目录结构）。调查策略：
1. 先用 grep 定位字段出现的文件（可试多个标识符变体；命中太多就加 path_glob 收窄）；
2. 对关键命中用 read_file 读上下文，搞清：定义、录入/校验、计算/变更、存储（SQL/实体）、下游使用（接口/打印/报表）；
3. 顺藤摸瓜：看到调用了别的方法/常量/SQL id，就继续 grep 或 read_file 追过去；
4. 路径猜错、无命中时换思路重试，不要放弃；但若确认本仓库与该字段无关，尽早停止。

结束时直接输出中文调查报告（不再调用工具），要求：
- 每条结论标注来源 `文件路径:行号`（行号必须来自 read_file/grep 的真实返回，禁止估算）；
- 按「字段定义与代码标识 / 页面与接口入口 / 校验规则 / 计算与变更逻辑 / 存储 / 下游使用」组织，未涉及的小节明确写"未涉及"；
- 只写有证据的内容，不编造。"""


async def run_repo_agent(llm, model: str, root: str, repo_label: str, layer: str,
                         query: str, variants: list, seed: str,
                         max_iters: int = MAX_ITERS, deadline_s: int = DEADLINE_S,
                         on_step=None):
    """在单个 clone 上跑 agent loop。返回 (调查报告文本, 工具调用轨迹)。

    llm: openai.AsyncOpenAI（复用调用方实例）。轨迹条目：
    {"tool": 名称, "args": 参数摘要, "result": 结果首行摘要}
    on_step: 可选 async 回调，每次工具调用后带轨迹条目触发（流式进度用）。
    """
    messages = [
        {"role": "system", "content": _system_prompt(repo_label, layer, query, variants)},
        {"role": "user", "content": "开始调查。已知线索（来自术语表/接口清单/精确检索，可直接引用其中行号）：\n"
                                    + (seed or "（无——从 grep 开始）")},
    ]
    return await run_tool_loop(llm, model, root, messages, max_iters=max_iters,
                               deadline_s=deadline_s, on_step=on_step, log_label=repo_label)


async def run_tool_loop(llm, model: str, root: str, messages: list,
                        max_iters: int = MAX_ITERS, deadline_s: int = DEADLINE_S,
                        on_step=None, log_label: str = ""):
    """通用 grep/read_file/list_dir 工具循环（字段追溯与可行性分析共用）。

    调用方自备 messages（system+user）；循环到模型不再调用工具或预算用尽，
    返回 (最终文本, 工具调用轨迹)。
    """
    steps = []
    started = time.monotonic()
    for it in range(max_iters):
        timed_out = time.monotonic() - started > deadline_s
        try:
            if timed_out:
                messages.append({"role": "user", "content": "时间预算已用完。立即基于已有证据输出最终调查报告，不要再调用工具。"})
            resp = await llm.chat.completions.create(
                model=model, messages=messages, temperature=0.2,
                **({} if timed_out else {"tools": TOOLS_SPEC}))
        except Exception as e:  # noqa: BLE001
            logger.error(f"tool-loop LLM 调用失败 [{log_label}] iter={it}: {e}")
            return f"（调查中断：{e}）", steps
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return (msg.content or "（模型未返回内容）"), steps
        # assistant 消息手动重建为 dict——避免 SDK 对象里 dashscope 不认的字段
        messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = await asyncio.to_thread(dispatch, root, tc.function.name, args)
            result = result[:MAX_TOOL_RESULT]
            step = {
                "tool": tc.function.name,
                "args": json.dumps(args, ensure_ascii=False)[:160],
                "result": (result.splitlines() or [""])[0][:120] + (f" …共{len(result.splitlines())}行" if len(result.splitlines()) > 1 else ""),
            }
            steps.append(step)
            if on_step:
                await on_step(step)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    # 迭代耗尽仍在调工具 → 收走工具强制收敛
    messages.append({"role": "user", "content": "迭代次数已用完。立即基于已有证据输出最终调查报告，不要再调用工具。"})
    try:
        resp = await llm.chat.completions.create(model=model, messages=messages, temperature=0.2)
        return (resp.choices[0].message.content or "（模型未返回内容）"), steps
    except Exception as e:  # noqa: BLE001
        return f"（调查中断：{e}）", steps
