"""
Agent 2 → Agent 3 HTTP Bridge
================================
Fetches the distress queue from Agent 2 and feeds each item
to Agent 3's /trigger endpoint for resource allocation.

Use this when Redis pub/sub isn't working or for demo/testing.

Usage:
  python connect_agent3.py                    # feed all queue items
  python connect_agent3.py --batch            # use /trigger_batch endpoint
  python connect_agent3.py --show-inventory   # show inventory after allocation

Author: Mahmudul Hasan
"""

import argparse
import json
import sys
import requests
import time

AGENT2_URL = "http://localhost:8002"
AGENT3_URL = "http://localhost:8003"


def fetch_queue():
    """Fetch Agent 2's current distress queue."""
    try:
        resp = requests.get(f"{AGENT2_URL}/queue", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"   ❌ Could not fetch Agent 2 queue: {e}")
        return []


def trigger_single(item):
    """Send a single distress item to Agent 3 for allocation."""
    try:
        resp = requests.post(
            f"{AGENT3_URL}/trigger",
            json=item,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 422:
            return {"error": "No resources available"}
        else:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def trigger_batch(items):
    """Send all items as a batch to Agent 3."""
    try:
        resp = requests.post(
            f"{AGENT3_URL}/trigger_batch",
            json=items,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"   ❌ Batch trigger failed: {e}")
        return None


def show_inventory():
    """Display current inventory status."""
    print("\n" + "=" * 70)
    print("  📦 RESOURCE INVENTORY")
    print("=" * 70)

    try:
        resp = requests.get(f"{AGENT3_URL}/inventory", timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"   ❌ Could not fetch inventory: {e}")
        return

    for rtype, counts in data.get("resources", {}).items():
        total = counts.get("total", 0)
        avail = counts.get("available", 0)
        deployed = counts.get("deployed", 0)
        icon = {
            "rescue_boat": "🚤",
            "medical_team": "🏥",
            "medical_kit": "💊",
            "food_supply": "🍚",
            "water_supply": "💧",
        }.get(rtype, "📦")
        bar = "█" * avail + "░" * deployed
        print(f"  {icon} {rtype:20s}  {bar}  {avail}/{total} available")


def show_allocations():
    """Display recent allocations."""
    print("\n" + "=" * 70)
    print("  📋 RESOURCE ALLOCATIONS")
    print("=" * 70)

    try:
        resp = requests.get(f"{AGENT3_URL}/allocations", timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"   ❌ Could not fetch allocations: {e}")
        return

    if not data:
        print("   (none yet)")
        return

    for i, a in enumerate(data):
        zone = a.get("zone_name", "?")
        urgency = a.get("urgency", "?")
        people = a.get("num_people_affected", 0)
        count = a.get("resource_count", 0)
        partial = "⚠️ PARTIAL" if a.get("partial_allocation") else "✅ FULL"
        print(
            f"  #{i+1} {zone:20s} {urgency:20s} {people:>8} people  "
            f"{count} resources  {partial}"
        )

    print(f"\n  Total: {len(data)} allocations")


def main():
    global AGENT2_URL, AGENT3_URL

    parser = argparse.ArgumentParser(description="Agent 2 → Agent 3 Bridge")
    parser.add_argument("--batch", action="store_true", help="Use batch endpoint")
    parser.add_argument(
        "--show-inventory", action="store_true", help="Show inventory after"
    )
    parser.add_argument("--agent2-url", default=AGENT2_URL)
    parser.add_argument("--agent3-url", default=AGENT3_URL)
    args = parser.parse_args()

    AGENT2_URL = args.agent2_url
    AGENT3_URL = args.agent3_url

    print("=" * 70)
    print("  AGENT 2 → AGENT 3 BRIDGE")
    print("  Feeding distress queue into resource allocation")
    print("=" * 70)
    print(f"  Agent 2: {AGENT2_URL}")
    print(f"  Agent 3: {AGENT3_URL}")

    # Fetch queue
    print(f"\n📥 Fetching distress queue from Agent 2...")
    queue = fetch_queue()
    if not queue:
        print("   Queue is empty — run connect_agent1.py --all-scenarios first")
        return

    print(f"   Got {len(queue)} items")

    if args.batch:
        # Batch mode
        print(f"\n▶  Sending batch of {len(queue)} items to Agent 3...")
        result = trigger_batch(queue)
        if result:
            print(f"   ✅ Processed {result['processed']}, allocated {result['allocated']}")
    else:
        # Individual mode
        print(f"\n▶  Processing {len(queue)} items individually...")
        success = 0
        failed = 0
        for i, item in enumerate(queue):
            zone = item.get("zone_name", "?")
            urgency = item.get("urgency", "?").upper()
            result = trigger_single(item)

            if "error" in result:
                print(f"   ❌ #{i+1} {zone} ({urgency}): {result['error']}")
                failed += 1
            else:
                count = len(result.get("allocated_resources", []))
                alloc_urgency = result.get("urgency", "?")
                partial = " ⚠️ PARTIAL" if result.get("partial_allocation") else ""
                print(f"   ✅ #{i+1} {zone} → {alloc_urgency} → {count} resources{partial}")
                success += 1

        print(f"\n   Done: {success} allocated, {failed} failed")

    # Show results
    time.sleep(1)
    show_allocations()

    if args.show_inventory:
        show_inventory()


if __name__ == "__main__":
    main()