"""
Emergency Hotline Distress Channel
====================================
Ingests distress reports from Bangladesh's 999 emergency system
and fire service hotlines.

In production: receives structured call records from 999 dispatch center.
For capstone: processes simulated call transcripts.

Author: Mahmudul Hasan
"""

import logging
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

from channels.base import BaseChannel
from models import (
    RawDistressReport, DistressChannel, DistressType,
    UrgencyLevel, DistressLocation,
)

logger = logging.getLogger(__name__)


# Zone lookup (shared with other channels)
ZONE_COORDS = {
    "mirpur":       {"lat": 23.8223, "lon": 90.3654, "name": "Mirpur"},
    "uttara":       {"lat": 23.8759, "lon": 90.3795, "name": "Uttara"},
    "mohammadpur":  {"lat": 23.7662, "lon": 90.3589, "name": "Mohammadpur"},
    "dhanmondi":    {"lat": 23.7461, "lon": 90.3742, "name": "Dhanmondi"},
    "badda":        {"lat": 23.7806, "lon": 90.4261, "name": "Badda"},
    "jatrabari":    {"lat": 23.7104, "lon": 90.4348, "name": "Jatrabari"},
    "demra":        {"lat": 23.7225, "lon": 90.4968, "name": "Demra"},
    "sylhet":       {"lat": 24.8949, "lon": 91.8687, "name": "Sylhet"},
    "sunamganj":    {"lat": 25.0715, "lon": 91.3950, "name": "Sunamganj"},
    # Sylhet Division upazilas
    "tahirpur":     {"lat": 25.11,   "lon": 91.42,   "name": "তাহিরপুর"},
    "companiganj":  {"lat": 25.0456, "lon": 91.5234, "name": "কোম্পানীগঞ্জ"},
    "chhatak":      {"lat": 25.168,  "lon": 91.655,  "name": "ছাতক"},
    "jamalganj":    {"lat": 25.15,   "lon": 91.25,   "name": "জামালগঞ্জ"},
    "dirai":        {"lat": 25.02,   "lon": 91.32,   "name": "দিরাই"},
    "dharmapasha":  {"lat": 25.10,   "lon": 91.28,   "name": "ধর্মপাশা"},
    "dowarabazar":  {"lat": 25.11,   "lon": 91.73,   "name": "দোয়ারাবাজার"},
    "bishwamvarpur":{"lat": 25.19,   "lon": 91.58,   "name": "বিশ্বম্ভরপুর"},
    "madhobpur":    {"lat": 24.75,   "lon": 91.82,   "name": "মাধবপুর"},
}

# Bengali zone name aliases for matching scenario location_description
ZONE_ALIASES_BN = {
    "সুনামগঞ্জ": "sunamganj", "সিলেট": "sylhet",
    "তাহিরপুর": "tahirpur", "কোম্পানীগঞ্জ": "companiganj",
    "ছাতক": "chhatak", "জামালগঞ্জ": "jamalganj",
    "দিরাই": "dirai", "ধর্মপাশা": "dharmapasha",
    "দোয়ারাবাজার": "dowarabazar", "বিশ্বম্ভরপুর": "bishwamvarpur",
    "মাধবপুর": "madhobpur", "আম্বরখানা": "sylhet", "টিলাগড়": "sylhet",
}


