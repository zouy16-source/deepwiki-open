from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .db import Base, engine
from .routers import analysis, requirements, reviews, tapd_sync


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.db_auto_create:
        Base.metadata.create_all(engine)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name}


app.include_router(requirements.router, prefix="/api/requirements", tags=["requirements"])
app.include_router(reviews.router, prefix="/api", tags=["reviews"])
# 分析发起/查询走 /api/**（经 BFF），回调走 /internal/**（服务间直连，不经 BFF）
app.include_router(analysis.router, prefix="/api", tags=["analysis"])
app.include_router(analysis.internal_router, tags=["analysis-internal"])
app.include_router(tapd_sync.router, prefix="/api", tags=["tapd"])
