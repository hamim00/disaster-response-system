"""
Data Models for Distress Intelligence Agent
=============================================
Pydantic models for multi-channel distress reports, cross-referencing,
and prioritized dispatch queue.

Agent 2: Distress Intelligence (Multi-Channel)
Author: Mahmudul Hasan
Version: 1.0.0
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, validator, ConfigDict
from uuid import UUID, uuid4


# =====================================================================
# ENUMS
# =====================================================================

class DistressChannel(str, Enum):
    """Source channel for distress reports"""
    SOCIAL_MEDIA = "social_media"
    SMS_USSD = "sms_ussd"
    EMERGENCY_HOTLINE = "emergency_hotline"
    SATELLITE_POPULATION = "satellite_population"


class UrgencyLevel(str, Enum):
    """Urgency classification for distress reports"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DistressType(str, Enum):
    """Type of distress situation"""
    STRANDED = "stranded"
    MEDICAL_EMERGENCY = "medical_emergency"
    STRUCTURAL_COLLAPSE = "structural_collapse"
    WATER_RISING = "water_rising"
    EVACUATION_NEEDED = "evacuation_needed"
    SUPPLIES_NEEDED = "supplies_needed"
    MISSING_PERSON = "missing_person"
    GENERAL_FLOOD_REPORT = "general_flood_report"
    POPULATION_AT_RISK = "population_at_risk"


class VerificationStatus(str, Enum):
    """Cross-reference verification status"""
    VERIFIED = "verified"          # Agent 1 confirms flooding in this zone
    UNVERIFIED = "unverified"      # Agent 1 has no data for this zone
    CONTRADICTED = "contradicted"  # Agent 1 says no flooding here
    PENDING = "pending"            # Waiting for Agent 1 response


class FloodSeverity(str, Enum):
    """Flood severity from Agent 1"""
    MINIMAL = "minimal"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


# =====================================================================
# LOCATION MODEL
# =====================================================================

