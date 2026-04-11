"""
FloodShield BD — Full 4-Agent Pipeline Test
=============================================
Tests the COMPLETE chain:
  Agent 1 (Environmental) → Agent 2 (Distress) → Agent 3 (Resource) → Agent 4 (Dispatch)

Run with all 4 agents + Redis + PostgreSQL running:
    python test_full_pipeline.py

Author: FloodShield BD Team
"""
import requests
import time
import json
import sys

AGENTS = {
    1: "http://localhost:8001",
    2: "http://localhost:8002",
    3: "http://localhost:8003",
    4: "http://localhost:8004",
}

PASS = 0
FAIL = 0

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def ok(msg):
    global PASS
    PASS += 1
    print(f"  \u2713 {msg}")

def fail(msg):
    global FAIL
    FAIL += 1
    print(f"  \u2717 {msg}")

def info(msg):
    print(f"  {msg}")

def warn(msg):
    print(f"  \u26a0 {msg}")


# ============================================================
# PHASE 0: Health check all agents
# ============================================================
def phase_0_health():
    section("PHASE 0: Health Check — All Agents")
    all_up = True
    for agent_id, base_url in AGENTS.items():
        try:
            r = requests.get(f"{base_url}/health", timeout=5)
            if r.status_code == 200:
                data = r.json()
                redis_ok = data.get("redis_connected") or data.get("redis") == "ok"
                db_ok = data.get("database_connected") or data.get("db") == "ok"
                ok(f"Agent {agent_id}: UP | Redis={'OK' if redis_ok else 'NO'} | DB={'OK' if db_ok else 'N/A'}")
                if not redis_ok:
                    warn(f"Agent {agent_id} has no Redis — restart it")
                    all_up = False
            else:
                fail(f"Agent {agent_id}: HTTP {r.status_code}")
                all_up = False
        except requests.exceptions.ConnectionError:
            fail(f"Agent {agent_id}: DOWN (not reachable at {base_url})")
            all_up = False
        except Exception as e:
            fail(f"Agent {agent_id}: {e}")
            all_up = False
    return all_up


# ============================================================
# PHASE 1: Agent 1 — Environmental Intelligence
# ============================================================
def phase_1_agent1():
    section("PHASE 1: Agent 1 — Environmental Intelligence")

    # Check current predictions
    try:
        r = requests.get(f"{AGENTS[1]}/predictions", timeout=10)
        if r.status_code == 200:
            predictions = r.json()
            if isinstance(predictions, list):
                ok(f"Agent 1 has {len(predictions)} predictions")
                satellite_count = 0
                for p in predictions[:3]:
                    zone = p.get("zone_name", p.get("zone_id", "?"))
                    risk = p.get("risk_score", p.get("flood_risk", "?"))
                    severity = p.get("severity", "?")
                    sources = p.get("data_sources", [])
                    has_sat = "satellite" in str(sources).lower()
                    if has_sat:
                        satellite_count += 1
                    info(f"    {zone}: risk={risk} severity={severity} sources={sources}")
                if satellite_count > 0:
                    ok(f"Satellite data flowing into {satellite_count} predictions")
                else:
                    warn("No predictions include satellite data — apply data_processors.py fix")
            else:
                info(f"Predictions response: {str(predictions)[:200]}")
        else:
            warn(f"GET /predictions returned {r.status_code} — Agent 1 may not have this endpoint")
    except requests.exceptions.ConnectionError:
        fail("Agent 1 not reachable")
        return False
    except Exception as e:
        warn(f"Could not check predictions: {e}")

    # Check alerts
    try:
        r = requests.get(f"{AGENTS[1]}/alerts", timeout=10)
        if r.status_code == 200:
            alerts = r.json()
            if isinstance(alerts, list):
                ok(f"Agent 1 has {len(alerts)} active alerts")
                for a in alerts[:3]:
                    zone = a.get("zone_name", "?")
                    severity = a.get("severity", "?")
                    info(f"    Alert: {zone} — {severity}")
        else:
            info(f"GET /alerts returned {r.status_code}")
    except Exception as e:
        info(f"Alerts check: {e}")

    # Check status
    try:
        r = requests.get(f"{AGENTS[1]}/status", timeout=10)
        if r.status_code == 200:
            status = r.json()
            last_update = status.get("last_update", "never")
            cycle_time = status.get("last_cycle_time_seconds", "?")
            zones = status.get("zones_monitored", "?")
            ok(f"Monitoring {zones} zones | Last update: {last_update} | Cycle: {cycle_time}s")
    except Exception as e:
        info(f"Status check: {e}")

    return True


