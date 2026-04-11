"""
Direct Redis pub/sub test — bypasses Agent 2 and Agent 3 entirely.
Run this WHILE Agent 3 is running to see if it receives messages.

Usage:
    python test_redis_pubsub.py
"""
import asyncio
import json
import time
import redis.asyncio as aioredis
from uuid import uuid4
from datetime import datetime, timezone

REDIS_URL = "redis://localhost:6379"

FAKE_DISTRESS_MESSAGE = {
    "message_id": str(uuid4()),
    "source_agent": "test_script",
    "target_agent": "agent_3_resource_management",
    "channel": "distress_queue",
    "message_type": "distress_report",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "priority": 1,
    "payload": {
        "distress_id": f"test-{uuid4().hex[:8]}",
        "channel": "sms_ussd",
        "location": {"latitude": 23.8223, "longitude": 90.3654},
        "zone_name": "Mirpur",
        "distress_type": "flood_report",
        "urgency": "critical",
        "people_count": 15,
        "needs_rescue": True,
        "water_level_meters": 1.2,
        "priority_score": 1.0,
        "flood_verified": True,
        "recommended_resources": [
            {"type": "rescue_boat", "count": 2},
            {"type": "medical_team", "count": 1},
        ],
        "summary": "TEST: 15 people trapped in Mirpur, 1.2m water",
    },
}


async def test_1_raw_pubsub():
    """Test: can a subscriber on 'distress_queue' receive a published message?"""
    print("\n=== TEST A: Raw Redis pub/sub (no agents involved) ===")
    pub = await aioredis.from_url(REDIS_URL, decode_responses=True)
    sub = await aioredis.from_url(REDIS_URL, decode_responses=True)

    pubsub = sub.pubsub()
    await pubsub.subscribe("distress_queue")

    # drain the subscribe confirmation
    msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)

    # publish
    payload = json.dumps(FAKE_DISTRESS_MESSAGE)
    listeners = await pub.publish("distress_queue", payload)
    print(f"  Published to distress_queue — {listeners} listener(s) received it")

    # try to receive
    received = await pubsub.get_message(ignore_subscribe_messages=True, timeout=3)
    if received and received["type"] == "message":
        data = json.loads(received["data"])
        print(f"  ✓ Received message: type={data.get('message_type')} zone={data['payload'].get('zone_name')}")
    else:
        print(f"  ✗ No message received (got: {received})")

    await pubsub.unsubscribe("distress_queue")
    await pub.aclose()
    await sub.aclose()
    return listeners


async def test_2_agent3_listening():
    """Test: is Agent 3 actually subscribed? Publish and check listener count."""
    print("\n=== TEST B: Publish to distress_queue (Agent 3 should be listening) ===")
    pub = await aioredis.from_url(REDIS_URL, decode_responses=True)

    payload = json.dumps(FAKE_DISTRESS_MESSAGE)
    listeners = await pub.publish("distress_queue", payload)
    print(f"  Listeners on distress_queue: {listeners}")

    if listeners == 0:
        print("  ✗ ZERO listeners — Agent 3's Redis subscriber is NOT connected")
        print("  ⚠ Check Agent 3 terminal for 'Subscribed to Redis channel: distress_queue'")
        print("  ⚠ If missing, Agent 3 may have failed Redis connection or handler task crashed")
    else:
        print(f"  ✓ {listeners} listener(s) — message was delivered")
        print("  Check Agent 3 terminal NOW for 'Received distress from test_script' log")

    await pub.aclose()
    return listeners


async def test_3_agent2_publishes():
    """Test: subscribe to distress_queue OURSELVES, then trigger Agent 2 and see if it publishes."""
    print("\n=== TEST C: Subscribe ourselves + trigger Agent 2 — does it publish? ===")
    import aiohttp

    sub = await aioredis.from_url(REDIS_URL, decode_responses=True)
    pubsub = sub.pubsub()
    await pubsub.subscribe("distress_queue")
    # drain subscribe confirmation
    await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)

    # Inject SMS into Agent 2 and trigger
    sms = [{"text": "FLOOD MIRPUR 4FT 20 TRAPPED URGENT", "sender_phone": "+8801700000000", "timestamp": "2026-04-11T12:00:00"}]
    async with aiohttp.ClientSession() as session:
        try:
            await session.post("http://localhost:8002/ingest/sms", json=sms, timeout=aiohttp.ClientTimeout(total=5))
            resp = await session.post("http://localhost:8002/trigger", timeout=aiohttp.ClientTimeout(total=15))
            trigger_data = await resp.json()
            print(f"  Agent 2 trigger response: {trigger_data}")
        except Exception as e:
            print(f"  ✗ Could not reach Agent 2: {e}")
            await pubsub.unsubscribe("distress_queue")
            await sub.aclose()
            return

    # Wait and collect messages
    print("  Waiting 5 seconds for messages...")
    received_count = 0
    deadline = time.time() + 5
    while time.time() < deadline:
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
        if msg and msg["type"] == "message":
            received_count += 1
            data = json.loads(msg["data"])
            zone = data.get("payload", {}).get("zone_name", "?")
            urgency = data.get("payload", {}).get("urgency", "?")
            if received_count <= 3:
                print(f"    Message {received_count}: zone={zone} urgency={urgency}")

    if received_count > 0:
        print(f"  ✓ Agent 2 published {received_count} messages to distress_queue")
        print("  The pub/sub channel works. If Agent 3 still shows 0, its subscriber task may have crashed.")
    else:
        print("  ✗ Agent 2 published ZERO messages after trigger")
        print("  ⚠ Agent 2's processing cycle produced an empty queue")
        print("  ⚠ Check Agent 2 terminal for 'Published X items to distress_queue' line")

    await pubsub.unsubscribe("distress_queue")
    await sub.aclose()


async def main():
    print("FloodShield BD — Redis Pub/Sub Diagnostic")
    print("=" * 60)

    listeners = await test_1_raw_pubsub()
    await test_2_agent3_listening()

    if listeners is not None:
        await test_3_agent2_publishes()

    print("\n" + "=" * 60)
    print("DONE")


if __name__ == "__main__":
    asyncio.run(main())
