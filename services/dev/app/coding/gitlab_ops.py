"""GitLab 的 GitOps 实现 —— push 工作分支 + 建 Merge Request(适配 git.ymdd.tech)。

git.ymdd.tech = 自建 GitLab(指纹:/api/v4 + /users/sign_in)。故 PR = GitLab Merge Request。
纯 stdlib(urllib),保持 coding 包零三方依赖。

鉴权:环境变量 `GITLAB_TOKEN`(Personal/Project Access Token,scope 需 `api` + 可 push,
角色 ≥ Developer)。token 只用于 push URL 与 API 头,**不写进任何进度事件/日志**。

自签证书内网可设 `GITLAB_INSECURE=1` 跳过校验。
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .models import CodingTask, ProgressCb, ProgressEvent, WorkerResult
from .worker import run_cmd


class GitLabGitOps:
    def __init__(self, token: Optional[str] = None, insecure: Optional[bool] = None,
                 remove_source_branch: bool = True):
        self.token = token or os.environ.get("GITLAB_TOKEN", "")
        self.insecure = insecure if insecure is not None else os.environ.get("GITLAB_INSECURE") == "1"
        self.remove_source_branch = remove_source_branch

    def push_and_open_pr(self, task: CodingTask, workdir: str, result: WorkerResult,
                         on_progress: ProgressCb) -> Optional[str]:
        if not self.token:
            on_progress(ProgressEvent("error", "未配置 GITLAB_TOKEN,跳过 push/开 MR(产出停在 branch+diff)"))
            return None
        try:
            scheme, host, project_path = self._parse_repo(task.repo_url)
        except ValueError as e:
            on_progress(ProgressEvent("error", f"无法从 repo_url 解析项目路径:{e}"))
            return None

        # 1) push 工作分支(token 注入 push URL,不落日志)
        push_url = f"{scheme}://oauth2:{self.token}@{host}/{project_path}.git"
        on_progress(ProgressEvent("push", f"push 分支 {task.branch} → {host}/{project_path}"))
        rc, _, err = run_cmd(["git", "-C", workdir, "push", push_url,
                              f"HEAD:refs/heads/{task.branch}"], timeout=600)
        if rc != 0:
            on_progress(ProgressEvent("error", f"push 失败:{self._redact(err)[:300]}"))
            return None

        # 2) 建 Merge Request
        on_progress(ProgressEvent("pr", "创建 Merge Request…"))
        try:
            mr_url = self._create_mr(scheme, host, project_path, task, result)
            on_progress(ProgressEvent("pr", f"MR 已创建:{mr_url}", {"pr_url": mr_url}))
            return mr_url
        except _GitLabError as e:
            # 已存在同源分支 MR 等情况:降级为不致命,产出仍有 pushed 分支
            on_progress(ProgressEvent("error", f"建 MR 失败:{self._redact(str(e))[:300]}"))
            return None

    # ---- GitLab API v4:POST /projects/:id/merge_requests(:id 用 URL 编码的项目路径)----
    def _create_mr(self, scheme: str, host: str, project_path: str,
                   task: CodingTask, result: WorkerResult) -> str:
        enc = urllib.parse.quote(project_path, safe="")
        api = f"{scheme}://{host}/api/v4/projects/{enc}/merge_requests"
        body = {
            "source_branch": task.branch,
            "target_branch": task.base_branch,
            "title": f"[AI] {task.title}",
            "description": self._mr_description(task, result),
            "remove_source_branch": self.remove_source_branch,
        }
        data = json.dumps(body).encode()
        req = urllib.request.Request(api, data=data, method="POST", headers={
            "PRIVATE-TOKEN": self.token,
            "Content-Type": "application/json",
        })
        ctx = ssl._create_unverified_context() if self.insecure else None  # noqa: S323
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            raise _GitLabError(f"HTTP {e.code}: {detail}") from None
        except urllib.error.URLError as e:
            raise _GitLabError(f"连接失败:{e.reason}") from None
        url = payload.get("web_url")
        if not url:
            raise _GitLabError(f"响应无 web_url:{str(payload)[:200]}")
        return url

    def _mr_description(self, task: CodingTask, result: WorkerResult) -> str:
        parts = ["由 AI Worker 自动生成。", "",
                 f"**任务**:{task.title}", f"**task_id**:{task.task_id}"]
        if result.summary:
            parts += ["", "**改动说明**:", result.summary[:1500]]
        parts += ["", "> 待人工 Review + Jenkins CI 通过后合并。"]
        return "\n".join(parts)

    # ---- 从 clone URL 解析 (scheme, host, project_path) ----
    @staticmethod
    def _parse_repo(repo_url: str) -> tuple[str, str, str]:
        u = repo_url.strip()
        # ssh: git@host:group/sub/repo(.git)
        m = re.match(r"^\w+@([^:/]+):(.+?)(?:\.git)?/?$", u)
        if m:
            return "https", m.group(1), m.group(2)
        # https/http(可能带 user:pass@)
        p = urllib.parse.urlparse(u)
        if p.scheme in ("http", "https") and p.netloc:
            host = p.hostname or ""
            if p.port:
                host = f"{host}:{p.port}"
            path = p.path.strip("/")
            path = re.sub(r"\.git$", "", path)
            if host and path:
                return p.scheme, host, path
        raise ValueError(repo_url)

    def _redact(self, text: str) -> str:
        return text.replace(self.token, "***") if self.token else text


class _GitLabError(Exception):
    pass
