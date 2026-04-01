"""
SpendGuard API — FastAPI application entry point.

Real-time authorization API for agent-initiated financial actions.
Returns allow, block, or escalate before any financial action executes.

All routes wired: health, policies, checks, violations, simulate.
Auth middleware on protected routes. Global exception handler.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.auth import require_api_key
from api.rate_limit import check_rate_limit_auth, check_rate_limit_demo

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

# -- CORS Middleware --
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -- Request ID Middleware --
@app.middleware("http")
async def add_request_id(request: Request, call_next) -> Response:
    """Attach a unique request_id to every request for logging and error responses."""
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    request.state.request_id = request_id
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# -- Global Exception Handlers --

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Override FastAPI default 422 to use our locked error format."""
    request_id = getattr(request.state, "request_id", "unknown")
    # Build a human-readable message from validation errors
    errors = exc.errors()
    if errors:
        first = errors[0]
        loc = " → ".join(str(l) for l in first.get("loc", []))
        msg = first.get("msg", "Validation error")
        message = f"{loc}: {msg}" if loc else msg
    else:
        message = "Request validation failed."

    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "validation_error",
                "message": message,
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch all unhandled exceptions and return standard error format."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error("Unhandled exception — request_id=%s error=%s", request_id, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "An unexpected error occurred. Please try again later.",
                "request_id": request_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        },
    )


# -- Register Route Modules --
from api.routes.health import router as health_router
from api.routes.policies import router as policies_router
from api.routes.checks import router as checks_router
from api.routes.violations import router as violations_router
from api.routes.simulate import router as simulate_router
from api.routes.keys import router as keys_router

# Public routes — no auth required
app.include_router(health_router)
app.include_router(
    simulate_router,
    prefix="/v1",
    dependencies=[Depends(check_rate_limit_demo)],
)

# Protected routes — require API key + auth rate limiting
auth_dependencies = [Depends(require_api_key), Depends(check_rate_limit_auth)]
app.include_router(policies_router, prefix="/v1", dependencies=auth_dependencies)
app.include_router(checks_router, prefix="/v1", dependencies=auth_dependencies)
app.include_router(violations_router, prefix="/v1", dependencies=auth_dependencies)

# Keys route — uses its own admin key check, NOT standard auth
app.include_router(keys_router, prefix="/v1")

# -- Marketing Website (static files) --
# Mounted LAST so API routes always take priority
import os
from fastapi.staticfiles import StaticFiles

_base_dir = os.path.dirname(os.path.abspath(__file__))
_website_dir = os.path.join(_base_dir, "website")
if os.path.isdir(_website_dir):
    app.mount("/", StaticFiles(directory=_website_dir, html=True), name="website")
    logger.info("Website mounted from: %s", _website_dir)
else:
    logger.warning("Website directory not found at: %s", _website_dir)


# -- Lifecycle Events --
@app.on_event("startup")
async def on_startup() -> None:
    """Log service startup."""
    logger.info("SpendGuard API starting up — version 1.0.0")
    logger.info(
        "Routes registered: /health, /v1/policies, /v1/checks, /v1/violations, /v1/simulate"
    )
    logger.info("Auth middleware active on: /v1/policies, /v1/checks, /v1/violations")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Log service shutdown."""
    logger.info("SpendGuard API shutting down")
