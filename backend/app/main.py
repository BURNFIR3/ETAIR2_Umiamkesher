import contextlib
import logging
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import create_tables
from app.routers import auth, workspaces, folders, files, query, graph, calendar

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer() if settings.DEBUG else structlog.processors.JSONRenderer(),
    ]
)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("etair_startup", env=settings.ENVIRONMENT)
    # In dev: auto-create tables. In prod: use Alembic.
    # Auto-create tables in both dev and prod (idempotent — safe to run every startup)
    await create_tables()
    yield
    logger.info("etair_shutdown")


app = FastAPI(
    title="ETAIR — Industrial Knowledge Intelligence Platform",
    description="Document-first, governance-first industrial workspace with AI retrieval.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://*.vercel.app",
        "https://etair-2-umiamkesher.vercel.app",
        "https://etair-umiamkesher.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request timing middleware ────────────────────────────────────────────────
@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = int((time.time() - start) * 1000)
    response.headers["X-Response-Time"] = f"{elapsed}ms"
    return response


# ─── Global error handler ─────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", exc=str(exc), path=request.url.path)
    import traceback
    if settings.DEBUG:
        return JSONResponse(status_code=500, content={"detail": str(exc), "traceback": traceback.format_exc()})
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ─── Routers ──────────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api/v1")
app.include_router(workspaces.router, prefix="/api/v1")
app.include_router(folders.router, prefix="/api/v1")
app.include_router(files.router, prefix="/api/v1")
app.include_router(query.router, prefix="/api/v1")
app.include_router(graph.router, prefix="/api/v1")
app.include_router(calendar.router, prefix="/api/v1")


# ─── Health check ─────────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "version": "0.1.0", "env": settings.ENVIRONMENT}
