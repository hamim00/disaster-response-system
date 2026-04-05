"""
Agent 1 → Agent 2 Bridge
==========================
Reads Agent 1's actual output files (from your previous test runs)
and feeds them into Agent 2's API.

This is how the two agents connect:
  1. Agent 1's flood detections → Agent 2's cross-reference engine
  2. Agent 1's social media results → Agent 2's social media channel
  3. Agent 1's satellite predictions → Agent 2's population overlay (Channel 4)

Usage:
  python connect_agent1.py                          # auto-detect Agent 1 outputs
  python connect_agent1.py --agent1-output ../agent_1_environmental/output
  python connect_agent1.py --sylhet                 # load Sylhet 2024 test scenario
  python connect_agent1.py --all-scenarios           # load all 5 historical scenarios

Author: Mahmudul Hasan
"""

import argparse
import json
import os
import sys
import requests
from datetime import datetime, timezone
from pathlib import Path

AGENT2_URL = "http://localhost:8002"

# =====================================================================
# Your ACTUAL Agent 1 test scenarios (from test_unified_pipeline.py)
# These are the real results from your previous session
# =====================================================================

HISTORICAL_SCENARIOS = {
    "sylhet_2024": {
        "name": "Sylhet 2024 Monsoon",
        "zone_id": "sylhet",
        "lat": 24.8949, "lon": 91.8687,
        "flood_pct": 37.0,
        "flood_depth_m": 1.5,
        "risk_score": 0.78,
        "severity": "high",
        "timestamp": "2024-09-15T14:00:00",
        "description": "SAR detected 37% flooding, 36.9 km² affected",
    },
    "sunamganj_2022": {
        "name": "Sunamganj 2022 Historic Flood",
        "zone_id": "sunamganj",
        "lat": 25.0715, "lon": 91.3950,
        "flood_pct": 55.0,
        "flood_depth_m": 2.3,
        "risk_score": 0.91,
        "severity": "critical",
        "timestamp": "2022-06-17T10:00:00",
        "description": "Historic flooding — 55% area submerged, depth >2m",
    },
    "mirpur_2024": {
        "name": "Mirpur 2024 Monsoon",
        "zone_id": "mirpur",
        "lat": 23.8223, "lon": 90.3654,
        "flood_pct": 28.0,
        "flood_depth_m": 1.2,
        "risk_score": 0.65,
        "severity": "high",
        "timestamp": "2024-08-20T14:00:00",
        "description": "Monsoon waterlogging in low-lying areas",
    },
    "jatrabari_2024": {
        "name": "Jatrabari 2024 Monsoon",
        "zone_id": "jatrabari",
        "lat": 23.7104, "lon": 90.4348,
        "flood_pct": 42.0,
        "flood_depth_m": 1.8,
        "risk_score": 0.82,
        "severity": "critical",
        "timestamp": "2024-08-20T14:00:00",
        "description": "Heavy waterlogging, Kadamtali area submerged",
    },
    "demra_2024": {
        "name": "Demra 2024 Monsoon",
        "zone_id": "demra",
        "lat": 23.7225, "lon": 90.4968,
        "flood_pct": 35.0,
        "flood_depth_m": 1.4,
        "risk_score": 0.70,
        "severity": "high",
        "timestamp": "2024-08-20T14:00:00",
        "description": "Industrial area flooding",
    },
}


def send_flood_data_for_crossref(scenarios: dict):
    """
    Send Agent 1 flood data to Agent 2 for cross-referencing.
    This is what Agent 2 uses to VERIFY distress reports.
    When someone calls 999 saying "Mirpur e pani", Agent 2 checks:
    does Agent 1 actually see flooding in Mirpur?
    """
    flood_data = {}
    for key, s in scenarios.items():
        flood_data[s["zone_id"]] = {
            "risk_score": s["risk_score"],
            "severity": s["severity"],
            "flood_pct": s["flood_pct"],
            "flood_depth_m": s["flood_depth_m"],
        }

    print(f"\n📡 Sending Agent 1 flood data for cross-referencing ({len(flood_data)} zones)...")
    try:
        resp = requests.post(f"{AGENT2_URL}/flood_data", json=flood_data)
        print(f"   ✅ {resp.json()['message']}")
        return True
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False


