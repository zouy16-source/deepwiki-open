"""编码执行子系统:Worker 抽象 + Runtime Dispatcher + 引擎适配器。

K8s 式:平台控制面把任务派给一个 Worker(Pod)。第一个 Worker = Claude Code Runtime;
换引擎(OpenHands-core / mini-swe-agent)只需再写一个 CodingWorker 子类、注册进 Dispatcher。
"""

from .claude_code_worker import ClaudeCodeWorker
from .gitlab_ops import GitLabGitOps
from .models import (
    CodingTask,
    ProgressCb,
    ProgressEvent,
    WorkerResult,
    WorkerStatus,
)
from .worker import CodingWorker, GitOps, RuntimeDispatcher, run_cmd

__all__ = [
    "CodingTask",
    "ProgressEvent",
    "ProgressCb",
    "WorkerResult",
    "WorkerStatus",
    "CodingWorker",
    "RuntimeDispatcher",
    "GitOps",
    "run_cmd",
    "ClaudeCodeWorker",
    "GitLabGitOps",
]
