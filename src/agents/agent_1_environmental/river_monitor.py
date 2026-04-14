"""
River Discharge Monitor — GloFAS via Open-Meteo Flood API
==========================================================
Polls river discharge data for Bangladesh flood-prone zones every 30 minutes.
Uses dynamic percentile-based thresholds computed from 30-day history.

Data source: https://flood-api.open-meteo.com (free, no API key)
Resolution: ~5 km (GloFAS grid)

Author: Environmental Intelligence Team
Version: 1.0.0
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import aiohttp
import numpy as np

logger = logging.getLogger(__name__)

# =====================================================================
# MONITORING POINTS — 5 major flood-prone zones
# =====================================================================

RIVER_ZONES: List[Dict[str, Any]] = [
    {
        "zone_id": "sylhet",
        "zone_name": "Sylhet Division",
        "lat": 24.8949,
        "lon": 91.8687,
        "river": "Surma",
    },
    {
        "zone_id": "sunamganj",
        "zone_name": "Sunamganj",
        "lat": 25.0658,
        "lon": 91.3950,
        "river": "Surma/Kushiyara",
    },
    {
        "zone_id": "sirajganj",
        "zone_name": "Sirajganj",
        "lat": 24.4534,
        "lon": 89.7100,
        "river": "Brahmaputra/Jamuna",
    },
    {
        "zone_id": "kurigram",
        "zone_name": "Kurigram",
        "lat": 25.8072,
        "lon": 89.6362,
        "river": "Brahmaputra",
    },
    {
        "zone_id": "chandpur",
        "zone_name": "Chandpur",
        "lat": 23.2332,
        "lon": 90.6712,
        "river": "Meghna",
    },
]

API_BASE = "https://flood-api.open-meteo.com/v1/flood"
POLL_INTERVAL_SECONDS = 1800  # 30 minutes


class RiverMonitor:
    """
    Monitors river discharge via the Open-Meteo Flood API (GloFAS backend).

    Computes dynamic thresholds from the past-30-day distribution and
    classifies current discharge as NORMAL / WATCH / WARNING / CRITICAL.
    Detects multi-day rising trends for early warning.
    """

    def __init__(self, config: dict):
        self._config = config
        self._running = False
        self._latest: Dict[str, Dict[str, Any]] = {}
        self._session: Optional[aiohttp.ClientSession] = None
        logger.info("RiverMonitor initialized for %d zones", len(RIVER_ZONES))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start_monitoring(self):
        """Main loop — poll every 30 min. Runs as asyncio task."""
        self._running = True
        logger.info("[RIVER] Starting river discharge monitoring loop")

        while self._running:
            try:
                await self._poll_all_zones()
            except asyncio.CancelledError:
                logger.info("[RIVER] Monitoring cancelled")
                break
            except Exception as exc:
                logger.error("[RIVER] Poll error: %s", exc, exc_info=True)

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

        await self._close_session()

    def stop_monitoring(self):
        self._running = False
        logger.info("[RIVER] Stop requested")

    # ------------------------------------------------------------------
    # Core fetch + analyse
    # ------------------------------------------------------------------

    async def check_river_discharge(
        self, zone_id: str, lat: float, lon: float
    ) -> Dict[str, Any]:
        """Fetch and analyse discharge for one zone. Safe to call standalone."""
        session = await self._get_session()

        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "river_discharge",
            "past_days": 30,
            "forecast_days": 7,
        }

        async with session.get(API_BASE, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            data = await resp.json()

        times: List[str] = data.get("daily", {}).get("time", [])
        values: List[Optional[float]] = data.get("daily", {}).get(
            "river_discharge", []
        )

        if not times or not values:
            logger.warning("[RIVER] Empty response for zone %s", zone_id)
            return self._empty_result(zone_id)

        # Separate history (past_days) from forecast
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        historical_vals: List[float] = []
        forecast_vals: List[float] = []
        forecast_dates: List[str] = []

        for t, v in zip(times, values):
            if v is None:
                continue
            if t <= today_str:
                historical_vals.append(v)
            else:
                forecast_vals.append(v)
                forecast_dates.append(t)

        if not historical_vals:
            logger.warning("[RIVER] No historical data for %s", zone_id)
            return self._empty_result(zone_id)

        arr = np.array(historical_vals)
        current = historical_vals[-1]

        # Dynamic thresholds
        p50 = float(np.percentile(arr, 50))
        p75 = float(np.percentile(arr, 75))
        p90 = float(np.percentile(arr, 90))
        p95 = float(np.percentile(arr, 95))

        # Percentile rank of current value
        percentile_rank = float(np.searchsorted(np.sort(arr), current) / len(arr) * 100)

        # Threshold classification
        if current >= p95:
            level = "CRITICAL"
        elif current >= p90:
            level = "WARNING"
        elif current >= p75:
            level = "WATCH"
        else:
            level = "NORMAL"

        # Trend detection (3+ consecutive days rising)
        trend, days_rising = self._detect_trend(historical_vals)

        # Forecast peak
        if forecast_vals:
            peak_val = max(forecast_vals)
            peak_idx = forecast_vals.index(peak_val)
            peak_date = forecast_dates[peak_idx]
        else:
            peak_val = current
            peak_date = today_str

        # Find river name from RIVER_ZONES
        river_name = ""
        for rz in RIVER_ZONES:
            if rz["zone_id"] == zone_id:
                river_name = rz["river"]
                break

        result = {
            "zone_id": zone_id,
            "river_name": river_name,
            "current_discharge_m3s": round(current, 1),
            "forecast_peak_m3s": round(peak_val, 1),
            "forecast_peak_date": peak_date,
            "percentile_rank": round(percentile_rank, 1),
            "threshold_level": level,
            "trend": trend,
            "days_rising": days_rising,
            "p50": round(p50, 1),
            "p75": round(p75, 1),
            "p90": round(p90, 1),
            "p95": round(p95, 1),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        logger.info(
            "[RIVER] %s: %.1f m³/s (%s, p%.0f, %s %dd)",
            zone_id,
            current,
            level,
            percentile_rank,
            trend,
            days_rising,
        )

        return result

    # ------------------------------------------------------------------
    # Public accessor
    # ------------------------------------------------------------------

    def get_latest_river_status(self) -> Dict[str, Dict[str, Any]]:
        """Return latest state for all zones. Called by main.py for fusion."""
        return dict(self._latest)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _poll_all_zones(self):
        """Fetch discharge for every configured zone."""
        logger.info("[RIVER] Polling %d zones...", len(RIVER_ZONES))
        for rz in RIVER_ZONES:
            try:
                result = await self.check_river_discharge(
                    rz["zone_id"], rz["lat"], rz["lon"]
                )
                self._latest[rz["zone_id"]] = result
            except Exception as exc:
                logger.warning(
                    "[RIVER] Failed for %s: %s", rz["zone_id"], exc
                )
            # Small delay between requests to be polite to the API
            await asyncio.sleep(1.0)
        logger.info("[RIVER] Poll complete — %d zones updated", len(self._latest))

    @staticmethod
    def _detect_trend(values: List[float]) -> tuple:
        """Return (trend_str, days_rising)."""
        if len(values) < 2:
            return "STABLE", 0

        days_rising = 0
        for i in range(len(values) - 1, 0, -1):
            if values[i] > values[i - 1]:
                days_rising += 1
            else:
                break

        if days_rising >= 3:
            return "RISING", days_rising
        # Check falling
        days_falling = 0
        for i in range(len(values) - 1, 0, -1):
            if values[i] < values[i - 1]:
                days_falling += 1
            else:
                break
        if days_falling >= 3:
            return "FALLING", 0

        return "STABLE", days_rising

    def _empty_result(self, zone_id: str) -> Dict[str, Any]:
        river_name = ""
        for rz in RIVER_ZONES:
            if rz["zone_id"] == zone_id:
                river_name = rz["river"]
                break
        return {
            "zone_id": zone_id,
            "river_name": river_name,
            "current_discharge_m3s": 0.0,
            "forecast_peak_m3s": 0.0,
            "forecast_peak_date": "",
            "percentile_rank": 0.0,
            "threshold_level": "NORMAL",
            "trend": "STABLE",
            "days_rising": 0,
            "p50": 0.0,
            "p75": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _close_session(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