def send_flood_alerts_for_population(scenarios: dict):
    """
    Send Agent 1 flood alerts to Agent 2's Channel 4 (Satellite+Population).
    Channel 4 takes the flood extent and adds population overlay from BBS census.
    
    THIS IS WHY CHANNEL 4 EXISTS:
    Agent 1 says: "Mirpur is 37% flooded, depth 1.5m"
    Channel 4 adds: "That means 618,750 people are in the flood zone,
                     ~216,000 potentially stranded, need 4,331 rescue boats"
    
    Agent 1 doesn't know about population. Channel 4 bridges that gap.
    """
    alerts = []
    for key, s in scenarios.items():
        alerts.append({
            "zone_id": s["zone_id"],
            "flood_pct": s["flood_pct"],
            "flood_depth_m": s["flood_depth_m"],
            "risk_score": s["risk_score"],
            "severity": s["severity"],
            "timestamp": s["timestamp"],
        })

    print(f"\n🛰️  Sending flood alerts for population estimation ({len(alerts)} zones)...")
    try:
        resp = requests.post(f"{AGENT2_URL}/ingest/flood_alerts", json=alerts)
        print(f"   ✅ {resp.json()['message']}")
        return True
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False


def send_agent1_social_media_results(output_dir: str):
    """
    Read Agent 1's social media flood detection results
    (from sample_dataset_generator + OpenAI processor)
    and feed them to Agent 2 as social media posts.
    """
    results_file = os.path.join(output_dir, "flood_detection_results_20251210_163859.json")
    if not os.path.exists(results_file):
        print(f"\n📱 Social media results not found at {results_file}")
        print("   (Run Agent 1's social media detection first)")
        return False

    with open(results_file, encoding="utf-8") as f:  # FIX: added encoding="utf-8"
        data = json.load(f)

    # Convert Agent 1's detection_results to Agent 2's social media post format
    posts = []
    for result in data.get("detection_results", []):
        if result.get("is_flood_related"):
            posts.append({
                "id": result["tweet_id"],
                "platform": "twitter",
                "text": result["original_text"],
                "author": f"user_{result['tweet_id'][-6:]}",
                "created_at": result.get("processed_at", datetime.now(timezone.utc).isoformat()),  # FIX: utcnow() → now(timezone.utc)
                "engagement": int(result.get("confidence", 0.5) * 200),
                "has_media": False,
            })

    if not posts:
        print("\n📱 No flood-related posts found in Agent 1 results")
        return False

    print(f"\n📱 Sending {len(posts)} flood-related posts from Agent 1's NLP results...")
    try:
        resp = requests.post(f"{AGENT2_URL}/ingest/social_media", json=posts)
        print(f"   ✅ {resp.json()['message']}")
        return True
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False


def trigger_processing():
    """Trigger Agent 2's processing cycle."""
    print("\n▶  Triggering processing cycle...")
    try:
        resp = requests.post(f"{AGENT2_URL}/trigger")
        print(f"   ✅ {resp.json()['message']}")
        return True
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        return False


