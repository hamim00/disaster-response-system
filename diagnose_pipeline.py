"""
FloodShield BD — Deep Pipeline Diagnostic
==========================================
Tests each piece of the Agent 2 → Agent 3 → Agent 4 pipeline in isolation.
Run: python diagnose_pipeline.py
"""
import requests
import json
import time
import sys

BASE = {
    2: "http://localhost:8002",
    3: "http://localhost:8003",
    4: "http://localhost:8004",
}

BOLD = "\033[1m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def section(title):
    print(f"\n{BOLD}{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}{RESET}")

def ok(msg):
    print(f"  {GREEN}✓ {msg}{RESET}")

def fail(msg):
    print(f"  {RED}✗ {msg}{RESET}")

def warn(msg):
    print(f"  {YELLOW}⚠ {msg}{RESET}")

def info(msg):
    print(f"  {msg}")


# ============================================================
# TEST 1: Agent 3 direct allocation (bypass Redis entirely)
# ============================================================
def test_agent3_direct():
    section("TEST 1: Agent 3 direct /trigger (no Redis needed)")
    
    distress_item = {
        "distress_id": "diag-001",
        "channel": "sms_ussd",
        "location": {
            "latitude": 23.8223,
            "longitude": 90.3654,
            "zone_name": "Mirpur",
            "zone_id": "mirpur"
        },
        "zone_name": "Mirpur",
        "distress_type": "stranded",
        "urgency": "critical",
        "people_count": 6,
        "needs_rescue": True,
        "water_level_meters": 1.2,
        "priority_score": 0.95,
        "flood_verified": True,
        "recommended_resources": ["rescue_boat", "medical_team"],
        "summary": "Diagnostic test"
    }
    
    try:
        r = requests.post(f"{BASE[3]}/trigger", json=distress_item, timeout=10)
        if r.status_code == 200:
            data = r.json()
            ok(f"Allocation created: {data.get('zone_name')} — {len(data.get('allocated_resources', []))} resources")
            info(f"  Allocation ID: {data.get('id', 'N/A')}")
            info(f"  Urgency: {data.get('urgency')}")
            for res in data.get('allocated_resources', []):
                info(f"    → {res.get('name', res.get('type'))} ({res.get('distance_km', '?')} km)")
            return data
        elif r.status_code == 422:
            fail(f"No resources available or invalid data: {r.text[:200]}")
            return None
        else:
            fail(f"HTTP {r.status_code}: {r.text[:200]}")
            return None
    except Exception as e:
        fail(f"Failed: {e}")
        return None


# ============================================================
# TEST 2: Agent 2 SMS ingest + synchronous trigger check
# ============================================================
def test_agent2_ingest_and_trigger():
    section("TEST 2: Agent 2 — ingest SMS and trigger cycle")
    
    # Step A: Check current queue size
    try:
        r = requests.get(f"{BASE[2]}/queue", timeout=5)
        before_count = len(r.json())
        info(f"Queue BEFORE trigger: {before_count} items")
    except Exception as e:
        warn(f"Could not check queue: {e}")
        before_count = -1
    
    # Step B: Ingest SMS
    sms = [{"text": "FLOOD MIRPUR 4FT 6 ROOFTOP", "sender_phone": "+8801700000000", "timestamp": "2026-04-10T12:00:00"}]
    try:
        r = requests.post(f"{BASE[2]}/ingest/sms", json=sms, timeout=5)
        if r.status_code == 200:
            ok(f"SMS ingested: {r.json()}")
        else:
            fail(f"SMS ingest failed: {r.status_code} {r.text[:200]}")
            return
    except Exception as e:
        fail(f"SMS ingest failed: {e}")
        return
    
    # Step C: Trigger cycle
    try:
        r = requests.post(f"{BASE[2]}/trigger", json={}, timeout=5)
        if r.status_code == 200:
            ok(f"Trigger response: {r.json()}")
        else:
            fail(f"Trigger failed: {r.status_code} {r.text[:200]}")
            return
    except Exception as e:
        fail(f"Trigger failed: {e}")
        return
    
    # Step D: Wait and check queue
    info("Waiting 8 seconds for async cycle to complete...")
    time.sleep(8)
    
    try:
        r = requests.get(f"{BASE[2]}/queue", timeout=5)
        queue = r.json()
        after_count = len(queue)
        info(f"Queue AFTER trigger: {after_count} items")
        
        if after_count > 0:
            ok(f"Agent 2 produced {after_count} queue items")
            for i, item in enumerate(queue[:3]):
                info(f"  [{i}] zone={item.get('zone_name')} urgency={item.get('urgency')} "
                     f"rescue={item.get('needs_rescue')} score={item.get('priority_score')}")
                # Check location
                loc = item.get("location", {})
                info(f"       location: lat={loc.get('latitude')} lon={loc.get('longitude')}")
                if not loc.get("latitude") or not loc.get("longitude"):
                    fail("LOCATION MISSING — Agent 3 allocator will reject this!")
        else:
            fail("Queue is EMPTY after trigger — Agent 2 cycle did not produce items")
            warn("Check Agent 2 terminal for errors during the triggered cycle")
        
        return queue
    except Exception as e:
        fail(f"Queue check failed: {e}")
        return None


