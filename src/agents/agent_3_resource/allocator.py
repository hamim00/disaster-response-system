"""
Resource Allocation Algorithm — the brain of Agent 3.
Adapted to consume Agent 2's DistressQueueItem format directly.

Allocation rules:
  LIFE_THREATENING : 2 boats + 1 medical_team + 2 medical_kits
  URGENT (medical) : 1 boat + 1 medical_team + 1 medical_kit
  URGENT (supply)  : 1 boat + 1 food_supply + 1 water_supply
  MODERATE         : 1 food_supply + 1 water_supply

Resources are scored by Haversine distance — closest available unit wins.
If a resource type is exhausted, partial_allocation=True and the allocation
still proceeds with whatever is available.

Author: Disaster Response Team
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from shared.geo_utils import haversine_km

from .inventory_manager import InventoryManager
from .models import (
    AllocationUrgency,
    GeoPoint,
    ResourceAllocation,
    ResourceType,
    ResourceUnit,
    map_agent2_urgency,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Allocation rules table
# ---------------------------------------------------------------------------

AllocationRule = Dict[ResourceType, int]

RULES: Dict[str, AllocationRule] = {
    "LIFE_THREATENING": {
        ResourceType.RESCUE_BOAT:  2,
        ResourceType.MEDICAL_TEAM: 1,
        ResourceType.MEDICAL_KIT:  2,
    },
    "URGENT_MEDICAL": {
        ResourceType.RESCUE_BOAT:  1,
        ResourceType.MEDICAL_TEAM: 1,
        ResourceType.MEDICAL_KIT:  1,
    },
    "URGENT_SUPPLY": {
        ResourceType.RESCUE_BOAT:  1,
        ResourceType.FOOD_SUPPLY:  1,
        ResourceType.WATER_SUPPLY: 1,
    },
    "MODERATE": {
        ResourceType.FOOD_SUPPLY:  1,
        ResourceType.WATER_SUPPLY: 1,
    },
}

# Distress types that imply medical need
MEDICAL_DISTRESS_TYPES = {
    "medical_emergency",
    "stranded",
    "structural_collapse",
}


def _pick_rule(urgency: str, medical_need: bool) -> AllocationRule:
    if urgency == AllocationUrgency.LIFE_THREATENING:
        return RULES["LIFE_THREATENING"]
    if urgency == AllocationUrgency.URGENT:
        return RULES["URGENT_MEDICAL"] if medical_need else RULES["URGENT_SUPPLY"]
    return RULES["MODERATE"]


def _closest(
    units: List[ResourceUnit],
    destination: GeoPoint,
    count: int,
    max_distance_km: float = 50.0,
) -> Tuple[List[ResourceUnit], bool]:
    """Pick up to `count` nearest available units by Haversine distance.
    Units beyond max_distance_km are excluded to prevent cross-region allocation."""
    scored = sorted(
        units,
        key=lambda u: haversine_km(
            u.current_location.latitude,
            u.current_location.longitude,
            destination.latitude,
            destination.longitude,
        ),
    )
    # Filter out units beyond max distance
    nearby = [
        u for u in scored
        if haversine_km(
            u.current_location.latitude, u.current_location.longitude,
            destination.latitude, destination.longitude,
        ) <= max_distance_km
    ]
    selected = nearby[:count]
    partial = len(selected) < count
    if partial:
        logger.warning(
            "Resource shortfall: needed %d but only %d within %.0f km",
            count, len(selected), max_distance_km,
        )
    return selected, partial


def _normalize_distress_item(raw_payload: dict) -> dict:
    """
    Convert Agent 2's DistressQueueItem payload into the internal
    incident format that the allocator understands.

    Agent 2 sends:
        distress_id, channel, location{latitude,longitude,zone_name,zone_id,...},
        zone_name, distress_type, urgency (critical/high/medium/low),
        people_count, needs_rescue, water_level_meters, priority_score (0-1),
        flood_verified, agent1_risk_score, recommended_resources, summary

    Allocator needs:
        incident_id, zone_id, zone_name, location{latitude,longitude},
        urgency (LIFE_THREATENING/URGENT/MODERATE), num_people,
        medical_need, priority (1-5)
    """
    # Extract location — Agent 2 nests it inside a DistressLocation object
    loc = raw_payload.get("location", {})
    lat = loc.get("latitude")
    lon = loc.get("longitude")

    # If location is missing, try zone-level fallback
    if lat is None or lon is None:
        logger.warning("Distress item missing coordinates, skipping")
        return {}

    # Map urgency: critical→LIFE_THREATENING, high→URGENT, medium/low→MODERATE
    raw_urgency = raw_payload.get("urgency", "medium")
    mapped_urgency = map_agent2_urgency(raw_urgency)

    # Determine medical need from distress_type and needs_rescue
    distress_type = raw_payload.get("distress_type", "")
    needs_rescue = raw_payload.get("needs_rescue", False)
    medical_need = needs_rescue or distress_type in MEDICAL_DISTRESS_TYPES

    # Map priority_score (0-1 float) → priority (1-5 int)
    priority_score = raw_payload.get("priority_score", 0.5)
    priority_int = max(1, min(5, int(priority_score * 5) + 1))

    return {
        "incident_id":      str(raw_payload.get("distress_id", raw_payload.get("id", "unknown"))),
        "zone_id":          raw_payload.get("zone_name", loc.get("zone_id", "unknown")),
        "zone_name":        raw_payload.get("zone_name", loc.get("zone_name", "Unknown")),
        "location":         {"latitude": lat, "longitude": lon},
        "urgency":          mapped_urgency,
        "num_people":       raw_payload.get("people_count") or 0,
        "medical_need":     medical_need,
        "priority":         priority_int,
        "water_level_meters": raw_payload.get("water_level_meters"),
        "flood_verified":   raw_payload.get("flood_verified", False),
        "distress_type":    distress_type,
        "distress_channel": raw_payload.get("channel", ""),
    }


class ResourceAllocator:
    """Stateless allocator — state lives in DB via InventoryManager."""

    def __init__(self, inventory: InventoryManager):
        self.inventory = inventory
        self._allocated_incidents: set = set()  # dedup by incident_id
        self._zone_allocations: dict = {}       # dedup by zone+urgency: {zone: highest_urgency}

    async def allocate(self, incident: dict) -> Optional[ResourceAllocation]:
        """
        Allocate resources for a single incident.

        Args:
            incident: Normalized incident dict (output of _normalize_distress_item)
        """
        if not incident or not incident.get("location"):
            return None

        # Deduplication: skip if already allocated for this incident
        inc_id = incident.get("incident_id", "")
        if inc_id in self._allocated_incidents:
            logger.info("Skipping duplicate allocation for incident %s", inc_id)
            return None
        self._allocated_incidents.add(inc_id)
        if len(self._allocated_incidents) > 500:
            self._allocated_incidents = set(list(self._allocated_incidents)[-200:])

        # Zone-level dedup: skip if this zone already has an equal-or-higher
        # urgency allocation (prevents 3× LIFE_THREATENING for Mirpur)
        zone_id = incident.get("zone_id", incident.get("zone_name", ""))
        urgency = incident.get("urgency", AllocationUrgency.MODERATE)
        urgency_rank = {"LIFE_THREATENING": 3, "URGENT": 2, "MODERATE": 1}
        new_rank = urgency_rank.get(urgency, 1)
        existing_rank = self._zone_allocations.get(zone_id, 0)

        if existing_rank >= new_rank:
            logger.info(
                "Skipping %s allocation for zone %s — already has %s-level allocation",
                urgency, zone_id, existing_rank,
            )
            return None
        self._zone_allocations[zone_id] = new_rank

        urgency      = incident.get("urgency", AllocationUrgency.MODERATE)
        medical_need = incident.get("medical_need", False)
        destination  = GeoPoint(**incident["location"])
        rule         = _pick_rule(urgency, medical_need)

        allocated_units: List[dict] = []
        partial = False

        for rtype, needed_count in rule.items():
            available = await self.inventory.get_available(rtype)
            selected, is_partial = _closest(available, destination, needed_count)
            if is_partial:
                partial = True
                logger.warning(
                    "Partial allocation for %s — needed %d %s, got %d",
                    incident.get("incident_id"), needed_count, rtype.value, len(selected),
                )

            for unit in selected:
                await self.inventory.deploy(
                    unit=unit,
                    incident_id=incident["incident_id"],
                    zone_id=incident["zone_id"],
                )
                allocated_units.append({
                    "unit_id":          str(unit.id),
                    "resource_type":    unit.resource_type.value,
                    "unit_name":        unit.name,
                    "current_location": {
                        "latitude":  unit.current_location.latitude,
                        "longitude": unit.current_location.longitude,
                    },
                    "distance_km": round(haversine_km(
                        unit.current_location.latitude,
                        unit.current_location.longitude,
                        destination.latitude,
                        destination.longitude,
                    ), 2),
                })

        if not allocated_units:
            logger.error(
                "Zero resources available for incident %s — skipping",
                incident.get("incident_id"),
            )
            return None

        allocation = ResourceAllocation(
            incident_id=incident["incident_id"],
            zone_id=incident["zone_id"],
            zone_name=incident.get("zone_name", "Unknown"),
            destination=destination,
            priority=incident.get("priority", 3),
            urgency=urgency,
            num_people_affected=incident.get("num_people", 0),
            water_level_meters=incident.get("water_level_meters"),
            flood_verified=incident.get("flood_verified", False),
            allocated_resources=allocated_units,
            partial_allocation=partial,
            requires_medical=medical_need or urgency == AllocationUrgency.LIFE_THREATENING,
            distress_type=incident.get("distress_type", ""),
            distress_channel=incident.get("distress_channel", ""),
            notes=(
                "Partial allocation — some resource types exhausted."
                if partial else "Full allocation."
            ),
        )

        await self.inventory.log_allocation(allocation)
        return allocation

    async def process_distress_item(self, raw_payload: dict) -> Optional[ResourceAllocation]:
        """
        Process a single Agent 2 DistressQueueItem payload.
        Normalizes the format, then allocates resources.
        """
        incident = _normalize_distress_item(raw_payload)
        if not incident:
            return None
        return await self.allocate(incident)

    async def process_distress_batch(
        self, items: List[dict],
    ) -> List[ResourceAllocation]:
        """
        Process a batch of distress items, sorted by priority (highest first).
        """
        sorted_items = sorted(
            items,
            key=lambda x: x.get("priority_score", 0),
            reverse=True,
        )
        results = []
        for item in sorted_items:
            allocation = await self.process_distress_item(item)
            if allocation:
                results.append(allocation)
        return results