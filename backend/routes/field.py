"""
Field Team Portal Routes — /api/field/*
=========================================
Endpoints for field teams: login, status updates,
mission responses, ground reports, resource consumption.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("routes.field")
router = APIRouter(prefix="/api/field", tags=["Field Portal"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class TeamLogin(BaseModel):
    team_id: str
    pin: str = "1234"


class MissionResponse(BaseModel):
    dispatch_id: int
    team_id: str
    response: str  # accepted | declined
    decline_reason: Optional[str] = None


class StatusUpdate(BaseModel):
    status: str  # en_route, on_site, returning, standby


class LocationPing(BaseModel):
    lat: float
    lng: float
    heading: Optional[float] = None
    speed_kmh: Optional[float] = None
    battery_pct: Optional[int] = None


class GroundReport(BaseModel):
    mission_id: int
    actual_affected_count: Optional[int] = None
    estimated_affected_count: Optional[int] = None
    area_accessibility: Optional[str] = None
    water_level_observation: Optional[str] = None
    additional_needs: Optional[str] = None
    route_conditions: Optional[str] = None
    notes: Optional[str] = None


class ConsumptionReport(BaseModel):
    dispatch_id: int
    consumption: list  # [{type, sent, consumed, returned}]


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/auth/login")
async def team_login(body: TeamLogin):
    """Simple team authentication."""
    from backend.main import db_pool
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    row = await db_pool.fetchrow(
        "SELECT * FROM team_status WHERE team_id = $1", body.team_id
    )
    if not row:
        raise HTTPException(404, "Team not found")

    # Simple PIN check (in production: bcrypt hash)
    if row["pin_hash"] != body.pin:
        raise HTTPException(401, "Invalid PIN")

    return {
        "team_id": row["team_id"],
        "team_name": row["team_name"],
        "status": row["status"],
        "members": row["team_members"],
        "has_boat": row["has_boat"],
        "has_medical_officer": row["has_medical_officer"],
    }


@router.get("/team/{team_id}/status")
async def get_team_status(team_id: str):
    from backend.main import db_pool
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    row = await db_pool.fetchrow("SELECT * FROM team_status WHERE team_id = $1", team_id)
    if not row:
        raise HTTPException(404, "Team not found")
    return dict(row)


@router.put("/team/{team_id}/status")
async def update_team_status(team_id: str, body: StatusUpdate):
    from backend.main import db_pool, redis_client
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    # Get current mission ID before updating
    current = await db_pool.fetchrow(
        "SELECT current_mission_id FROM team_status WHERE team_id = $1", team_id
    )
    mission_id = current["current_mission_id"] if current else None

    # If returning to standby, clear the mission assignment
    if body.status == "standby":
        await db_pool.execute(
            "UPDATE team_status SET status = $1, current_mission_id = NULL, updated_at = NOW() WHERE team_id = $2",
            body.status, team_id,
        )
    else:
        await db_pool.execute(
            "UPDATE team_status SET status = $1, updated_at = NOW() WHERE team_id = $2",
            body.status, team_id,
        )

    # Publish status change with mission_id for dispatch correlation
    if redis_client:
        await redis_client.publish("team_status_update", json.dumps({
            "team_id": team_id,
            "status": body.status,
            "mission_id": mission_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))

    return {"team_id": team_id, "status": body.status}


@router.get("/team/{team_id}/missions")
async def get_team_missions(team_id: str, limit: int = 10):
    from backend.main import db_pool
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    rows = await db_pool.fetch(
        """SELECT tr.id, tr.response, tr.dispatch_id, tr.responded_at, tr.decline_reason
           FROM team_responses tr
           WHERE tr.team_id = $1
           ORDER BY tr.responded_at DESC LIMIT $2""",
        team_id, limit,
    )
    return [dict(r) for r in rows]


@router.post("/mission/{mission_id}/respond")
async def respond_to_mission(mission_id: int, body: MissionResponse):
    from backend.main import db_pool, redis_client
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    # Record response
    await db_pool.execute(
        """INSERT INTO team_responses (dispatch_id, team_id, response, decline_reason)
           VALUES ($1, $2, $3, $4)""",
        body.dispatch_id, body.team_id, body.response, body.decline_reason,
    )

    # Update team status
    new_status = "en_route" if body.response == "accepted" else "standby"
    await db_pool.execute(
        "UPDATE team_status SET status = $1, current_mission_id = $2, updated_at = NOW() WHERE team_id = $3",
        new_status, body.dispatch_id if body.response == "accepted" else None, body.team_id,
    )

    # Publish feedback (Agent 4 listens to this for dispatch status tracking)
    if redis_client:
        await redis_client.publish("team_feedback", json.dumps({
            "dispatch_id": body.dispatch_id,
            "team_id": body.team_id,
            "response": body.response,
            "decline_reason": body.decline_reason,
            "responded_at": datetime.now(timezone.utc).isoformat(),
        }))
        await redis_client.publish("team_status_update", json.dumps({
            "team_id": body.team_id,
            "status": new_status,
            "mission_id": body.dispatch_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))

    return {"status": "ok", "team_status": new_status}


@router.post("/team/{team_id}/location")
async def send_location(team_id: str, body: LocationPing):
    from backend.main import db_pool, redis_client
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    await db_pool.execute(
        """UPDATE team_status
           SET current_lat = $1, current_lng = $2, last_heartbeat = NOW(), updated_at = NOW()
           WHERE team_id = $3""",
        body.lat, body.lng, team_id,
    )

    if redis_client:
        await redis_client.publish("team_location", json.dumps({
            "team_id": team_id,
            "lat": body.lat,
            "lng": body.lng,
            "heading": body.heading,
            "speed_kmh": body.speed_kmh,
            "battery_pct": body.battery_pct,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))

    return {"status": "ok"}


@router.post("/mission/{mission_id}/report")
async def submit_ground_report(mission_id: int, body: GroundReport):
    from backend.main import db_pool, redis_client
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    # Get team_id from mission
    team_row = await db_pool.fetchrow(
        "SELECT team_id FROM team_status WHERE current_mission_id = $1", mission_id
    )
    team_id = team_row["team_id"] if team_row else "unknown"

    await db_pool.execute(
        """INSERT INTO ground_reports
           (mission_id, team_id, actual_affected_count, estimated_affected_count,
            area_accessibility, water_level_observation, additional_needs,
            route_conditions, notes)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
        mission_id, team_id,
        body.actual_affected_count, body.estimated_affected_count,
        body.area_accessibility, body.water_level_observation,
        body.additional_needs, body.route_conditions, body.notes,
    )

    if redis_client:
        await redis_client.publish("ground_reports", json.dumps({
            "mission_id": mission_id,
            "team_id": team_id,
            "actual_affected_count": body.actual_affected_count,
            "estimated_affected_count": body.estimated_affected_count,
            "area_accessibility": body.area_accessibility,
            "water_level_observation": body.water_level_observation,
            "additional_needs": body.additional_needs,
            "route_conditions": body.route_conditions,
            "reported_at": datetime.now(timezone.utc).isoformat(),
        }))

    return {"status": "ok", "mission_id": mission_id}


