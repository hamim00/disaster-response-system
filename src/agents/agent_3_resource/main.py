"""
Agent 3 — Resource Management
FastAPI service on port 8003.

Subscribes to Agent 2's distress_queue via Redis.
Allocates nearest resources using Haversine distance.
Publishes dispatch_order to Agent 4.

Author: Disaster Response Team
"""
import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import asyncpg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from redis import asyncio as aioredis

# Make shared/ importable — works for both local dev and Docker
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from .inventory_manager import InventoryManager
from .models import (
    GeoPoint,
    ResourceAllocation,
    ResourceType,
    RestockRequest,
    RestockResponse,
)
from .redis_handler import Agent3RedisHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler("agent_3_resource.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("agent_3_resource")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://disaster_admin:disaster123@localhost:5432/disaster_response",
)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
AGENT_PORT = int(os.getenv("AGENT_PORT", "8003"))

# ---------------------------------------------------------------------------
# App state
# ---------------------------------------------------------------------------
db_pool: Optional[asyncpg.Pool] = None
redis_client = None
handler: Optional[Agent3RedisHandler] = None


# ---------------------------------------------------------------------------
# Seed data — realistic Bangladesh depot locations
# BIWTA river stations, major hospitals, Mohakhali depots
# ---------------------------------------------------------------------------
SEED_RESOURCES = [
    # Rescue boats — BIWTA river stations + district boats
    {"type": "rescue_boat", "name": "Boat Mirpur-1",     "capacity": 15, "lat": 23.8041, "lon": 90.3654},
    {"type": "rescue_boat", "name": "Boat Mirpur-2",     "capacity": 15, "lat": 23.8041, "lon": 90.3654},
    {"type": "rescue_boat", "name": "Boat Sadarghat-1",  "capacity": 20, "lat": 23.7104, "lon": 90.4074},
    {"type": "rescue_boat", "name": "Boat Sadarghat-2",  "capacity": 20, "lat": 23.7104, "lon": 90.4074},
    {"type": "rescue_boat", "name": "Boat Sylhet-1",     "capacity": 12, "lat": 24.8949, "lon": 91.8687},
    {"type": "rescue_boat", "name": "Boat Sylhet-2",     "capacity": 12, "lat": 24.8949, "lon": 91.8687},
    {"type": "rescue_boat", "name": "Boat Sirajganj-1",  "capacity": 18, "lat": 24.4534, "lon": 89.7007},
    {"type": "rescue_boat", "name": "Boat Sunamganj-1",  "capacity": 10, "lat": 25.0715, "lon": 91.3953},

    # Medical teams — major hospitals
    {"type": "medical_team", "name": "MedTeam DMCH",         "capacity": 50, "lat": 23.7465, "lon": 90.3760},
    {"type": "medical_team", "name": "MedTeam Dhaka-2",      "capacity": 40, "lat": 23.7376, "lon": 90.3957},
    {"type": "medical_team", "name": "MedTeam MAG Osmani",   "capacity": 30, "lat": 24.8998, "lon": 91.8710},
    {"type": "medical_team", "name": "MedTeam Sirajganj",    "capacity": 25, "lat": 24.4600, "lon": 89.7100},

    # Medical kits — depot stockpiles
    {"type": "medical_kit", "name": "Kit-Depot-Dhaka-1",    "capacity": 100, "lat": 23.8103, "lon": 90.4125},
    {"type": "medical_kit", "name": "Kit-Depot-Dhaka-2",    "capacity": 100, "lat": 23.7500, "lon": 90.3800},
    {"type": "medical_kit", "name": "Kit-Depot-Sylhet",     "capacity":  60, "lat": 24.9000, "lon": 91.8700},
    {"type": "medical_kit", "name": "Kit-Depot-Chittagong", "capacity":  80, "lat": 22.3569, "lon": 91.7832},

    # Food supply depots — Mohakhali + district
    {"type": "food_supply", "name": "Food-Mohakhali-1",  "capacity": 500, "lat": 23.7781, "lon": 90.4070},
    {"type": "food_supply", "name": "Food-Mohakhali-2",  "capacity": 500, "lat": 23.7781, "lon": 90.4070},
    {"type": "food_supply", "name": "Food-Sylhet",       "capacity": 300, "lat": 24.8900, "lon": 91.8650},
    {"type": "food_supply", "name": "Food-Sirajganj",    "capacity": 400, "lat": 24.4500, "lon": 89.7050},
    {"type": "food_supply", "name": "Food-Sunamganj",    "capacity": 250, "lat": 25.0700, "lon": 91.3900},

    # Water supply depots
    {"type": "water_supply", "name": "Water-Mohakhali-1", "capacity": 1000, "lat": 23.7781, "lon": 90.4070},
    {"type": "water_supply", "name": "Water-Mohakhali-2", "capacity": 1000, "lat": 23.7781, "lon": 90.4070},
    {"type": "water_supply", "name": "Water-Sylhet",      "capacity":  600, "lat": 24.8900, "lon": 91.8650},
    {"type": "water_supply", "name": "Water-Sirajganj",   "capacity":  800, "lat": 24.4500, "lon": 89.7050},
    {"type": "water_supply", "name": "Water-Sunamganj",   "capacity":  500, "lat": 25.0700, "lon": 91.3900},
]