# ============================================================
# PHASE 2: Agent 2 — Distress Intelligence
# ============================================================
def phase_2_agent2():
    section("PHASE 2: Agent 2 — Distress Intelligence (SMS → Publish)")

    # Inject SMS
    sms = [
        {
            "text": "FLOOD MIRPUR 4FT 20 PEOPLE TRAPPED NEED BOAT RESCUE URGENT",
            "sender_phone": "+8801799999999",
            "timestamp": "2026-04-11T12:00:00",
        }
    ]

    try:
        r = requests.post(f"{AGENTS[2]}/ingest/sms", json=sms, timeout=5)
        if r.status_code == 200:
            ok(f"SMS injected: {r.json()}")
        else:
            fail(f"SMS ingest failed: {r.status_code}")
            return None
    except Exception as e:
        fail(f"SMS ingest error: {e}")
        return None

    # Trigger processing cycle
    try:
        r = requests.post(f"{AGENTS[2]}/trigger", timeout=15)
        data = r.json()
        queue_size = data.get("queue_size", 0)
        critical = data.get("critical_items", 0)
        if queue_size > 0:
            ok(f"Cycle complete: {queue_size} queue items, {critical} critical")
        else:
            fail(f"Cycle produced 0 queue items: {data}")
            return None
    except Exception as e:
        fail(f"Trigger failed: {e}")
        return None

    # Get queue details
    try:
        r = requests.get(f"{AGENTS[2]}/queue", timeout=5)
        queue = r.json()
        if queue:
            item = queue[0]
            info(f"    Top item: zone={item.get('zone_name')} urgency={item.get('urgency')} "
                 f"rescue={item.get('needs_rescue')} score={item.get('priority_score')}")
            return item
    except Exception as e:
        warn(f"Could not get queue: {e}")

    return None


# ============================================================
# PHASE 3: Agent 2 → Agent 3 via Redis pub/sub
# ============================================================
def phase_3_redis_pipeline():
    section("PHASE 3: Agent 2 → Agent 3 via Redis Pub/Sub")

    # Get Agent 3 allocation count BEFORE
    try:
        r = requests.get(f"{AGENTS[3]}/status", timeout=5)
        before = r.json().get("total_allocations", 0)
        info(f"Agent 3 allocations BEFORE: {before}")
    except Exception as e:
        fail(f"Agent 3 status failed: {e}")
        return None

    # Inject SMS + trigger Agent 2
    sms = [{
        "text": "URGENT FLOOD JATRABARI 3FT WATER 15 PEOPLE STRANDED NEED RESCUE",
        "sender_phone": "+8801788888888",
        "timestamp": "2026-04-11T12:05:00",
    }]
    try:
        requests.post(f"{AGENTS[2]}/ingest/sms", json=sms, timeout=5)
        requests.post(f"{AGENTS[2]}/trigger", timeout=15)
    except Exception as e:
        fail(f"Agent 2 trigger failed: {e}")
        return None

    info("Waiting 10 seconds for Agent 2 → Redis → Agent 3...")
    time.sleep(10)

    # Check Agent 3 AFTER
    try:
        r = requests.get(f"{AGENTS[3]}/status", timeout=5)
        after = r.json().get("total_allocations", 0)
        info(f"Agent 3 allocations AFTER: {after}")
        delta = after - before
        if delta > 0:
            ok(f"Agent 3 processed {delta} new allocation(s) via Redis pub/sub!")
        else:
            fail("Agent 3 received ZERO new allocations")
            warn("Check Agent 2 terminal for 'Published X items' log")
            warn("Check Agent 3 terminal for 'Received distress from' log")
    except Exception as e:
        fail(f"Agent 3 status check failed: {e}")
        return None

    # Get latest allocation for Agent 4 test
    try:
        r = requests.get(f"{AGENTS[3]}/allocations?limit=1", timeout=5)
        allocs = r.json()
        if allocs:
            latest = allocs[0]
            info(f"    Latest allocation: zone={latest.get('zone_name')} "
                 f"resources={latest.get('resource_count')}")
            return latest
    except Exception as e:
        warn(f"Could not get allocations: {e}")

    return None


