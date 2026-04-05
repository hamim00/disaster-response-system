"""
Standard Redis message envelope used by ALL agents.
Compatible with Agent 2's AgentMessage format.

Agent 2 publishes:
    AgentMessage(source_agent, target_agent, channel, message_type, payload, priority)

All other agents must parse this same format.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AgentMessage(BaseModel):
    """
    Standard envelope for ALL Redis pub/sub messages.
    Field names match Agent 2's output exactly.
    """
    message_id: UUID = Field(default_factory=uuid4)
    source_agent: str
    target_agent: str
    channel: str = ""                       # Redis channel name
    message_type: str                       # "distress_report", "dispatch_order", etc.
    payload: dict
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    priority: int = Field(3, ge=1, le=5)


class HeartbeatMessage(BaseModel):
    """Heartbeat published on 'agent_status' by every agent."""
    agent_id: str
    status: str = "running"
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    uptime_seconds: Optional[float] = None
    last_action: Optional[str] = None
    metrics: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Redis helpers
# ---------------------------------------------------------------------------

async def publish_message(redis_client: Any, channel: str, message: AgentMessage) -> None:
    """Publish an AgentMessage to a Redis channel."""
    await redis_client.publish(channel, message.model_dump_json())
    logger.debug("Published %s → %s", message.message_type, channel)


async def log_message_to_db(db_pool: Any, message: AgentMessage) -> None:
    """Persist every inter-agent message to the agent_messages table."""
    try:
        await db_pool.execute(
            """
            INSERT INTO agent_messages
                (message_id, timestamp, sender_agent, receiver_agent,
                 message_type, zone_id, priority, payload)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            message.message_id,
            message.timestamp,
            message.source_agent,
            message.target_agent,
            message.message_type,
            message.payload.get("zone_name") or message.payload.get("zone_id"),
            message.priority,
            json.dumps(message.payload),
        )
    except Exception as exc:
        logger.error("Failed to log message to DB: %s", exc)


async def listen_for_messages(
    redis_client: Any,
    channel: str,
    handler: Callable[[AgentMessage], Coroutine],
) -> None:
    """
    Subscribe to a Redis channel and call handler for every valid message.
    Runs forever — launch as an asyncio task.
    """
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    logger.info("Subscribed to Redis channel: %s", channel)

    async for raw in pubsub.listen():
        if raw["type"] != "message":
            continue
        try:
            data = json.loads(raw["data"])
            envelope = AgentMessage(**data)
            await handler(envelope)
        except Exception as exc:
            logger.error("Error processing message on %s: %s", channel, exc)
