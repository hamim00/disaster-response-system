"""
Command Center Routes — /api/command/*
========================================
Extended endpoints for the unified command center dashboard.
Team tracking, ground reports, consumption, resupply.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("routes.command")
router = APIRouter(prefix="/api/command", tags=["Command Center"])


@router.get("/overview")
async def get_overview():
    """Full system overview for the command center dashboard."""
    from backend.main import db_pool
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    # Intake stats
    intake = await db_pool.fetchrow("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE processing_status = 'processed') AS processed,
               COUNT(*) FILTER (WHERE auto_detected_urgency = 'critical') AS critical
        FROM intake_log
    """)

    # Team stats
    teams = await db_pool.fetchrow("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status = 'standby') AS standby,
               COUNT(*) FILTER (WHERE status = 'en_route') AS en_route,
               COUNT(*) FILTER (WHERE status = 'on_site') AS on_site,
               COUNT(*) FILTER (WHERE status = 'returning') AS returning_teams,
               COUNT(*) FILTER (WHERE status = 'unreachable') AS unreachable
        FROM team_status
    """)

    # Ground reports count
    reports = await db_pool.fetchval("SELECT COUNT(*) FROM ground_reports")

    # Resupply alerts
    resupply = await db_pool.fetchval(
        "SELECT COUNT(*) FROM resupply_requests WHERE status = 'pending'"
    )

    return {
        "intake": dict(intake) if intake else {},
        "teams": dict(teams) if teams else {},
        "ground_reports_count": reports or 0,
        "pending_resupply": resupply or 0,
    }


@router.get("/teams")
async def get_all_teams():
    from backend.main import db_pool
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    rows = await db_pool.fetch(
        "SELECT * FROM team_status ORDER BY team_id"
    )
    return [dict(r) for r in rows]


@router.get("/ground-reports")
async def get_ground_reports(limit: int = 20):
    from backend.main import db_pool
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    rows = await db_pool.fetch(
        "SELECT * FROM ground_reports ORDER BY reported_at DESC LIMIT $1", limit
    )
    return [dict(r) for r in rows]


@router.get("/consumption")
async def get_consumption(limit: int = 30):
    from backend.main import db_pool
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    rows = await db_pool.fetch(
        "SELECT * FROM resource_consumption ORDER BY created_at DESC LIMIT $1", limit
    )
    return [dict(r) for r in rows]


@router.get("/resupply")
async def get_resupply_requests(status: Optional[str] = None):
    from backend.main import db_pool
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    if status:
        rows = await db_pool.fetch(
            "SELECT * FROM resupply_requests WHERE status = $1 ORDER BY requested_at DESC", status
        )
    else:
        rows = await db_pool.fetch(
            "SELECT * FROM resupply_requests ORDER BY requested_at DESC LIMIT 50"
        )
    return [dict(r) for r in rows]


@router.get("/intake/recent")
async def get_recent_intake(limit: int = 20):
    from backend.main import db_pool
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    rows = await db_pool.fetch(
        "SELECT * FROM intake_log ORDER BY received_at DESC LIMIT $1", limit
    )
    return [dict(r) for r in rows]


# ------------------------------------------------------------------
# River levels (simulated — based on Jobayer's Sylhet river data)
# ------------------------------------------------------------------

import random

_SYLHET_RIVERS = [
    {"name": "Surma",     "danger_level": 9.0, "base_level": 7.2},
    {"name": "Kushiyara", "danger_level": 8.5, "base_level": 5.8},
    {"name": "Manu",      "danger_level": 6.5, "base_level": 4.1},
    {"name": "Khowai",    "danger_level": 5.8, "base_level": 3.9},
    {"name": "Piyain",    "danger_level": 7.5, "base_level": 6.8},
    {"name": "Juri",      "danger_level": 5.0, "base_level": 3.2},
    {"name": "Saree",     "danger_level": 4.5, "base_level": 2.8},
    {"name": "Kangsha",   "danger_level": 7.0, "base_level": 5.5},
]


@router.get("/rivers")
async def get_river_levels():
    """Simulated river level data for Sylhet Division (8 rivers)."""
    results = []
    for river in _SYLHET_RIVERS:
        # Add random jitter for a live-sensor feel
        jitter = random.uniform(-0.4, 0.8)
        current_level = round(river["base_level"] + jitter, 2)
        danger = river["danger_level"]
        pct = round(current_level / danger * 100, 1)

        if current_level >= danger:
            status = "DANGER"
        elif current_level >= danger * 0.9:
            status = "WARNING"
        elif current_level >= danger * 0.75:
            status = "ALERT"
        else:
            status = "NORMAL"

        results.append({
            "name": river["name"],
            "current_level_m": current_level,
            "danger_level_m": danger,
            "percentage": pct,
            "status": status,
        })
    return results
