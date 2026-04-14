"""
Social Media Distress Channel
==============================
Ingests distress reports from social media (Facebook, Twitter/X).
Uses the existing trilingual NLP pipeline (Bengali/English/Banglish)
originally built for Agent 1.

This channel works best in EARLY-STAGE flooding when mobile data
connectivity is still available. As connectivity degrades, SMS/USSD
and hotline channels take over.

Author: Mahmudul Hasan
"""

import json
import logging
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import uuid4

from channels.base import BaseChannel
from models import (
    RawDistressReport, DistressChannel, DistressType,
    UrgencyLevel, DistressLocation, SocialMediaDistress,
)

logger = logging.getLogger(__name__)


# =====================================================================
# ZONE DETECTION (from existing config.py in Agent 1)
# =====================================================================

DHAKA_ZONES = {
    "mirpur": {
        "name": "Mirpur",
        "lat": 23.8223, "lon": 90.3654,
        "keywords_bn": ["মিরপুর", "পল্লবী", "কাজীপাড়া", "রূপনগর", "শেওড়াপাড়া"],
        "keywords_en": ["mirpur", "pallabi", "kazipara", "rupnagar", "shewrapara"],
    },
    "uttara": {
        "name": "Uttara",
        "lat": 23.8759, "lon": 90.3795,
        "keywords_bn": ["উত্তরা", "আজমপুর", "দিয়াবাড়ি"],
        "keywords_en": ["uttara", "azampur", "diabari"],
    },
    "mohammadpur": {
        "name": "Mohammadpur",
        "lat": 23.7662, "lon": 90.3589,
        "keywords_bn": ["মোহাম্মদপুর", "শ্যামলী", "আদাবর"],
        "keywords_en": ["mohammadpur", "shyamoli", "adabor"],
    },
    "dhanmondi": {
        "name": "Dhanmondi",
        "lat": 23.7461, "lon": 90.3742,
        "keywords_bn": ["ধানমন্ডি", "কলাবাগান"],
        "keywords_en": ["dhanmondi", "kalabagan"],
    },
    "badda": {
        "name": "Badda",
        "lat": 23.7806, "lon": 90.4261,
        "keywords_bn": ["বাড্ডা", "গুলশান", "বারিধারা"],
        "keywords_en": ["badda", "gulshan", "baridhara"],
    },
    "jatrabari": {
        "name": "Jatrabari",
        "lat": 23.7104, "lon": 90.4348,
        "keywords_bn": ["যাত্রাবাড়ী", "জাত্রাবাড়ী", "কদমতলী"],
        "keywords_en": ["jatrabari", "kadamtali"],
    },
    "demra": {
        "name": "Demra",
        "lat": 23.7225, "lon": 90.4968,
        "keywords_bn": ["ডেমরা", "মাতুয়াইল"],
        "keywords_en": ["demra", "matuail"],
    },
    # ── Sylhet Division ──
    "sunamganj": {
        "name": "সুনামগঞ্জ",
        "lat": 25.0715, "lon": 91.3950,
        "keywords_bn": ["সুনামগঞ্জ", "সুনামগন্জ", "সদর", "পশ্চিম পাড়া", "পূর্ব বাজার", "রণগোপালপুর", "দক্ষিণ পাড়া"],
        "keywords_en": ["sunamganj", "sunamgonj"],
    },
    "sylhet": {
        "name": "সিলেট",
        "lat": 24.8949, "lon": 91.8687,
        "keywords_bn": ["সিলেট", "আম্বরখানা", "টিলাগড়", "সুরমা তীর"],
        "keywords_en": ["sylhet", "ambarkhana", "tilagar", "surma"],
    },
    "tahirpur": {
        "name": "তাহিরপুর",
        "lat": 25.11, "lon": 91.42,
        "keywords_bn": ["তাহিরপুর"],
        "keywords_en": ["tahirpur"],
    },
    "companiganj": {
        "name": "কোম্পানীগঞ্জ",
        "lat": 25.0456, "lon": 91.5234,
        "keywords_bn": ["কোম্পানীগঞ্জ"],
        "keywords_en": ["companiganj", "kompaniganj"],
    },
    "chhatak": {
        "name": "ছাতক",
        "lat": 25.168, "lon": 91.655,
        "keywords_bn": ["ছাতক"],
        "keywords_en": ["chhatak", "chatok"],
    },
    "jamalganj": {
        "name": "জামালগঞ্জ",
        "lat": 25.15, "lon": 91.25,
        "keywords_bn": ["জামালগঞ্জ"],
        "keywords_en": ["jamalganj", "jamalgonj"],
    },
    "dirai": {
        "name": "দিরাই",
        "lat": 25.02, "lon": 91.32,
        "keywords_bn": ["দিরাই"],
        "keywords_en": ["dirai"],
    },
    "dharmapasha": {
        "name": "ধর্মপাশা",
        "lat": 25.10, "lon": 91.28,
        "keywords_bn": ["ধর্মপাশা"],
        "keywords_en": ["dharmapasha", "dharmpasha"],
    },
    "dowarabazar": {
        "name": "দোয়ারাবাজার",
        "lat": 25.11, "lon": 91.73,
        "keywords_bn": ["দোয়ারাবাজার"],
        "keywords_en": ["dowarabazar"],
    },
    "bishwamvarpur": {
        "name": "বিশ্বম্ভরপুর",
        "lat": 25.19, "lon": 91.58,
        "keywords_bn": ["বিশ্বম্ভরপুর"],
        "keywords_en": ["bishwamvarpur", "bishwamborpur"],
    },
    "madhobpur": {
        "name": "মাধবপুর",
        "lat": 24.75, "lon": 91.82,
        "keywords_bn": ["মাধবপুর"],
        "keywords_en": ["madhobpur", "madhabpur"],
    },
}


