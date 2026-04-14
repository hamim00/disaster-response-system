"""
Redis → WebSocket Bridge
==========================
Background task that subscribes to ALL Redis channels and forwards
relevant messages to the appropriate WebSocket connections.

Uses get_message() polling instead of async-for listen() to avoid
'aclose(): asynchronous generator is already running' crash on shutdown.
"""
import asyncio
import json
import logging
from typing import Optional

from redis import asyncio as aioredis
from .manager import manager

logger = logging.getLogger("ws_bridge")

# All channels this bridge listens on
CHANNELS = [
    "raw_distress_intake",
    "intake_status_update",
    "verified_distress",
    "dispatch_order",
    "team_notifications",
    "team_feedback",
    "team_location",
    "team_status_update",
    "ground_reports",
    "resource_consumed",
    "resupply_alerts",
    "inventory_update",
    "dispatch_status",
    "dispatch_status_change",  # NEW: per-dispatch status transitions
]


async def redis_to_websocket_bridge(redis_url: str):
    """
    Subscribe to all Redis channels and forward messages to WebSocket clients.
    Uses get_message() polling to avoid async generator crash on shutdown.
    """
    while True:
        pubsub = None
        redis = None
        try:
            redis = await aioredis.from_url(redis_url, decode_responses=True)
            await redis.ping()
            logger.info("Bridge connected to Redis at %s", redis_url)

            pubsub = redis.pubsub()
            await pubsub.subscribe(*CHANNELS)
            logger.info("Bridge subscribed to %d channels", len(CHANNELS))

            # Use get_message() polling instead of async for listen()
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=0.5,
                )
                if message is None:
                    await asyncio.sleep(0.01)
                    continue

                if message["type"] != "message":
                    continue

                channel = message["channel"]
                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    logger.warning("Bridge: invalid JSON on channel %s", channel)
                    continue

                logger.info(
                    "Bridge received: channel=%s, gw=%d, cmd=%d, field=%s",
                    channel,
                    len(manager.gateway_connections),
                    len(manager.command_connections),
                    list(manager.field_connections.keys()),
                )

                await _route_message(channel, data)

        except asyncio.CancelledError:
            logger.info("Bridge task cancelled — shutting down")
            if pubsub:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.aclose()
                except Exception:
                    pass
            if redis:
                try:
                    await redis.aclose()
                except Exception:
                    pass
            break
        except Exception as e:
            logger.error("Bridge error: %s — reconnecting in 3s", e, exc_info=True)
            if pubsub:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.aclose()
                except Exception:
                    pass
            if redis:
                try:
                    await redis.aclose()
                except Exception:
                    pass
            await asyncio.sleep(3)


async def _route_message(channel: str, data: dict):
    """Route a Redis message to the correct WebSocket clients."""
    try:
        if channel == "raw_distress_intake":
            gw = len(manager.gateway_connections)
            cmd = len(manager.command_connections)
            logger.info("Routing new_intake → %d gateway + %d command clients", gw, cmd)
            await manager.broadcast_to_gateway({"type": "new_intake", "data": data})
            await manager.broadcast_to_command({"type": "new_intake", "data": data})

        elif channel == "intake_status_update":
            await manager.broadcast_to_gateway({"type": "intake_update", "data": data})
            await manager.broadcast_to_command({"type": "intake_update", "data": data})

        elif channel == "verified_distress":
            await manager.broadcast_to_command({"type": "verified_distress", "data": data})

        elif channel == "dispatch_order":
            await manager.broadcast_to_command({"type": "dispatch_order", "data": data})

        elif channel == "team_notifications":
            team_id = data.get("team_id")
            if team_id:
                has_ws = team_id in manager.field_connections
                logger.info(
                    "Routing dispatch → team=%s, connected=%s, all_teams=%s",
                    team_id, has_ws, list(manager.field_connections.keys()),
                )
                await manager.send_to_team(team_id, {"type": "new_dispatch", "data": data})
            else:
                logger.warning("team_notifications has no team_id!")
            await manager.broadcast_to_command({"type": "dispatch_sent", "data": data})

        elif channel == "team_feedback":
            await manager.broadcast_to_command({"type": "team_response", "data": data})

        elif channel == "team_location":
            await manager.broadcast_to_command({"type": "team_location", "data": data})

        elif channel == "team_status_update":
            await manager.broadcast_to_command({"type": "team_status", "data": data})

        elif channel == "ground_reports":
            await manager.broadcast_to_command({"type": "ground_report", "data": data})

        elif channel == "resource_consumed":
            await manager.broadcast_to_command({"type": "resource_consumed", "data": data})

        elif channel == "resupply_alerts":
            await manager.broadcast_to_command({"type": "resupply_alert", "data": data})

        elif channel == "inventory_update":
            await manager.broadcast_to_command({"type": "inventory_update", "data": data})

        elif channel == "dispatch_status":
            await manager.broadcast_to_command({"type": "dispatch_status", "data": data})

        elif channel == "dispatch_status_change":
            # NEW: Forward per-dispatch status transitions (accepted, en_route, on_site, completed)
            await manager.broadcast_to_command({"type": "dispatch_status_change", "data": data})

    except Exception as e:
        logger.error("Route error on %s: %s", channel, e, exc_info=True)
