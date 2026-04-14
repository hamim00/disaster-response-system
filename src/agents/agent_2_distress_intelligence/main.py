"""
Distress Intelligence Agent — Main Orchestrator
=================================================
Agent 2: Multi-channel distress aggregation, cross-referencing,
and prioritized dispatch to Agent 3.

Channels:
    1. Social Media (Facebook/Twitter — works in early flooding)
    2. SMS/USSD (*999# — works on 2G when data is down)
    3. Emergency Hotline (999 system — operator-verified)
    4. Satellite + Population (proactive — no victim communication needed)

Redis channels:
    Subscribes to: flood_alert (from Agent 1)
    Publishes to:  distress_queue (to Agent 3)

FastAPI port: 8002

Author: Mahmudul Hasan
Version: 1.0.0
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, cast

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from redis import asyncio as aioredis
import uvicorn

from models import (
    Agent2Output, Agent2HealthCheck, DistressQueueItem,
    AgentMessage, RawDistressReport, DistressChannel,
    UrgencyLevel, CrossReferencedDistress,
)
from channels.social_media import SocialMediaChannel
from channels.sms_ussd import SMSUSSDChannel
from channels.emergency_hotline import EmergencyHotlineChannel
from channels.satellite_population import SatellitePopulationChannel
from cross_reference import CrossReferenceEngine
from prioritizer import DistressPrioritizer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('agent_2_distress.log'),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# =====================================================================
# CONFIGURATION
# =====================================================================

class Agent2Config:
    """Agent 2 configuration."""
    
    def __init__(self):
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        # Redis
        self.redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
        
        # Agent 1 API
        self.agent1_url = os.getenv('AGENT1_URL', 'http://localhost:8001')
        
        # OpenAI (optional — for LLM enrichment of social media)
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        
        # Monitoring
        self.monitoring_interval = int(os.getenv('AGENT2_INTERVAL', '120'))
        self.agent_id = 'agent_2_distress_intelligence'
        
        # Channels
        self.enable_social_media = os.getenv('ENABLE_SOCIAL_MEDIA', 'true').lower() == 'true'
        self.enable_sms = os.getenv('ENABLE_SMS', 'true').lower() == 'true'
        self.enable_hotline = os.getenv('ENABLE_HOTLINE', 'true').lower() == 'true'
        self.enable_satellite_pop = os.getenv('ENABLE_SATELLITE_POP', 'true').lower() == 'true'


# =====================================================================
# DISTRESS INTELLIGENCE AGENT
# =====================================================================

class DistressIntelligenceAgent:
    """
    Main Agent 2 class.
    Coordinates multi-channel intake, cross-referencing, and dispatch.
    """
    
    def __init__(self, config: Agent2Config):
        self.config = config
        self.running = False
        
        # Redis
        self.redis_client: Optional[aioredis.Redis] = None
        
        # Channels
        self.social_channel = SocialMediaChannel(
            openai_api_key=config.openai_api_key,
        ) if config.enable_social_media else None
        
        self.sms_channel = SMSUSSDChannel() if config.enable_sms else None
        self.hotline_channel = EmergencyHotlineChannel() if config.enable_hotline else None
        self.satellite_channel = SatellitePopulationChannel() if config.enable_satellite_pop else None
        
        # Processing
        self.cross_reference = CrossReferenceEngine(
            agent1_base_url=config.agent1_url,
        )
        self.prioritizer = DistressPrioritizer()
        
        # State
        self.latest_output: Optional[Agent2Output] = None
        self.latest_queue: List[DistressQueueItem] = []
        self.last_update: Optional[datetime] = None
        
        # Accumulated flood alerts from Agent 1 (via Redis subscription)
        self._pending_flood_alerts: List[Dict[str, Any]] = []
        
        logger.info(f"DistressIntelligenceAgent initialized (channels: "
                     f"social={config.enable_social_media}, "
                     f"sms={config.enable_sms}, "
                     f"hotline={config.enable_hotline}, "
                     f"satellite_pop={config.enable_satellite_pop})")
    
    async def startup(self):
        """Initialize connections."""
        logger.info("Starting Agent 2...")
        
        try:
            self.redis_client = await aioredis.from_url(
                self.config.redis_url,
                decode_responses=True,
            )
            await self.redis_client.ping()
            logger.info("Redis connected and verified")
        except Exception as e:
            logger.warning(f"Redis connection failed (will work without it): {e}")
            self.redis_client = None
        
        logger.info("Agent 2 startup complete")
    
    async def shutdown(self):
        """Clean shutdown."""
        self.running = False
        if self.redis_client:
            await self.redis_client.aclose()  # FIX: .close() → .aclose()
        logger.info("Agent 2 shut down")
    
    async def _subscribe_flood_alerts(self):
        """Subscribe to Agent 1's flood_alert Redis channel."""
        if not self.redis_client:
            return
        
        try:
            pubsub = self.redis_client.pubsub()
            await pubsub.subscribe("flood_alert")
            logger.info("Subscribed to flood_alert channel")
            
            async for message in pubsub.listen():
                if not self.running:
                    break
                if message["type"] == "message":
                    try:
                        alert = json.loads(message["data"])
                        self._pending_flood_alerts.append(alert)
                        logger.info(
                            f"Received flood alert: zone={alert.get('zone_id')}, "
                            f"risk={alert.get('risk_score')}"
                        )
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON in flood_alert message")
        except Exception as e:
            logger.error(f"flood_alert subscription error: {e}")
    
    async def _publish_distress_queue(self, queue: List[DistressQueueItem]):
        """Publish prioritized distress queue to Redis for Agent 3."""
        if not self.redis_client:
            logger.debug("No Redis — skipping publish")
            return
        
        for item in queue:
            try:
                message = AgentMessage(
                    source_agent="agent_2_distress_intelligence",
                    target_agent="agent_3_resource_management",
                    channel="distress_queue",
                    message_type="distress_report",
                    payload=item.model_dump(mode="json"),
                    priority=self._urgency_to_redis_priority(item.urgency),
                )
                
                await self.redis_client.publish(
                    "distress_queue",
                    message.model_dump_json(),
                )
                
                # Also log to agent_messages (for dashboard)
                await self.redis_client.rpush(
                    "agent_messages_log",
                    message.model_dump_json(),
                )
                
            except Exception as e:
                logger.error(f"Failed to publish distress item: {e}")
        
        logger.info(f"Published {len(queue)} items to distress_queue")
    
    async def _http_push_to_agent3(self, queue: List[DistressQueueItem]):
        """HTTP fallback: push distress items directly to Agent 3's /trigger_batch."""
        import aiohttp
        agent3_url = os.getenv("AGENT3_URL", "http://localhost:8003")
        payload = [item.model_dump(mode="json") for item in queue]
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{agent3_url}/trigger_batch",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(
                            f"HTTP push to Agent 3: {data.get('allocated', 0)} allocations "
                            f"from {data.get('processed', 0)} items"
                        )
                    else:
                        body = await resp.text()
                        logger.warning(f"Agent 3 HTTP push returned {resp.status}: {body[:200]}")
        except Exception as e:
            logger.warning(f"Agent 3 HTTP push failed (non-fatal): {e}")
    
    async def run_processing_cycle(self) -> Agent2Output:
        """
        Run one complete processing cycle:
        1. Ingest from all channels
        2. Cross-reference with Agent 1
        3. Prioritize and build queue
        4. Publish to Redis
        """
        start_time = time.time()
        all_reports: List[RawDistressReport] = []
        channel_counts: Dict[str, int] = {}
        
        # ── Step 1: Ingest from all channels ──
        
        if self.social_channel and self.social_channel.enabled:
            try:
                social_reports = await self.social_channel.ingest()
                all_reports.extend(social_reports)
                channel_counts["social_media"] = len(social_reports)
            except Exception as e:
                logger.error(f"Social media channel error: {e}")
                channel_counts["social_media"] = 0
        
        if self.sms_channel and self.sms_channel.enabled:
            try:
                sms_reports = await self.sms_channel.ingest()
                all_reports.extend(sms_reports)
                channel_counts["sms_ussd"] = len(sms_reports)
            except Exception as e:
                logger.error(f"SMS channel error: {e}")
                channel_counts["sms_ussd"] = 0
        
        if self.hotline_channel and self.hotline_channel.enabled:
            try:
                hotline_reports = await self.hotline_channel.ingest()
                all_reports.extend(hotline_reports)
                channel_counts["emergency_hotline"] = len(hotline_reports)
            except Exception as e:
                logger.error(f"Hotline channel error: {e}")
                channel_counts["emergency_hotline"] = 0
        
        if self.satellite_channel and self.satellite_channel.enabled:
            # Feed pending flood alerts to satellite channel
            if self._pending_flood_alerts:
                self.satellite_channel.load_flood_alerts(self._pending_flood_alerts)
                self._pending_flood_alerts = []
            
            try:
                sat_reports = await self.satellite_channel.ingest()
                all_reports.extend(sat_reports)
                channel_counts["satellite_population"] = len(sat_reports)
            except Exception as e:
                logger.error(f"Satellite channel error: {e}")
                channel_counts["satellite_population"] = 0
        
        logger.info(f"Ingested {len(all_reports)} total reports from {len(channel_counts)} channels")
        
        # ── Step 2: Cross-reference with Agent 1 ──
        
        cross_referenced: List[CrossReferencedDistress] = []
        if all_reports:
            cross_referenced = await self.cross_reference.cross_reference(all_reports)
        
        # ── Step 3: Prioritize and build queue ──
        
        self.prioritizer.reset_dedup_state()
        queue = self.prioritizer.build_queue(cross_referenced)
        
        # ── Step 4: Publish to Redis ──
        
        await self._publish_distress_queue(queue)
        
        # ── Step 4b: HTTP fallback — push to Agent 3 directly ──
        if queue:
            await self._http_push_to_agent3(queue)
        
        # ── Build output ──
        
        verified = sum(1 for x in cross_referenced
                       if x.verification_status.value == "verified")
        contradicted = sum(1 for x in cross_referenced
                          if x.verification_status.value == "contradicted")
        unverified = sum(1 for x in cross_referenced
                        if x.verification_status.value == "unverified")
        
        output = Agent2Output(
            total_reports_ingested=len(all_reports),
            reports_by_channel=channel_counts,
            verified_reports=verified,
            contradicted_reports=contradicted,
            unverified_reports=unverified,
            duplicate_reports=len(all_reports) - len(queue) - contradicted,
            queue_size=len(queue),
            critical_items=sum(1 for q in queue if q.urgency == UrgencyLevel.CRITICAL),
            rescue_situations=sum(1 for q in queue if q.needs_rescue),
            active_queue=queue,
            channel_status={
                "social_media": "active" if self.social_channel else "disabled",
                "sms_ussd": "active" if self.sms_channel else "disabled",
                "emergency_hotline": "active" if self.hotline_channel else "disabled",
                "satellite_population": "active" if self.satellite_channel else "disabled",
            },
            processing_time_seconds=round(time.time() - start_time, 3),
        )
        
        self.latest_output = output
        self.latest_queue = queue
        self.last_update = datetime.now(timezone.utc)  # FIX: utcnow() → now(timezone.utc)
        
        logger.info(
            f"Processing cycle complete: {len(queue)} queue items, "
            f"{output.critical_items} critical, "
            f"{output.rescue_situations} rescues, "
            f"in {output.processing_time_seconds}s"
        )
        
        return output
    
    async def _subscribe_intake(self):
        """
        Subscribe to raw_distress_intake Redis channel (published by scenario feeder).
        Routes each incoming event into the appropriate channel for processing.
        """
        if not self.redis_client:
            return

        try:
            pubsub = self.redis_client.pubsub()
            await pubsub.subscribe("raw_distress_intake")
            logger.info("Subscribed to raw_distress_intake channel (scenario feeder link)")

            async for message in pubsub.listen():
                if not self.running:
                    break
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])

                    # Skip scenario-complete markers
                    if data.get("type") == "scenario_complete":
                        logger.info("Scenario complete marker received — triggering final processing cycle")
                        await self.run_processing_cycle()
                        continue

                    source_type = data.get("source_type", "")
                    event_id = data.get("event_id", "")
                    raw_msg = data.get("raw_message", "")
                    loc_desc = data.get("location_description", "")
                    urgency = data.get("auto_detected_urgency", "medium")

                    # Extract pinpoint location from scenario event
                    scenario_loc = data.get("location", {})
                    scenario_lat = scenario_loc.get("lat")
                    scenario_lng = scenario_loc.get("lng")

                    logger.info(
                        f"Intake received: type={source_type}, event={event_id}, "
                        f"location={loc_desc}, urgency={urgency}, "
                        f"coords=({scenario_lat},{scenario_lng})"
                    )

                    # Route to the appropriate channel, passing scenario coords
                    if source_type == "call_999" and self.hotline_channel:
                        self.hotline_channel.load_simulated_calls([{
                            "zone": loc_desc or "Unknown",
                            "urgency": urgency,
                            "situation": "flood_report",
                            "people_count": data.get("people_count", 5),
                            "water_feet": data.get("water_feet", 4),
                            "notes": raw_msg,
                            "scenario_lat": scenario_lat,
                            "scenario_lng": scenario_lng,
                            "location_description": loc_desc,
                        }])

                    elif source_type == "sms" and self.sms_channel:
                        self.sms_channel.load_simulated_messages([{
                            "text": raw_msg,
                            "sender_phone": data.get("source_phone", "+880170000000"),
                            "timestamp": data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                            "scenario_lat": scenario_lat,
                            "scenario_lng": scenario_lng,
                            "location_description": loc_desc,
                        }])

                    elif source_type == "social_media" and self.social_channel:
                        self.social_channel.load_simulated_posts([{
                            "id": event_id or f"sm_{int(time.time()*1000)}",
                            "platform": "facebook",
                            "text": raw_msg,
                            "author": data.get("author", "citizen_bd"),
                            "created_at": data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                            "engagement": 100,
                            "scenario_lat": scenario_lat,
                            "scenario_lng": scenario_lng,
                            "location_description": loc_desc,
                        }])

                    else:
                        logger.warning(f"Unknown source_type '{source_type}' — skipping")
                        continue

                    # Immediately trigger a processing cycle so events flow through quickly
                    await self.run_processing_cycle()

                    # Publish status update so Gateway UI can show "processed"
                    if event_id:
                        await self.redis_client.publish("intake_status_update", json.dumps({
                            "event_id": event_id,
                            "status": "processed",
                        }))

                except json.JSONDecodeError:
                    logger.warning("Invalid JSON in raw_distress_intake message")
                except Exception as e:
                    logger.error(f"Error processing intake message: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"raw_distress_intake subscription error: {e}")

    async def start_monitoring(self):
        """Continuous monitoring loop."""
        self.running = True
        logger.info("Starting continuous monitoring...")
        
        # Start flood_alert subscription in background
        if self.redis_client:
            asyncio.create_task(self._subscribe_flood_alerts())
            asyncio.create_task(self._subscribe_intake())
        
        while self.running:
            try:
                await self.run_processing_cycle()
                await asyncio.sleep(self.config.monitoring_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitoring cycle error: {e}", exc_info=True)
                await asyncio.sleep(30)
    
    @staticmethod
    def _urgency_to_redis_priority(urgency: UrgencyLevel) -> int:
        return {
            UrgencyLevel.LOW: 1,
            UrgencyLevel.MEDIUM: 2,
            UrgencyLevel.HIGH: 4,
            UrgencyLevel.CRITICAL: 5,
        }.get(urgency, 2)


# =====================================================================
# FASTAPI APPLICATION
# =====================================================================

agent: Optional[DistressIntelligenceAgent] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    config = Agent2Config()
    agent = DistressIntelligenceAgent(config)
    await agent.startup()
    agent.monitoring_task = asyncio.create_task(agent.start_monitoring())
    yield
    await agent.shutdown()


app = FastAPI(
    title="Distress Intelligence Agent",
    description=(
        "Agent 2: Multi-channel distress aggregation — "
        "Social Media, SMS/USSD, 999 Hotline, Satellite+Population"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allows demo_console.html to call the API from a browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Endpoints ──

@app.get("/")
async def root():
    return {
        "agent": "Distress Intelligence Agent",
        "status": "operational",
        "version": "1.0.0",
        "channels": ["social_media", "sms_ussd", "emergency_hotline", "satellite_population"],
    }


@app.get("/health", response_model=Agent2HealthCheck)
async def health_check():
    global agent
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    return Agent2HealthCheck(
        status="healthy",
        channels_active={
            "social_media": agent.social_channel is not None,
            "sms_ussd": agent.sms_channel is not None,
            "emergency_hotline": agent.hotline_channel is not None,
            "satellite_population": agent.satellite_channel is not None,
        },
        redis_connected=agent.redis_client is not None,
        database_connected=False,  # Agent 2 doesn't need direct DB access
        agent1_reachable=True,  # TODO: actual health check
    )


@app.get("/output", response_model=Agent2Output)
async def get_output():
    global agent
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    if not agent.latest_output:
        raise HTTPException(status_code=404, detail="No output yet")
    return agent.latest_output


@app.get("/queue", response_model=List[DistressQueueItem])
async def get_queue():
    """Get current prioritized distress queue."""
    global agent
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return agent.latest_queue


@app.post("/trigger")
async def trigger_cycle():
    """Manually trigger a processing cycle."""
    global agent
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    try:
        output = await agent.run_processing_cycle()
        return {
            "message": "Processing cycle completed",
            "queue_size": output.queue_size if output else 0,
            "critical_items": output.critical_items if output else 0,
        }
    except Exception as e:
        logger.error(f"Triggered cycle failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest/social_media")
async def ingest_social_media(posts: List[Dict[str, Any]]):
    """Manually feed social media posts for processing."""
    global agent
    if not agent or not agent.social_channel:
        raise HTTPException(status_code=503, detail="Social media channel not available")
    agent.social_channel.load_simulated_posts(posts)
    return {"message": f"Loaded {len(posts)} social media posts"}


@app.post("/ingest/sms")
async def ingest_sms(messages: List[Dict[str, Any]]):
    """Manually feed SMS messages for processing."""
    global agent
    if not agent or not agent.sms_channel:
        raise HTTPException(status_code=503, detail="SMS channel not available")
    agent.sms_channel.load_simulated_messages(messages)
    return {"message": f"Loaded {len(messages)} SMS messages"}


@app.post("/ingest/hotline")
async def ingest_hotline(calls: List[Dict[str, Any]]):
    """Manually feed 999 call records for processing."""
    global agent
    if not agent or not agent.hotline_channel:
        raise HTTPException(status_code=503, detail="Hotline channel not available")
    agent.hotline_channel.load_simulated_calls(calls)
    return {"message": f"Loaded {len(calls)} call records"}


@app.post("/ingest/flood_alerts")
async def ingest_flood_alerts(alerts: List[Dict[str, Any]]):
    """Manually feed Agent 1 flood alerts for satellite+population channel."""
    global agent
    if not agent or not agent.satellite_channel:
        raise HTTPException(status_code=503, detail="Satellite channel not available")
    agent.satellite_channel.load_flood_alerts(alerts)
    return {"message": f"Loaded {len(alerts)} flood alerts"}


@app.post("/flood_data")
async def set_flood_data(data: Dict[str, Dict[str, Any]]):
    """Set Agent 1 flood data directly (for testing cross-referencing)."""
    global agent
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    agent.cross_reference.set_flood_data(data)
    return {"message": f"Flood data set for {len(data)} zones"}


# =====================================================================
# SCRIPTED DEMO SCENARIO — "Bangladesh Monsoon 2024"
# =====================================================================

@app.post("/scenario/monsoon2024")
async def run_monsoon_scenario():
    """
    One-button scripted demo that plays the full pipeline story:
    1. Satellite alerts verify flood zones
    2. SMS distress reports arrive
    3. Social media posts flood in
    4. 999 hotline calls come through
    5. Processing cycle cross-references, prioritizes, allocates, dispatches
    Returns progress events as they happen.
    """
    global agent
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    log = []

    # ── Step 0: Reset Agent 3 inventory for clean demo ──
    try:
        import httpx
        agent3_url = os.getenv("AGENT3_URL", "http://agent3:8003")
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(f"{agent3_url}/inventory/reset")
            if r.status_code == 200:
                log.append({"step": 0, "action": "reset_inventory", "detail": r.json()})
    except Exception as e:
        log.append({"step": 0, "action": "reset_inventory", "detail": f"skip: {e}"})

    # ── Step 1: Satellite flood alerts (verifies zones) ──
    flood_alerts = [
        {"zone_name": "Mirpur",       "risk_score": 0.82, "flood_pct": 35, "water_depth_m": 1.2,
         "latitude": 23.8223, "longitude": 90.3654, "source": "sentinel_1_sar"},
        {"zone_name": "Jatrabari",    "risk_score": 0.91, "flood_pct": 52, "water_depth_m": 1.8,
         "latitude": 23.7104, "longitude": 90.4348, "source": "sentinel_1_sar"},
        {"zone_name": "Demra",        "risk_score": 0.88, "flood_pct": 45, "water_depth_m": 1.5,
         "latitude": 23.7225, "longitude": 90.4968, "source": "sentinel_1_sar"},
        {"zone_name": "Uttara",       "risk_score": 0.65, "flood_pct": 18, "water_depth_m": 0.6,
         "latitude": 23.8759, "longitude": 90.3795, "source": "sentinel_1_sar"},
        {"zone_name": "Mohammadpur",  "risk_score": 0.58, "flood_pct": 12, "water_depth_m": 0.4,
         "latitude": 23.7662, "longitude": 90.3589, "source": "sentinel_1_sar"},
        {"zone_name": "Badda",        "risk_score": 0.72, "flood_pct": 22, "water_depth_m": 0.8,
         "latitude": 23.7806, "longitude": 90.4261, "source": "sentinel_1_sar"},
        {"zone_name": "Dhanmondi",    "risk_score": 0.42, "flood_pct": 8,  "water_depth_m": 0.3,
         "latitude": 23.7461, "longitude": 90.3742, "source": "sentinel_1_sar"},
        {"zone_name": "Sylhet",       "risk_score": 0.95, "flood_pct": 68, "water_depth_m": 2.5,
         "latitude": 24.8949, "longitude": 91.8687, "source": "sentinel_1_sar"},
        {"zone_name": "Sunamganj",    "risk_score": 0.93, "flood_pct": 72, "water_depth_m": 3.0,
         "latitude": 25.0715, "longitude": 91.3950, "source": "sentinel_1_sar"},
    ]
    if agent.satellite_channel:
        agent.satellite_channel.load_flood_alerts(flood_alerts)
    # Also set cross-reference flood data so zones get VERIFIED
    flood_data = {}
    for a in flood_alerts:
        flood_data[a["zone_name"].lower()] = {
            "risk_score": a["risk_score"],
            "flood_pct": a["flood_pct"],
            "flood_depth_m": a["water_depth_m"],
            "severity": "critical" if a["risk_score"] >= 0.9 else "high",
            "verified": True,
        }
    agent.cross_reference.set_flood_data(flood_data)
    log.append({"step": 1, "action": "satellite_alerts", "detail": f"{len(flood_alerts)} zones verified"})

    await asyncio.sleep(0.5)

    # ── Step 2: SMS distress reports ──
    sms_messages = [
        {"text": "FLOOD MIRPUR 4FT 6 ROOFTOP", "sender_phone": "+8801711000001", "timestamp": datetime.now(timezone.utc).isoformat()},
        {"text": "FLOOD JATRABARI 6FT 12 TRAPPED", "sender_phone": "+8801711000002", "timestamp": datetime.now(timezone.utc).isoformat()},
        {"text": "FLOOD DEMRA 5FT 15 EVACUATE", "sender_phone": "+8801711000003", "timestamp": datetime.now(timezone.utc).isoformat()},
        {"text": "FLOOD SYLHET 8FT 20 ROOFTOP", "sender_phone": "+8801711000004", "timestamp": datetime.now(timezone.utc).isoformat()},
        {"text": "FLOOD SUNAMGANJ 10FT 30 TRAPPED", "sender_phone": "+8801711000005", "timestamp": datetime.now(timezone.utc).isoformat()},
    ]
    if agent.sms_channel:
        agent.sms_channel.load_simulated_messages(sms_messages)
    log.append({"step": 2, "action": "sms_distress", "detail": f"{len(sms_messages)} SMS loaded"})

    await asyncio.sleep(0.3)

    # ── Step 3: Social media posts ──
    try:
        from SAMPLE_DATA import SOCIAL_MEDIA_POSTS
        social_posts = SOCIAL_MEDIA_POSTS
    except ImportError:
        social_posts = [
            {"id":"fb_001","platform":"facebook","text":"মিরপুর ১২ নম্বর সেক্টরে পানি উঠে গেছে! 😱","author":"Ahmed_Mirpur","created_at":"2024-09-15T14:30:00","engagement":156,"has_media":True},
            {"id":"fb_002","platform":"facebook","text":"URGENT! 5 families stranded on rooftop in Pallabi, Mirpur! Water is chest deep! 🆘","author":"FloodWatch_BD","created_at":"2024-09-15T15:00:00","engagement":843,"has_media":True},
            {"id":"fb_005","platform":"facebook","text":"জাত্রাবাড়ী এলাকায় ভয়াবহ বন্যা! পানি ৬ ফুট! একটা বাড়ি ভেঙে পড়েছে!","author":"jatrabari_crisis","created_at":"2024-09-15T15:30:00","engagement":2105,"has_media":True},
            {"id":"fb_007","platform":"facebook","text":"Demra industrial area te heavy flooding. 30 workers trapped upstairs.","author":"demra_news","created_at":"2024-09-15T15:45:00","engagement":312},
            {"id":"fb_009","platform":"facebook","text":"HELP! Badda Gulshan link road completely flooded! Rescue boat needed!","author":"badda_help","created_at":"2024-09-15T15:20:00","engagement":534,"has_media":True},
        ]
    if agent.social_channel:
        agent.social_channel.load_simulated_posts(social_posts)
    log.append({"step": 3, "action": "social_media", "detail": f"{len(social_posts)} posts loaded"})

    await asyncio.sleep(0.3)

    # ── Step 4: 999 hotline calls ──
    hotline_calls = [
        {"zone": "Mirpur",    "urgency": "critical", "situation": "stranded",
         "people_count": 5,   "water_feet": 5, "notes": "Elderly trapped on 2nd floor, one needs insulin urgently"},
        {"zone": "Jatrabari", "urgency": "critical", "situation": "structural_collapse",
         "people_count": 20,  "water_feet": 6, "notes": "Building collapse near Kadamtali bridge. Multiple families trapped"},
        {"zone": "Demra",     "urgency": "high",     "situation": "evacuation",
         "people_count": 30,  "water_feet": 4, "notes": "Garment factory workers moved to upper floor, need evacuation"},
    ]
    if agent.hotline_channel:
        agent.hotline_channel.load_simulated_calls(hotline_calls)
    log.append({"step": 4, "action": "hotline_999", "detail": f"{len(hotline_calls)} calls loaded"})

    await asyncio.sleep(0.3)

    # ── Step 5: Trigger processing cycle ──
    try:
        output = await agent.run_processing_cycle()
        log.append({
            "step": 5, "action": "processing_cycle",
            "detail": {
                "reports_ingested": output.total_reports_ingested,
                "queue_size": output.queue_size,
                "verified": output.verified_reports,
                "critical": output.critical_items,
            },
        })
    except Exception as e:
        log.append({"step": 5, "action": "processing_cycle", "detail": f"error: {e}"})

    return {
        "scenario": "Bangladesh Monsoon 2024",
        "status": "completed",
        "steps": log,
        "message": "Full pipeline executed: satellite → SMS → social → hotline → process → allocate → dispatch",
    }


# =====================================================================
# MAIN
# =====================================================================

def main():
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8002,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()