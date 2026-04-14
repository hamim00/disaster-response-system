"""
Redis handler for Agent 4 — Dispatch Optimization.
Subscribes to:  dispatch_order   (from Agent 3)
                team_feedback    (from Field Portal via backend)
                team_status_update (from Field Portal via backend)
Publishes to:   dispatch_status  (to Dashboard)
                agent_status     (heartbeat)
"""
import asyncio
import json
import logging
import math
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
        # Track dispatch_id → team_id mapping for status correlation
        self._dispatch_team_map: dict = {}

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

    async def start_feedback_listener(self):
        """Subscribe to team_feedback and team_status_update channels
        to track dispatch lifecycle based on actual field team actions."""
        if not self.redis:
            logger.warning("Redis not available — skipping feedback subscription")
            return

        pubsub = self.redis.pubsub()
        await pubsub.subscribe("team_feedback", "team_status_update")
        logger.info("Agent 4 subscribed to team_feedback + team_status_update")

        while True:
            try:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=0.5,
                )
                if message is None:
                    await asyncio.sleep(0.05)
                    continue
                if message["type"] != "message":
                    continue

                channel = message["channel"]
                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue

                if channel == "team_feedback":
                    await self._handle_team_feedback(data)
                elif channel == "team_status_update":
                    await self._handle_team_status_update(data)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Feedback listener error: %s", exc, exc_info=True)
                await asyncio.sleep(1)

    async def _handle_team_feedback(self, data: dict):
        """Handle team accept/decline of a dispatch."""
        dispatch_id = data.get("dispatch_id")
        team_id = data.get("team_id")
        response = data.get("response")

        if not dispatch_id or not team_id:
            return

        logger.info(
            "Team feedback: team=%s %s dispatch #%s",
            team_id, response, dispatch_id,
        )

        if response == "accepted":
            self._dispatch_team_map[str(dispatch_id)] = team_id
            # Update dispatch_routes status to 'accepted'
            await self._update_dispatch_status(dispatch_id, "accepted", team_id)
        elif response == "declined":
            await self._update_dispatch_status(dispatch_id, "declined", team_id)

    async def _handle_team_status_update(self, data: dict):
        """Handle team status changes (en_route, on_site, returning, standby)
        and update the corresponding dispatch status."""
        team_id = data.get("team_id")
        new_status = data.get("status")

        if not team_id or not new_status:
            return

        logger.info("Team status update: team=%s → %s", team_id, new_status)

        # Find the dispatch associated with this team
        dispatch_id = None

        # Check our in-memory map first
        for did, tid in self._dispatch_team_map.items():
            if tid == team_id:
                dispatch_id = did
                break

        # Fallback: check DB for current_mission_id
        if not dispatch_id and self.db:
            try:
                row = await self.db.fetchrow(
                    "SELECT current_mission_id FROM team_status WHERE team_id = $1",
                    team_id,
                )
                if row and row["current_mission_id"]:
                    dispatch_id = row["current_mission_id"]
            except Exception:
                pass

        if not dispatch_id:
            return

        # Map team status to dispatch status
        status_map = {
            "en_route": "en_route",
            "on_site": "on_site",
            "returning": "completed",
            "standby": "completed",
        }
        dispatch_status = status_map.get(new_status)
        if dispatch_status:
            await self._update_dispatch_status(dispatch_id, dispatch_status, team_id)

        # If completed, clean up the mapping
        if new_status in ("standby", "returning"):
            self._dispatch_team_map.pop(str(dispatch_id), None)

    async def _update_dispatch_status(self, dispatch_id, new_status, team_id=None):
        """Update dispatch_routes table and publish status change to dashboard."""
        if self.db:
            try:
                if new_status == "completed":
                    await self.db.execute(
                        "UPDATE dispatch_routes SET status = $1, completed_at = NOW() WHERE id = $2",
                        new_status, dispatch_id,
                    )
                else:
                    await self.db.execute(
                        "UPDATE dispatch_routes SET status = $1 WHERE id = $2",
                        new_status, dispatch_id,
                    )
            except Exception as exc:
                # dispatch_id might be an int counter, not a UUID — try by integer
                logger.debug("dispatch_routes update failed for id=%s: %s", dispatch_id, exc)

        # Publish status change for the dashboard
        if self.redis:
            await self.redis.publish("dispatch_status_change", json.dumps({
                "dispatch_id": dispatch_id,
                "status": new_status,
                "team_id": team_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))

        self._last_action = f"dispatch #{dispatch_id} → {new_status} (team={team_id})"
        logger.info("Dispatch #%s status → %s (team=%s)", dispatch_id, new_status, team_id)

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
            await self._notify_field_team(plan, envelope.payload)
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

    async def _notify_field_team(self, plan, allocation: dict):
        """
        Pick the nearest standby field team and publish a team_notifications
        message so the Field Portal receives the dispatch order.
        
        Does NOT auto-set team status to 'dispatched' — that happens when the
        team ACCEPTS via the Field Portal. This prevents the dashboard from
        showing dispatched status before the team confirms.
        """
        if not self.redis:
            return

        # --- Pick the best team ---
        dest_lat = plan.destination.latitude
        dest_lon = plan.destination.longitude
        chosen_team_id = None
        chosen_team_name = "Field Team"

        if self.db:
            try:
                teams = await self.db.fetch(
                    "SELECT team_id, team_name, current_lat, current_lng "
                    "FROM team_status WHERE status = 'standby'"
                )
                best_dist = float("inf")
                for t in teams:
                    tlat = t["current_lat"] or 0
                    tlng = t["current_lng"] or 0
                    dlat = math.radians(dest_lat - tlat)
                    dlng = math.radians(dest_lon - tlng)
                    a = (math.sin(dlat / 2) ** 2 +
                         math.cos(math.radians(tlat)) *
                         math.cos(math.radians(dest_lat)) *
                         math.sin(dlng / 2) ** 2)
                    d = 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                    if d < best_dist:
                        best_dist = d
                        chosen_team_id = t["team_id"]
                        chosen_team_name = t["team_name"]

                if chosen_team_id:
                    # Set mission ID but keep status as standby until team accepts
                    await self.db.execute(
                        "UPDATE team_status SET current_mission_id = $1, updated_at = NOW() "
                        "WHERE team_id = $2",
                        self._dispatch_count, chosen_team_id,
                    )
                    # Track in memory
                    self._dispatch_team_map[str(self._dispatch_count)] = chosen_team_id
                    logger.info(
                        "Selected %s (%s) for dispatch → %s (awaiting acceptance)",
                        chosen_team_id, chosen_team_name, plan.zone_name,
                    )
            except Exception as exc:
                logger.error("Team selection failed: %s", exc, exc_info=True)

        if not chosen_team_id:
            team_ids = ["team_alpha", "team_bravo", "team_charlie",
                        "team_delta", "team_echo"]
            chosen_team_id = team_ids[self._dispatch_count % len(team_ids)]
            chosen_team_name = chosen_team_id.replace("_", " ").title()

        # --- Build notification payload ---
        notification = {
            "dispatch_id": self._dispatch_count,
            "team_id": chosen_team_id,
            "team_name": chosen_team_name,
            "mission_type": "rescue_and_relief",
            "destination": {
                "lat": dest_lat,
                "lng": dest_lon,
            },
            "destination_name": plan.zone_name,
            "estimated_affected": allocation.get("num_people_affected", 45),
            "priority": plan.priority,
            "priority_label": (
                "CRITICAL" if plan.priority <= 2 else
                "HIGH" if plan.priority <= 3 else "MEDIUM"
            ),
            "resources_assigned": [
                {"type": tr.resource_type, "quantity": 1,
                 "unit_name": tr.unit_name}
                for tr in plan.team_routes
            ],
            "estimated_travel_time_min": plan.total_eta_minutes,
            "route_safety_score": plan.route_safety_score,
            "route_notes": (
                f"Dispatch from nearest depot, "
                f"{plan.route_safety_score:.0%} route safety"
            ),
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
        }

        # Publish to the chosen team's channel
        await self.redis.publish(
            "team_notifications", json.dumps(notification)
        )
        logger.info(
            "Published team_notifications → %s for zone %s",
            chosen_team_id, plan.zone_name,
        )

        # ALSO broadcast to ALL teams so any logged-in portal receives it
        if self.db:
            try:
                all_teams = await self.db.fetch(
                    "SELECT team_id FROM team_status WHERE team_id != $1",
                    chosen_team_id,
                )
                for t in all_teams:
                    alt_notification = {**notification, "team_id": t["team_id"],
                                        "originally_assigned_to": chosen_team_id}
                    await self.redis.publish(
                        "team_notifications", json.dumps(alt_notification)
                    )
            except Exception:
                pass  # non-fatal

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

    # ------------------------------------------------------------------
    # Resource Return Lifecycle (simplified — no auto-complete)
    # ------------------------------------------------------------------

    async def run_lifecycle_manager(self):
        """
        Background task that manages resource lifecycle AFTER team confirms completion.
        
        Unlike the old version, this does NOT auto-complete dispatches based on ETA.
        Dispatch completion is driven by team_feedback and team_status_update.
        
        This task now only handles returning resources to available status
        after a return delay following completion.
        """
        if not self.db:
            logger.warning("No DB — lifecycle manager disabled")
            return

        TIME_SCALE = 60.0  # 1 real second = 1 sim minute (for demo)
        RETURN_FACTOR = 0.5  # return trip = 50% of outbound ETA

        logger.info("Lifecycle manager started (feedback-driven, time_scale=%.0f×)", TIME_SCALE)

        while True:
            try:
                # Only handle returning resources after dispatch is marked completed
                # by team feedback (not auto-completed by timer)
                returned = await self.db.fetch("""
                    SELECT tr.unit_id, tr.eta_minutes, tr.arrived_at, tr.dispatch_id
                    FROM team_routes tr
                    WHERE tr.status = 'returning'
                      AND tr.arrived_at IS NOT NULL
                      AND tr.arrived_at + (tr.eta_minutes * $1 / $2) * INTERVAL '1 minute' <= NOW()
                """, RETURN_FACTOR, TIME_SCALE)

                for row in returned:
                    unit_id = row["unit_id"]
                    await self.db.execute("""
                        UPDATE resource_units
                        SET status = 'available',
                            current_location = base_location,
                            assigned_zone_id = NULL,
                            assigned_incident_id = NULL,
                            deployed_at = NULL,
                            updated_at = NOW()
                        WHERE id = $1
                    """, unit_id)

                    await self.db.execute("""
                        UPDATE team_routes
                        SET status = 'arrived'
                        WHERE unit_id = $1 AND dispatch_id = $2 AND status = 'returning'
                    """, unit_id, row["dispatch_id"])

                    logger.info("Resource %s returned to base — now available", unit_id)

                if returned:
                    self._last_action = f"lifecycle: {len(returned)} resources returned"

            except Exception as exc:
                logger.error("Lifecycle manager error: %s", exc, exc_info=True)

            await asyncio.sleep(10)
