"""
FloodShield BD — Pipeline Diagnostic
Run from project root: python test_pipeline.py
Tests each agent and the full pipeline end-to-end.
"""
import requests
import json
import time
import sys

BASE = {
    1: "http://localhost:8001",
    2: "http://localhost:8002",
    3: "http://localhost:8003",
    4: "http://localhost:8004",
}

def test_agent(n, url):
    print(f"\n{'='*50}")
    print(f"AGENT {n}: {url}")
    print(f"{'='*50}")
    
    # Test root
    try:
        r = requests.get(f"{url}/", timeout=3)
        print(f"  /        -> {r.status_code}")
    except Exception as e:
        print(f"  /        -> FAILED: {e}")
        return False
    
    # Test health
    try:
        r = requests.get(f"{url}/health", timeout=3)
        print(f"  /health  -> {r.status_code}: {r.json()}")
    except Exception as e:
        print(f"  /health  -> FAILED: {e}")
    
    # Test CORS header
    try:
        r = requests.options(f"{url}/health", timeout=3, headers={
            "Origin": "http://127.0.0.1:5500",
            "Access-Control-Request-Method": "GET",
        })
        cors = r.headers.get("access-control-allow-origin", "MISSING")
        print(f"  CORS     -> {cors}")
        if cors == "MISSING":
            print(f"  *** CORS MIDDLEWARE NOT ACTIVE — dashboard cannot reach Agent {n} ***")
    except Exception as e:
        print(f"  CORS     -> FAILED: {e}")
    
    return True


def test_agent4_trigger():
    print(f"\n{'='*50}")
    print("AGENT 4: Direct trigger test")
    print(f"{'='*50}")
    
    payload = {
        "zone_name": "Mirpur",
        "zone_id": "mirpur",
        "incident_id": "diag_test_001",
        "allocation_id": "00000000-0000-0000-0000-000000000001",
        "destination": {"latitude": 23.8223, "longitude": 90.3654},
        "priority": 1,
        "urgency": "LIFE_THREATENING",
        "water_level_meters": 1.5,
        "flood_verified": True,
        "allocated_resources": [
            {
                "unit_id": "00000000-0000-0000-0000-000000000002",
                "unit_name": "BIWTA Rescue Boat 1",
                "resource_type": "rescue_boat",
                "current_location": {"latitude": 23.78, "longitude": 90.40},
            },
            {
                "unit_id": "00000000-0000-0000-0000-000000000003",
                "unit_name": "DMCH Medical Team",
                "resource_type": "medical_team",
                "current_location": {"latitude": 23.75, "longitude": 90.39},
            },
        ],
    }
    
    try:
        r = requests.post(f"{BASE[4]}/trigger", json=payload, timeout=10)
        print(f"  POST /trigger -> {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"  Zone:     {data.get('zone_name')}")
            print(f"  Teams:    {len(data.get('team_routes', []))}")
            print(f"  ETA:      {data.get('total_eta_minutes')} min")
            print(f"  Safety:   {data.get('route_safety_score')}")
            print(f"  *** AGENT 4 DISPATCH LOGIC WORKS ***")
            return True
        else:
            print(f"  Response: {r.text[:300]}")
            return False
    except Exception as e:
        print(f"  FAILED: {e}")
        return False


def test_full_pipeline():
    print(f"\n{'='*50}")
    print("FULL PIPELINE: SMS -> Agent 2 -> trigger -> Agent 3 -> Agent 4")
    print(f"{'='*50}")
    
    # 1. Send SMS to Agent 2
    sms = [{"text": "FLOOD MIRPUR 4FT 6 ROOFTOP", "sender_phone": "+8801700000000", "timestamp": "2026-04-10T12:00:00"}]
    try:
        r = requests.post(f"{BASE[2]}/ingest/sms", json=sms, timeout=5)
        print(f"  1. Ingest SMS     -> {r.status_code}: {r.json().get('message', '')}")
    except Exception as e:
        print(f"  1. Ingest SMS     -> FAILED: {e}")
        return
    
    # 2. Trigger processing
    try:
        r = requests.post(f"{BASE[2]}/trigger", json={}, timeout=5)
        print(f"  2. Trigger cycle  -> {r.status_code}")
    except Exception as e:
        print(f"  2. Trigger cycle  -> FAILED: {e}")
        return
    
    # 3. Wait and check
    print("  3. Waiting 4 seconds for pipeline...")
    time.sleep(4)
    
    # Check Agent 2 queue
    try:
        r = requests.get(f"{BASE[2]}/queue", timeout=3)
        q = r.json()
        print(f"  4. Agent 2 queue  -> {len(q)} items")
    except Exception as e:
        print(f"  4. Agent 2 queue  -> FAILED: {e}")
    
    # Check Agent 3 allocations
    try:
        r = requests.get(f"{BASE[3]}/allocations?limit=5", timeout=3)
        al = r.json()
        print(f"  5. Agent 3 allocs -> {len(al)} records")
        if al:
            latest = al[0]
            print(f"     Latest: zone={latest.get('zone_name')} time={latest.get('timestamp','?')[:19]}")
    except Exception as e:
        print(f"  5. Agent 3 allocs -> FAILED: {e}")
    
    # Check Agent 4 dispatches
    try:
        r = requests.get(f"{BASE[4]}/dispatches?limit=5", timeout=3)
        d = r.json()
        print(f"  6. Agent 4 disps  -> {len(d)} records")
        if d:
            latest = d[0]
            print(f"     Latest: zone={latest.get('zone_name')} eta={latest.get('total_eta_minutes')} min")
    except Exception as e:
        print(f"  6. Agent 4 disps  -> FAILED: {e}")


if __name__ == "__main__":
    print("FloodShield BD — Pipeline Diagnostic")
    print("=" * 50)
    
    results = {}
    for n in [1, 2, 3, 4]:
        results[n] = test_agent(n, BASE[n])
    
    print(f"\n\nSUMMARY:")
    for n, ok in results.items():
        print(f"  Agent {n}: {'UP' if ok else 'DOWN'}")
    
    if results[4]:
        test_agent4_trigger()
    
    if results[2] and results[3] and results[4]:
        test_full_pipeline()
    
    print("\nDone.")
