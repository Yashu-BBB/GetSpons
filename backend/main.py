"""
main.py — FastAPI application entry point for GetSpons.

Middleware
----------
- CORS
- Request / response logger: logs method, path, client IP, status code,
  response time (ms). Warns on any request exceeding 2 seconds.
"""

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from auth import router as auth_router
from brands import router as brands_router
from logger import get_logger
from mediakit import router as mediakit_router
from pitch import router as pitch_router
from profile import router as profile_router

load_dotenv()

log = get_logger(__name__)

app = FastAPI()

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5500",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:5500",
        "null",                    # for opening HTML files directly
        "https://*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / Response logging middleware
# ---------------------------------------------------------------------------

SLOW_REQUEST_THRESHOLD_MS = 2_000   # warn if request takes longer than this


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every request and its response, warn on slow responses."""
    client_ip = request.client.host if request.client else "unknown"
    method    = request.method
    path      = request.url.path

    log.info("→ %s %s | ip=%s", method, path, client_ip)

    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1_000

    status = response.status_code

    if elapsed_ms > SLOW_REQUEST_THRESHOLD_MS:
        log.warning(
            "← %s %s | status=%d | %.1fms  ⚠ SLOW REQUEST",
            method, path, status, elapsed_ms,
        )
    else:
        log.info(
            "← %s %s | status=%d | %.1fms",
            method, path, status, elapsed_ms,
        )

    return response

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth_router,     prefix="/api/auth")
app.include_router(profile_router,  prefix="/api/profile")
app.include_router(mediakit_router, prefix="/api/mediakit")
app.include_router(brands_router,   prefix="/api/brands")
app.include_router(pitch_router,    prefix="/api/pitches")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    log.debug("Health check called")
    return {"status": "ok"}