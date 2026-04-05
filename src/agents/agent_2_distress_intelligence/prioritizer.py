"""
Distress Prioritizer & Queue Builder
======================================
Takes cross-referenced distress reports, deduplicates them,
and builds the final prioritized queue for Agent 3 (Resource Management).

Deduplication logic:
- Same zone + same channel within 15 minutes → duplicate
- Same phone hash (SMS/hotline) within 30 minutes → duplicate
- Duplicates are merged: highest urgency wins, people counts summed

Author: Mahmudul Hasan
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Set
from collections import defaultdict

from models import (
    CrossReferencedDistress, DistressQueueItem, RawDistressReport,
    DistressLocation, DistressType, UrgencyLevel, DistressChannel,
    VerificationStatus,
)

logger = logging.getLogger(__name__)


# Resource recommendation rules
RESOURCE_RULES: Dict[DistressType, List[str]] = {
    DistressType.STRANDED: ["rescue_boat", "medical_team"],
    DistressType.MEDICAL_EMERGENCY: ["medical_team", "evacuation_vehicle"],
    DistressType.STRUCTURAL_COLLAPSE: ["rescue_boat", "medical_team"],
    DistressType.WATER_RISING: ["rescue_boat", "food_water"],
    DistressType.EVACUATION_NEEDED: ["evacuation_vehicle", "food_water"],
    DistressType.SUPPLIES_NEEDED: ["food_water"],
    DistressType.MISSING_PERSON: ["rescue_boat"],
    DistressType.GENERAL_FLOOD_REPORT: ["food_water"],
    DistressType.POPULATION_AT_RISK: ["rescue_boat", "medical_team", "food_water"],
}

# Scale resources by water depth
DEPTH_RESOURCE_BOOST = {
    # depth_threshold_m: extra resources
    2.0: ["rescue_boat", "rescue_boat"],  # Deep = more boats
    1.0: ["rescue_boat"],
    0.5: [],
}


class DistressPrioritizer:
    """
    Deduplicates cross-referenced distress reports and builds
    the final prioritized queue for Agent 3.
    """
    
    def __init__(
        self,
        dedup_window_minutes: int = 15,
        phone_dedup_window_minutes: int = 30,
        min_priority_threshold: float = 0.1,
    ):
        self.dedup_window = timedelta(minutes=dedup_window_minutes)
        self.phone_dedup_window = timedelta(minutes=phone_dedup_window_minutes)
        self.min_priority_threshold = min_priority_threshold
        
        # Dedup state
        self._seen_zone_channel: Dict[str, datetime] = {}
        self._seen_phones: Dict[str, datetime] = {}
        
        logger.info("DistressPrioritizer initialized")
    
    def _is_duplicate(self, report: RawDistressReport) -> bool:
        """Check if a report is a likely duplicate."""
        now = report.timestamp
        
        # Phone-based dedup (SMS and hotline)
        if report.channel in (DistressChannel.SMS_USSD, DistressChannel.EMERGENCY_HOTLINE):
            phone_hash = report.channel_metadata.get(
                "sender_phone_hash",
                report.channel_metadata.get("caller_phone_hash"),
            )
            if phone_hash and phone_hash != "unknown":
                if phone_hash in self._seen_phones:
                    if (now - self._seen_phones[phone_hash]) < self.phone_dedup_window:
                        return True
                self._seen_phones[phone_hash] = now
        
        # Zone + channel dedup
        zone = report.location.zone_id or report.location.zone_name or "unknown"
        key = f"{zone}:{report.channel.value}"
        
        if key in self._seen_zone_channel:
            if (now - self._seen_zone_channel[key]) < self.dedup_window:
                return True
        
        self._seen_zone_channel[key] = now
        return False
    
    def _recommend_resources(
        self,
        distress_type: DistressType,
        water_level: Optional[float],
        people_count: Optional[int],
    ) -> List[str]:
        """Generate resource recommendations."""
        resources = list(RESOURCE_RULES.get(distress_type, ["food_water"]))
        
        # Depth-based boost
        if water_level:
            for threshold, extra in sorted(DEPTH_RESOURCE_BOOST.items(), reverse=True):
                if water_level >= threshold:
                    resources.extend(extra)
                    break
        
        # People-count scaling
        if people_count and people_count > 20:
            resources.append("food_water")
        if people_count and people_count > 50:
            resources.append("rescue_boat")
        
        # Deduplicate while preserving order
        seen: Set[str] = set()
        unique = []
        for r in resources:
            if r not in seen:
                seen.add(r)
                unique.append(r)
        
        return unique
    
    def _build_summary(self, xref: CrossReferencedDistress) -> str:
        """Build a human-readable summary for the dashboard."""
        r = xref.distress_report
        parts = []
        
        # Channel indicator
        channel_icons = {
            DistressChannel.SOCIAL_MEDIA: "📱",
            DistressChannel.SMS_USSD: "💬",
            DistressChannel.EMERGENCY_HOTLINE: "📞",
            DistressChannel.SATELLITE_POPULATION: "🛰️",
        }
        parts.append(channel_icons.get(r.channel, "📌"))
        
        # Urgency
        urgency_labels = {
            UrgencyLevel.CRITICAL: "🔴 CRITICAL",
            UrgencyLevel.HIGH: "🟠 HIGH",
            UrgencyLevel.MEDIUM: "🟡 MEDIUM",
            UrgencyLevel.LOW: "🟢 LOW",
        }
        parts.append(urgency_labels.get(xref.final_urgency, "MEDIUM"))
        
        # Location
        zone = r.location.zone_name or r.location.zone_id or "Unknown"
        parts.append(f"@ {zone}")
        
        # Type
        parts.append(f"— {r.distress_type.value.replace('_', ' ').title()}")
        
        # Details
        if r.people_count:
            parts.append(f"({r.people_count} people)")
        if r.water_level_meters:
            parts.append(f"[water: {r.water_level_meters:.1f}m]")
        
        # Verification
        ver_labels = {
            VerificationStatus.VERIFIED: "✅ Flood verified",
            VerificationStatus.CONTRADICTED: "❌ Not verified",
            VerificationStatus.UNVERIFIED: "❓ Unverified",
        }
        parts.append(ver_labels.get(xref.verification_status, ""))
        
        return " ".join(parts)
    
    def build_queue(
        self,
        cross_referenced: List[CrossReferencedDistress],
    ) -> List[DistressQueueItem]:
        """
        Build the final prioritized distress queue.
        
        Steps:
        1. Filter below minimum priority
        2. Deduplicate
        3. Generate resource recommendations
        4. Build queue items sorted by priority
        
        Args:
            cross_referenced: Cross-referenced distress reports
            
        Returns:
            Prioritized queue items for Agent 3
        """
        queue: List[DistressQueueItem] = []
        duplicates = 0
        filtered = 0
        
        for xref in cross_referenced:
            report = xref.distress_report
            
            # Filter low-priority contradicted reports
            if (xref.verification_status == VerificationStatus.CONTRADICTED
                    and xref.final_priority_score < 0.3):
                filtered += 1
                continue
            
            # Filter below threshold
            if xref.final_priority_score < self.min_priority_threshold:
                filtered += 1
                continue
            
            # Dedup check
            if self._is_duplicate(report):
                duplicates += 1
                continue
            
            # Resource recommendations
            resources = self._recommend_resources(
                report.distress_type,
                report.water_level_meters,
                report.people_count,
            )
            
            # Build queue item
            item = DistressQueueItem(
                distress_id=report.id,
                channel=report.channel,
                location=report.location,
                zone_name=report.location.zone_name or report.location.zone_id or "unknown",
                distress_type=report.distress_type,
                urgency=xref.final_urgency,
                people_count=report.people_count,
                needs_rescue=report.needs_rescue,
                water_level_meters=report.water_level_meters,
                priority_score=xref.final_priority_score,
                flood_verified=(xref.verification_status == VerificationStatus.VERIFIED),
                agent1_risk_score=xref.agent1_risk_score,
                reported_at=report.timestamp,
                recommended_resources=resources,
                summary=self._build_summary(xref),
            )
            queue.append(item)
        
        # Sort by priority (highest first)
        queue.sort(key=lambda x: x.priority_score, reverse=True)
        
        logger.info(
            f"Queue built: {len(queue)} items "
            f"({duplicates} duplicates removed, {filtered} filtered)"
        )
        
        return queue
    
    def reset_dedup_state(self):
        """Reset deduplication state (e.g., between monitoring cycles)."""
        self._seen_zone_channel.clear()
        self._seen_phones.clear()