# =====================================================================
# KEYWORD-BASED NLP (lightweight, no OpenAI needed for initial parse)
# =====================================================================

FLOOD_KEYWORDS_BN = [
    "বন্যা", "পানি", "জলাবদ্ধতা", "ডুবে", "ডুবছে", "ভাসছে",
    "পানিতে", "জলে", "তলিয়ে", "প্লাবিত", "উদ্ধার", "আটকে",
    "সাহায্য", "বাঁচাও", "হেল্প",
]

FLOOD_KEYWORDS_EN = [
    "flood", "flooding", "waterlog", "submerged", "underwater",
    "stranded", "trapped", "rescue", "help", "drowning",
    "water level", "rising water", "waist deep", "knee deep",
    "chest deep", "neck deep",
]

RESCUE_KEYWORDS = [
    "rescue", "save", "help", "trapped", "stranded", "stuck",
    "উদ্ধার", "বাঁচাও", "আটকে", "সাহায্য", "হেল্প",
    "bachao", "uddar", "help korbo", "atke",
]

WATER_LEVEL_PATTERNS = [
    # English
    (r"(\d+(?:\.\d+)?)\s*(?:ft|feet|foot)", "ft"),
    (r"(\d+(?:\.\d+)?)\s*(?:m|meter|metre)", "m"),
    (r"knee\s*deep", "0.5m"),
    (r"waist\s*deep", "1.0m"),
    (r"chest\s*deep", "1.3m"),
    (r"neck\s*deep", "1.5m"),
    # Bengali/Banglish
    (r"(\d+)\s*ফুট", "ft"),
    (r"হাঁটু\s*পানি", "0.5m"),
    (r"কোমর\s*পানি", "1.0m"),
    (r"বুক\s*পানি", "1.3m"),
    (r"গলা\s*পানি", "1.5m"),
]

PEOPLE_COUNT_PATTERNS = [
    (r"(\d+)\s*(?:people|person|family|families|জন|পরিবার)", None),
    (r"(\d+)\s*(?:lok|jon|poribar)", None),  # Banglish
]


def detect_zone(text: str) -> Optional[Dict[str, Any]]:
    """Detect Dhaka zone from text using keyword matching."""
    text_lower = text.lower()
    for zone_id, zone_info in DHAKA_ZONES.items():
        for kw in zone_info["keywords_en"]:
            if kw in text_lower:
                return {"zone_id": zone_id, **zone_info}
        for kw in zone_info["keywords_bn"]:
            if kw in text:
                return {"zone_id": zone_id, **zone_info}
    return None


