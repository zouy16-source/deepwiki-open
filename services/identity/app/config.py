from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "identity-service"
    database_url: str = "mysql+pymysql://root:devroot@localhost:3306/identity_db"
    # Dev convenience: create tables on startup. Production uses alembic migrations.
    db_auto_create: bool = False
    # Empty secret = auth disabled (local dev only). BFF issues internal JWTs with this secret.
    internal_jwt_secret: str = ""

    # --- LDAP/AD（FR-ADM-01，平台唯一认证源；已决策不做本地回退：目录不可达则登录不可用） ---
    ldap_url: str = ""  # 生产用 ldaps://host:636；留空 = 登录接口一律 503
    ldap_base_dn: str = ""
    ldap_bind_dn: str = ""  # 搜索用服务账号（不依赖匿名搜索）
    ldap_bind_password: str = ""
    ldap_user_filter: str = "(uid={username})"  # AD 域用 (sAMAccountName={username})
    ldap_attr_display: str = "displayName"  # 部分目录用 cn
    ldap_attr_email: str = "mail"
    ldap_timeout: int = 5  # 连接/搜索超时（秒）
    ldap_ca_cert_file: str = ""  # ldaps 证书校验 CA；留空用系统信任库

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
