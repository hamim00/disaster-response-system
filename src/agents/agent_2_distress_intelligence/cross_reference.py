"""
Cross-Reference Engine
=======================
Verifies distress reports against Agent 1's real-time flood data.

This is the intelligence core of Agent 2. For every incoming distress
report, we ask: "Does Agent 1 actually detect flooding at this location?"

Verification outcomes:
- VERIFIED:     Agent 1 confirms active flooding → priority boosted
- UNVERIFIED:   Agent 1 has no data for this zone → treat with caution
- CONTRADICTED: Agent 1 says no flooding here → lower priority (possible hoax/stale report)

Author: Mahmudul Hasan
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from uuid import uuid4

import aiohttp

from models import (
    RawDistressReport, CrossReferencedDistress,
    VerificationStatus, FloodSeverity, UrgencyLevel,
    DistressChannel,
)

logger = logging.getLogger(__name__)


class CrossReferenceEngine:
    """
    Cross-references distress reports with Agent 1's flood predictions.
    
    Can work in two modes:
    1. API mode: queries Agent 1's REST API at http://agent1:8001
    2. Direct mode: accepts flood data dict (for testing without Agent 1 running)
    """
    
    def __init__(
        self,
        agent1_base_url: str = "http://localhost:8001",
        flood_data_override: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        """
        Args:
            agent1_base_url: Agent 1 API URL
            flood_data_override: Direct flood data dict keyed by zone_id
                                 (bypasses API call, for testing)
        """
        self.agent1_url = agent1_base_url
        self._flood_data_override = flood_data_override
        self._flood_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamp: Optional[datetime] = None
        
        logger.info(
            f"CrossReferenceEngine initialized "
            f"(agent1={agent1_base_url}, override={'YES' if flood_data_override else 'NO'})"
        )
    
    def set_flood_data(self, data: Dict[str, Dict[str, Any]]):
        """
        Directly set flood data for testing.
        
        Format:
        {
            "mirpur": {
                "risk_score": 0.75,
                "severity": "high",
                "flood_pct": 37.5,
                "flood_depth_m": 1.2,
            },
            "uttara": {
                "risk_score": 0.25,
                "severity": "low",
                "flood_pct": 2.0,
                "flood_depth_m": 0.0,
            },
        }
        """
        self._flood_data_override = data
        logger.info(f"Flood data set directly for {len(data)} zones")
    
    async def _fetch_agent1_data(self) -> Dict[str, Dict[str, Any]]:
        """Fetch current flood data from Agent 1 API."""
        if self._flood_data_override is not None:
            return self._flood_data_override
        
        try:
            async with aiohttp.ClientSession() as session:
                # Get latest output from Agent 1
                async with session.get(
                    f"{self.agent1_url}/output",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"Agent 1 returned status {resp.status}")
                        return {}
                    
                    data = await resp.json()
                    
                    # Parse predictions into zone-keyed dict
                    flood_data = {}
                    for pred in data.get("predictions", []):
                        zone = pred.get("zone", {})
                        zone_name = zone.get("name", "").lower()
                        if zone_name:
                            flood_data[zone_name] = {
                                "risk_score": pred.get("risk_score", 0),
                                "severity": pred.get("severity_level", "minimal"),
                                "flood_pct": pred.get("risk_factors", {}).get("satellite_flood_pct", 0),
                                "flood_depth_m": pred.get("risk_factors", {}).get("flood_depth_m", 0),
                            }
                    
                    self._flood_cache = flood_data
                    self._cache_timestamp = datetime.utcnow()
                    return flood_data
                    
        except Exception as e:
            logger.error(f"Failed to fetch Agent 1 data: {e}")
            # Return cached data if available
            if self._flood_cache:
                logger.info("Using cached Agent 1 data")
                return self._flood_cache
            return {}
    
    def _verify_single(
        self,
        report: RawDistressReport,
        flood_data: Dict[str, Dict[str, Any]],
    ) -> CrossReferencedDistress:
        """Cross-reference a single distress report."""
        
        zone_id = report.location.zone_id
        zone_name = (report.location.zone_name or "").lower()
        
        # Try to find matching flood data
        zone_flood = None
        if zone_id and zone_id in flood_data:
            zone_flood = flood_data[zone_id]
        elif zone_name and zone_name in flood_data:
            zone_flood = flood_data[zone_name]
        
        # Determine verification status
        if zone_flood is None:
            # No data for this zone
            verification = VerificationStatus.UNVERIFIED
            a1_severity = None
            a1_risk = None
            a1_depth = None
            a1_flood_pct = None
        else:
            a1_risk = zone_flood.get("risk_score", 0)
            a1_severity_str = zone_flood.get("severity", "minimal")
            a1_depth = zone_flood.get("flood_depth_m")
            a1_flood_pct = zone_flood.get("flood_pct", 0)
            
            # Map string to enum
            severity_map = {
                "minimal": FloodSeverity.MINIMAL,
                "low": FloodSeverity.LOW,
                "moderate": FloodSeverity.MODERATE,
                "high": FloodSeverity.HIGH,
                "critical": FloodSeverity.CRITICAL,
            }
            a1_severity = severity_map.get(a1_severity_str, FloodSeverity.MINIMAL)
            
            # Verification logic
            if a1_risk >= 0.4 or a1_flood_pct >= 5:
                verification = VerificationStatus.VERIFIED
            elif a1_risk <= 0.15 and a1_flood_pct < 2:
                verification = VerificationStatus.CONTRADICTED
            else:
                verification = VerificationStatus.UNVERIFIED
        
        # Calculate final priority score (0-1)
        base_priority = self._urgency_to_score(report.urgency)
        
        # Adjust based on verification
        if verification == VerificationStatus.VERIFIED:
            # Boost: satellite confirms flooding
            priority_boost = 0.10
            reasoning = (
                f"VERIFIED by Agent 1: {zone_name} has "
                f"risk={a1_risk:.2f}, flood_pct={a1_flood_pct:.1f}%. "
                f"Priority boosted."
            )
        elif verification == VerificationStatus.CONTRADICTED:
            # Penalty: satellite sees no flooding
            priority_boost = -0.20
            reasoning = (
                f"CONTRADICTED by Agent 1: {zone_name} shows "
                f"risk={a1_risk:.2f}, flood_pct={a1_flood_pct:.1f}%. "
                f"Possible false report or stale data. Priority reduced."
            )
        else:
            priority_boost = 0.0
            reasoning = (
                f"UNVERIFIED: No Agent 1 data for {zone_name or 'unknown zone'}. "
                f"Treating with standard priority."
            )
        
        # Channel credibility bonus
        channel_bonus = {
            DistressChannel.EMERGENCY_HOTLINE: 0.08,   # Operator-verified
            DistressChannel.SMS_USSD: 0.04,             # Direct from victim
            DistressChannel.SOCIAL_MEDIA: 0.0,           # May be stale/fake
            DistressChannel.SATELLITE_POPULATION: 0.06,  # Data-driven
        }
        
        # Rescue need bonus
        rescue_bonus = 0.10 if report.needs_rescue else 0.0
        
        # Water level bonus
        depth_bonus = 0.0
        if report.water_level_meters:
            if report.water_level_meters >= 1.5:
                depth_bonus = 0.08
            elif report.water_level_meters >= 1.0:
                depth_bonus = 0.05
            elif report.water_level_meters >= 0.5:
                depth_bonus = 0.03
        
        final_score = min(1.0, max(0.0,
            base_priority
            + priority_boost
            + channel_bonus.get(report.channel, 0)
            + rescue_bonus
            + depth_bonus
        ))
        
        # Map score back to urgency
        final_urgency = self._score_to_urgency(final_score)
        
        return CrossReferencedDistress(
            distress_report=report,
            verification_status=verification,
            agent1_flood_severity=a1_severity,
            agent1_risk_score=a1_risk,
            agent1_flood_depth_m=a1_depth,
            agent1_flood_pct=a1_flood_pct,
            final_urgency=final_urgency,
            final_priority_score=final_score,
            priority_reasoning=reasoning,
        )
    
    async def cross_reference(
        self,
        reports: List[RawDistressReport],
    ) -> List[CrossReferencedDistress]:
        """
        Cross-reference a batch of distress reports with Agent 1 data.
        
        Args:
            reports: Raw distress reports from all channels
            
        Returns:
            List of CrossReferencedDistress, sorted by priority (highest first)
        """
        flood_data = await self._fetch_agent1_data()
        
        results = []
        for report in reports:
            xref = self._verify_single(report, flood_data)
            results.append(xref)
        
        # Sort by priority (highest first)
        results.sort(key=lambda x: x.final_priority_score, reverse=True)
        
        # Log summary
        verified = sum(1 for r in results if r.verification_status == VerificationStatus.VERIFIED)
        contradicted = sum(1 for r in results if r.verification_status == VerificationStatus.CONTRADICTED)
        unverified = sum(1 for r in results if r.verification_status == VerificationStatus.UNVERIFIED)
        
        logger.info(
            f"Cross-referenced {len(results)} reports: "
            f"{verified} verified, {contradicted} contradicted, {unverified} unverified"
        )
        
        return results
    
    @staticmethod
    def _urgency_to_score(urgency: UrgencyLevel) -> float:
        return {
            UrgencyLevel.LOW: 0.2,
            UrgencyLevel.MEDIUM: 0.45,
            UrgencyLevel.HIGH: 0.7,
            UrgencyLevel.CRITICAL: 0.9,
        }.get(urgency, 0.45)
    
    @staticmethod
    def _score_to_urgency(score: float) -> UrgencyLevel:
        if score >= 0.8:
            return UrgencyLevel.CRITICAL
        elif score >= 0.6:
            return UrgencyLevel.HIGH
        elif score >= 0.35:
            return UrgencyLevel.MEDIUM
        return UrgencyLevel.LOW
