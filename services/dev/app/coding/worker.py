"""Worker 抽象 + Runtime Dispatcher(K8s 式:控制面派任务给 Worker/Pod)。

分工:
  · RuntimeDispatcher 负责 **workspace 生命周期**——clone、切工作分支、记录 base、
    Worker 干完后 commit、算 diff,并把 push/开 PR 交给可插拔的 GitOps 钩子(seam)。
  · CodingWorker 只负责在「已 clone、已切分支」的 workdir 上把代码改对(引擎相关)。
这样换引擎(Claude Code → OpenHands-core / mini-swe)只动 Worker,控制面零改动。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import Optional, Protocol

from .models import CodingTask, ProgressCb, ProgressEvent, WorkerResult, WorkerStatus, _noop


def run_cmd(cmd: list[str], cwd: Optional[str] = None, timeout: int = 1800) -> tuple[int, str, str]:
    """跑一条命令,返回 (returncode, stdout, stderr)。不抛异常,由调用方判 rc。"""
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


class CodingWorker(ABC):
    """一个编码引擎的适配器。name 用于 Dispatcher 路由与进度标注。"""
    name: str = "base"

    @abstractmethod
    def run(self, task: CodingTask, workdir: str, on_progress: ProgressCb) -> WorkerResult:
        """在 workdir(已 clone、已切到 task.branch)上执行任务。

        约定:Worker **只改文件、不 commit**(commit 由 Dispatcher 统一做,以控制提交信息/署名)。
        返回的 WorkerResult 里 branch/diff/commits 可留空——Dispatcher 会据 git 状态补全;
        Worker 需负责填 status(引擎视角:成功/失败)、summary、raw_events。
        """
        raise NotImplementedError


class GitOps(Protocol):
    """push + 开 PR 的可插拔钩子(seam)。真实实现依赖你的 git 平台(GitLab/Gitee/GitHub)与凭据。"""
    def push_and_open_pr(self, task: CodingTask, workdir: str, result: WorkerResult,
                         on_progress: ProgressCb) -> Optional[str]:
        """push 分支并开 PR,返回 PR URL(失败/未配置返回 None)。"""
        ...


class RuntimeDispatcher:
    def __init__(self, workers: dict[str, CodingWorker], workspace_root: str,
                 git_ops: Optional[GitOps] = None, keep_workspace: bool = True):
        if not workers:
            raise ValueError("至少注册一个 Worker")
        self.workers = workers
        self.workspace_root = workspace_root
        self.git_ops = git_ops
        self.keep_workspace = keep_workspace
        os.makedirs(workspace_root, exist_ok=True)

    def dispatch(self, task: CodingTask, worker_name: Optional[str] = None,
                 on_progress: ProgressCb = _noop) -> WorkerResult:
        # 选 Worker(不指定则取唯一/第一个)
        name = worker_name or next(iter(self.workers))
        worker = self.workers.get(name)
        if worker is None:
            return WorkerResult(WorkerStatus.FAILED, error=f"未知 Worker '{name}';已注册:{list(self.workers)}")

        workdir = os.path.join(self.workspace_root, task.task_id)
        try:
            self._prepare_workspace(task, workdir, on_progress)
            base_sha = self._rev_parse(workdir)

            on_progress(ProgressEvent("log", f"[{name}] 开始执行任务 {task.task_id}"))
            result = worker.run(task, workdir, on_progress)

            # 引擎失败:直接返回(保留 workspace 供排障)
            if result.status is WorkerStatus.FAILED:
                result.branch = task.branch
                return result

            # 控制面统一 commit + 算 diff
            self._commit_all(task, workdir, on_progress, result)
            result.branch = task.branch
            head_sha = self._rev_parse(workdir)
            if head_sha == base_sha:
                result.status = WorkerStatus.NO_CHANGES
                on_progress(ProgressEvent("log", "工作树无改动 → NO_CHANGES"))
                return result
            result.commits = [head_sha]
            _, diff, _ = run_cmd(["git", "diff", f"{base_sha}..HEAD"], cwd=workdir)
            result.diff = diff
            result.status = WorkerStatus.SUCCESS

            # seam:push + 开 PR(未配置就跳过,产出停在 branch+diff)
            if self.git_ops is not None:
                result.pr_url = self.git_ops.push_and_open_pr(task, workdir, result, on_progress)
            return result
        except subprocess.TimeoutExpired as e:
            return WorkerResult(WorkerStatus.FAILED, branch=task.branch, error=f"命令超时:{e}")
        except Exception as e:  # noqa: BLE001
            on_progress(ProgressEvent("error", str(e)))
            return WorkerResult(WorkerStatus.FAILED, branch=task.branch, error=str(e))
        finally:
            if not self.keep_workspace:
                shutil.rmtree(workdir, ignore_errors=True)

    # ---- workspace / git 生命周期 ----
    def _prepare_workspace(self, task: CodingTask, workdir: str, on_progress: ProgressCb) -> None:
        shutil.rmtree(workdir, ignore_errors=True)
        on_progress(ProgressEvent("log", f"clone {task.repo_url} @ {task.base_branch}"))
        rc, _, err = run_cmd(["git", "clone", "--depth", "1", "-b", task.base_branch,
                              task.repo_url, workdir])
        if rc != 0:
            raise RuntimeError(f"clone 失败:{err.strip()}")
        rc, _, err = run_cmd(["git", "checkout", "-b", task.branch], cwd=workdir)
        if rc != 0:
            raise RuntimeError(f"建分支失败:{err.strip()}")
        on_progress(ProgressEvent("log", f"已切到分支 {task.branch}"))

    def _rev_parse(self, workdir: str) -> str:
        _, out, _ = run_cmd(["git", "rev-parse", "HEAD"], cwd=workdir)
        return out.strip()

    def _commit_all(self, task: CodingTask, workdir: str, on_progress: ProgressCb,
                    result: WorkerResult) -> None:
        run_cmd(["git", "add", "-A"], cwd=workdir)
        # 无暂存改动就不 commit(交由上层判 NO_CHANGES)
        rc, _, _ = run_cmd(["git", "diff", "--cached", "--quiet"], cwd=workdir)
        if rc == 0:
            return
        # 平台控制提交信息;这里给个可读默认(真实可换成 LLM 生成 message)
        summary = (result.summary or "").strip().splitlines()[0][:100] if result.summary else ""
        msg = f"[AI] {task.title}\n\ntask_id={task.task_id}"
        if summary:
            msg += f"\n{summary}"
        run_cmd(["git", "-c", "user.name=AI Worker",
                 "-c", "user.email=ai-worker@platform.local",
                 "commit", "-m", msg], cwd=workdir)
        on_progress(ProgressEvent("commit", f"已提交:{task.title}"))
