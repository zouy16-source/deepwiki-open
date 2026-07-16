"""Claude Code Runtime 适配器 —— Phase-3 第一个 Worker。

以无头子进程方式调用 Claude Code:
    claude -p "<prompt>" --output-format stream-json --verbose --dangerously-skip-permissions
在已 clone、已切分支的 workdir 上让它自主改代码(+可跑测试),逐行解析 stream-json 事件转成
ProgressEvent。**不 commit**——commit 由 RuntimeDispatcher 统一做。

起步直连 Claude API:只需环境变量 ANTHROPIC_API_KEY(用真 Claude 模型,数据出海,已知情)。
将来接国产模型时,设 ANTHROPIC_BASE_URL 指向 poc/coding-engine 网关即可,本 adapter 不用改。

前置:已安装 Claude Code CLI(`npm i -g @anthropic-ai/claude-code`,命令名 `claude`)。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Optional

from .models import CodingTask, ProgressCb, ProgressEvent, WorkerResult, WorkerStatus
from .worker import CodingWorker


class ClaudeCodeWorker(CodingWorker):
    name = "claude-code"

    def __init__(self, claude_bin: str = "claude", deadline_s: int = 1800,
                 dangerously_skip_permissions: bool = True):
        # Pod = 沙箱边界,故默认 skip-permissions 让其能自主 edit + 跑测试而不卡在授权;
        # 若在非隔离环境跑,置 False 走 allowedTools 白名单。
        self.claude_bin = claude_bin
        self.deadline_s = deadline_s
        self.skip_perm = dangerously_skip_permissions

    def run(self, task: CodingTask, workdir: str, on_progress: ProgressCb) -> WorkerResult:
        if shutil.which(self.claude_bin) is None:
            return WorkerResult(WorkerStatus.FAILED,
                                error=f"未找到 `{self.claude_bin}` CLI(npm i -g @anthropic-ai/claude-code)")
        if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            return WorkerResult(WorkerStatus.FAILED, error="缺 ANTHROPIC_API_KEY(起步直连 Claude API 需要)")

        cmd = [self.claude_bin, "-p", self._build_prompt(task),
               "--output-format", "stream-json", "--verbose"]
        if self.skip_perm:
            cmd += ["--dangerously-skip-permissions"]
        else:
            cmd += ["--permission-mode", "acceptEdits",
                    "--allowedTools", "Read,Edit,Write,Glob,Grep,Bash"]
        if task.model:
            cmd += ["--model", task.model]

        raw_events: list[dict] = []
        summary = ""
        try:
            proc = subprocess.Popen(cmd, cwd=workdir, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, bufsize=1)
        except Exception as e:  # noqa: BLE001
            return WorkerResult(WorkerStatus.FAILED, error=f"启动 claude 失败:{e}")

        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                raw_events.append(evt)
                final = self._emit(evt, on_progress)
                if final:
                    summary = final
            proc.wait(timeout=self.deadline_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            return WorkerResult(WorkerStatus.FAILED, error=f"claude 执行超时(>{self.deadline_s}s)",
                                raw_events=raw_events)

        if proc.returncode not in (0, None):
            err = (proc.stderr.read() if proc.stderr else "") or "非零退出"
            return WorkerResult(WorkerStatus.FAILED, error=f"claude 退出码 {proc.returncode}:{err[:400]}",
                                raw_events=raw_events, summary=summary)

        # 引擎正常结束;是否真有改动交由 Dispatcher 据 git 判定(此处标 SUCCESS)
        return WorkerResult(WorkerStatus.SUCCESS, summary=summary or "(引擎未给出总结)",
                            raw_events=raw_events)

    # ---- stream-json 事件 → ProgressEvent;返回值为最终总结文本(仅 result 事件有)----
    def _emit(self, evt: dict, on_progress: ProgressCb) -> Optional[str]:
        etype = evt.get("type")
        if etype == "assistant":
            for block in (evt.get("message", {}) or {}).get("content", []) or []:
                btype = block.get("type")
                if btype == "text" and block.get("text", "").strip():
                    on_progress(ProgressEvent("think", block["text"].strip()[:2000]))
                elif btype == "tool_use":
                    args = json.dumps(block.get("input", {}), ensure_ascii=False)[:160]
                    on_progress(ProgressEvent("tool", f'{block.get("name")}({args})',
                                              {"tool": block.get("name")}))
        elif etype == "result":
            text = evt.get("result") or ""
            if evt.get("is_error"):
                on_progress(ProgressEvent("error", str(text)[:500]))
            elif text:
                on_progress(ProgressEvent("log", "引擎完成"))
            return text.strip() if isinstance(text, str) else None
        return None

    def _build_prompt(self, task: CodingTask) -> str:
        lines = [
            "你是自主软件工程 agent。当前工作目录已是任务仓库、已切到工作分支。",
            f"# 任务:{task.title}",
            task.description.strip(),
        ]
        if task.extra_context.strip():
            lines += ["", "# 已知线索(来自平台的代码调查/术语表,可直接参考):", task.extra_context.strip()]
        if task.test_cmd:
            lines += ["", f"# 验收:改完后运行 `{task.test_cmd}`,必须通过(失败则继续修直到通过)。"]
        lines += [
            "",
            "# 要求:",
            "1. 只做完成任务所需的**最小改动**,不要顺手重构无关代码;",
            "2. 直接用工具改文件;**不要执行 git commit / git push**(平台会统一提交);",
            "3. 完成后用一段话总结:改了哪些文件、为什么这样改。",
        ]
        return "\n".join(lines)
