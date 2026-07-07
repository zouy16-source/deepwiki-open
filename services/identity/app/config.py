from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "identity-service"
    database_url: str = "mysql+pymysql://root:devroot@localhost:3306/identity_db"
    # Dev convenience: create tables on startup. Production uses alembic migrations.
    db_auto_create: bool = False
    # Empty secret = auth disabled (local dev only). BFF issues internal JWTs with this secret.
    internal_jwt_secret: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
