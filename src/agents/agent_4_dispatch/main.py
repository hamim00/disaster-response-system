"""
Agent 4 — Dispatch Optimization
=================================
Receives allocations from Agent 3 via Redis (dispatch_order channel),
calculates optimized routes, ETAs, and safety scores, then persists
dispatch plans and publishes status updates.

FastAPI on port 8004.

Author: Mahmudul Hasan
"""
import asyncio
import json
import logging
import os
import signal
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import asyncpg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from redis import asyncio as aioredis

# ---------------------------------------------------------------------------
# Append project root so shared/ is importable
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from .redis_handler import Agent4RedisHandler
from .models import DispatchPlan, DispatchSummary

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(name)-28s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.FileHandler("agent_4_dispatch.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("agent_4_dispatch")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

AGENT_PORT = int(os.getenv("AGENT_4_PORT", "8004"))
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://disaster_admin:disaster123@localhost:5432/disaster_response",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
db_pool: Optional[asyncpg.Pool] = None
redis_client: Optional[aioredis.Redis] = None
handler: Optional[Agent4RedisHandler] = None


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, redis_client, handler

    # ── Database ──
    try:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        await db_pool.fetchval("SELECT 1")
        logger.info("[OK] PostgreSQL connected")
    except Exception as exc:
        logger.warning("[WARN] PostgreSQL unavailable: %s — running without DB", exc)
        db_pool = None

    # ── Redis ──
    try:
        redis_client = await aioredis.from_url(REDIS_URL, decode_responses=True)
        await redis_client.ping()
        logger.info("[OK] Redis connected and verified")
    except Exception as exc:
        logger.warning("[WARN] Redis unavailable: %s — running without pub/sub", exc)
        redis_client = None

    # ── Handler ──
    if db_pool or redis_client:
        handler = Agent4RedisHandler(redis_client, db_pool)
        if redis_client:
            asyncio.create_task(handler.start_listening())
            asyncio.create_task(handler.publish_heartbeat())
            logger.info("Agent 4 listening on dispatch_order channel")
        else:
            logger.info("Agent 4 running without Redis subscription")
    else:
        handler = Agent4RedisHandler(None, None)
        logger.warning("Agent 4 running in degraded mode (no DB, no Redis)")

    logger.info("[START] Agent 4 — Dispatch Optimization started on port %d", AGENT_PORT)

    yield

    # ── Shutdown ──
    if redis_client:
        await redis_client.aclose()
    if db_pool:
        await db_pool.close()
    logger.info("Agent 4 shut down")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Agent 4 — Dispatch Optimization",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "agent": "agent_4_dispatch",
        "version": "1.0.0",
        "port": AGENT_PORT,
        "subscribes_to": ["dispatch_order"],
        "publishes_to": ["dispatch_status", "agent_status"],
        "db_connected": db_pool is not None,
        "redis_connected": redis_client is not None,
    }


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
    status = "healthy" if db_ok else "degraded"
    return {
        "status": status,
        "db": "ok" if db_ok else "disconnected",
        "redis": "ok" if redis_ok else "disconnected",
    }


@app.get("/dispatches")
async def get_dispatches(limit: int = 20):
    """Get recent dispatch plans."""
    # Try DB first
    if db_pool:
        try:
            rows = await db_pool.fetch(
                """
                SELECT dr.id, dr.timestamp, dr.allocation_id,
                       dr.incident_id, dr.zone_name, dr.priority,
                       dr.total_eta_minutes, dr.route_safety_score,
                       dr.status,
                       (SELECT COUNT(*) FROM team_routes tr
                        WHERE tr.dispatch_id = dr.id) AS team_count
                FROM dispatch_routes dr
                ORDER BY dr.timestamp DESC
                LIMIT $1
                """,
                limit,
            )
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("DB query failed: %s", exc)

    # Fallback to in-memory
    if handler and handler._plans:
        return [
            {
                "id": str(p.id),
                "timestamp": p.timestamp.isoformat(),
                "allocation_id": str(p.allocation_id),
                "zone_name": p.zone_name,
                "priority": p.priority,
                "total_eta_minutes": p.total_eta_minutes,
                "route_safety_score": p.route_safety_score,
                "status": p.status.value,
                "team_count": len(p.team_routes),
            }
            for p in handler._plans[:limit]
        ]
    return []


@app.get("/dispatches/{dispatch_id}")
async def get_dispatch(dispatch_id: str):
    """Get detailed dispatch plan including team routes."""
    if handler:
        for p in handler._plans:
            if str(p.id) == dispatch_id:
                return p.model_dump(mode="json")
    if db_pool:
        row = await db_pool.fetchrow(
            "SELECT * FROM dispatch_routes WHERE id = $1::uuid", dispatch_id
        )
        if row:
            return dict(row)
    raise HTTPException(status_code=404, detail="Dispatch not found")


@app.get("/active")
async def get_active_dispatches():
    """Get currently active dispatches."""
    if db_pool:
        try:
            rows = await db_pool.fetch(
                "SELECT * FROM active_dispatches ORDER BY priority ASC"
            )
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("Active dispatch query failed: %s", exc)

    if handler:
        return [
            {
                "dispatch_id": str(p.id),
                "zone_name": p.zone_name,
                "priority": p.priority,
                "total_eta_minutes": p.total_eta_minutes,
                "route_safety_score": p.route_safety_score,
                "team_count": len(p.team_routes),
                "team_names": [tr.unit_name for tr in p.team_routes],
                "fastest_eta": min((tr.eta_minutes for tr in p.team_routes), default=0),
                "slowest_eta": max((tr.eta_minutes for tr in p.team_routes), default=0),
            }
            for p in handler._plans
            if p.status == "active"
        ]
    return []


@app.post("/trigger")
async def trigger_dispatch(allocation: dict):
    """Manually trigger dispatch for one allocation."""
    if not handler:
        raise HTTPException(status_code=503, detail="Handler not ready")
    plan = await handler.optimizer.create_dispatch_plan(allocation)
    if not plan:
        raise HTTPException(status_code=422, detail="Could not create plan")
    handler._plans.insert(0, plan)
    if len(handler._plans) > 100:
        handler._plans = handler._plans[:100]
    handler._dispatch_count += 1
    return plan.model_dump(mode="json")


@app.post("/trigger_batch")
async def trigger_batch_dispatch(allocations: list):
    """Manually trigger dispatch for a batch of allocations."""
    if not handler:
        raise HTTPException(status_code=503, detail="Handler not ready")
    plans = []
    for alloc in allocations:
        plan = await handler.optimizer.create_dispatch_plan(alloc)
        if plan:
            handler._plans.insert(0, plan)
            handler._dispatch_count += 1
            plans.append(plan)
    if len(handler._plans) > 100:
        handler._plans = handler._plans[:100]
    return {
        "processed": len(allocations),
        "dispatched": len(plans),
        "plans": [p.model_dump(mode="json") for p in plans],
    }


@app.get("/status")
async def status():
    if not handler:
        return {"status": "starting"}
    uptime = (datetime.now(timezone.utc) - handler._start_time).total_seconds()
    return {
        "status": "running",
        "uptime_s": uptime,
        "last_action": handler._last_action,
        "total_dispatches": handler._dispatch_count,
        "active_plans": len([p for p in handler._plans if p.status == "active"]) if handler._plans else 0,
        "db_connected": db_pool is not None,
        "redis_connected": redis_client is not None,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=AGENT_PORT,
        log_level="info",
        access_log=True,
    )