"""identity 服务测试基座：SQLite 落盘库（models.PK 已适配），认证默认关闭。

必须在导入 app.* 之前设好环境变量——settings/engine 都在模块导入时初始化。
"""

import os
import tempfile

_db_file = os.path.join(tempfile.mkdtemp(prefix="identity-test-"), "identity.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file}"
os.environ["INTERNAL_JWT_SECRET"] = ""  # 关认证（current_subject 返回 "dev"）；JWT 校验单独用例覆盖
os.environ["LDAP_URL"] = ""  # 单测不连真实目录；用例各自 monkeypatch

import pytest
from fastapi.testclient import TestClient

from app.db import Base, SessionLocal, engine
from app.main import app


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db):
    with TestClient(app) as c:
        yield c