class EmergencyHotlineChannel(BaseChannel):
    """
    Emergency hotline (999 / fire service) distress intake.
    
    In Bangladesh, 999 is the national emergency number.
    Call records include: caller location (cell tower triangulation),
    operator notes, urgency classification, and transcribed keywords.
    
    Simulated call records have this structure:
    {
        "call_id": "999-2024-001234",
        "timestamp": "2024-09-15T14:30:00",
        "zone": "mirpur",
        "caller_phone_hash": "abc123",
        "operator_notes": "Caller reports family trapped on rooftop...",
        "urgency": "critical",
        "people_count": 5,
        "situation": "stranded",
        "water_level_ft": 6,
        "call_duration_seconds": 120
    }
    """
    
    def __init__(self, simulated_calls: Optional[List[Dict[str, Any]]] = None):
        super().__init__(channel_type=DistressChannel.EMERGENCY_HOTLINE)
        self._simulated_calls = simulated_calls or []
    
    def load_simulated_calls(self, calls: List[Dict[str, Any]]):
        """Load simulated 999 call records."""
        self._simulated_calls = calls
        logger.info(f"Loaded {len(calls)} simulated 999 call records")
    
    def _parse_call_record(self, call: Dict[str, Any]) -> Optional[RawDistressReport]:
        """Parse a single 999 call record."""
        
        # Zone resolution — try English key first, then Bengali alias matching
        zone_key = call.get("zone", "").lower()
        zone_info = ZONE_COORDS.get(zone_key)
        
        # If direct lookup fails, try matching Bengali zone names from location description
        if not zone_info:
            zone_text = call.get("zone", "")
            loc_desc = call.get("location_description", zone_text)
            for bn_name, en_key in ZONE_ALIASES_BN.items():
                if bn_name in loc_desc or bn_name in zone_text:
                    zone_info = ZONE_COORDS.get(en_key)
                    zone_key = en_key
                    break
        
        # Use scenario pinpoint coordinates if available
        scenario_lat = call.get("scenario_lat")
        scenario_lng = call.get("scenario_lng")
        loc_desc = call.get("location_description", call.get("zone", ""))
        
        # Water level (call records typically report in feet)
        water_ft = call.get("water_level_ft")
        water_m = round(water_ft * 0.3048, 2) if water_ft else None
        
        # Urgency mapping
        urgency_map = {
            "low": UrgencyLevel.LOW,
            "medium": UrgencyLevel.MEDIUM,
            "high": UrgencyLevel.HIGH,
            "critical": UrgencyLevel.CRITICAL,
        }
        urgency = urgency_map.get(
            call.get("urgency", "medium").lower(),
            UrgencyLevel.MEDIUM,
        )
        
        # Situation mapping
        situation_map = {
            "stranded": DistressType.STRANDED,
            "trapped": DistressType.STRANDED,
            "medical": DistressType.MEDICAL_EMERGENCY,
            "rising": DistressType.WATER_RISING,
            "evacuate": DistressType.EVACUATION_NEEDED,
            "collapse": DistressType.STRUCTURAL_COLLAPSE,
            "missing": DistressType.MISSING_PERSON,
            "supplies": DistressType.SUPPLIES_NEEDED,
        }
        dtype = situation_map.get(
            call.get("situation", "").lower(),
            DistressType.GENERAL_FLOOD_REPORT,
        )
        
        # Operator notes as raw content
        notes = call.get("operator_notes", call.get("transcript", ""))
        if not notes:
            notes = f"999 call: {dtype.value} in {zone_key}, urgency={urgency.value}"
        
        if scenario_lat and scenario_lng:
            location = DistressLocation(
                latitude=scenario_lat,
                longitude=scenario_lng,
                zone_name=zone_info["name"] if zone_info else loc_desc or zone_key,
                zone_id=zone_key if zone_info else None,
                address_text=loc_desc or call.get("address"),
                confidence=0.95,
            )
        else:
            location = DistressLocation(
                latitude=zone_info["lat"] if zone_info else None,
                longitude=zone_info["lon"] if zone_info else None,
                zone_name=zone_info["name"] if zone_info else zone_key,
                zone_id=zone_key if zone_info else None,
                address_text=call.get("address"),
                # Cell tower triangulation gives moderate accuracy
                confidence=0.7 if zone_info else 0.4,
            )
        
        needs_rescue = dtype in (
            DistressType.STRANDED,
            DistressType.MEDICAL_EMERGENCY,
            DistressType.STRUCTURAL_COLLAPSE,
        )
        
        return RawDistressReport(
            channel=DistressChannel.EMERGENCY_HOTLINE,
            timestamp=datetime.fromisoformat(call["timestamp"]) if "timestamp" in call else datetime.utcnow(),
            raw_content=notes,
            language="bn",
            distress_type=dtype,
            urgency=urgency,
            location=location,
            people_count=call.get("people_count"),
            needs_rescue=needs_rescue,
            water_level_meters=water_m,
            # 999 calls are high confidence — a human operator verified the report
            nlp_confidence=0.95,
            channel_metadata={
                "call_id": call.get("call_id", "unknown"),
                "operator_id": call.get("operator_id"),
                "call_duration_seconds": call.get("call_duration_seconds"),
                "caller_phone_hash": call.get("caller_phone_hash"),
            },
        )
    
    async def ingest(self) -> List[RawDistressReport]:
        """Ingest 999 call records."""
        reports = []
        for call in self._simulated_calls:
            try:
                report = self._parse_call_record(call)
                if report:
                    reports.append(report)
                    self.total_ingested += 1
            except Exception as e:
                logger.error(f"Error parsing 999 call record: {e}")
                self.total_errors += 1
        
        logger.info(f"Emergency hotline: {len(reports)} distress reports from {len(self._simulated_calls)} calls")
        return reports
    
    async def health_check(self) -> bool:
        return True
