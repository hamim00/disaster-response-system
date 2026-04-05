"""
Satellite + Population Overlay Distress Channel
=================================================
Proactive distress estimation using Agent 1's satellite flood data
combined with population density overlays.

KEY ADVANTAGE: This channel works even with ZERO communication
from victims. When Agent 1 detects flooding in a zone via SAR
imagery, this channel estimates the population at risk using
census-level ward data from Bangladesh Bureau of Statistics.

This enables pre-positioning of rescue resources BEFORE any
distress calls are received.

Author: Mahmudul Hasan
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from channels.base import BaseChannel
from models import (
    RawDistressReport, DistressChannel, DistressType,
    UrgencyLevel, DistressLocation,
)

logger = logging.getLogger(__name__)


# =====================================================================
# POPULATION DENSITY DATA (Bangladesh Bureau of Statistics)
# Ward-level estimates for monitored zones (2022 Census)
# =====================================================================

ZONE_POPULATION_DATA = {
    "mirpur": {
        "name": "Mirpur",
        "lat": 23.8223, "lon": 90.3654,
        "area_km2": 20.73,
        "population": 1_650_000,
        "density_per_km2": 79_594,
        "vulnerable_pct": 0.35,  # Slum areas, low-income housing
        "avg_floor_count": 3.5,  # Multi-story = more rooftop refuge
        "hospitals_nearby": 4,
        "fire_stations": 2,
    },
    "uttara": {
        "name": "Uttara",
        "lat": 23.8759, "lon": 90.3795,
        "area_km2": 18.48,
        "population": 750_000,
        "density_per_km2": 40_584,
        "vulnerable_pct": 0.20,
        "avg_floor_count": 5.0,
        "hospitals_nearby": 3,
        "fire_stations": 1,
    },
    "mohammadpur": {
        "name": "Mohammadpur",
        "lat": 23.7662, "lon": 90.3589,
        "area_km2": 12.24,
        "population": 620_000,
        "density_per_km2": 50_654,
        "vulnerable_pct": 0.30,
        "avg_floor_count": 4.0,
        "hospitals_nearby": 3,
        "fire_stations": 1,
    },
    "dhanmondi": {
        "name": "Dhanmondi",
        "lat": 23.7461, "lon": 90.3742,
        "area_km2": 7.85,
        "population": 300_000,
        "density_per_km2": 38_217,
        "vulnerable_pct": 0.10,
        "avg_floor_count": 6.0,
        "hospitals_nearby": 5,
        "fire_stations": 1,
    },
    "badda": {
        "name": "Badda",
        "lat": 23.7806, "lon": 90.4261,
        "area_km2": 15.60,
        "population": 520_000,
        "density_per_km2": 33_333,
        "vulnerable_pct": 0.25,
        "avg_floor_count": 4.5,
        "hospitals_nearby": 2,
        "fire_stations": 1,
    },
    "jatrabari": {
        "name": "Jatrabari",
        "lat": 23.7104, "lon": 90.4348,
        "area_km2": 14.42,
        "population": 850_000,
        "density_per_km2": 58_945,
        "vulnerable_pct": 0.40,
        "avg_floor_count": 3.0,
        "hospitals_nearby": 2,
        "fire_stations": 1,
    },
    "demra": {
        "name": "Demra",
        "lat": 23.7225, "lon": 90.4968,
        "area_km2": 25.91,
        "population": 430_000,
        "density_per_km2": 16_597,
        "vulnerable_pct": 0.45,
        "avg_floor_count": 2.5,
        "hospitals_nearby": 1,
        "fire_stations": 1,
    },
    "sylhet": {
        "name": "Sylhet City",
        "lat": 24.8949, "lon": 91.8687,
        "area_km2": 26.50,
        "population": 550_000,
        "density_per_km2": 20_755,
        "vulnerable_pct": 0.30,
        "avg_floor_count": 3.0,
        "hospitals_nearby": 3,
        "fire_stations": 2,
    },
    "sunamganj": {
        "name": "Sunamganj",
        "lat": 25.0715, "lon": 91.3950,
        "area_km2": 45.00,
        "population": 280_000,
        "density_per_km2": 6_222,
        "vulnerable_pct": 0.50,
        "avg_floor_count": 2.0,
        "hospitals_nearby": 1,
        "fire_stations": 1,
    },
}


def estimate_affected_population(
    zone_id: str,
    flood_pct: float,
    flood_depth_m: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Estimate population at risk from satellite flood data.
    
    Args:
        zone_id: Zone identifier
        flood_pct: Percentage of zone area flooded (0-100, from Agent 1 SAR)
        flood_depth_m: Estimated flood depth in meters (from Agent 1 depth CNN)
    
    Returns:
        Population impact estimate
    """
    zone = ZONE_POPULATION_DATA.get(zone_id)
    if not zone:
        return {"error": f"Unknown zone: {zone_id}"}
    
    flood_fraction = flood_pct / 100.0
    
    # Total people in flooded area (proportional to area)
    people_in_flood_zone = int(zone["population"] * flood_fraction)
    
    # Vulnerable subset (slums, ground-floor housing)
    vulnerable_people = int(people_in_flood_zone * zone["vulnerable_pct"])
    
    # Depth-based impact assessment
    if flood_depth_m is None:
        flood_depth_m = 0.5  # Conservative estimate
    
    # People who can't shelter in place (depth > ground floor threshold)
    if flood_depth_m >= 2.0:
        # Deep flooding — everyone below 2nd floor is at risk
        stranded_pct = 0.6
    elif flood_depth_m >= 1.0:
        # Moderate — ground floor residents at risk
        stranded_pct = 0.35
    elif flood_depth_m >= 0.5:
        # Shallow — mainly vulnerable populations
        stranded_pct = 0.15
    else:
        stranded_pct = 0.05
    
    estimated_stranded = int(people_in_flood_zone * stranded_pct)
    
    # Resource estimates
    rescue_boats_needed = max(1, estimated_stranded // 50)  # 1 boat per 50 people
    medical_teams_needed = max(1, estimated_stranded // 200)
    food_water_kits = people_in_flood_zone  # Everyone in flood zone needs supplies
    
    return {
        "zone_id": zone_id,
        "zone_name": zone["name"],
        "flood_pct": flood_pct,
        "flood_depth_m": flood_depth_m,
        "total_zone_population": zone["population"],
        "people_in_flood_zone": people_in_flood_zone,
        "vulnerable_people": vulnerable_people,
        "estimated_stranded": estimated_stranded,
        "resource_estimates": {
            "rescue_boats": rescue_boats_needed,
            "medical_teams": medical_teams_needed,
            "food_water_kits": food_water_kits,
        },
        "nearby_hospitals": zone["hospitals_nearby"],
        "fire_stations": zone["fire_stations"],
    }


# =====================================================================
# SATELLITE POPULATION CHANNEL
# =====================================================================

class SatellitePopulationChannel(BaseChannel):
    """
    Proactive distress channel using satellite data + population overlay.
    
    Unlike other channels, this doesn't wait for people to report.
    When Agent 1 publishes flood_alert on Redis, this channel
    automatically generates population-at-risk estimates.
    
    Input: Agent 1 flood alerts (via Redis or direct API call)
    Output: RawDistressReport with type=POPULATION_AT_RISK
    """
    
    def __init__(
        self,
        flood_alerts: Optional[List[Dict[str, Any]]] = None,
    ):
        super().__init__(channel_type=DistressChannel.SATELLITE_POPULATION)
        self._flood_alerts = flood_alerts or []
    
    def load_flood_alerts(self, alerts: List[Dict[str, Any]]):
        """
        Load flood alerts from Agent 1.
        
        Each alert should have:
        {
            "zone_id": "mirpur",
            "flood_pct": 37.5,
            "flood_depth_m": 1.2,
            "risk_score": 0.75,
            "severity": "high",
            "timestamp": "2024-09-15T14:00:00"
        }
        """
        self._flood_alerts = alerts
        logger.info(f"Loaded {len(alerts)} flood alerts from Agent 1")
    
    async def ingest(self) -> List[RawDistressReport]:
        """
        Generate population-at-risk distress reports from flood alerts.
        Only generates reports for zones with flood_pct >= 5%.
        """
        reports = []
        
        for alert in self._flood_alerts:
            try:
                zone_id = alert.get("zone_id", "").lower()
                flood_pct = alert.get("flood_pct", 0)
                flood_depth = alert.get("flood_depth_m")
                risk_score = alert.get("risk_score", 0)
                
                # Only process if meaningful flooding detected
                if flood_pct < 5.0:
                    continue
                
                # Estimate population impact
                impact = estimate_affected_population(
                    zone_id, flood_pct, flood_depth,
                )
                
                if "error" in impact:
                    logger.warning(f"Population estimate failed: {impact['error']}")
                    continue
                
                zone = ZONE_POPULATION_DATA.get(zone_id, {})
                
                # Urgency based on stranded count
                stranded = impact["estimated_stranded"]
                if stranded >= 1000 or (flood_depth and flood_depth >= 2.0):
                    urgency = UrgencyLevel.CRITICAL
                elif stranded >= 500 or (flood_depth and flood_depth >= 1.0):
                    urgency = UrgencyLevel.HIGH
                elif stranded >= 100:
                    urgency = UrgencyLevel.MEDIUM
                else:
                    urgency = UrgencyLevel.LOW
                
                # Build summary
                summary = (
                    f"SATELLITE ALERT: {impact['zone_name']} — "
                    f"{flood_pct:.1f}% flooded"
                    f"{f', depth ~{flood_depth:.1f}m' if flood_depth else ''}. "
                    f"Est. {impact['people_in_flood_zone']:,} people in flood zone, "
                    f"~{stranded:,} potentially stranded. "
                    f"Needs: {impact['resource_estimates']['rescue_boats']} boats, "
                    f"{impact['resource_estimates']['medical_teams']} medical teams."
                )
                
                location = DistressLocation(
                    latitude=zone.get("lat"),
                    longitude=zone.get("lon"),
                    zone_name=impact["zone_name"],
                    zone_id=zone_id,
                    confidence=0.85,  # Satellite is high confidence for area
                )
                
                report = RawDistressReport(
                    channel=DistressChannel.SATELLITE_POPULATION,
                    timestamp=datetime.fromisoformat(alert["timestamp"]) if "timestamp" in alert else datetime.utcnow(),
                    raw_content=summary,
                    language="en",
                    distress_type=DistressType.POPULATION_AT_RISK,
                    urgency=urgency,
                    location=location,
                    people_count=impact["people_in_flood_zone"],
                    needs_rescue=stranded >= 100,
                    water_level_meters=flood_depth,
                    nlp_confidence=0.85,  # Satellite-based = high confidence
                    channel_metadata={
                        "source": "agent1_satellite",
                        "flood_pct": flood_pct,
                        "risk_score": risk_score,
                        "population_estimate": impact,
                    },
                )
                reports.append(report)
                self.total_ingested += 1
                
            except Exception as e:
                logger.error(f"Error processing flood alert: {e}")
                self.total_errors += 1
        
        logger.info(
            f"Satellite+Population channel: {len(reports)} population-at-risk "
            f"reports from {len(self._flood_alerts)} flood alerts"
        )
        return reports
    
    async def health_check(self) -> bool:
        return True