def detect_language(text: str) -> str:
    """Simple language detection: bn, en, or banglish."""
    bengali_chars = len(re.findall(r'[\u0980-\u09FF]', text))
    latin_chars = len(re.findall(r'[a-zA-Z]', text))
    total = bengali_chars + latin_chars
    if total == 0:
        return "en"
    bn_ratio = bengali_chars / total
    if bn_ratio > 0.7:
        return "bn"
    elif bn_ratio > 0.2:
        return "banglish"
    return "en"


def extract_water_level(text: str) -> Optional[float]:
    """Extract water level in meters from text."""
    text_lower = text.lower()
    for pattern, unit in WATER_LEVEL_PATTERNS:
        match = re.search(pattern, text_lower if unit != "ft" else text)
        if match:
            if unit in ("0.5m", "1.0m", "1.3m", "1.5m"):
                return float(unit.replace("m", ""))
            val = float(match.group(1))
            if unit == "ft":
                return round(val * 0.3048, 2)
            return val
    return None


def extract_people_count(text: str) -> Optional[int]:
    """Extract number of people mentioned."""
    text_lower = text.lower()
    for pattern, _ in PEOPLE_COUNT_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            return int(match.group(1))
    return None


def is_flood_related(text: str) -> float:
    """Return confidence (0-1) that text is flood-related."""
    text_lower = text.lower()
    hits = 0
    for kw in FLOOD_KEYWORDS_EN:
        if kw in text_lower:
            hits += 1
    for kw in FLOOD_KEYWORDS_BN:
        if kw in text:
            hits += 1
    # Max out at 5 hits = 1.0 confidence
    return min(hits / 3.0, 1.0)


def needs_rescue(text: str) -> bool:
    """Check if text indicates a rescue situation."""
    text_lower = text.lower()
    for kw in RESCUE_KEYWORDS:
        if kw in text_lower or kw in text:
            return True
    return False


def classify_urgency(
    flood_conf: float,
    rescue: bool,
    water_level: Optional[float],
    people: Optional[int],
) -> UrgencyLevel:
    """Classify urgency from extracted features."""
    if rescue and water_level and water_level >= 1.3:
        return UrgencyLevel.CRITICAL
    if rescue:
        return UrgencyLevel.HIGH
    if water_level and water_level >= 1.0:
        return UrgencyLevel.HIGH
    if flood_conf >= 0.8:
        return UrgencyLevel.HIGH
    if flood_conf >= 0.5:
        return UrgencyLevel.MEDIUM
    return UrgencyLevel.LOW


def classify_distress_type(
    rescue: bool,
    water_level: Optional[float],
    text: str,
) -> DistressType:
    """Classify distress type from content."""
    text_lower = text.lower()
    if rescue:
        return DistressType.STRANDED
    if any(w in text_lower for w in ["medical", "doctor", "hospital", "injured", "চিকিৎসা", "ডাক্তার"]):
        return DistressType.MEDICAL_EMERGENCY
    if any(w in text_lower for w in ["collapse", "ভেঙে", "ধসে"]):
        return DistressType.STRUCTURAL_COLLAPSE
    if water_level and water_level >= 0.5:
        return DistressType.WATER_RISING
    if any(w in text_lower for w in ["evacuate", "সরিয়ে", "presanno", "transfer"]):
        return DistressType.EVACUATION_NEEDED
    if any(w in text_lower for w in ["food", "water", "supply", "খাবার", "পানি", "khabar"]):
        return DistressType.SUPPLIES_NEEDED
    return DistressType.GENERAL_FLOOD_REPORT


# =====================================================================
# SOCIAL MEDIA CHANNEL
# =====================================================================

