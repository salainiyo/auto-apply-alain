from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import auth, resumes, users
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.database import Base, engine
from app.db import models  # noqa: F401
from app.middleware.request_logging import RequestLoggingMiddleware

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(RequestLoggingMiddleware)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(resumes.router)


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