class DistressLocation(BaseModel):
    """Location information for a distress report"""
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    zone_name: Optional[str] = Field(None, description="Known zone name (e.g., Mirpur, Uttara)")
    zone_id: Optional[str] = Field(None, description="Matches Agent 1 sentinel zone ID")
    address_text: Optional[str] = Field(None, description="Free-text address or landmark")
    confidence: float = Field(default=0.5, ge=0, le=1, description="Location accuracy confidence")

    @property
    def has_coordinates(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    @property
    def has_zone(self) -> bool:
        return self.zone_name is not None or self.zone_id is not None

    def to_wkt(self) -> Optional[str]:
        if self.has_coordinates:
            return f"POINT({self.longitude} {self.latitude})"
        return None


# =====================================================================
# RAW DISTRESS REPORTS (per channel)
# =====================================================================

class RawDistressReport(BaseModel):
    """
    A single distress report from any channel.
    This is the unified intake format — every channel parser
    converts its raw input into this structure.
    """
    id: UUID = Field(default_factory=uuid4)
    channel: DistressChannel
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Content
    raw_content: str = Field(..., description="Original message text")
    language: Optional[str] = Field(None, description="Detected language: bn/en/banglish")
    
    # Extracted fields
    distress_type: DistressType = Field(default=DistressType.GENERAL_FLOOD_REPORT)
    urgency: UrgencyLevel = Field(default=UrgencyLevel.MEDIUM)
    location: DistressLocation = Field(default_factory=DistressLocation)
    people_count: Optional[int] = Field(None, ge=0, description="Number of people affected")
    needs_rescue: bool = Field(default=False)
    water_level_meters: Optional[float] = Field(None, ge=0, description="Reported water level")
    
    # Channel-specific metadata
    channel_metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Processing
    nlp_confidence: float = Field(default=0.5, ge=0, le=1)
    is_duplicate: bool = Field(default=False)
    duplicate_of: Optional[UUID] = None


class SocialMediaDistress(BaseModel):
    """Social media specific fields (extends RawDistressReport via metadata)"""
    platform: str = Field(default="facebook", description="facebook/twitter/youtube")
    post_id: str = Field(..., description="Original post ID")
    author: str = Field(default="anonymous")
    engagement_score: float = Field(default=0.0, ge=0, description="likes+shares+comments")
    has_media: bool = Field(default=False, description="Contains image/video")
    media_shows_flooding: Optional[bool] = None


class SMSDistress(BaseModel):
    """SMS/USSD specific fields"""
    sender_phone_hash: str = Field(..., description="Hashed phone number for dedup")
    message_type: str = Field(default="free_text", description="free_text/structured/ussd")
    ussd_code: Optional[str] = Field(None, description="e.g., *999#")
    network_operator: Optional[str] = Field(None, description="GP/Robi/Banglalink/Teletalk")
    signal_strength: Optional[str] = Field(None, description="2G/3G/4G")


class HotlineDistress(BaseModel):
    """Emergency hotline specific fields"""
    call_id: str = Field(..., description="Call record ID")
    operator_id: Optional[str] = None
    call_duration_seconds: Optional[int] = None
    caller_phone_hash: Optional[str] = None
    transcript: Optional[str] = None


# =====================================================================
# CROSS-REFERENCED DISTRESS (after Agent 1 verification)
# =====================================================================

class CrossReferencedDistress(BaseModel):
    """
    A distress report after cross-referencing with Agent 1's flood data.
    This is the key output — every report gets tagged with whether
    Agent 1 actually detects flooding at that location.
    """
    id: UUID = Field(default_factory=uuid4)
    distress_report: RawDistressReport
    
    # Cross-reference results
    verification_status: VerificationStatus = Field(default=VerificationStatus.PENDING)
    agent1_flood_severity: Optional[FloodSeverity] = None
    agent1_risk_score: Optional[float] = Field(None, ge=0, le=1)
    agent1_flood_depth_m: Optional[float] = Field(None, ge=0)
    agent1_flood_pct: Optional[float] = Field(None, ge=0, le=100)
    
    # Adjusted priority (after cross-referencing)
    final_urgency: UrgencyLevel = Field(default=UrgencyLevel.MEDIUM)
    final_priority_score: float = Field(default=0.0, ge=0, le=1)
    
    # Reasoning
    priority_reasoning: str = Field(default="")
    
    cross_referenced_at: datetime = Field(default_factory=datetime.utcnow)


# =====================================================================
# PRIORITIZED DISTRESS QUEUE (output to Agent 3)
# =====================================================================

class DistressQueueItem(BaseModel):
    """
    Final prioritized item ready for Agent 3 (Resource Management).
    Published to Redis channel: distress_queue
    """
    id: UUID = Field(default_factory=uuid4)
    
    # Source
    distress_id: UUID
    channel: DistressChannel
    
    # Location (best available)
    location: DistressLocation
    zone_name: str = Field(default="unknown")
    
    # Situation
    distress_type: DistressType
    urgency: UrgencyLevel
    people_count: Optional[int] = None
    needs_rescue: bool = False
    water_level_meters: Optional[float] = None
    
    # Priority
    priority_score: float = Field(..., ge=0, le=1, description="0=low, 1=critical")
    
    # Verification
    flood_verified: bool = Field(default=False)
    agent1_risk_score: Optional[float] = None
    
    # Timing
    reported_at: datetime
    queued_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Resource hints for Agent 3
    recommended_resources: List[str] = Field(
        default_factory=list,
        description="Suggested resource types: rescue_boat, medical_team, food_water, evacuation_vehicle"
    )
    
    summary: str = Field(default="", description="Human-readable summary for dashboard")


# =====================================================================
# AGENT MESSAGE ENVELOPE (Redis pub/sub)
# =====================================================================

class AgentMessage(BaseModel):
    """
    Standard message envelope for inter-agent Redis communication.
    Matches the protocol from AGENT_3_4_GUIDELINES.md
    """
    message_id: UUID = Field(default_factory=uuid4)
    source_agent: str = Field(default="agent_2_distress_intelligence")
    target_agent: str
    channel: str = Field(..., description="Redis channel name")
    message_type: str = Field(..., description="flood_alert / distress_report / dispatch_order / etc.")
    payload: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    priority: int = Field(default=3, ge=1, le=5)


# =====================================================================
# AGENT 2 OUTPUT & STATUS
# =====================================================================

class Agent2Output(BaseModel):
    """Complete output from Distress Intelligence Agent"""
    agent_id: str = "agent_2_distress_intelligence"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Intake stats
    total_reports_ingested: int = 0
    reports_by_channel: Dict[str, int] = Field(default_factory=dict)
    
    # Processing stats
    verified_reports: int = 0
    contradicted_reports: int = 0
    unverified_reports: int = 0
    duplicate_reports: int = 0
    
    # Queue stats
    queue_size: int = 0
    critical_items: int = 0
    rescue_situations: int = 0
    
    # Active distress items
    active_queue: List[DistressQueueItem] = Field(default_factory=list)
    
    # Channel health
    channel_status: Dict[str, str] = Field(default_factory=dict)
    
    processing_time_seconds: float = 0.0


class Agent2HealthCheck(BaseModel):
    """Health check response"""
    status: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    agent_id: str = "agent_2_distress_intelligence"
    version: str = "1.0.0"
    channels_active: Dict[str, bool] = Field(default_factory=dict)
    redis_connected: bool = False
    database_connected: bool = False
    agent1_reachable: bool = False
