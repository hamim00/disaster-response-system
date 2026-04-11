"""
Pydantic models for Agent 4 — Dispatch Optimization.
Consumes Agent 3's ResourceAllocation (via dispatch_order channel)
and produces optimized dispatch routes.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class TransportMode(str, Enum):
    ROAD      = "road"
    WATERWAY  = "waterway"


class DispatchStatus(str, Enum):
    ACTIVE     = "active"
    COMPLETED  = "completed"
    CANCELLED  = "cancelled"


class TeamStatus(str, Enum):
    DISPATCHED = "dispatched"
    EN_ROUTE   = "en_route"
    ARRIVED    = "arrived"
    RETURNING  = "returning"


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------

class GeoPoint(BaseModel):
    latitude:  float = Field(..., ge=-90,  le=90)
    longitude: float = Field(..., ge=-180, le=180)


class TeamRoute(BaseModel):
    """Route for a single resource unit dispatched to an incident."""
    id:             UUID          = Field(default_factory=uuid4)
    dispatch_id:    UUID
    unit_id:        UUID
    unit_name:      str
    resource_type:  str
    transport_mode: TransportMode
    origin:         GeoPoint
    destination:    GeoPoint
    route_geometry: Optional[dict] = None   # GeoJSON LineString
    distance_km:    float          = 0.0
    eta_minutes:    float          = 0.0
    status:         TeamStatus     = TeamStatus.DISPATCHED
    departed_at:    datetime       = Field(default_factory=lambda: datetime.now(timezone.utc))
    arrived_at:     Optional[datetime] = None
    created_at:     datetime       = Field(default_factory=lambda: datetime.now(timezone.utc))


class DispatchPlan(BaseModel):
    """Complete dispatch plan for one incident (one allocation → one plan)."""
    id:                 UUID     = Field(default_factory=uuid4)
    timestamp:          datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    allocation_id:      UUID
    incident_id:        str
    zone_id:            str
    zone_name:          str
    destination:        GeoPoint
    priority:           int      = Field(3, ge=1, le=5)
    total_eta_minutes:  float    = 0.0
    route_safety_score: float    = Field(1.0, ge=0.0, le=1.0)
    status:             DispatchStatus = DispatchStatus.ACTIVE
    team_routes:        List[TeamRoute] = Field(default_factory=list)
    completed_at:       Optional[datetime] = None


# ---------------------------------------------------------------------------
# API models
# ---------------------------------------------------------------------------

class DispatchSummary(BaseModel):
    """Lightweight summary for dashboard."""
    dispatch_id:        UUID
    zone_name:          str
    priority:           int
    team_count:         int
    total_eta_minutes:  float
    route_safety_score: float
    status:             str
    timestamp:          datetime