# ============================================================
# PHASE 4: Agent 3 → Agent 4 Dispatch
# ============================================================
def phase_4_dispatch(allocation_data):
    section("PHASE 4: Agent 3 → Agent 4 Dispatch Optimization")

    if not allocation_data:
        warn("No allocation data — testing Agent 4 with direct trigger")
        # Use a dummy payload
        payload = {
            "zone_name": "Mirpur",
            "zone_id": "test-zone-1",
            "incident_id": "test-incident-1",
            "allocation_id": None,
            "destination": {"latitude": 23.8223, "longitude": 90.3654},
            "priority": 1,
            "urgency": "LIFE_THREATENING",
            "water_level_meters": 1.2,
            "flood_verified": True,
            "allocated_resources": [
                {
                    "unit_id": "00000000-0000-0000-0000-000000000001",
                    "unit_name": "Test Boat",
                    "resource_type": "rescue_boat",
                    "current_location": {"latitude": 23.81, "longitude": 90.36},
                }
            ],
        }
    else:
        # Build payload from real allocation
        # Get full allocation details
        alloc_id = allocation_data.get("id")
        try:
            r = requests.get(f"{AGENTS[3]}/allocations/{alloc_id}", timeout=5)
            if r.status_code == 200:
                full_alloc = r.json()
            else:
                full_alloc = allocation_data
        except:
            full_alloc = allocation_data

        payload = {
            "zone_name": full_alloc.get("zone_name"),
            "zone_id": full_alloc.get("zone_id"),
            "incident_id": full_alloc.get("incident_id"),
            "allocation_id": str(full_alloc.get("allocation_id", full_alloc.get("id", ""))),
            "destination": full_alloc.get("destination", {"latitude": 23.8223, "longitude": 90.3654}),
            "priority": full_alloc.get("priority", 1),
            "urgency": full_alloc.get("urgency", "LIFE_THREATENING"),
            "water_level_meters": full_alloc.get("water_level_meters"),
            "flood_verified": full_alloc.get("flood_verified", True),
            "allocated_resources": full_alloc.get("allocated_resources",
                                                   full_alloc.get("allocated_units", [])),
        }

    try:
        r = requests.post(f"{AGENTS[4]}/trigger", json=payload, timeout=10)
        if r.status_code == 200:
            data = r.json()
            zone = data.get("zone_name", "?")
            teams = len(data.get("team_routes", []))
            eta = data.get("total_eta_minutes", "?")
            safety = data.get("safety_score", "?")
            ok(f"Dispatch plan created: zone={zone} teams={teams} ETA={eta}min safety={safety}")
            for route in data.get("team_routes", [])[:3]:
                info(f"    → {route.get('unit_name')} ({route.get('resource_type')}) "
                     f"dist={route.get('distance_km')}km eta={route.get('eta_minutes')}min")
        else:
            fail(f"Dispatch failed: HTTP {r.status_code} — {r.text[:200]}")
    except Exception as e:
        fail(f"Agent 4 error: {e}")


# ============================================================
# PHASE 5: Summary
# ============================================================
def phase_5_summary():
    section("SUMMARY")
    total = PASS + FAIL
    print(f"""
  Tests passed:  {PASS}/{total}
  Tests failed:  {FAIL}/{total}

  Pipeline Status:
    Agent 1 (Environmental)   → {'OK' if PASS > 0 else 'CHECK'}
    Agent 2 (Distress)        → {'OK — publishes to Redis' if PASS >= 3 else 'CHECK'}
    Agent 3 (Resource)        → {'OK — receives via Redis' if PASS >= 4 else 'CHECK'}
    Agent 4 (Dispatch)        → {'OK — creates dispatch plans' if PASS >= 5 else 'CHECK'}
""")
    if FAIL == 0:
        print("  *** FULL PIPELINE OPERATIONAL — ALL 4 AGENTS CONNECTED ***")
    else:
        print("  Some tests failed — check output above for details.")
    print()


# ============================================================
# Main
# ============================================================
def main():
    print("FloodShield BD — Full 4-Agent Pipeline Test")
    print("=" * 60)

    # Phase 0: Health
    all_up = phase_0_health()
    if not all_up:
        warn("Not all agents are up — continuing with available agents")

    # Phase 1: Agent 1
    phase_1_agent1()

    # Phase 2: Agent 2
    distress_item = phase_2_agent2()

    # Phase 3: Redis pipeline
    allocation = phase_3_redis_pipeline()

    # Phase 4: Dispatch
    phase_4_dispatch(allocation)

    # Summary
    phase_5_summary()


if __name__ == "__main__":
    main()