async def seed_inventory_if_empty(pool: asyncpg.Pool):
    """Seed resource inventory with real Bangladesh depot locations."""
    count = await pool.fetchval("SELECT COUNT(*) FROM resource_units")
    if count and count > 0:
        logger.info("Inventory already seeded (%d units) — skipping", count)
        return

    logger.info("Seeding inventory with %d resources…", len(SEED_RESOURCES))
    for r in SEED_RESOURCES:
        await pool.execute(
            """
            INSERT INTO resource_units
                (resource_type, name, status, capacity, current_location, base_location)
            VALUES ($1, $2, 'available', $3,
                    ST_SetSRID(ST_MakePoint($5, $4), 4326),
                    ST_SetSRID(ST_MakePoint($5, $4), 4326))
            """,
            r["type"], r["name"], r["capacity"], r["lat"], r["lon"],
        )
    logger.info("Seed complete — %d resource units in inventory.", len(SEED_RESOURCES))


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, redis_client, handler

    # ── PostgreSQL (REQUIRED for Agent 3) ──
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
        await pool.fetchval("SELECT 1")  # Verify connection
        db_pool = pool
        logger.info("PostgreSQL connected and verified")
    except Exception as e:
        logger.error("PostgreSQL connection FAILED: %s", e)
        logger.error(
            "Agent 3 REQUIRES PostgreSQL with PostGIS. "
            "Run: docker-compose up postgres -d"
        )
        db_pool = None

    # Seed inventory if DB is available
    if db_pool:
        try:
            await seed_inventory_if_empty(db_pool)
        except Exception as e:
            logger.error("Inventory seed failed (run database/004_resource_schema.sql first): %s", e)

    # ── Redis (needed for Agent 2 → Agent 3 pub/sub) ──
    try:
        redis_client = await aioredis.from_url(REDIS_URL, decode_responses=True)
        await redis_client.ping()  # Actually verify connection
        logger.info("Redis connected and verified")
    except Exception as e:
        logger.warning("Redis not available (Agent 3 won't receive live distress_queue): %s", e)
        if redis_client:
            try:
                await redis_client.aclose()
            except Exception:
                pass
        redis_client = None

    # ── Start Redis handler (if both DB and Redis are up) ──
    if db_pool and redis_client:
        handler = Agent3RedisHandler(redis_client, db_pool)
        asyncio.create_task(handler.start_listening())
        asyncio.create_task(handler.publish_heartbeat())
        logger.info("Agent 3 listening on distress_queue channel")
    elif db_pool:
        # DB works but no Redis — manual trigger via /trigger endpoint still works
        handler = Agent3RedisHandler(None, db_pool)
        logger.info("Agent 3 running in HTTP-only mode (no Redis — use /trigger endpoint)")
    else:
        logger.warning("Agent 3 running in DEGRADED mode — no DB, no Redis")

    logger.info("Agent 3 startup complete on port %d", AGENT_PORT)

    yield

    if db_pool:
        await db_pool.close()
    if redis_client:
        await redis_client.aclose()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Agent 3 — Resource Management",
    description="Disaster response resource inventory and allocation.",
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
        "agent": "agent_3_resource",
        "version": "1.0.0",
        "port": AGENT_PORT,
        "subscribes_to": ["distress_queue"],
        "publishes_to":  ["dispatch_order", "inventory_update", "agent_status"],
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
    return {"status": status, "db": "ok" if db_ok else "disconnected", "redis": "ok" if redis_ok else "disconnected"}


