"""编码执行的核心数据模型(与引擎无关)。

Worker 抽象的契约用这几个 dataclass 表达:
    输入 CodingTask  →  Worker 执行  →  输出 WorkerResult(+ 过程 ProgressEvent 流)
刻意零外部依赖(dataclass 而非 pydantic),让 Worker 核可独立测试、可被任何服务复用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional


class WorkerStatus(str, Enum):
    SUCCESS = "success"        # 引擎正常结束且产生了改动
    NO_CHANGES = "no_changes"  # 引擎结束但工作树无改动(判定为未完成/无需改)
    FAILED = "failed"          # 引擎异常/超时/退出码非零


@dataclass
class CodingTask:
    """一次具体的软件工程任务(K8s 类比:一个 Pod 的 spec)。"""
    task_id: str                     # 平台任务 ID(如 TAPD external_id),也用作分支名/工作区名
    repo_url: str                    # git clone 地址(平台注入,含凭据或走 ssh/凭据助手)
    title: str
    description: str                 # 需求/任务描述,喂给 agent
    base_branch: str = "main"        # 从哪个分支拉出来改
    branch_prefix: str = "ai/"       # 生成分支 = branch_prefix + task_id
    test_cmd: Optional[str] = None   # 可选验收命令(如 "mvn -q test");引擎需跑通它
    extra_context: str = ""          # 复用平台已有的 agentic 调查/术语表结论,作种子上下文注入
    model: Optional[str] = None      # 覆盖默认模型(Claude Code 起步直连 Claude API,一般留空)

    @property
    def branch(self) -> str:
        return f"{self.branch_prefix}{self.task_id}"


@dataclass
class ProgressEvent:
    """执行过程中的流式进度(与 api/agentic_chat.py 的 on_step/on_think 一脉相承)。"""
    kind: str                        # think | tool | commit | push | pr | log | error
    message: str
    data: dict = field(default_factory=dict)


# 进度回调:Worker 每产生一个事件就调它(平台侧转成 SSE 推给前端)
ProgressCb = Callable[[ProgressEvent], None]


@dataclass
class WorkerResult:
    """一次执行的产出(K8s 类比:Pod 的终态 + 产物)。"""
    status: WorkerStatus
    branch: Optional[str] = None
    diff: str = ""                             # 统一 diff(base..HEAD)
    commits: list[str] = field(default_factory=list)   # 生成的 commit sha
    pr_url: Optional[str] = None               # 若配置了 GitOps 钩子并开了 PR
    summary: str = ""                          # 引擎自述:改了什么、为什么
    error: Optional[str] = None
    raw_events: list[dict] = field(default_factory=list)  # 引擎原始事件,排障用

    @property
    def ok(self) -> bool:
        return self.status is WorkerStatus.SUCCESS


def _noop(_e: ProgressEvent) -> None:  # 默认无回调
    pass
