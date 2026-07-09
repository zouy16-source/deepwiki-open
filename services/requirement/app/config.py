from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "requirement-service"
    database_url: str = "mysql+pymysql://root:devroot@localhost:3306/requirement_db"
    # Dev convenience: create tables on startup. Production uses alembic migrations.
    db_auto_create: bool = False
    # Empty secret = auth disabled (local dev only). BFF issues internal JWTs with this secret.
    internal_jwt_secret: str = ""

    # api 服务（AI 与知识库，:8001）——可行性分析任务在那边执行。
    analysis_base_url: str = "http://localhost:8001"
    # identity 服务（:8003）——发起分析时查项目空间绑定的代码库。
    identity_base_url: str = "http://localhost:8003"
    # 本服务对 api 服务可达的回调地址（compose 内为 http://requirement:8002；
    # api 跑 Docker、本服务跑宿主机时为 http://host.docker.internal:8002）。
    callback_base_url: str = "http://localhost:8002"

    # --- TAPD OpenAPI（企业级 Basic Auth，公司一套凭证）---
    tapd_api_user: str = ""
    tapd_api_password: str = ""
    tapd_timeout: int = 20
    tapd_fake: bool = False  # =true 时用内置样例，离线验证同步逻辑（无凭证）

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
