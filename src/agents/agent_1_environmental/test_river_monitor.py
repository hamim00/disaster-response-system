"""
Test River Monitor — standalone verification
=============================================
Tests the GloFAS river discharge monitor against the live Open-Meteo API.

Usage:
    cd src/agents/agent_1_environmental
    python test_river_monitor.py
"""

import asyncio
import sys
import os

# Add parent to path so imports work standalone
sys.path.insert(0, os.path.dirname(__file__))

from river_monitor import RiverMonitor, RIVER_ZONES


async def test_single_zone():
    """Test fetching discharge for a single zone (Sylhet)."""
    print("=" * 60)
    print("TEST 1: Single zone — Sylhet")
    print("=" * 60)

    rm = RiverMonitor({})
    try:
        result = await rm.check_river_discharge("sylhet", 24.8949, 91.8687)

        print(f"  Zone:        {result['zone_id']}")
        print(f"  River:       {result['river_name']}")
        print(f"  Current:     {result['current_discharge_m3s']} m³/s")
        print(f"  Forecast Pk: {result['forecast_peak_m3s']} m³/s on {result['forecast_peak_date']}")
        print(f"  Percentile:  p{result['percentile_rank']}")
        print(f"  Level:       {result['threshold_level']}")
        print(f"  Trend:       {result['trend']} ({result['days_rising']}d rising)")
        print(f"  Thresholds:  p50={result['p50']}, p90={result['p90']}, p95={result['p95']}")

        assert result['current_discharge_m3s'] >= 0, "Discharge must be non-negative"
        assert result['threshold_level'] in ['NORMAL', 'WATCH', 'WARNING', 'CRITICAL']
        assert result['trend'] in ['RISING', 'STABLE', 'FALLING']
        print("✅ Single zone test PASSED\n")
    finally:
        await rm._close_session()


async def test_all_zones():
    """Test fetching discharge for all 5 configured zones."""
    print("=" * 60)
    print("TEST 2: All zones")
    print("=" * 60)

    rm = RiverMonitor({})
    try:
        for rz in RIVER_ZONES:
            result = await rm.check_river_discharge(rz["zone_id"], rz["lat"], rz["lon"])
            print(
                f"  {rz['zone_id']:12s} | {result['current_discharge_m3s']:>10.1f} m³/s | "
                f"{result['threshold_level']:8s} | p{result['percentile_rank']:>5.1f} | "
                f"{result['trend']}"
            )
            assert result['current_discharge_m3s'] >= 0

        print("✅ All zones test PASSED\n")
    finally:
        await rm._close_session()


async def test_get_latest():
    """Test the get_latest_river_status accessor after polling."""
    print("=" * 60)
    print("TEST 3: get_latest_river_status()")
    print("=" * 60)

    rm = RiverMonitor({})
    try:
        # Manually poll to populate latest
        await rm._poll_all_zones()

        status = rm.get_latest_river_status()
        assert len(status) == len(RIVER_ZONES), (
            f"Expected {len(RIVER_ZONES)} zones, got {len(status)}"
        )
        for zone_id, data in status.items():
            print(f"  {zone_id}: {data['threshold_level']}")

        print("✅ get_latest_river_status test PASSED\n")
    finally:
        await rm._close_session()


async def main():
    print("\n🌊 River Monitor Test Suite\n")
    await test_single_zone()
    await test_all_zones()
    await test_get_latest()
    print("🎉 ALL TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
