#!/usr/bin/env python3
"""本地跑通一条任务的 CLI —— S1 的"hello-world":clone → Claude Code 改 → commit → 出 diff。

用法(需先 npm i -g @anthropic-ai/claude-code 且 export ANTHROPIC_API_KEY=...):

    python services/dev/run_worker.py \
        --repo /path/to/local-or-remote-git-repo \
        --title "给 README 顶部加一行标题" \
        --desc  "在 README.md 第一行加 '# Hello from AI Worker'" \
        --base  main

repo 可以是远程 URL,也可以是本地已有仓库的路径(本地路径会被当作 clone 源,原仓库不受影响)。
产出打印:分支名、引擎总结、统一 diff。push/开 PR 是后续 seam,这里不做。
"""

from __future__ import annotations

import argparse
import os
import sys

# 允许直接 `python services/dev/run_worker.py` 运行(把 services/dev 加进 path)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.coding import (  # noqa: E402
    ClaudeCodeWorker,
    CodingTask,
    ProgressEvent,
    RuntimeDispatcher,
    WorkerStatus,
)


def _print_progress(e: ProgressEvent) -> None:
    icon = {"think": "💭", "tool": "🔧", "commit": "✅", "push": "⬆️",
            "pr": "🔀", "error": "❌", "log": "·"}.get(e.kind, "·")
    msg = e.message if len(e.message) <= 200 else e.message[:200] + " …"
    print(f"{icon} {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="S1 本地 Worker 跑通器")
    ap.add_argument("--repo", required=True, help="git 仓库(远程 URL 或本地路径)")
    ap.add_argument("--title", required=True, help="任务标题")
    ap.add_argument("--desc", required=True, help="任务描述(喂给 agent)")
    ap.add_argument("--base", default="main", help="基分支(默认 main)")
    ap.add_argument("--task-id", default="local-1", help="任务 ID(用作分支名/工作区名)")
    ap.add_argument("--test-cmd", default=None, help="可选验收命令,如 'pytest -q'")
    ap.add_argument("--model", default=None, help="覆盖模型(一般留空,用 Claude Code 默认)")
    ap.add_argument("--workspace", default="/tmp/ai-worker-ws", help="工作区根目录")
    ap.add_argument("--keep", action="store_true", help="保留工作区(默认保留;此参数兼容占位)")
    args = ap.parse_args()

    task = CodingTask(
        task_id=args.task_id, repo_url=args.repo, title=args.title,
        description=args.desc, base_branch=args.base, test_cmd=args.test_cmd,
        model=args.model,
    )
    dispatcher = RuntimeDispatcher(
        workers={"claude-code": ClaudeCodeWorker()},
        workspace_root=args.workspace, keep_workspace=True,
    )

    print(f"→ 任务 {task.task_id}:{task.title}\n→ 仓库 {task.repo_url} @ {task.base_branch}\n")
    result = dispatcher.dispatch(task, worker_name="claude-code", on_progress=_print_progress)

    print("\n" + "=" * 60)
    print(f"状态   : {result.status.value}")
    print(f"分支   : {result.branch}")
    if result.summary:
        print(f"总结   : {result.summary[:800]}")
    if result.error:
        print(f"错误   : {result.error}")
    if result.diff:
        print(f"\n--- diff ({result.diff.count(chr(10))} 行) ---\n{result.diff[:4000]}")
    print(f"\n工作区 : {os.path.join(args.workspace, task.task_id)}")
    return 0 if result.status is WorkerStatus.SUCCESS else 1


if __name__ == "__main__":
    raise SystemExit(main())
