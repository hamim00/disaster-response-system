"""
Redis handler for Agent 4 — Dispatch Optimization.
Subscribes to:  dispatch_order   (from Agent 3)
Publishes to:   dispatch_status  (to Dashboard)
                agent_status     (heartbeat)
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
from .dispatcher import DispatchOptimizer

logger = logging.getLogger(__name__)

AGENT_ID = "agent_4_dispatch"


class Agent4RedisHandler:
    def __init__(self, redis_client, db_pool):
        self.redis     = redis_client
        self.db        = db_pool
        self.optimizer = DispatchOptimizer(db_pool)
        self._start_time = datetime.now(timezone.utc)
        self._last_action: str = "initialized"
        self._dispatch_count: int = 0
        self._plans: list = []  # keep last N plans in memory for API

    # ------------------------------------------------------------------
    # Subscriber
    # ------------------------------------------------------------------

    async def start_listening(self):
        """Subscribe to dispatch_order channel."""
        if not self.redis:
            logger.warning("Redis not available — skipping subscription")
            return
        await listen_for_messages(
            self.redis, "dispatch_order", self._handle_dispatch_order,
        )

    async def _handle_dispatch_order(self, envelope: AgentMessage):
        """
        Handle a dispatch_order from Agent 3.
        The payload is a ResourceAllocation dict.
        """
        zone = envelope.payload.get("zone_name", "unknown")
        urgency = envelope.payload.get("urgency", "?")
        logger.info(
            "Received dispatch_order from %s | zone=%s | urgency=%s",
            envelope.source_agent, zone, urgency,
        )
        self._last_action = f"received order zone={zone}"

        plan = await self.optimizer.create_dispatch_plan(envelope.payload)
        if plan:
            self._dispatch_count += 1
            self._plans.insert(0, plan)
            if len(self._plans) > 100:
                self._plans = self._plans[:100]

            await self._publish_dispatch_status(plan)
            logger.info(
                "Dispatched %d teams to %s — ETA %.1f min, safety %.2f",
                len(plan.team_routes), zone,
                plan.total_eta_minutes, plan.route_safety_score,
            )
        else:
            logger.warning("Could not create dispatch plan for zone=%s", zone)

    # ------------------------------------------------------------------
    # Publishers
    # ------------------------------------------------------------------

    async def _publish_dispatch_status(self, plan):
        """Publish dispatch status update for dashboard."""
        msg = AgentMessage(
            source_agent=AGENT_ID,
            target_agent="dashboard",
            channel="dispatch_status",
            message_type="dispatch_status",
            payload={
                "dispatch_id": str(plan.id),
                "allocation_id": str(plan.allocation_id),
                "zone_name": plan.zone_name,
                "priority": plan.priority,
                "team_count": len(plan.team_routes),
                "total_eta_minutes": plan.total_eta_minutes,
                "route_safety_score": plan.route_safety_score,
                "status": plan.status.value,
                "teams": [
                    {
                        "unit_name": tr.unit_name,
                        "resource_type": tr.resource_type,
                        "transport_mode": tr.transport_mode.value,
                        "distance_km": tr.distance_km,
                        "eta_minutes": tr.eta_minutes,
                        "status": tr.status.value,
                    }
                    for tr in plan.team_routes
                ],
            },
            priority=plan.priority,
        )
        if self.redis:
            await publish_message(self.redis, "dispatch_status", msg)
        if self.db:
            await log_message_to_db(self.db, msg)
        self._last_action = f"dispatched {len(plan.team_routes)} teams → {plan.zone_name}"

    async def publish_heartbeat(self):
        """Heartbeat every 30 seconds."""
        if not self.redis:
            return
        while True:
            uptime = (datetime.now(timezone.utc) - self._start_time).total_seconds()
            hb = HeartbeatMessage(
                agent_id=AGENT_ID,
                uptime_seconds=uptime,
                last_action=self._last_action,
                metrics={"total_dispatches": self._dispatch_count},
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