"""
SMS / USSD Distress Channel
============================
Ingests distress reports via SMS and USSD (*999#) messages.

KEY ADVANTAGE: Works on 2G networks when mobile data is completely down.
During severe flooding, 2G cell towers survive longer than 3G/4G
infrastructure. USSD sessions require even less bandwidth than SMS.

In production: connects to a Telco SMS gateway (e.g., Banglalink/GP SMPP).
For capstone: processes simulated SMS messages.

STRUCTURED SMS FORMAT:
    FLOOD <ZONE> <WATER_LEVEL> <PEOPLE_COUNT> <SITUATION>
    Example: FLOOD MIRPUR 4FT 6 ROOFTOP

USSD FORMAT (menu-driven, no typing needed):
    *999# → 1. Report Flood → Select Zone → Select Severity → Confirm
    Output: USSD|MIRPUR|SEVERE|ROOFTOP|5_PEOPLE

Author: Mahmudul Hasan
"""

import logging
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import uuid4

from channels.base import BaseChannel
from models import (
    RawDistressReport, DistressChannel, DistressType,
    UrgencyLevel, DistressLocation,
)

logger = logging.getLogger(__name__)


# =====================================================================
# ZONE LOOKUP (same zones as social_media.py, coords for mapping)
# =====================================================================

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

# Aliases (people might type short forms in SMS)
ZONE_ALIASES = {
    "mir": "mirpur", "utt": "uttara", "moh": "mohammadpur",
    "dhan": "dhanmondi", "bad": "badda", "jat": "jatrabari",
    "dem": "demra", "syl": "sylhet", "sun": "sunamganj",
    "pallabi": "mirpur", "kazipara": "mirpur",
    "azampur": "uttara", "diabari": "uttara",
    "shyamoli": "mohammadpur", "adabor": "mohammadpur",
    "gulshan": "badda", "baridhara": "badda",
    # Sylhet Division Bengali aliases
    "সুনামগঞ্জ": "sunamganj", "সিলেট": "sylhet",
    "তাহিরপুর": "tahirpur", "কোম্পানীগঞ্জ": "companiganj",
    "ছাতক": "chhatak", "জামালগঞ্জ": "jamalganj",
    "দিরাই": "dirai", "ধর্মপাশা": "dharmapasha",
    "দোয়ারাবাজার": "dowarabazar", "বিশ্বম্ভরপুর": "bishwamvarpur",
    "মাধবপুর": "madhobpur",
    # Banglish aliases for Sylhet
    "sunamgonj": "sunamganj", "sunamgonj": "sunamganj",
    "companigonj": "companiganj", "kompaniganj": "companiganj",
    "tahirpur": "tahirpur", "chatok": "chhatak",
    "jamalgonj": "jamalganj", "dharmpasha": "dharmapasha",
    "ambarkhana": "sylhet", "tilagar": "sylhet",
    "আম্বরখানা": "sylhet", "টিলাগড়": "sylhet",
    "সদর": "sunamganj",
}

# Situation codes
SITUATION_MAP = {
    "ROOFTOP": DistressType.STRANDED,
    "TRAPPED": DistressType.STRANDED,
    "MEDICAL": DistressType.MEDICAL_EMERGENCY,
    "RISING": DistressType.WATER_RISING,
    "EVACUATE": DistressType.EVACUATION_NEEDED,
    "FOOD": DistressType.SUPPLIES_NEEDED,
    "MISSING": DistressType.MISSING_PERSON,
    "COLLAPSE": DistressType.STRUCTURAL_COLLAPSE,
}


def resolve_zone(zone_text: str) -> Optional[Dict[str, Any]]:
    """Resolve a zone name/alias to zone info."""
    key = zone_text.lower().strip()
    if key in ZONE_COORDS:
        return {"zone_id": key, **ZONE_COORDS[key]}
    if key in ZONE_ALIASES:
        resolved = ZONE_ALIASES[key]
        return {"zone_id": resolved, **ZONE_COORDS[resolved]}
    return None


def parse_water_level_sms(text: str) -> Optional[float]:
    """Parse water level from SMS shorthand. Returns meters."""
    text = text.upper().strip()
    # Patterns: 4FT, 1.5M, 2M, KNEE, WAIST, CHEST, NECK
    match = re.match(r"^(\d+(?:\.\d+)?)\s*FT$", text)
    if match:
        return round(float(match.group(1)) * 0.3048, 2)
    match = re.match(r"^(\d+(?:\.\d+)?)\s*M$", text)
    if match:
        return float(match.group(1))
    level_map = {"KNEE": 0.5, "WAIST": 1.0, "CHEST": 1.3, "NECK": 1.5}
    if text in level_map:
        return level_map[text]
    return None


# =====================================================================
# STRUCTURED SMS PARSER
# =====================================================================

