"""
Inventory Manager — CRUD operations for resource_units table.
All write operations also log to inventory_transactions.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID

from .models import (
    GeoPoint,
    InventorySnapshot,
    ResourceStatus,
    ResourceType,
    ResourceUnit,
)

logger = logging.getLogger(__name__)


class InventoryManager:
    """Wraps all DB reads/writes for the resource inventory."""

    def __init__(self, db_pool):
        self.pool = db_pool

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get_available(
        self,
        resource_type: ResourceType,
    ) -> List[ResourceUnit]:
        """Return all AVAILABLE units of a given type, ordered by id."""
        rows = await self.pool.fetch(
            """
            SELECT id, resource_type, name, status, capacity,
                   ST_Y(current_location::geometry) AS cur_lat,
                   ST_X(current_location::geometry) AS cur_lon,
                   ST_Y(base_location::geometry)    AS base_lat,
                   ST_X(base_location::geometry)    AS base_lon,
                   assigned_zone_id, assigned_incident_id, deployed_at
            FROM resource_units
            WHERE resource_type = $1 AND status = 'available'
            ORDER BY id
            """,
            resource_type.value,
        )
        return [self._row_to_unit(r) for r in rows]

    async def get_all(
        self,
        resource_type: Optional[ResourceType] = None,
    ) -> List[ResourceUnit]:
        if resource_type:
            rows = await self.pool.fetch(
                """
                SELECT id, resource_type, name, status, capacity,
                       ST_Y(current_location::geometry) AS cur_lat,
                       ST_X(current_location::geometry) AS cur_lon,
                       ST_Y(base_location::geometry)    AS base_lat,
                       ST_X(base_location::geometry)    AS base_lon,
                       assigned_zone_id, assigned_incident_id, deployed_at
                FROM resource_units WHERE resource_type = $1
                ORDER BY name
                """,
                resource_type.value,
            )
        else:
            rows = await self.pool.fetch(
                """
                SELECT id, resource_type, name, status, capacity,
                       ST_Y(current_location::geometry) AS cur_lat,
                       ST_X(current_location::geometry) AS cur_lon,
                       ST_Y(base_location::geometry)    AS base_lat,
                       ST_X(base_location::geometry)    AS base_lon,
                       assigned_zone_id, assigned_incident_id, deployed_at
                FROM resource_units ORDER BY resource_type, name
                """
            )
        return [self._row_to_unit(r) for r in rows]

    async def snapshot(self) -> InventorySnapshot:
        """Build an InventorySnapshot from the inventory_summary view."""
        rows = await self.pool.fetch(
            "SELECT resource_type, total, available, deployed, \"returning\", maintenance "
            "FROM inventory_summary"
        )
        resources: Dict[str, Dict[str, int]] = {}
        for r in rows:
            resources[r["resource_type"]] = {
                "total":       r["total"],
                "available":   r["available"],
                "deployed":    r["deployed"],
                "returning":   r["returning"],
                "maintenance": r["maintenance"],
            }
        return InventorySnapshot(
            timestamp=datetime.now(timezone.utc),
            resources=resources,
        )

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def deploy(
        self,
        unit: ResourceUnit,
        incident_id: str,
        zone_id: str,
        triggered_by: str = "agent_3_auto",
    ) -> None:
        """Mark a unit as DEPLOYED and log the transaction."""
        now = datetime.now(timezone.utc)
        await self.pool.execute(
            """
            UPDATE resource_units
            SET status = 'deployed',
                assigned_zone_id     = $2,
                assigned_incident_id = $3,
                deployed_at          = $4,
                updated_at           = $4
            WHERE id = $1
            """,
            unit.id, zone_id, incident_id, now,
        )
        await self._log_transaction(
            resource_type=unit.resource_type,
            unit_id=unit.id,
            direction="allocated",
            triggered_by=triggered_by,
            incident_id=incident_id,
            zone_id=zone_id,
        )
        logger.info("Deployed %s -> incident %s", unit.name, incident_id)

    async def add_units(
        self,
        resource_type: ResourceType,
        quantity: int,
        location: GeoPoint,
        notes: Optional[str] = None,
    ) -> List[ResourceUnit]:
        """Create N new units of a given type (manual restock)."""
        units = []
        existing_count = await self.pool.fetchval(
            "SELECT COUNT(*) FROM resource_units WHERE resource_type = $1",
            resource_type.value,
        )
        for i in range(quantity):
            seq = int(existing_count) + i + 1
            name = f"{resource_type.value.replace('_', '-').title()}-{seq:03d}"
            unit_id = await self.pool.fetchval(
                """
                INSERT INTO resource_units
                    (resource_type, name, status, capacity,
                     current_location, base_location)
                VALUES ($1, $2, 'available', 10,
                        ST_SetSRID(ST_MakePoint($4, $3), 4326),
                        ST_SetSRID(ST_MakePoint($4, $3), 4326))
                RETURNING id
                """,
                resource_type.value,
                name,
                location.latitude,
                location.longitude,
            )
            await self._log_transaction(
                resource_type=resource_type,
                unit_id=unit_id,
                direction="restocked",
                triggered_by="manual_restock",
                notes=notes,
            )
            units.append(
                ResourceUnit(
                    id=unit_id,
                    resource_type=resource_type,
                    name=name,
                    capacity=10,
                    current_location=location,
                    base_location=location,
                )
            )
        return units

    async def mark_returning(self, unit_id: UUID) -> None:
        await self.pool.execute(
            "UPDATE resource_units SET status = 'returning', updated_at = NOW() WHERE id = $1",
            unit_id,
        )
        await self._log_transaction(
            resource_type=ResourceType.RESCUE_BOAT,  # placeholder; real type fetched if needed
            unit_id=unit_id,
            direction="returned",
            triggered_by="agent_4_return",
        )

    # ------------------------------------------------------------------
    # Allocation log
    # ------------------------------------------------------------------

    async def log_allocation(self, allocation) -> None:
        """Persist a ResourceAllocation to resource_allocations table."""
        import json
        await self.pool.execute(
            """
            INSERT INTO resource_allocations
                (id, timestamp, incident_id, zone_id, zone_name,
                 destination, priority, urgency, num_people_affected,
                 allocated_units, partial_allocation, requires_medical)
            VALUES ($1, $2, $3, $4, $5,
                    ST_SetSRID(ST_MakePoint($7, $6), 4326),
                    $8, $9, $10, $11, $12, $13)
            """,
            allocation.allocation_id,
            allocation.timestamp,
            allocation.incident_id,
            allocation.zone_id,
            allocation.zone_name,
            allocation.destination.latitude,
            allocation.destination.longitude,
            allocation.priority,
            allocation.urgency,
            allocation.num_people_affected,
            json.dumps(allocation.allocated_resources),
            allocation.partial_allocation,
            allocation.requires_medical,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _log_transaction(
        self,
        resource_type: ResourceType,
        unit_id,
        direction: str,
        triggered_by: str = "agent_3_auto",
        incident_id: Optional[str] = None,
        zone_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        await self.pool.execute(
            """
            INSERT INTO inventory_transactions
                (resource_type, unit_id, direction, triggered_by,
                 incident_id, zone_id, notes)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            resource_type.value if hasattr(resource_type, "value") else str(resource_type),
            unit_id,
            direction,
            triggered_by,
            incident_id,
            zone_id,
            notes,
        )

    @staticmethod
    def _row_to_unit(row) -> ResourceUnit:
        return ResourceUnit(
            id=row["id"],
            resource_type=ResourceType(row["resource_type"]),
            name=row["name"],
            status=ResourceStatus(row["status"]),
            capacity=row["capacity"],
            current_location=GeoPoint(
                latitude=row["cur_lat"], longitude=row["cur_lon"]
            ),
            base_location=GeoPoint(
                latitude=row["base_lat"], longitude=row["base_lon"]
            ),
            assigned_zone=row.get("assigned_zone_id"),
            assigned_incident_id=row.get("assigned_incident_id"),
            deployed_at=row.get("deployed_at"),
        )