"""
Gateway Routes — /api/gateway/*
=================================
Endpoints for the 999/SMS Gateway interface.
Scenario feeder control + intake log queries.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from redis import asyncio as aioredis

logger = logging.getLogger("routes.gateway")
router = APIRouter(prefix="/api/gateway", tags=["Gateway"])


def get_deps():
    """Injected by main.py at startup."""
    from backend.main import db_pool, redis_client
    return db_pool, redis_client


# ------------------------------------------------------------------
# Intake log queries
# ------------------------------------------------------------------

@router.get("/intake")
async def get_intake_log(limit: int = 50, status: Optional[str] = None):
    """Get recent intake log entries."""
    from backend.main import db_pool
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    if status:
        rows = await db_pool.fetch(
            "SELECT * FROM intake_log WHERE processing_status = $1 ORDER BY received_at DESC LIMIT $2",
            status, limit,
        )
    else:
        rows = await db_pool.fetch(
            "SELECT * FROM intake_log ORDER BY received_at DESC LIMIT $1", limit
        )
    return [dict(r) for r in rows]


@router.get("/intake/stats")
async def get_intake_stats():
    """Get intake statistics for the dashboard."""
    from backend.main import db_pool
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    row = await db_pool.fetchrow("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE processing_status = 'received') AS pending,
            COUNT(*) FILTER (WHERE processing_status = 'sent_to_agent2') AS processing,
            COUNT(*) FILTER (WHERE processing_status = 'processed') AS processed,
            COUNT(*) FILTER (WHERE processing_status = 'duplicate') AS duplicate,
            COUNT(*) FILTER (WHERE processing_status = 'false_alarm') AS false_alarm,
            COUNT(*) FILTER (WHERE auto_detected_urgency = 'critical') AS critical,
            COUNT(*) FILTER (WHERE auto_detected_urgency = 'high') AS high,
            COUNT(*) FILTER (WHERE auto_detected_urgency = 'medium') AS medium,
            COUNT(*) FILTER (WHERE auto_detected_urgency = 'low') AS low_urgency,
            COUNT(*) FILTER (WHERE source_type = 'call_999') AS calls_999,
            COUNT(*) FILTER (WHERE source_type = 'sms') AS sms,
            COUNT(*) FILTER (WHERE source_type = 'social_media') AS social_media
        FROM intake_log
    """)
    return dict(row) if row else {}


# ------------------------------------------------------------------
# Scenario feeder proxy (forwards to feeder service on port 8010)
# ------------------------------------------------------------------

@router.post("/scenario/start")
async def start_scenario(speed: Optional[float] = None):
    """Start the scenario feeder."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            params = {"speed": speed} if speed else {}
            r = await client.post("http://scenario-feeder:8010/start", params=params)
            return r.json()
    except Exception:
        # Fallback: try localhost for non-Docker dev
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                params = {"speed": speed} if speed else {}
                r = await client.post("http://localhost:8010/start", params=params)
                return r.json()
        except Exception as e:
            raise HTTPException(503, f"Feeder not reachable: {e}")


@router.post("/scenario/pause")
async def pause_scenario():
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post("http://scenario-feeder:8010/pause")
            return r.json()
    except Exception:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post("http://localhost:8010/pause")
                return r.json()
        except Exception as e:
            raise HTTPException(503, f"Feeder not reachable: {e}")


@router.post("/scenario/reset")
async def reset_scenario():
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post("http://scenario-feeder:8010/reset")
            return r.json()
    except Exception:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post("http://localhost:8010/reset")
                return r.json()
        except Exception as e:
            raise HTTPException(503, f"Feeder not reachable: {e}")


@router.get("/scenario/status")
async def scenario_status():
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("http://scenario-feeder:8010/status")
            return r.json()
    except Exception:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get("http://localhost:8010/status")
                return r.json()
        except Exception as e:
            return {"state": "unreachable", "error": str(e)}
