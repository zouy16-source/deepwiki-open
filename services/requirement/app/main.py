from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .db import Base, engine
from .routers import requirements, reviews


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