def show_queue():
    """Fetch and display the distress queue."""
    print("\n" + "=" * 70)
    print("  📋 DISTRESS QUEUE (output for Agent 3)")
    print("=" * 70)

    try:
        resp = requests.get(f"{AGENT2_URL}/queue")
        queue = resp.json()
    except Exception as e:
        print(f"   ❌ Could not fetch queue: {e}")
        return

    if not queue:
        print("   (empty — trigger processing first)")
        return

    for i, item in enumerate(queue):
        channel_icons = {
            "social_media": "📱",
            "sms_ussd": "💬",
            "emergency_hotline": "📞",
            "satellite_population": "🛰️",
        }
        icon = channel_icons.get(item["channel"], "📌")
        verified = "✅" if item.get("flood_verified") else "❓"
        score = int(item.get("priority_score", 0) * 100)
        zone = item.get("zone_name", "?")
        urgency = item.get("urgency", "?").upper()
        dtype = item.get("distress_type", "?").replace("_", " ")
        people = item.get("people_count")
        water = item.get("water_level_meters")
        rescue = "🆘" if item.get("needs_rescue") else ""
        resources = ", ".join(item.get("recommended_resources", []))

        print(f"\n  #{i+1} [{score:3d}] {icon} {urgency:8s} {zone} {verified}")
        print(f"       {dtype}{f' · {people} people' if people else ''}"
              f"{f' · water {water:.1f}m' if water else ''} {rescue}")
        print(f"       Resources: {resources}")

    print(f"\n  Total: {len(queue)} items")


def main():
    parser = argparse.ArgumentParser(description="Agent 1 → Agent 2 Bridge")
    parser.add_argument("--agent1-output", default=None,
                        help="Path to Agent 1's output directory")
    parser.add_argument("--sylhet", action="store_true",
                        help="Load Sylhet 2024 monsoon scenario")
    parser.add_argument("--sunamganj", action="store_true",
                        help="Load Sunamganj 2022 historic flood scenario")
    parser.add_argument("--all-scenarios", action="store_true",
                        help="Load all 5 historical flood scenarios")
    parser.add_argument("--url", default="http://localhost:8002",
                        help="Agent 2 API URL")
    parser.add_argument("--show-queue", action="store_true",
                        help="Show current queue and exit")
    args = parser.parse_args()

    global AGENT2_URL
    AGENT2_URL = args.url

    print("=" * 70)
    print("  AGENT 1 → AGENT 2 BRIDGE")
    print("  Connecting flood detection to distress intelligence")
    print("=" * 70)

    if args.show_queue:
        show_queue()
        return

    # Select scenarios
    if args.all_scenarios:
        scenarios = HISTORICAL_SCENARIOS
    elif args.sylhet:
        scenarios = {"sylhet_2024": HISTORICAL_SCENARIOS["sylhet_2024"]}
    elif args.sunamganj:
        scenarios = {"sunamganj_2022": HISTORICAL_SCENARIOS["sunamganj_2022"]}
    else:
        # Default: all Dhaka zones
        scenarios = {
            k: v for k, v in HISTORICAL_SCENARIOS.items()
            if k not in ("sylhet_2024", "sunamganj_2022")
        }

    print(f"\n  Scenarios: {', '.join(s['name'] for s in scenarios.values())}")
    print(f"  Agent 2: {AGENT2_URL}")

    # Step 1: Send flood data for cross-referencing
    send_flood_data_for_crossref(scenarios)

    # Step 2: Send flood alerts for population estimation (Channel 4)
    send_flood_alerts_for_population(scenarios)

    # Step 3: If Agent 1 output directory exists, send social media results
    output_dir = args.agent1_output
    if output_dir is None:
        # Try to auto-detect
        candidates = [
            "../agent_1_environmental/output",
            "../../agent_1_environmental/output",
            os.path.join(os.path.dirname(__file__), "..", "agent_1_environmental", "output"),
        ]
        for c in candidates:
            if os.path.isdir(c):
                output_dir = c
                break

    if output_dir and os.path.isdir(output_dir):
        send_agent1_social_media_results(output_dir)
    else:
        print(f"\n📱 Agent 1 output dir not found (social media results skipped)")
        print(f"   Pass --agent1-output <path> to specify location")

    # Step 4: Trigger processing
    import time
    trigger_processing()
    print("\n⏳ Waiting for processing...")
    time.sleep(3)

    # Step 5: Show queue
    show_queue()


if __name__ == "__main__":
    main()