@app.get("/inventory")
async def get_inventory():
    """Get full inventory snapshot — used by dashboard."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not connected")
    inv = InventoryManager(db_pool)
    snapshot = await inv.snapshot()
    return snapshot.model_dump(mode="json")


@app.get("/inventory/{resource_type}")
async def get_inventory_by_type(resource_type: ResourceType):
    """Get all units of a specific resource type."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not connected")
    inv = InventoryManager(db_pool)
    units = await inv.get_all(resource_type)
    return {
        "resource_type": resource_type.value,
        "count": len(units),
        "units": [u.model_dump(mode="json") for u in units],
    }


@app.post("/inventory/restock", response_model=RestockResponse)
async def restock(request: RestockRequest):
    """Manually restock resources at a location."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not connected")
    inv = InventoryManager(db_pool)
    units = await inv.add_units(
        resource_type=request.resource_type,
        quantity=request.quantity,
        location=request.location,
        notes=request.notes,
    )

    # Publish inventory update if Redis is available
    if redis_client:
        snapshot = await inv.snapshot()
        from shared.message_protocol import AgentMessage, publish_message
        msg = AgentMessage(
            source_agent="agent_3_resource",
            target_agent="dashboard",
            channel="inventory_update",
            message_type="inventory_update",
            payload=snapshot.model_dump(mode="json"),
            priority=3,
        )
        await publish_message(redis_client, "inventory_update", msg)

    return RestockResponse(
        added=len(units),
        message=f"Added {len(units)} × {request.resource_type.value}",
        units=[u.model_dump(mode="json") for u in units],
    )


@app.get("/allocations")
async def get_allocations(limit: int = 20):
    """Get recent allocation history."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not connected")
    rows = await db_pool.fetch(
        """
        SELECT id, timestamp, incident_id, zone_name, urgency,
               num_people_affected,
               jsonb_array_length(allocated_units) AS resource_count,
               partial_allocation
        FROM resource_allocations
        ORDER BY timestamp DESC
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


@app.get("/allocations/{allocation_id}")
async def get_allocation(allocation_id: str):
    """Get details of a specific allocation."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="Database not connected")
    row = await db_pool.fetchrow(
        "SELECT * FROM resource_allocations WHERE id = $1::uuid",
        allocation_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Allocation not found")
    return dict(row)


@app.post("/trigger")
async def trigger_allocation(distress_item: dict):
    """
    Manually trigger allocation for a single distress item.
    Accepts Agent 2's DistressQueueItem format directly.
    """
    if not handler:
        raise HTTPException(status_code=503, detail="Handler not ready")
    allocation = await handler.allocator.process_distress_item(distress_item)
    if not allocation:
        raise HTTPException(status_code=422, detail="No resources available or invalid data")
    return allocation.model_dump(mode="json")


@app.post("/trigger_batch")
async def trigger_batch_allocation(distress_items: list):
    """
    Manually trigger allocation for a batch of distress items.
    Accepts Agent 2's queue format (list of DistressQueueItem dicts).
    """
    if not handler:
        raise HTTPException(status_code=503, detail="Handler not ready")
    allocations = await handler.allocator.process_distress_batch(distress_items)
    return {
        "processed": len(distress_items),
        "allocated": len(allocations),
        "allocations": [a.model_dump(mode="json") for a in allocations],
    }


@app.get("/status")
async def status():
    if not handler:
        return {"status": "starting"}
    uptime = (datetime.now(timezone.utc) - handler._start_time).total_seconds()
    return {
        "status":           "running",
        "uptime_s":         uptime,
        "last_action":      handler._last_action,
        "total_allocations": handler._allocations_count,
        "db_connected":     db_pool is not None,
        "redis_connected":  redis_client is not None,
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
