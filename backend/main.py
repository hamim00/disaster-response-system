"""
FloodShield BD — Unified Backend
==================================
Serves all three interfaces from a single FastAPI application:
  /gateway  → 999/SMS Gateway
  /field    → Field Team Portal
  /command  → Command Center Dashboard

Also provides WebSocket endpoints and REST APIs for all components.

Port: 8000
"""
import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import asyncpg
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from redis import asyncio as aioredis
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("floodshield_backend")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://disaster_admin:disaster123@localhost:5432/disaster_response",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))

# Resolve paths
BASE_DIR = Path(__file__).resolve().parent.parent  # project root
FRONTEND_DIR = BASE_DIR / "frontend"

# ---------------------------------------------------------------------------
# Global state (used by route modules via `from backend.main import ...`)
# ---------------------------------------------------------------------------
db_pool: Optional[asyncpg.Pool] = None
redis_client: Optional[aioredis.Redis] = None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, redis_client

    # PostgreSQL
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        await db_pool.fetchval("SELECT 1")
        logger.info("[OK] PostgreSQL connected")
    except Exception as e:
        logger.warning("[WARN] PostgreSQL not available: %s", e)
        db_pool = None

    # Redis
    try:
        redis_client = await aioredis.from_url(REDIS_URL, decode_responses=True)
        await redis_client.ping()
        logger.info("[OK] Redis connected")
    except Exception as e:
        logger.warning("[WARN] Redis not available: %s", e)
        redis_client = None

    # Start Redis → WebSocket bridge
    if redis_client:
        from backend.websocket.bridge import redis_to_websocket_bridge

        async def _bridge_wrapper():
            """Wrapper to catch and log bridge crashes."""
            try:
                logger.info("Bridge task starting...")
                await redis_to_websocket_bridge(REDIS_URL)
            except Exception as e:
                logger.error("BRIDGE TASK CRASHED: %s", e, exc_info=True)

        asyncio.create_task(_bridge_wrapper())
        logger.info("Redis → WebSocket bridge started")
    else:
        logger.error("Redis not connected — bridge NOT started! Gateway/Field will not receive live events.")

    logger.info("FloodShield Backend started on port %d", BACKEND_PORT)

    yield

    if redis_client:
        await redis_client.aclose()
    if db_pool:
        await db_pool.close()
    logger.info("Backend shut down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="FloodShield BD — Unified Backend",
    description="Serves 999 Gateway, Field Portal, and Command Center",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Include route modules
# ---------------------------------------------------------------------------
from backend.routes.gateway import router as gateway_router
from backend.routes.field import router as field_router
from backend.routes.command import router as command_router

app.include_router(gateway_router)
app.include_router(field_router)
app.include_router(command_router)


# ---------------------------------------------------------------------------
# WebSocket endpoints
# ---------------------------------------------------------------------------
from backend.websocket.manager import manager


@app.websocket("/api/ws/gateway")
async def ws_gateway(ws: WebSocket):
    await manager.connect_gateway(ws)
    try:
        while True:
            await ws.receive_text()  # keep alive
    except WebSocketDisconnect:
        manager.disconnect_gateway(ws)


@app.websocket("/api/ws/command")
async def ws_command(ws: WebSocket):
    await manager.connect_command(ws)
    try:
        while True:
            data = await ws.receive_text()
            # Command center can send commands back (future use)
    except WebSocketDisconnect:
        manager.disconnect_command(ws)


@app.websocket("/api/ws/field/{team_id}")
async def ws_field(ws: WebSocket, team_id: str):
    await manager.connect_field(team_id, ws)
    try:
        while True:
            data = await ws.receive_text()
            # Field portal can send heartbeats / status via WS too
            try:
                msg = json.loads(data)
                if msg.get("type") == "heartbeat" and redis_client:
                    await redis_client.publish("team_location", json.dumps({
                        "team_id": team_id,
                        "lat": msg.get("lat"),
                        "lng": msg.get("lng"),
                        "timestamp": msg.get("timestamp"),
                    }))
            except (json.JSONDecodeError, Exception):
                pass
    except WebSocketDisconnect:
        manager.disconnect_field(team_id)


# ---------------------------------------------------------------------------
# Frontend page routes (serve static HTML)
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "service": "FloodShield BD — Unified Backend",
        "interfaces": {
            "gateway": "/gateway",
            "command": "/command",
            "field": "/field",
        },
        "api_docs": "/docs",
    }


@app.get("/gateway")
async def serve_gateway():
    path = FRONTEND_DIR / "gateway" / "index.html"
    if path.exists():
        return FileResponse(path, media_type="text/html")
    return HTMLResponse("<h1>Gateway — frontend not built yet</h1>", 404)


@app.get("/field")
async def serve_field():
    path = FRONTEND_DIR / "field" / "index.html"
    if path.exists():
        return FileResponse(path, media_type="text/html")
    return HTMLResponse("<h1>Field Portal — frontend not built yet</h1>", 404)


@app.get("/command")
async def serve_command():
    path = FRONTEND_DIR / "command" / "index.html"
    if path.exists():
        return FileResponse(path, media_type="text/html")
    return HTMLResponse("<h1>Command Center — frontend not built yet</h1>", 404)


@app.get("/diagnostics")
async def serve_diagnostics():
    path = FRONTEND_DIR / "diagnostics.html"
    if path.exists():
        return FileResponse(path, media_type="text/html")
    return HTMLResponse("<h1>Diagnostics page not found</h1>", 404)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    db_ok = False
    redis_ok = False
    try:
        if db_pool:
            await db_pool.fetchval("SELECT 1")
            db_ok = True
    except Exception:
        pass
    try:
        if redis_client:
            await redis_client.ping()
            redis_ok = True
    except Exception:
        pass
    return {
        "status": "healthy" if db_ok and redis_ok else "degraded",
        "db": "ok" if db_ok else "disconnected",
        "redis": "ok" if redis_ok else "disconnected",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=BACKEND_PORT,
        log_level="info",
        reload=True,
    )
