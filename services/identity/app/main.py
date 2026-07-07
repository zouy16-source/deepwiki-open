from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .db import Base, engine
from .routers import audit, projects, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.db_auto_create:
        Base.metadata.create_all(engine)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name}


app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(audit.router, prefix="/api/audit-logs", tags=["audit"])
