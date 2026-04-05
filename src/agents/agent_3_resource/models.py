"""
Pydantic models for Agent 3 — Resource Management.
Updated to be compatible with Agent 2's DistressQueueItem format.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ResourceType(str, Enum):
    RESCUE_BOAT  = "rescue_boat"
    MEDICAL_TEAM = "medical_team"
    MEDICAL_KIT  = "medical_kit"
    FOOD_SUPPLY  = "food_supply"
    WATER_SUPPLY = "water_supply"


class ResourceStatus(str, Enum):
    AVAILABLE   = "available"
    DEPLOYED    = "deployed"
    RETURNING   = "returning"
    MAINTENANCE = "maintenance"


class AllocationUrgency(str, Enum):
    """
    Internal urgency levels for allocation rules.
    Agent 2 sends: critical / high / medium / low
    We map them to these allocation tiers.
    """
    LIFE_THREATENING = "LIFE_THREATENING"   # ← Agent 2 "critical"
    URGENT           = "URGENT"             # ← Agent 2 "high"
    MODERATE         = "MODERATE"           # ← Agent 2 "medium" or "low"


def map_agent2_urgency(agent2_urgency: str) -> str:
    """
    Map Agent 2's urgency levels to Agent 3's allocation tiers.

    Agent 2 sends: critical, high, medium, low
    Agent 3 needs: LIFE_THREATENING, URGENT, MODERATE
    """
    mapping = {
        "critical": AllocationUrgency.LIFE_THREATENING,
        "high":     AllocationUrgency.URGENT,
        "medium":   AllocationUrgency.MODERATE,
        "low":      AllocationUrgency.MODERATE,
    }
    return mapping.get(agent2_urgency.lower(), AllocationUrgency.MODERATE).value


# ---------------------------------------------------------------------------
# Core domain models
# ---------------------------------------------------------------------------

class GeoPoint(BaseModel):
    latitude:  float = Field(..., ge=-90,  le=90)
    longitude: float = Field(..., ge=-180, le=180)


class ResourceUnit(BaseModel):
    """A single physical resource unit (one boat, one team, …)."""
    id:                    UUID          = Field(default_factory=uuid4)
    resource_type:         ResourceType
    name:                  str
    status:                ResourceStatus = ResourceStatus.AVAILABLE
    capacity:              int            = Field(..., gt=0)
    current_location:      GeoPoint
    base_location:         GeoPoint
    assigned_zone:         Optional[str]  = None
    assigned_incident_id:  Optional[str]  = None
    deployed_at:           Optional[datetime] = None


class InventorySnapshot(BaseModel):
    """Point-in-time inventory counts — sent to dashboard."""
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    resources: Dict[str, Dict[str, int]]


class ResourceAllocation(BaseModel):
    """What Agent 3 sends to Agent 4 via the dispatch_order channel."""
    allocation_id:       UUID     = Field(default_factory=uuid4)
    timestamp:           datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    incident_id:         str
    zone_id:             str
    zone_name:           str
    destination:         GeoPoint
    priority:            int = Field(..., ge=1, le=5)
    urgency:             str
    num_people_affected: int
    water_level_meters:  Optional[float] = None
    flood_verified:      bool = False
    allocated_resources: List[dict]
    partial_allocation:  bool = False
    requires_medical:    bool = False
    distress_type:       str = ""
    distress_channel:    str = ""
    notes:               str = ""


# ---------------------------------------------------------------------------
# API request/response models
# ---------------------------------------------------------------------------

class RestockRequest(BaseModel):
    resource_type: ResourceType
    quantity:      int = Field(..., gt=0)
    location:      GeoPoint
    notes:         Optional[str] = None


class RestockResponse(BaseModel):
    added:   int
    message: str
    units:   List[dict]
