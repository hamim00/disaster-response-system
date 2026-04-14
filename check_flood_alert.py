"""
Listen to Redis flood_alert channel and display incoming alerts.
Run in a separate terminal while Agent 1 is running.

Usage:
    python check_flood_alert.py
"""
import redis
import json

r = redis.Redis()
p = r.pubsub()
p.subscribe("flood_alert")
print("Listening on flood_alert... (waiting for next Agent 1 cycle)\n")

count = 0
for msg in p.listen():
    if msg["type"] != "message":
        continue

    data = json.loads(msg["data"])
    zone = data.get("zone_id", "?")
    risk = data.get("risk_score", 0)
    severity = data.get("severity", "?")
    sources = data.get("data_sources", {})

    print(f"--- {zone.upper()} ---")
    print(f"  Risk: {risk:.2f}  Severity: {severity}")

    if "weather" in sources:
        w = sources["weather"]
        print(f"  Weather: {w.get('rainfall_mm', 0)} mm, {w.get('alert_level', 'N/A')}")

    if "satellite" in sources:
        s = sources["satellite"]
        print(f"  Satellite: {s.get('flood_area_pct', 0):.1f}% flood, {s.get('risk_level', 'N/A')}")

    if "river_discharge" in sources:
        rd = sources["river_discharge"]
        print(
            f"  River: {rd.get('current_m3s', 0):.1f} m3/s, "
            f"{rd.get('threshold_level', 'N/A')}, "
            f"p{rd.get('percentile_rank', 0):.0f}, "
            f"{rd.get('trend', 'N/A')}"
        )
    else:
        print("  River: N/A (no GloFAS data for this zone)")

    print()
    count += 1

    # Stop after all 9 zones
    if count >= 9:
        print(f"Received {count} flood alerts. Done.")
        break
