"""
Dispatch Optimization Engine for Agent 4.

Receives ResourceAllocation from Agent 3 and produces an optimized
DispatchPlan with:
  * Per-unit routes (straight-line for boats, road-factor for vehicles)
  * ETA estimation (speed model by transport mode + flood penalty)
  * Route safety scoring (flood depth, distance, time-of-day factors)
"""
import logging
import math
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from shared.geo_utils import haversine_km, straight_line_geojson, geojson_to_wkt_point
from .models import (
    DispatchPlan, DispatchStatus, GeoPoint,
    TeamRoute, TeamStatus, TransportMode,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Speed / safety configuration (km/h)
# ---------------------------------------------------------------------------

SPEED_KMH = {
    TransportMode.WATERWAY: 12.0,   # rescue boats in flood water
    TransportMode.ROAD:     25.0,   # vehicles on partially-flooded roads
}

# Resource types that travel by waterway
WATERWAY_TYPES = {"rescue_boat"}

# Flood-depth penalty: every metre of flood depth reduces road speed by 30 %
FLOOD_DEPTH_ROAD_PENALTY = 0.30

# Minimum safety score (even critical situations get a non-zero score)
MIN_SAFETY = 0.15


class DispatchOptimizer:
    """Produce dispatch plans from Agent 3 allocations."""

    def __init__(self, db_pool=None):
        self.db = db_pool
        self._dispatch_count = 0

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def create_dispatch_plan(self, allocation: dict) -> Optional[DispatchPlan]:
        """
        Turn a single Agent 3 ResourceAllocation dict into a DispatchPlan.

        Expected keys in *allocation*:
            allocation_id, incident_id, zone_id, zone_name,
            destination {latitude, longitude},
            priority, urgency, water_level_meters, flood_verified,
            allocated_resources: [{unit_id, unit_name, resource_type,
                                   current_location {latitude, longitude}, ...}]
        """
        try:
            dest_raw = allocation.get("destination", {})
            dest = GeoPoint(
                latitude=dest_raw.get("latitude", 0),
                longitude=dest_raw.get("longitude", 0),
            )

            resources = allocation.get("allocated_resources", [])
            if not resources:
                logger.warning("Allocation has no resources — skipping")
                return None

            water_m = allocation.get("water_level_meters") or 0.0
            flood_verified = allocation.get("flood_verified", False)
            priority = allocation.get("priority", 3)
            alloc_id = allocation.get("allocation_id", str(uuid4()))

            team_routes: List[TeamRoute] = []
            max_eta = 0.0

            for unit in resources:
                loc_raw = unit.get("current_location", unit.get("base_location", {}))
                origin = GeoPoint(
                    latitude=loc_raw.get("latitude", 0),
                    longitude=loc_raw.get("longitude", 0),
                )

                rtype = unit.get("resource_type", "")
                mode = TransportMode.WATERWAY if rtype in WATERWAY_TYPES else TransportMode.ROAD

                dist = haversine_km(origin.latitude, origin.longitude,
                                    dest.latitude, dest.longitude)

                # Road distance factor (roads aren't straight)
                if mode == TransportMode.ROAD:
                    dist *= 1.4   # Manhattan-ish factor for Dhaka grid

                eta = self._calc_eta(dist, mode, water_m)
                safety = self._calc_safety(dist, water_m, flood_verified, mode)
                geojson = straight_line_geojson(
                    origin.latitude, origin.longitude,
                    dest.latitude, dest.longitude,
                )

                route = TeamRoute(
                    dispatch_id=UUID(alloc_id) if isinstance(alloc_id, str) else alloc_id,
                    unit_id=UUID(unit.get("unit_id", str(uuid4()))) if isinstance(unit.get("unit_id"), str) else unit.get("unit_id", uuid4()),
                    unit_name=unit.get("unit_name", unit.get("name", "unknown")),
                    resource_type=rtype,
                    transport_mode=mode,
                    origin=origin,
                    destination=dest,
                    route_geometry=geojson,
                    distance_km=round(dist, 2),
                    eta_minutes=round(eta, 1),
                    status=TeamStatus.DISPATCHED,
                )
                team_routes.append(route)
                if eta > max_eta:
                    max_eta = eta

            # Overall safety = weighted average
            avg_safety = (
                sum(self._calc_safety(
                    r.distance_km, water_m, flood_verified, r.transport_mode
                ) for r in team_routes) / len(team_routes)
            ) if team_routes else 1.0

            plan = DispatchPlan(
                allocation_id=UUID(alloc_id) if isinstance(alloc_id, str) else alloc_id,
                incident_id=allocation.get("incident_id", ""),
                zone_id=allocation.get("zone_id", ""),
                zone_name=allocation.get("zone_name", "unknown"),
                destination=dest,
                priority=priority,
                total_eta_minutes=round(max_eta, 1),
                route_safety_score=round(avg_safety, 2),
                team_routes=team_routes,
            )

            self._dispatch_count += 1

            # Persist if DB available
            if self.db:
                await self._persist_plan(plan)

            logger.info(
                "Dispatch plan created: zone=%s teams=%d eta=%.1f min safety=%.2f",
                plan.zone_name, len(team_routes), max_eta, avg_safety,
            )
            return plan

        except Exception as exc:
            logger.error("Failed to create dispatch plan: %s", exc, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _calc_eta(self, distance_km: float, mode: TransportMode,
                  water_depth_m: float) -> float:
        """ETA in minutes."""
        speed = SPEED_KMH.get(mode, 20.0)

        if mode == TransportMode.ROAD and water_depth_m > 0:
            penalty = min(water_depth_m * FLOOD_DEPTH_ROAD_PENALTY, 0.8)
            speed *= (1 - penalty)
            speed = max(speed, 5.0)     # minimum 5 km/h even in deep flood

        if speed <= 0:
            return 999.0

        return (distance_km / speed) * 60.0

    def _calc_safety(self, distance_km: float, water_depth_m: float,
                     flood_verified: bool, mode: TransportMode) -> float:
        """Safety score 0..1 (1 = safest)."""
        score = 1.0

        # Distance penalty — longer routes are riskier
        if distance_km > 10:
            score -= 0.15
        elif distance_km > 5:
            score -= 0.08

        # Flood depth penalty
        if water_depth_m > 2.0:
            score -= 0.35
        elif water_depth_m > 1.0:
            score -= 0.20
        elif water_depth_m > 0.5:
            score -= 0.10

        # Unverified flood = uncertain = less safe
        if not flood_verified:
            score -= 0.10

        # Boats are safer in flood than road vehicles
        if mode == TransportMode.ROAD and water_depth_m > 0.5:
            score -= 0.15

        return max(score, MIN_SAFETY)

    async def _persist_plan(self, plan: DispatchPlan):
        """Write dispatch plan + team routes to PostgreSQL."""
        try:
            dest_wkt = geojson_to_wkt_point(
                plan.destination.latitude, plan.destination.longitude
            )
            await self.db.execute(
                """
                INSERT INTO dispatch_routes
                    (id, allocation_id, incident_id, zone_id, zone_name,
                     destination, priority, total_eta_minutes,
                     route_safety_score, status)
                VALUES ($1, $2, $3, $4, $5,
                        ST_GeogFromText($6), $7, $8, $9, $10)
                """,
                plan.id, plan.allocation_id, plan.incident_id,
                plan.zone_id, plan.zone_name,
                dest_wkt, plan.priority, plan.total_eta_minutes,
                plan.route_safety_score, plan.status.value,
            )

            for tr in plan.team_routes:
                orig_wkt = geojson_to_wkt_point(
                    tr.origin.latitude, tr.origin.longitude
                )
                dest_wkt2 = geojson_to_wkt_point(
                    tr.destination.latitude, tr.destination.longitude
                )
                import json
                await self.db.execute(
                    """
                    INSERT INTO team_routes
                        (id, dispatch_id, unit_id, unit_name, resource_type,
                         transport_mode, origin, destination,
                         route_geometry, distance_km, eta_minutes, status)
                    VALUES ($1, $2, $3, $4, $5,
                            $6, ST_GeogFromText($7), ST_GeogFromText($8),
                            $9, $10, $11, $12)
                    """,
                    tr.id, plan.id, tr.unit_id, tr.unit_name,
                    tr.resource_type, tr.transport_mode.value,
                    orig_wkt, dest_wkt2,
                    json.dumps(tr.route_geometry) if tr.route_geometry else None,
                    tr.distance_km, tr.eta_minutes, tr.status.value,
                )

        except Exception as exc:
            logger.error("DB persist failed: %s", exc)