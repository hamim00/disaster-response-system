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
            logger.info("Redis connected")
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
                
                self.redis_client.publish(
                    "distress_queue",
                    message.model_dump_json(),
                )
                
                # Also log to agent_messages (for dashboard)
                self.redis_client.rpush(
                    "agent_messages_log",
                    message.model_dump_json(),
                )
                
            except Exception as e:
                logger.error(f"Failed to publish distress item: {e}")
        
        logger.info(f"Published {len(queue)} items to distress_queue")
    
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
    
    async def start_monitoring(self):
        """Continuous monitoring loop."""
        self.running = True
        logger.info("Starting continuous monitoring...")
        
        # Start flood_alert subscription in background
        if self.redis_client:
            asyncio.create_task(self._subscribe_flood_alerts())
        
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
async def trigger_cycle(background_tasks: BackgroundTasks):
    """Manually trigger a processing cycle."""
    global agent
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    background_tasks.add_task(agent.run_processing_cycle)
    return {"message": "Processing cycle triggered"}


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