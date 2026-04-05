"""
Redis handler for Agent 3 — Resource Management.
Subscribes to:  distress_queue  (from Agent 2 — individual DistressQueueItem messages)
Publishes to:   dispatch_order  (to Agent 4)
                inventory_update (to Dashboard)
                agent_status    (heartbeat)

Agent 2 publishes ONE message per distress item (not a batch).
Each message's payload is a DistressQueueItem dict with fields:
    distress_id, channel, location, zone_name, distress_type,
    urgency (critical/high/medium/low), people_count, needs_rescue,
    water_level_meters, priority_score, flood_verified,
    recommended_resources, summary
"""
import asyncio
import logging
from datetime import datetime, timezone

from shared.message_protocol import (
    AgentMessage,
    HeartbeatMessage,
    listen_for_messages,
    log_message_to_db,
    publish_message,
)

from .allocator import ResourceAllocator
from .inventory_manager import InventoryManager

logger = logging.getLogger(__name__)

AGENT_ID = "agent_3_resource"


class Agent3RedisHandler:
    def __init__(self, redis_client, db_pool):
        self.redis   = redis_client
        self.db      = db_pool
        self.inventory = InventoryManager(db_pool) if db_pool else None
        self.allocator = ResourceAllocator(self.inventory) if self.inventory else None
        self._start_time = datetime.now(timezone.utc)
        self._last_action: str = "initialized"
        self._allocations_count: int = 0

    # ------------------------------------------------------------------
    # Subscriber
    # ------------------------------------------------------------------

    async def start_listening(self):
        """Start the distress_queue subscriber (run as asyncio task)."""
        if not self.redis:
            logger.warning("Redis not available — skipping subscription")
            return
        await listen_for_messages(
            self.redis, "distress_queue", self._handle_distress_message,
        )

    async def _handle_distress_message(self, envelope: AgentMessage):
        """
        Handle a single distress message from Agent 2.

        Agent 2 publishes each DistressQueueItem as an individual message.
        The payload IS the distress item — not wrapped in an 'incidents' list.
        """
        if not self.allocator:
            logger.error("Allocator not ready (no DB connection)")
            return

        zone = envelope.payload.get("zone_name", "unknown")
        urgency = envelope.payload.get("urgency", "medium")
        channel = envelope.payload.get("channel", "unknown")
        rescue = envelope.payload.get("needs_rescue", False)

        logger.info(
            "Received distress from %s | zone=%s | urgency=%s | channel=%s | rescue=%s",
            envelope.source_agent, zone, urgency, channel, rescue,
        )
        self._last_action = f"received distress zone={zone} urgency={urgency}"

        # Process the single distress item
        allocation = await self.allocator.process_distress_item(envelope.payload)

        if allocation:
            self._allocations_count += 1
            await self._publish_dispatch_order(allocation)
            await self._publish_inventory_update()

            logger.info(
                "Allocated %d resources for %s (%s) → dispatching to Agent 4",
                len(allocation.allocated_resources),
                zone,
                allocation.urgency,
            )
        else:
            logger.warning("No allocation possible for zone=%s", zone)

    # ------------------------------------------------------------------
    # Publishers
    # ------------------------------------------------------------------

    async def _publish_dispatch_order(self, allocation):
        """Publish a dispatch_order to Agent 4."""
        message = AgentMessage(
            source_agent=AGENT_ID,
            target_agent="agent_4_dispatch",
            channel="dispatch_order",
            message_type="dispatch_order",
            payload=allocation.model_dump(mode="json"),
            priority=allocation.priority,
        )
        if self.redis:
            await publish_message(self.redis, "dispatch_order", message)
        if self.db:
            await log_message_to_db(self.db, message)
        self._last_action = f"dispatched {len(allocation.allocated_resources)} resources → {allocation.zone_name}"

    async def _publish_inventory_update(self):
        """Publish current inventory snapshot to dashboard."""
        if not self.redis or not self.inventory:
            return
        snapshot = await self.inventory.snapshot()
        message = AgentMessage(
            source_agent=AGENT_ID,
            target_agent="dashboard",
            channel="inventory_update",
            message_type="inventory_update",
            payload=snapshot.model_dump(mode="json"),
        )
        await publish_message(self.redis, "inventory_update", message)

    async def publish_heartbeat(self):
        """Publish a heartbeat on agent_status every 30 seconds."""
        if not self.redis:
            return
        while True:
            uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds()
            hb = HeartbeatMessage(
                agent_id=AGENT_ID,
                uptime_seconds=uptime,
                last_action=self._last_action,
                metrics={"total_allocations": self._allocations_count},
            )
            msg = AgentMessage(
                source_agent=AGENT_ID,
                target_agent="dashboard",
                channel="agent_status",
                message_type="heartbeat",
                payload=hb.model_dump(mode="json"),
            )
            await publish_message(self.redis, "agent_status", msg)
            await asyncio.sleep(30)
