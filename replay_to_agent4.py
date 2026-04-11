"""
replay_to_agent4.py — Replay missed allocations to Agent 4
============================================================
Redis pub/sub is fire-and-forget. If Agent 4 wasn't listening when
Agent 3 published dispatch_order messages, they're gone.

This script reads resource_allocations from the DB that have no
matching dispatch_routes entry, and POSTs them to Agent 4's
/trigger_batch endpoint.

Usage:
    python replay_to_agent4.py
    python replay_to_agent4.py --agent4-url http://localhost:8004
    python replay_to_agent4.py --dry-run
"""
import argparse
import asyncio
import json
import sys

import asyncpg
import httpx

DATABASE_URL = "postgresql://disaster_admin:disaster123@localhost:5432/disaster_response"
AGENT4_URL = "http://localhost:8004"


async def get_missed_allocations(db_url: str) -> list:
    """Find allocations that have no dispatch plan."""
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
    try:
        rows = await pool.fetch("""
            SELECT
                ra.id AS allocation_id,
                ra.incident_id,
                ra.zone_id,
                ra.zone_name,
                ST_Y(ra.destination::geometry) AS dest_lat,
                ST_X(ra.destination::geometry) AS dest_lon,
                ra.priority,
                ra.urgency,
                ra.num_people_affected,
                ra.allocated_units,
                ra.partial_allocation,
                ra.requires_medical
            FROM resource_allocations ra
            LEFT JOIN dispatch_routes dr ON dr.allocation_id = ra.id
            WHERE dr.id IS NULL
            ORDER BY ra.timestamp ASC
        """)
        allocations = []
        for r in rows:
            units = json.loads(r["allocated_units"]) if isinstance(r["allocated_units"], str) else r["allocated_units"]
            allocations.append({
                "allocation_id": str(r["allocation_id"]),
                "incident_id": r["incident_id"],
                "zone_id": r["zone_id"],
                "zone_name": r["zone_name"],
                "destination": {"latitude": r["dest_lat"], "longitude": r["dest_lon"]},
                "priority": r["priority"],
                "urgency": r["urgency"],
                "num_people_affected": r["num_people_affected"],
                "allocated_resources": units,
                "partial_allocation": r["partial_allocation"],
                "requires_medical": r["requires_medical"],
                "water_level_meters": 0.0,
                "flood_verified": False,
            })
        return allocations
    finally:
        await pool.close()


async def replay(agent4_url: str, db_url: str, dry_run: bool = False):
    allocations = await get_missed_allocations(db_url)

    if not allocations:
        print("✓ No missed allocations — Agent 4 has processed everything.")
        return

    print(f"Found {len(allocations)} allocation(s) with no dispatch plan:\n")
    for a in allocations:
        n_units = len(a.get("allocated_resources", []))
        print(f"  • {a['zone_name']:20s}  priority={a['priority']}  urgency={a['urgency']:20s}  units={n_units}")

    if dry_run:
        print("\n[DRY RUN] — no requests sent.")
        return

    print(f"\nSending to Agent 4 at {agent4_url}/trigger_batch ...")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{agent4_url}/trigger_batch", json=allocations)
        if resp.status_code == 200:
            result = resp.json()
            print(f"\n✓ Agent 4 processed {result['processed']} allocations, dispatched {result['dispatched']} plans.")
        else:
            print(f"\n✗ Agent 4 returned {resp.status_code}: {resp.text}")


def main():
    parser = argparse.ArgumentParser(description="Replay missed allocations to Agent 4")
    parser.add_argument("--agent4-url", default=AGENT4_URL)
    parser.add_argument("--db-url", default=DATABASE_URL)
    parser.add_argument("--dry-run", action="store_true", help="Show what would be sent without sending")
    args = parser.parse_args()
    asyncio.run(replay(args.agent4_url, args.db_url, args.dry_run))


if __name__ == "__main__":
    main()