@router.post("/mission/{mission_id}/consumption")
async def report_consumption(mission_id: int, body: ConsumptionReport):
    from backend.main import db_pool, redis_client
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    team_row = await db_pool.fetchrow(
        "SELECT team_id FROM team_status WHERE current_mission_id = $1", mission_id
    )
    team_id = team_row["team_id"] if team_row else body.consumption[0].get("team_id", "unknown") if body.consumption else "unknown"

    for item in body.consumption:
        await db_pool.execute(
            """INSERT INTO resource_consumption
               (dispatch_id, team_id, resource_type, quantity_sent, quantity_consumed, quantity_returned, reported_by_team, consumed_at)
               VALUES ($1, $2, $3, $4, $5, $6, TRUE, NOW())""",
            body.dispatch_id, team_id,
            item.get("type", "unknown"),
            item.get("sent", 0), item.get("consumed", 0), item.get("returned", 0),
        )

    if redis_client:
        await redis_client.publish("resource_consumed", json.dumps({
            "dispatch_id": body.dispatch_id,
            "team_id": team_id,
            "consumption": body.consumption,
            "reported_at": datetime.now(timezone.utc).isoformat(),
        }))

    return {"status": "ok", "items_logged": len(body.consumption)}


@router.get("/teams")
async def list_all_teams():
    """List all field teams (for command center)."""
    from backend.main import db_pool
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    rows = await db_pool.fetch("SELECT * FROM team_status ORDER BY team_id")
    return [dict(r) for r in rows]


@router.get("/team/{team_id}/mission")
async def get_active_mission(team_id: str):
    """
    Get the active dispatch mission for a field team.
    Used by the Field Portal to catch up on missed dispatch notifications.
    """
    from backend.main import db_pool
    if not db_pool:
        raise HTTPException(503, "Database not connected")

    team = await db_pool.fetchrow(
        "SELECT team_id, team_name, status, current_mission_id FROM team_status WHERE team_id = $1",
        team_id,
    )
    if not team:
        raise HTTPException(404, "Team not found")

    if team["status"] not in ("dispatched", "en_route", "on_site"):
        return {"dispatch_id": None, "status": team["status"], "message": "No active mission"}

    mission_id = team["current_mission_id"]
    if not mission_id:
        return {"dispatch_id": None, "status": team["status"], "message": "No mission ID assigned"}

    # Try to get dispatch details from dispatch_routes table
    dispatch = None
    try:
        dispatch = await db_pool.fetchrow(
            """SELECT id, zone_name, priority, total_eta_minutes, route_safety_score, status
               FROM dispatch_routes
               WHERE id = (
                   SELECT id FROM dispatch_routes
                   ORDER BY timestamp DESC LIMIT 1
               )"""
        )
    except Exception:
        pass

    return {
        "dispatch_id": mission_id,
        "team_id": team_id,
        "team_name": team["team_name"],
        "mission_type": "rescue_and_relief",
        "destination_name": dispatch["zone_name"] if dispatch else "Assigned Zone",
        "destination": {
            "lat": 25.07,
            "lng": 91.40,
        },
        "estimated_affected": 45,
        "priority": dispatch["priority"] if dispatch else 3,
        "priority_label": "HIGH",
        "resources_assigned": [],
        "estimated_travel_time_min": dispatch["total_eta_minutes"] if dispatch else 10,
        "route_safety_score": dispatch["route_safety_score"] if dispatch else 0.85,
        "route_notes": "Dispatch from nearest depot",
        "status": team["status"],
    }