class SocialMediaChannel(BaseChannel):
    """
    Social media distress intake channel.
    
    In production: connects to Facebook Graph API / Twitter API v2.
    For capstone: processes simulated posts from a JSON feed or
    the sample_dataset_generator from Agent 1.
    
    Pipeline:
    1. Fetch posts (real API or simulated)
    2. Keyword-based NLP for fast triage (no API cost)
    3. Zone detection from text
    4. Extract water level, people count, rescue need
    5. Output RawDistressReport objects
    """
    
    def __init__(
        self,
        openai_api_key: Optional[str] = None,
        use_llm_enrichment: bool = False,
        simulated_posts: Optional[List[Dict[str, Any]]] = None,
    ):
        super().__init__(channel_type=DistressChannel.SOCIAL_MEDIA)
        self.openai_api_key = openai_api_key
        self.use_llm_enrichment = use_llm_enrichment
        self._simulated_posts = simulated_posts or []
        self._post_buffer: List[Dict[str, Any]] = []
    
    def load_simulated_posts(self, posts: List[Dict[str, Any]]):
        """Load simulated social media posts for testing."""
        self._simulated_posts = posts
        logger.info(f"Loaded {len(posts)} simulated social media posts")
    
    async def ingest(self) -> List[RawDistressReport]:
        """
        Ingest and parse social media posts into distress reports.
        Only returns posts that are flood-related (confidence >= 0.3).
        """
        reports = []
        posts = self._simulated_posts  # In production: fetch from API
        
        for post in posts:
            try:
                text = post.get("text", post.get("content", ""))
                if not text:
                    continue
                
                # Step 1: Is it flood-related?
                flood_conf = is_flood_related(text)
                if flood_conf < 0.3:
                    continue
                
                # Step 2: Extract features
                zone = detect_zone(text)
                lang = detect_language(text)
                water_level = extract_water_level(text)
                people = extract_people_count(text)
                rescue = needs_rescue(text)
                urgency = classify_urgency(flood_conf, rescue, water_level, people)
                dtype = classify_distress_type(rescue, water_level, text)
                
                # Step 3: Build location
                # Use scenario pinpoint coords if available (highest accuracy)
                scenario_lat = post.get("scenario_lat")
                scenario_lng = post.get("scenario_lng")
                loc_desc = post.get("location_description", "")
                
                if scenario_lat and scenario_lng:
                    location = DistressLocation(
                        latitude=scenario_lat,
                        longitude=scenario_lng,
                        zone_name=zone["name"] if zone else loc_desc or None,
                        zone_id=zone["zone_id"] if zone else None,
                        address_text=loc_desc or post.get("location_text"),
                        confidence=0.95,
                    )
                else:
                    location = DistressLocation(
                        latitude=zone["lat"] if zone else post.get("lat"),
                        longitude=zone["lon"] if zone else post.get("lon"),
                        zone_name=zone["name"] if zone else None,
                        zone_id=zone["zone_id"] if zone else None,
                        address_text=post.get("location_text"),
                        confidence=0.8 if zone else 0.3,
                    )
                
                # Step 4: Build report
                report = RawDistressReport(
                    channel=DistressChannel.SOCIAL_MEDIA,
                    timestamp=datetime.fromisoformat(post["created_at"]) if "created_at" in post else datetime.utcnow(),
                    raw_content=text,
                    language=lang,
                    distress_type=dtype,
                    urgency=urgency,
                    location=location,
                    people_count=people,
                    needs_rescue=rescue,
                    water_level_meters=water_level,
                    nlp_confidence=flood_conf,
                    channel_metadata={
                        "platform": post.get("platform", "facebook"),
                        "post_id": post.get("id", str(uuid4())),
                        "author": post.get("author", "anonymous"),
                        "engagement": post.get("engagement", 0),
                        "has_media": post.get("has_media", False),
                    },
                )
                reports.append(report)
                self.total_ingested += 1
                
            except Exception as e:
                logger.error(f"Error parsing social media post: {e}")
                self.total_errors += 1
        
        logger.info(
            f"Social media channel: {len(reports)} distress reports "
            f"from {len(posts)} posts (flood-related filter applied)"
        )
        return reports
    
    async def health_check(self) -> bool:
        """Social media channel is healthy if we have posts to process or API is reachable."""
        return True  # Simulated = always healthy
