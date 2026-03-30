"""
SpendGuard API — FastAPI application entry point.

Real-time authorization API for agent-initiated financial actions.
Returns allow, block, or escalate before any financial action executes.

Only GET /health is wired in this loop. All other routes are added in Loop 4.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("spendguard")

app = FastAPI(
    title="SpendGuard API",
    version="1.0.0",
    description=(
        "Real-time authorization API for agent-initiated financial actions. "
        "Returns allow, block, or escalate before any financial action executes."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    """Log service startup."""
    logger.info("SpendGuard API starting up — version 1.0.0")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Log service shutdown."""
    logger.info("SpendGuard API shutting down")


@app.get("/health", tags=["health"], summary="Health check")
async def health() -> dict:
    """
    Returns service health status.
    No authentication required.
    """
    return {
        "status": "ok",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
