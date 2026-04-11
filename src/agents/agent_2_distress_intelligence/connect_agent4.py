"""
connect_agent4.py — Bridge: Agent 3 → Agent 4
================================================
Fetches allocations from Agent 3's /allocations endpoint and
sends them to Agent 4's /trigger_batch for dispatch optimization.

Usage:
    python connect_agent4.py                  # fetch & dispatch all
    python connect_agent4.py --show-status    # show Agent 4 status
"""
import argparse
import json
import sys
import time

import requests

AGENT3_URL = "http://localhost:8003"
AGENT4_URL = "http://localhost:8004"


def get_allocations(limit: int = 20) -> list:
    """Fetch allocation details from Agent 3."""
    resp = requests.get(f"{AGENT3_URL}/allocations?limit={limit}", timeout=5)
    resp.raise_for_status()
    allocs = resp.json()
    print(f"📋 Fetched {len(allocs)} allocations from Agent 3")

    # For each allocation, get full details (with allocated_units)
    detailed = []
    for a in allocs:
        try:
            r = requests.get(f"{AGENT3_URL}/allocations/{a['id']}", timeout=5)
            r.raise_for_status()
            detail = r.json()
            # Map allocated_units to allocated_resources format Agent 4 expects
            if "allocated_units" in detail and isinstance(detail["allocated_units"], str):
                detail["allocated_units"] = json.loads(detail["allocated_units"])
            detail["allocated_resources"] = detail.get("allocated_units", [])
            detailed.append(detail)
        except Exception as e:
            print(f"  ⚠ Could not fetch detail for {a['id']}: {e}")
            # Construct minimal allocation from summary
            detailed.append({
                "allocation_id": a["id"],
                "incident_id": a.get("incident_id", ""),
                "zone_id": a.get("zone_name", "").lower(),
                "zone_name": a.get("zone_name", ""),
                "destination": {"latitude": 23.78, "longitude": 90.40},
                "priority": 3,
                "urgency": a.get("urgency", "MODERATE"),
                "water_level_meters": 0,
                "flood_verified": False,
                "allocated_resources": [],
            })

    return detailed


def send_to_agent4(allocations: list):
    """Send allocations to Agent 4 for dispatch."""
    print(f"\n🚀 Sending {len(allocations)} allocations to Agent 4...")
    try:
        resp = requests.post(
            f"{AGENT4_URL}/trigger_batch",
            json=allocations,
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        print(f"✅ Dispatched: {result['dispatched']}/{result['processed']}")
        for plan in result.get("plans", []):
            print(
                f"   📍 {plan['zone_name']} — "
                f"{len(plan['team_routes'])} teams, "
                f"ETA {plan['total_eta_minutes']:.1f} min, "
                f"safety {plan['route_safety_score']:.2f}"
            )
    except Exception as e:
        print(f"❌ Failed: {e}")


def show_status():
    """Show Agent 4 status."""
    try:
        r = requests.get(f"{AGENT4_URL}/status", timeout=5)
        r.raise_for_status()
        st = r.json()
        print(f"\n📊 Agent 4 Status:")
        print(f"   Status:       {st['status']}")
        print(f"   Uptime:       {st['uptime_s']:.0f}s")
        print(f"   Dispatches:   {st['total_dispatches']}")
        print(f"   Active plans: {st.get('active_plans', 0)}")
        print(f"   Last action:  {st['last_action']}")
        print(f"   DB:           {'✅' if st['db_connected'] else '❌'}")
        print(f"   Redis:        {'✅' if st['redis_connected'] else '❌'}")
    except Exception as e:
        print(f"❌ Agent 4 unreachable: {e}")

    try:
        r = requests.get(f"{AGENT4_URL}/dispatches?limit=10", timeout=5)
        r.raise_for_status()
        dispatches = r.json()
        if dispatches:
            print(f"\n📋 Recent Dispatches ({len(dispatches)}):")
            for d in dispatches:
                print(
                    f"   {d['zone_name']} — "
                    f"priority {d['priority']}, "
                    f"{d.get('team_count', '?')} teams, "
                    f"ETA {d.get('total_eta_minutes', 0):.1f} min, "
                    f"safety {d.get('route_safety_score', 0):.2f}"
                )
    except Exception as e:
        print(f"   Could not fetch dispatches: {e}")


def main():
    parser = argparse.ArgumentParser(description="Bridge: Agent 3 → Agent 4")
    parser.add_argument("--show-status", action="store_true", help="Show Agent 4 status")
    parser.add_argument("--limit", type=int, default=20, help="Max allocations to fetch")
    args = parser.parse_args()

    if args.show_status:
        show_status()
        return

    # Check agents are up
    for name, url in [("Agent 3", AGENT3_URL), ("Agent 4", AGENT4_URL)]:
        try:
            requests.get(f"{url}/health", timeout=3)
            print(f"✅ {name} is running at {url}")
        except Exception:
            print(f"❌ {name} not reachable at {url}")
            sys.exit(1)

    allocs = get_allocations(args.limit)
    if allocs:
        send_to_agent4(allocs)
    else:
        print("No allocations to dispatch.")

    print("\n" + "=" * 50)
    show_status()


if __name__ == "__main__":
    main()