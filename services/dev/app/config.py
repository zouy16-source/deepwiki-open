from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "dev-service"
    # 编码 Worker 的工作区根目录(compose 内挂卷持久化;每个任务一个子目录)
    workspace_root: str = "/tmp/ai-worker-ws"
    # 起步全量克隆更稳(GitLab 拒绝浅克隆 push 新分支的情况);量大再调 1 加速
    clone_depth: int | None = None
    # ANTHROPIC_API_KEY / GITLAB_TOKEN / GITLAB_INSECURE 由 worker/gitops 直接读环境变量

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
