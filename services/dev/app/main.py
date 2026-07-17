"""dev 服务(:8004)—— AI 编码执行层。

对外只暴露内部端点(requirement 服务调用触发编码);Worker/Dispatcher 逻辑在 app/coding。
运行:cd services/dev && uvicorn app.main:app --port 8004
"""

from fastapi import FastAPI

from .config import settings
from .routers import coding

app = FastAPI(title=settings.app_name)


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name}


app.include_router(coding.internal_router, tags=["coding-internal"])