def parse_structured_sms(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse a structured SMS message.
    Format: FLOOD <ZONE> <WATER_LEVEL> <PEOPLE_COUNT> <SITUATION>
    Example: FLOOD MIRPUR 4FT 6 ROOFTOP
    
    Returns None if not a structured flood SMS.
    """
    text = text.strip().upper()
    if not text.startswith("FLOOD"):
        return None
    
    parts = text.split()
    if len(parts) < 3:
        return None
    
    result: Dict[str, Any] = {
        "zone_text": parts[1] if len(parts) > 1 else None,
        "water_level_text": None,
        "people_count": None,
        "situation": None,
    }
    
    # Parse remaining parts flexibly
    for part in parts[2:]:
        # Water level?
        wl = parse_water_level_sms(part)
        if wl is not None:
            result["water_level_text"] = part
            result["water_level_m"] = wl
            continue
        # People count?
        if part.isdigit():
            result["people_count"] = int(part)
            continue
        # Situation code?
        if part in SITUATION_MAP:
            result["situation"] = part
            continue
    
    return result


# =====================================================================
# USSD PARSER
# =====================================================================

def parse_ussd_response(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse a USSD response string.
    Format: USSD|<ZONE>|<SEVERITY>|<SITUATION>|<PEOPLE>_PEOPLE
    Example: USSD|MIRPUR|SEVERE|ROOFTOP|5_PEOPLE
    """
    text = text.strip().upper()
    if not text.startswith("USSD"):
        return None
    
    parts = text.split("|")
    if len(parts) < 3:
        return None
    
    result: Dict[str, Any] = {
        "zone_text": parts[1] if len(parts) > 1 else None,
        "severity": parts[2] if len(parts) > 2 else "MODERATE",
        "situation": parts[3] if len(parts) > 3 else None,
        "people_count": None,
    }
    
    # Parse people count from "5_PEOPLE"
    if len(parts) > 4:
        match = re.match(r"(\d+)_PEOPLE", parts[4])
        if match:
            result["people_count"] = int(match.group(1))
    
    # Map severity to water level estimate
    severity_to_depth = {
        "MINOR": 0.3, "MODERATE": 0.7, "SEVERE": 1.2, "CRITICAL": 2.0,
    }
    result["water_level_m"] = severity_to_depth.get(result["severity"], 0.5)
    
    return result


# =====================================================================
# FREE-TEXT SMS PARSER (fallback)
# =====================================================================

def parse_freetext_sms(text: str) -> Dict[str, Any]:
    """
    Parse unstructured SMS using keyword extraction.
    Handles Bengali, English, and Banglish mix.
    """
    result: Dict[str, Any] = {
        "zone_text": None,
        "water_level_m": None,
        "people_count": None,
        "situation": None,
        "needs_rescue": False,
    }
    
    text_lower = text.lower()
    
    # Zone detection
    for alias, zone_id in ZONE_ALIASES.items():
        if alias in text_lower:
            result["zone_text"] = zone_id.upper()
            break
    if result["zone_text"] is None:
        for zone_id in ZONE_COORDS:
            if zone_id in text_lower:
                result["zone_text"] = zone_id.upper()
                break
    
    # Water level
    for pattern_text in ["(\\d+)\\s*ft", "(\\d+)\\s*feet", "(\\d+)\\s*ফুট"]:
        match = re.search(pattern_text, text_lower)
        if match:
            result["water_level_m"] = round(float(match.group(1)) * 0.3048, 2)
            break
    
    # People count
    match = re.search(r"(\d+)\s*(?:people|jon|জন|family|poribar)", text_lower)
    if match:
        result["people_count"] = int(match.group(1))
    
    # Rescue keywords
    rescue_words = ["help", "rescue", "trapped", "stuck", "save",
                    "bachao", "বাঁচাও", "উদ্ধার", "আটকে", "atke"]
    result["needs_rescue"] = any(w in text_lower or w in text for w in rescue_words)
    
    if result["needs_rescue"]:
        result["situation"] = "TRAPPED"
    
    return result


# =====================================================================
# SMS/USSD CHANNEL
# =====================================================================

class SMSUSSDChannel(BaseChannel):
    """
    SMS and USSD distress intake channel.
    
    Supports three message formats:
    1. Structured SMS: FLOOD MIRPUR 4FT 6 ROOFTOP
    2. USSD response: USSD|MIRPUR|SEVERE|ROOFTOP|5_PEOPLE
    3. Free-text SMS: "Pani 3ft Mirpur sec 12 help 4 jon"
    
    For the capstone, messages are simulated. In production,
    this connects to a Telco SMPP gateway.
    """
    
    def __init__(self, simulated_messages: Optional[List[Dict[str, Any]]] = None):
        super().__init__(channel_type=DistressChannel.SMS_USSD)
        self._simulated_messages = simulated_messages or []
    
    def load_simulated_messages(self, messages: List[Dict[str, Any]]):
        """Load simulated SMS/USSD messages for testing."""
        self._simulated_messages = messages
        logger.info(f"Loaded {len(messages)} simulated SMS/USSD messages")
    
    def _parse_single_message(self, msg: Dict[str, Any]) -> Optional[RawDistressReport]:
        """Parse a single SMS/USSD message into a distress report."""
        text = msg.get("text", msg.get("body", ""))
        if not text:
            return None
        
        text_upper = text.strip().upper()
        parsed = None
        msg_type = "free_text"
        
        # Try structured SMS first
        if text_upper.startswith("FLOOD"):
            parsed = parse_structured_sms(text)
            msg_type = "structured"
        
        # Try USSD
        elif text_upper.startswith("USSD"):
            parsed = parse_ussd_response(text)
            msg_type = "ussd"
        
        # Fallback to free-text
        if parsed is None:
            parsed = parse_freetext_sms(text)
            msg_type = "free_text"
        
        # Resolve zone from text
        zone_info = None
        if parsed.get("zone_text"):
            zone_info = resolve_zone(parsed["zone_text"])
        
        # If text-based zone detection failed, try matching Bengali location
        # description from scenario data against known Bengali zone aliases
        if not zone_info:
            loc_desc = msg.get("location_description", "")
            if loc_desc:
                for alias, zone_id in ZONE_ALIASES.items():
                    if alias in loc_desc:
                        zone_info = {"zone_id": zone_id, **ZONE_COORDS[zone_id]}
                        break
        
        # Use scenario pinpoint coordinates if available (highest accuracy)
        scenario_lat = msg.get("scenario_lat")
        scenario_lng = msg.get("scenario_lng")
        loc_desc = msg.get("location_description", "")
        
        if scenario_lat and scenario_lng:
            # Scenario provides exact coordinates — use them with high confidence
            location = DistressLocation(
                latitude=scenario_lat,
                longitude=scenario_lng,
                zone_name=zone_info["name"] if zone_info else loc_desc or None,
                zone_id=zone_info["zone_id"] if zone_info else None,
                address_text=loc_desc or parsed.get("zone_text"),
                confidence=0.95,
            )
        else:
            # Fall back to zone centroid
            location = DistressLocation(
                latitude=zone_info["lat"] if zone_info else None,
                longitude=zone_info["lon"] if zone_info else None,
                zone_name=zone_info["name"] if zone_info else None,
                zone_id=zone_info["zone_id"] if zone_info else None,
                address_text=parsed.get("zone_text"),
                confidence=0.9 if zone_info else 0.2,
            )
        
        water_level = parsed.get("water_level_m")
        people = parsed.get("people_count")
        rescue = parsed.get("needs_rescue", False)
        situation_code = parsed.get("situation")
        
        # Situation codes TRAPPED/ROOFTOP imply rescue need
        if situation_code in ("ROOFTOP", "TRAPPED", "MEDICAL"):
            rescue = True
        
        # Determine distress type
        if situation_code and situation_code in SITUATION_MAP:
            dtype = SITUATION_MAP[situation_code]
        elif rescue:
            dtype = DistressType.STRANDED
        elif water_level and water_level >= 0.5:
            dtype = DistressType.WATER_RISING
        else:
            dtype = DistressType.GENERAL_FLOOD_REPORT
        
        # Urgency
        if rescue and water_level and water_level >= 1.3:
            urgency = UrgencyLevel.CRITICAL
        elif rescue or (water_level and water_level >= 1.0):
            urgency = UrgencyLevel.HIGH
        elif water_level and water_level >= 0.5:
            urgency = UrgencyLevel.MEDIUM
        elif msg_type == "structured" or msg_type == "ussd":
            urgency = UrgencyLevel.MEDIUM  # They took effort to send structured msg
        else:
            urgency = UrgencyLevel.LOW
        
        return RawDistressReport(
            channel=DistressChannel.SMS_USSD,
            timestamp=datetime.fromisoformat(msg["timestamp"]) if "timestamp" in msg else datetime.utcnow(),
            raw_content=text,
            language="banglish",  # SMS is typically mixed
            distress_type=dtype,
            urgency=urgency,
            location=location,
            people_count=people,
            needs_rescue=rescue,
            water_level_meters=water_level,
            nlp_confidence=0.9 if msg_type == "structured" else (0.85 if msg_type == "ussd" else 0.6),
            channel_metadata={
                "message_type": msg_type,
                "sender_phone_hash": msg.get("phone_hash", "unknown"),
                "network_operator": msg.get("operator", "unknown"),
                "signal_strength": msg.get("signal", "2G"),
                "ussd_code": "*999#" if msg_type == "ussd" else None,
            },
        )
    
    async def ingest(self) -> List[RawDistressReport]:
        """Ingest and parse SMS/USSD messages."""
        reports = []
        for msg in self._simulated_messages:
            try:
                report = self._parse_single_message(msg)
                if report:
                    reports.append(report)
                    self.total_ingested += 1
            except Exception as e:
                logger.error(f"Error parsing SMS message: {e}")
                self.total_errors += 1
        
        logger.info(f"SMS/USSD channel: {len(reports)} distress reports from {len(self._simulated_messages)} messages")
        return reports
    
    async def health_check(self) -> bool:
        return True