# ============================================================
# TEST 3: Redis pub/sub connectivity
# ============================================================
def test_redis_pubsub():
    section("TEST 3: Redis pub/sub between Agent 2 and Agent 3")
    
    info("Checking Agent 3 allocation count BEFORE...")
    try:
        r = requests.get(f"{BASE[3]}/status", timeout=5)
        status = r.json()
        before_allocs = status.get("total_allocations", 0)
        info(f"  Agent 3 total_allocations: {before_allocs}")
    except Exception as e:
        fail(f"Agent 3 status check failed: {e}")
        return
    
    info("Sending SMS + triggering Agent 2 cycle...")
    sms = [{"text": "FLOOD SYLHET 3FT 10 TRAPPED", "sender_phone": "+8801799999999", "timestamp": "2026-04-10T13:00:00"}]
    try:
        requests.post(f"{BASE[2]}/ingest/sms", json=sms, timeout=5)
        requests.post(f"{BASE[2]}/trigger", json={}, timeout=5)
    except Exception as e:
        fail(f"Could not trigger: {e}")
        return
    
    info("Waiting 10 seconds for full pipeline (Agent 2 → Redis → Agent 3)...")
    time.sleep(10)
    
    info("Checking Agent 3 allocation count AFTER...")
    try:
        r = requests.get(f"{BASE[3]}/status", timeout=5)
        status = r.json()
        after_allocs = status.get("total_allocations", 0)
        info(f"  Agent 3 total_allocations: {after_allocs}")
        
        if after_allocs > before_allocs:
            ok(f"Pipeline WORKS! Agent 3 processed {after_allocs - before_allocs} new allocations via Redis pub/sub")
        else:
            fail("Agent 3 received ZERO new allocations via Redis")
            warn("This means Redis pub/sub is not delivering messages from Agent 2 to Agent 3")
            warn("Check Agent 2 terminal for 'Published X items to distress_queue' log")
            warn("Check Agent 3 terminal for 'Received distress from' log")
            warn("If Agent 2 published but Agent 3 didn't receive → Redis pub/sub issue")
            warn("If Agent 2 didn't publish → Agent 2 cycle failed silently")
    except Exception as e:
        fail(f"Agent 3 status check failed: {e}")
    
    # Also check DB allocations
    try:
        r = requests.get(f"{BASE[3]}/allocations?limit=5", timeout=5)
        allocs = r.json()
        info(f"  Agent 3 DB allocations: {len(allocs)} records")
        if allocs:
            latest = allocs[0]
            info(f"  Latest: zone={latest.get('zone_name')} time={str(latest.get('timestamp','?'))[:19]}")
    except:
        pass


# ============================================================
# TEST 4: Agent 3 → Agent 4 (with real allocation ID)
# ============================================================
def test_agent3_to_agent4(allocation_data):
    section("TEST 4: Agent 4 dispatch from real Agent 3 allocation")
    
    if not allocation_data:
        warn("Skipping — no allocation data from previous tests")
        return
    
    # Build dispatch payload from allocation
    payload = {
        "zone_name": allocation_data.get("zone_name"),
        "zone_id": allocation_data.get("zone_id"),
        "incident_id": allocation_data.get("incident_id"),
        "allocation_id": str(allocation_data.get("allocation_id", allocation_data.get("id", ""))),
        "destination": {
            "latitude": allocation_data.get("destination", {}).get("latitude"),
            "longitude": allocation_data.get("destination", {}).get("longitude"),
        },
        "priority": allocation_data.get("priority", 1),
        "urgency": allocation_data.get("urgency", "LIFE_THREATENING"),
        "water_level_meters": allocation_data.get("water_level_meters"),
        "flood_verified": allocation_data.get("flood_verified", True),
        "allocated_resources": allocation_data.get("allocated_resources", []),
    }
    
    try:
        r = requests.post(f"{BASE[4]}/trigger", json=payload, timeout=10)
        if r.status_code == 200:
            data = r.json()
            ok(f"Dispatch created: zone={data.get('zone_name')} teams={len(data.get('team_routes',[]))} "
               f"eta={data.get('total_eta_minutes')} min")
        else:
            fail(f"HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        fail(f"Failed: {e}")


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print(f"\n{BOLD}FloodShield BD — Deep Pipeline Diagnostic{RESET}")
    print(f"{'='*60}\n")
    
    # Test 1: Agent 3 allocation works at all?
    alloc = test_agent3_direct()
    
    # Test 2: Agent 2 produces queue items?
    queue = test_agent2_ingest_and_trigger()
    
    # Test 3: Redis pub/sub delivers messages?
    test_redis_pubsub()
    
    # Test 4: Agent 4 dispatch with real allocation
    test_agent3_to_agent4(alloc)
    
    section("DONE — Check Agent 2 and Agent 3 terminals for log output!")
    print()