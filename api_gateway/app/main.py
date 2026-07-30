"""Visitor Management System - API Gateway.

This service handles everything except face math. Face detection and matching
live in a completely separate service that is not reachable from the internet.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (approvals, auth, blocklist, dashboard, invites, kiosk,
                        people, public, system, visitors, visits)
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.jobs.scheduler import run_all

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


async def _periodic_jobs():
    while True:
        await asyncio.sleep(300)  # every 5 minutes
        try:
            run_all()
        except Exception as e:
            log.error("Job run failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import app.models  # noqa: F401  - registers every table
    Base.metadata.create_all(bind=engine)

    from app.db.session import SessionLocal
    from seed import seed_if_empty
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()

    task = asyncio.create_task(_periodic_jobs())
    log.info("VMS API ready. Docs at /docs")
    yield
    task.cancel()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Visitor Management System API. Three caller types: staff (JWT), "
                "visitor (invite token), kiosk device (device token).",
    lifespan=lifespan,
)

# Locked to the known frontend origins - never "*"
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API = "/api/v1"
for r in (auth.router, dashboard.router, invites.router, public.router, kiosk.router,
          visitors.router, visits.router, approvals.router, blocklist.router,
          people.router, system.router):
    app.include_router(r, prefix=API)


@app.get("/health", tags=["Health"])
def health():
    from app.clients.face_client import face_client
    return {
        "status": "ok",
        "service": "api_gateway",
        "database": settings.DATABASE_URL.split("://")[0],
        "face_service": "up" if face_client.available() else "down",
    }


@app.get("/", tags=["Health"])
def root():
    return {"service": settings.APP_NAME, "docs": "/docs", "health": "/health"}
