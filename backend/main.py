"""
main.py — FastAPI application entry point for GetSpons.

Middleware
----------
- CORS
- Bot protection: blocks missing User-Agent, blocks >200 req/min per IP
- Request / response logger: method, path, client IP, status, response time ms
  (warns on requests exceeding 2 seconds)

Rate limiting
-------------
Uses slowapi. Limits are defined here and applied via decorators in each
router file. See comments below for exact limits per endpoint.
"""

import time
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from dotenv import load_dotenv
from limiter import limiter
from auth import router as auth_router
from brands import router as brands_router
from logger import get_logger
from mediakit import router as mediakit_router
from pitch import router as pitch_router
from profile import router as profile_router
from admin import router as admin_router

load_dotenv()

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter  (shared instance — imported by all router files)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI()

# Attach limiter state and its built-in exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Override the default slowapi 429 response format to match our API style
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    client_ip = request.client.host if request.client else "unknown"
    log.warning(
        "Rate limit hit | ip=%s | path=%s | limit=%s",
        client_ip, request.url.path, str(exc.detail),
    )
    return JSONResponse(
        status_code=429,
        content={
            "error":   "Rate limit exceeded",
            "message": "Too many requests, try again later",
        },
    )


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
        "null",
        "https://*.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Bot protection middleware
# ---------------------------------------------------------------------------

# In-memory sliding-window counter: { ip: [timestamp, ...] }
# Good enough for a single-process deployment; swap for Redis in production.
_request_log: dict[str, list[float]] = defaultdict(list)
_BOT_WINDOW_SECONDS = 60
_BOT_MAX_REQUESTS   = 200


@app.middleware("http")
async def bot_protection(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"

    # ── Block missing User-Agent ──────────────────────────────────────
    user_agent = request.headers.get("user-agent", "").strip()
    if not user_agent:
        log.warning("Bot blocked (no User-Agent) | ip=%s | path=%s", client_ip, request.url.path)
        return JSONResponse(
            status_code=429,
            content={"error": "Too many requests, slow down"},
        )

    # ── Block >200 requests per minute per IP ─────────────────────────
    now = time.time()
    window_start = now - _BOT_WINDOW_SECONDS

    # Prune timestamps outside the rolling window
    _request_log[client_ip] = [
        t for t in _request_log[client_ip] if t > window_start
    ]
    _request_log[client_ip].append(now)

    if len(_request_log[client_ip]) > _BOT_MAX_REQUESTS:
        log.warning(
            "Bot blocked (>%d req/min) | ip=%s | count=%d | path=%s",
            _BOT_MAX_REQUESTS, client_ip,
            len(_request_log[client_ip]), request.url.path,
        )
        return JSONResponse(
            status_code=429,
            content={"error": "Too many requests, slow down"},
        )

    return await call_next(request)


# ---------------------------------------------------------------------------
# Request / Response logging middleware
# ---------------------------------------------------------------------------

SLOW_REQUEST_THRESHOLD_MS = 2_000


@app.middleware("http")
async def log_requests(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    method    = request.method
    path      = request.url.path

    log.info("→ %s %s | ip=%s", method, path, client_ip)

    start    = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1_000

    status = response.status_code

    if elapsed_ms > SLOW_REQUEST_THRESHOLD_MS:
        log.warning(
            "← %s %s | status=%d | %.1fms  ⚠ SLOW REQUEST",
            method, path, status, elapsed_ms,
        )
    else:
        log.info("← %s %s | status=%d | %.1fms", method, path, status, elapsed_ms)

    return response


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth_router,     prefix="/api/auth")
app.include_router(profile_router,  prefix="/api/profile")
app.include_router(mediakit_router, prefix="/api/mediakit")
app.include_router(brands_router,   prefix="/api/brands")
app.include_router(pitch_router,    prefix="/api/pitches")
app.include_router(admin_router,    prefix="/api/admin")


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    log.debug("Health check called")
    return {"status": "ok"}