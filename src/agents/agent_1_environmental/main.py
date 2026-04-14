"""
Environmental Intelligence Agent - Main Orchestrator
===================================================
Agent 1: Real-time environmental monitoring and flood prediction.
Coordinates data collection, processing, analysis, and prediction.

Author: Environmental Intelligence Team
Version: 1.0.0
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, cast
import signal
import sys
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncpg
from redis import asyncio as aioredis
import uvicorn

# Import all components
from models import (
    AgentOutput, SentinelZone, GeoPoint, SeverityLevel,
    HealthCheckResponse, MonitoringStatus
)
from data_collectors import (
    WeatherAPICollector,
    SocialMediaCollector,
    DataCollectionOrchestrator
)
from services.satellite_service import SatelliteDataCollector
from data_processors import (
    LLMEnrichmentProcessor,
    WeatherDataNormalizer,
    SocialMediaAnalyzer,
    DataProcessingOrchestrator
)
from spatial_analyzer import PostGISSpatialAnalyzer
from predictor import (
    FloodRiskPredictor,
    AlertGenerator,
    PredictionOrchestrator
)
from river_monitor import RiverMonitor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('agent_1_environmental.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


# =====================================================================
# CONFIGURATION
# =====================================================================

class AgentConfig:
    """Agent configuration from environment variables"""
    
    def __init__(self):
        """Load configuration from environment"""
        import os
        from dotenv import load_dotenv
        from pathlib import Path
    
        # Debug: Show current directory
        current_dir = os.getcwd()
        print(f"🔍 DEBUG: Current directory = {current_dir}")
    
        # Debug: Check if .env exists
        env_path = Path('.env')
        print(f"🔍 DEBUG: .env exists in current dir = {env_path.exists()}")
    
        # Load .env file
        loaded = load_dotenv()
        print(f"🔍 DEBUG: load_dotenv() returned = {loaded}")
    
        # API Keys
        self.openweather_api_key = os.getenv('OPENWEATHER_API_KEY')
        self.twitter_bearer_token = os.getenv('TWITTER_BEARER_TOKEN')
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
    
        # Database
        self.database_url = os.getenv(
            'DATABASE_URL',
            'postgresql://user:password@postgres:5432/disaster_response'
        )
    
    # Debug: Show what DATABASE_URL was loaded
        print(f"🔍 DEBUG: DATABASE_URL = {self.database_url}")
    
        # Redis
        self.redis_url = os.getenv('REDIS_URL', 'redis://redis:6379')
    
        # Agent Settings
        self.agent_id = os.getenv('AGENT_ID', 'agent_1_environmental')
        self.monitoring_interval = int(os.getenv('MONITORING_INTERVAL', '300'))
        self.enable_adaptive_polling = os.getenv('ENABLE_ADAPTIVE_POLLING', 'true').lower() == 'true'
    
        # Validate required config
        self._validate()

        # Tell type checkers these values are non-None after validation
        self.openweather_api_key = cast(str, self.openweather_api_key)
        self.twitter_bearer_token = cast(str, self.twitter_bearer_token)
        self.openai_api_key = cast(str, self.openai_api_key)
    
    def _validate(self):
        """Validate required configuration"""
        required = {
            'OPENWEATHER_API_KEY': self.openweather_api_key,
            'TWITTER_BEARER_TOKEN': self.twitter_bearer_token,
            'OPENAI_API_KEY': self.openai_api_key
        }
        
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Missing required configuration: {', '.join(missing)}")


# =====================================================================
# ENVIRONMENTAL INTELLIGENCE AGENT
# =====================================================================

class EnvironmentalIntelligenceAgent:
    """
    Main agent class coordinating all environmental monitoring operations.
    Implements adaptive polling, prediction, and alert generation.
    """
    
    def __init__(self, config: AgentConfig):
        """
        Initialize the agent with all components.
        
        Args:
            config: Agent configuration
        """
        self.config = config
        self.running = False
        self.monitoring_task: Optional[asyncio.Task] = None
        
        # Component instances (initialized in startup)
        self.db_pool: Optional[asyncpg.Pool] = None
        self.redis_client: Optional[aioredis.Redis] = None
        self.weather_collector: Optional[WeatherAPICollector] = None
        self.social_collector: Optional[SocialMediaCollector] = None
        self.collection_orchestrator: Optional[DataCollectionOrchestrator] = None
        self.satellite_collector: Optional[SatelliteDataCollector] = None
        self.llm_processor: Optional[LLMEnrichmentProcessor] = None
        self.weather_normalizer: Optional[WeatherDataNormalizer] = None
        self.social_analyzer: Optional[SocialMediaAnalyzer] = None
        self.processing_orchestrator: Optional[DataProcessingOrchestrator] = None
        self.spatial_analyzer: Optional[PostGISSpatialAnalyzer] = None
        self.flood_predictor: Optional[FloodRiskPredictor] = None
        self.alert_generator: Optional[AlertGenerator] = None
        self.prediction_orchestrator: Optional[PredictionOrchestrator] = None
        
        # River discharge monitor (GloFAS via Open-Meteo)
        self.river_monitor: Optional[RiverMonitor] = None
        self.river_monitoring_task: Optional[asyncio.Task] = None
        
        # Sentinel zones (loaded from database or config)
        self.sentinel_zones: List[SentinelZone] = []
        
        # Latest output
        self.latest_output: Optional[AgentOutput] = None
        self.last_update: Optional[datetime] = None
        
        logger.info(f"Agent {config.agent_id} initialized")
    
    async def startup(self):
        """Initialize all components and connections (graceful degradation)"""
        logger.info("Starting up Environmental Intelligence Agent...")
        
        # ── Database (optional — degrade gracefully) ──
        try:
            self.db_pool = await asyncpg.create_pool(
                self.config.database_url,
                min_size=2,
                max_size=10,
                timeout=5,
            )
            await self.db_pool.fetchval("SELECT 1")
            logger.info("Database connection pool created")
        except Exception as e:
            logger.warning(f"Database unavailable: {e} -- running without DB")
            self.db_pool = None
        
        # ── Redis (optional — degrade gracefully) ──
        try:
            self.redis_client = await aioredis.from_url(
                self.config.redis_url,
                decode_responses=True,
            )
            await self.redis_client.ping()
            logger.info("Redis connected and verified")
        except Exception as e:
            logger.warning(f"Redis unavailable: {e} -- running without cache/pubsub")
            self.redis_client = None
        
        # ── Data collectors ──
        try:
            self.weather_collector = WeatherAPICollector(
                api_key=cast(str, self.config.openweather_api_key),
                cache_client=self.redis_client
            )
            logger.info("Weather collector initialized")
        except Exception as e:
            logger.warning(f"Weather collector failed: {e}")
        
        # Twitter/X disabled — bearer token expired, not needed for flood pipeline
        self.social_collector = None
        logger.info("Social media collector disabled (Twitter removed)")
        
        # Satellite collector (GEE + CNN flood detection)
        try:
            self.satellite_collector = SatelliteDataCollector(
                cache_client=self.redis_client
            )
            logger.info("Satellite collector initialized")
        except Exception as e:
            logger.warning(f"Satellite collector unavailable: {e} -- continuing without satellite data")
            self.satellite_collector = None
        
        self.collection_orchestrator = DataCollectionOrchestrator(
            weather_collector=self.weather_collector,
            social_collector=self.social_collector,
            satellite_collector=self.satellite_collector
        )
        logger.info("Data collectors initialized")
        
        # ── Data processors ──
        try:
            self.llm_processor = LLMEnrichmentProcessor(
                api_key=cast(str, self.config.openai_api_key)
            )
        except Exception as e:
            logger.warning(f"LLM processor failed: {e}")
        
        self.weather_normalizer = WeatherDataNormalizer()
        self.social_analyzer = SocialMediaAnalyzer()
        
        self.processing_orchestrator = DataProcessingOrchestrator(
            llm_processor=self.llm_processor,
            weather_normalizer=self.weather_normalizer,
            social_analyzer=self.social_analyzer
        )
        logger.info("Data processors initialized")
        
        # ── Spatial analyzer (needs DB) ──
        if self.db_pool:
            try:
                self.spatial_analyzer = PostGISSpatialAnalyzer(
                    db_pool=cast(asyncpg.Pool, self.db_pool)
                )
                await self.spatial_analyzer.initialize_schema()
                logger.info("Spatial analyzer initialized")
            except Exception as e:
                logger.warning(f"Spatial analyzer failed: {e}")
                self.spatial_analyzer = None
        else:
            logger.warning("Spatial analyzer skipped (no database)")
        
        # ── Predictors ──
        self.flood_predictor = FloodRiskPredictor()
        self.alert_generator = AlertGenerator()
        
        self.prediction_orchestrator = PredictionOrchestrator(
            predictor=self.flood_predictor,
            alert_generator=self.alert_generator
        )
        logger.info("Prediction system initialized")
        
        # ── River discharge monitor (GloFAS) ──
        try:
            self.river_monitor = RiverMonitor({})
            # Pre-fetch river data so it's ready for the first monitoring cycle
            await self.river_monitor._poll_all_zones()
            logger.info("River discharge monitor initialized (initial poll complete)")
        except Exception as e:
            logger.warning(f"River monitor failed to init: {e}")
            self.river_monitor = None
        
        # ── Load sentinel zones ──
        try:
            await self.load_sentinel_zones()
        except Exception as e:
            logger.warning(f"Sentinel zones failed to load: {e} -- using defaults")
            self.sentinel_zones = self._create_default_zones()
        
        logger.info("Agent startup complete")
    
    async def shutdown(self):
        """Cleanup and close all connections"""
        logger.info("Shutting down Environmental Intelligence Agent...")
        
        self.running = False
        
        # Cancel monitoring task
        if self.monitoring_task and not self.monitoring_task.done():
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        # Cancel river monitoring task
        if self.river_monitoring_task and not self.river_monitoring_task.done():
            self.river_monitoring_task.cancel()
            try:
                await self.river_monitoring_task
            except asyncio.CancelledError:
                pass
        if self.river_monitor:
            self.river_monitor.stop_monitoring()
        
        # Close connections
        if self.db_pool:
            await self.db_pool.close()
            logger.info("Database pool closed")
        
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Redis connection closed")
        
        logger.info("Agent shutdown complete")
    
    async def load_sentinel_zones(self):
        """Load sentinel zones from database or create default zones."""
        REQUIRED_ZONES = {"Mirpur", "Uttara", "Mohammadpur", "Dhanmondi",
                          "Badda", "Jatrabari", "Demra", "Sylhet", "Sunamganj"}

        if self.db_pool is None:
            self.sentinel_zones = self._create_default_zones()
            logger.info(f"Created {len(self.sentinel_zones)} default sentinel zones (no DB)")
            return

        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM sentinel_zones;")
            existing_names = {row['name'] for row in rows} if rows else set()

            # If DB zones are stale (missing required zones), recreate
            if not REQUIRED_ZONES.issubset(existing_names):
                logger.info(f"DB has {existing_names} but need {REQUIRED_ZONES} -- recreating zones")
                # Clear dependent tables first, then zones
                await conn.execute("DELETE FROM flood_predictions;")
                await conn.execute("DELETE FROM weather_data;")
                await conn.execute("DELETE FROM social_media_posts;")
                await conn.execute("DELETE FROM sentinel_zones;")
                self.sentinel_zones = self._create_default_zones()
                if self.spatial_analyzer:
                    for zone in self.sentinel_zones:
                        await cast(PostGISSpatialAnalyzer, self.spatial_analyzer).store_sentinel_zone(zone)
                logger.info(f"Created {len(self.sentinel_zones)} sentinel zones (matched to Agent 2)")
            elif rows:
                self.sentinel_zones = [
                    SentinelZone(
                        id=row['id'],
                        name=row['name'],
                        center=GeoPoint(
                            latitude=await conn.fetchval(
                                "SELECT ST_Y($1::geometry);", row['center']
                            ),
                            longitude=await conn.fetchval(
                                "SELECT ST_X($1::geometry);", row['center']
                            )
                        ),
                        radius_km=row['radius_km'],
                        risk_level=SeverityLevel(row['risk_level']),
                        population_density=row['population_density'],
                        elevation=row['elevation'],
                        drainage_capacity=row['drainage_capacity'],
                        created_at=row['created_at'],
                        last_monitored=row['last_monitored']
                    )
                    for row in rows
                ]
                logger.info(f"Loaded {len(self.sentinel_zones)} sentinel zones from database")
    
    def _create_default_zones(self) -> List[SentinelZone]:
        """
        Default sentinel zones for Bangladesh flood monitoring.
        MUST match Agent 2's ZONE_COORDS so cross-referencing works.
        Agents 2/3/4 use these same zone names and coordinates.
        """
        return [
            SentinelZone(
                name="Mirpur",
                center=GeoPoint(latitude=23.8223, longitude=90.3654),
                radius_km=4.0,
                risk_level=SeverityLevel.HIGH,
                population_density=52000,
                elevation=4.0,
                drainage_capacity="poor"
            ),
            SentinelZone(
                name="Uttara",
                center=GeoPoint(latitude=23.8759, longitude=90.3795),
                radius_km=4.5,
                risk_level=SeverityLevel.MODERATE,
                population_density=42000,
                elevation=7.0,
                drainage_capacity="moderate"
            ),
            SentinelZone(
                name="Mohammadpur",
                center=GeoPoint(latitude=23.7662, longitude=90.3589),
                radius_km=4.0,
                risk_level=SeverityLevel.MODERATE,
                population_density=48000,
                elevation=5.0,
                drainage_capacity="poor"
            ),
            SentinelZone(
                name="Dhanmondi",
                center=GeoPoint(latitude=23.7461, longitude=90.3742),
                radius_km=3.0,
                risk_level=SeverityLevel.LOW,
                population_density=38000,
                elevation=7.0,
                drainage_capacity="moderate"
            ),
            SentinelZone(
                name="Badda",
                center=GeoPoint(latitude=23.7806, longitude=90.4261),
                radius_km=3.5,
                risk_level=SeverityLevel.MODERATE,
                population_density=40000,
                elevation=5.5,
                drainage_capacity="poor"
            ),
            SentinelZone(
                name="Jatrabari",
                center=GeoPoint(latitude=23.7104, longitude=90.4348),
                radius_km=3.5,
                risk_level=SeverityLevel.HIGH,
                population_density=55000,
                elevation=3.5,
                drainage_capacity="poor"
            ),
            SentinelZone(
                name="Demra",
                center=GeoPoint(latitude=23.7225, longitude=90.4968),
                radius_km=4.0,
                risk_level=SeverityLevel.HIGH,
                population_density=35000,
                elevation=3.0,
                drainage_capacity="poor"
            ),
            SentinelZone(
                name="Sylhet",
                center=GeoPoint(latitude=24.8949, longitude=91.8687),
                radius_km=6.0,
                risk_level=SeverityLevel.CRITICAL,
                population_density=15000,
                elevation=2.0,
                drainage_capacity="poor"
            ),
            SentinelZone(
                name="Sunamganj",
                center=GeoPoint(latitude=25.0715, longitude=91.3950),
                radius_km=6.0,
                risk_level=SeverityLevel.CRITICAL,
                population_density=8000,
                elevation=1.5,
                drainage_capacity="poor"
            ),
        ]
    
    async def run_monitoring_cycle(self) -> AgentOutput:
        """
        Execute one complete monitoring cycle.
        
        Returns:
            Agent output with predictions and alerts
        """
        cycle_start = datetime.utcnow()
        logger.info("=" * 60)
        logger.info("Starting monitoring cycle")
        
        try:
            # Step 1: Collect data from all sources
            logger.info("Step 1: Collecting data...")
            assert self.collection_orchestrator is not None, "DataCollectionOrchestrator not initialized"
            collected_data = await self.collection_orchestrator.collect_all_zones(
                self.sentinel_zones
            )
            
            # Step 2: Process and enrich data
            logger.info("Step 2: Processing and enriching data...")
            assert self.processing_orchestrator is not None, "DataProcessingOrchestrator not initialized"
            processed_data = await self.processing_orchestrator.process_all_zones(
                collected_data
            )
            
            # Step 3: Perform spatial analysis
            logger.info("Step 3: Performing spatial analysis...")
            spatial_results = {}
            satellite_summary = {}
            for data in processed_data:
                zone = data['zone']
                
                # Store weather and social data (skip if no DB/spatial analyzer)
                if self.spatial_analyzer and data.get('weather'):
                    try:
                        await cast(PostGISSpatialAnalyzer, self.spatial_analyzer).store_weather_data(
                            data['weather'],
                            str(zone.id)
                        )
                    except Exception as e:
                        logger.warning(f"Failed to store weather data for {zone.name}: {e}")
                
                if self.spatial_analyzer:
                    for post in data.get('enriched_posts', []):
                        try:
                            await cast(PostGISSpatialAnalyzer, self.spatial_analyzer).store_social_post(
                                post,
                                str(zone.id)
                            )
                        except Exception as e:
                            logger.warning(f"Failed to store social post for {zone.name}: {e}")
                
                # Carry satellite data forward for prediction
                # (it was collected in Step 1 alongside weather+social)
                sat = data.get('satellite')
                if sat and hasattr(sat, 'flood_detection') and sat.flood_detection:
                    fd = sat.flood_detection
                    satellite_summary[str(zone.id)] = {
                        'risk_level': fd.risk_level,
                        'flood_pct': fd.flood_percentage,
                        'flood_area_km2': fd.flood_area_km2,
                        'confidence': fd.confidence,
                        'status': fd.status,
                    }
                    data['satellite_risk'] = fd.risk_level
                    data['satellite_flood_pct'] = fd.flood_percentage
                    data['satellite_flood_area_km2'] = fd.flood_area_km2
                
                # Perform spatial analysis
                if self.spatial_analyzer:
                    try:
                        spatial_result = await cast(PostGISSpatialAnalyzer, self.spatial_analyzer).analyze_zone_spatial_patterns(
                            zone
                        )
                        spatial_results[str(zone.id)] = spatial_result
                        data['spatial_analysis'] = spatial_result
                    except Exception as e:
                        logger.warning(f"Spatial analysis failed for {zone.name}: {e}")
            
            if satellite_summary:
                logger.info(f"   Satellite data merged for {len(satellite_summary)} zones")
            
            # Merge river discharge data (from GloFAS monitor)
            river_status = {}
            if self.river_monitor:
                river_status = self.river_monitor.get_latest_river_status()
                if river_status:
                    logger.info(f"   River discharge data available for {len(river_status)} zones")
                for data in processed_data:
                    zone = data['zone']
                    zone_name_lower = zone.name.lower()
                    river_data = river_status.get(zone_name_lower)
                    if river_data:
                        data['river_discharge'] = river_data
                        logger.info(
                            f"   [RIVER] {zone.name}: "
                            f"{river_data['current_discharge_m3s']} m³/s "
                            f"({river_data['threshold_level']}, "
                            f"p{river_data['percentile_rank']:.0f})"
                        )
            
            # Step 4: Get historical risk scores
            logger.info("Step 4: Retrieving historical risk scores...")
            historical_risks = {}
            for zone in self.sentinel_zones:
                risk = await self.spatial_analyzer.get_historical_risk_score(zone)
                historical_risks[str(zone.id)] = risk
            
            # Step 5: Generate predictions and alerts
            logger.info("Step 5: Generating predictions and alerts...")
            assert self.prediction_orchestrator is not None, "PredictionOrchestrator not initialized"
            predictions, alerts = await self.prediction_orchestrator.predict_all_zones(
                processed_data,
                historical_risks
            )
            
            # Step 6: Store predictions in database
            logger.info("Step 6: Storing predictions...")
            for prediction in predictions:
                if self.db_pool is None:
                    logger.error("Database pool is not initialized.")
                    continue
                async with self.db_pool.acquire() as conn:
                    await conn.execute("""
                        INSERT INTO flood_predictions (
                            id, zone_id, timestamp, risk_score, severity_level,
                            confidence, time_to_impact_hours, affected_area_km2,
                            risk_factors, recommended_actions
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10);
                    """,
                        prediction.id,
                        prediction.zone.id,
                        prediction.timestamp,
                        prediction.risk_score,
                        prediction.severity_level.value,
                        prediction.confidence,
                        prediction.time_to_impact_hours,
                        prediction.affected_area_km2,
                        prediction.risk_factors.model_dump_json(),
                        json.dumps(prediction.recommended_actions)
                    )
            
            # Update zone monitoring timestamps
            for zone in self.sentinel_zones:
                zone.last_monitored = datetime.utcnow()
                await self.spatial_analyzer.store_sentinel_zone(zone)
            
            # Step 7: Publish flood alerts to Redis for Agent 2
            logger.info("Step 7: Publishing flood alerts to Redis...")
            if self.redis_client:
                published_count = 0
                for prediction, pdata in zip(predictions, processed_data):
                    zone = prediction.zone
                    zone_name_lower = zone.name.lower()
                    
                    # Build data_sources dict
                    data_sources = {}
                    
                    # Weather
                    weather = pdata.get('weather')
                    if weather:
                        data_sources['weather'] = {
                            'rainfall_mm': getattr(weather, 'rainfall', 0) or 0,
                            'alert_level': pdata.get('normalized_weather', {}).get(
                                'weather_severity_label', 'NORMAL'
                            ),
                        }
                    
                    # Satellite
                    sat_flood_pct = pdata.get('satellite_flood_pct', 0.0) or 0.0
                    if pdata.get('satellite_risk'):
                        data_sources['satellite'] = {
                            'flood_area_pct': sat_flood_pct,
                            'risk_level': pdata.get('satellite_risk', 'MINIMAL'),
                        }
                    
                    # Social media
                    social = pdata.get('social_analysis', {})
                    if social.get('flood_reports', 0) > 0:
                        data_sources['social_media'] = {
                            'flood_reports': social.get('flood_reports', 0),
                            'urgency': social.get('urgency_label', 'LOW'),
                        }
                    
                    # River discharge
                    river = pdata.get('river_discharge')
                    if river:
                        data_sources['river_discharge'] = {
                            'current_m3s': river['current_discharge_m3s'],
                            'forecast_peak_m3s': river['forecast_peak_m3s'],
                            'forecast_peak_date': river['forecast_peak_date'],
                            'percentile_rank': river['percentile_rank'],
                            'threshold_level': river['threshold_level'],
                            'trend': river['trend'],
                            'days_rising': river['days_rising'],
                        }
                    
                    # Build flood alert message (matches Agent 2 expected format)
                    flood_alert = {
                        'zone_id': zone_name_lower,
                        'zone_name': zone.name,
                        'flood_pct': sat_flood_pct,
                        'flood_depth_m': pdata.get('depth_analysis', {}).get(
                            'statistics', {}
                        ).get('mean_depth_m'),
                        'risk_score': prediction.risk_score,
                        'severity': prediction.severity_level.value,
                        'confidence': prediction.confidence,
                        'coordinates': {
                            'lat': zone.center.latitude,
                            'lon': zone.center.longitude,
                        },
                        'data_sources': data_sources,
                        'timestamp': datetime.utcnow().isoformat(),
                    }
                    
                    await self.redis_client.publish(
                        'flood_alert', json.dumps(flood_alert)
                    )
                    published_count += 1
                
                logger.info(f"   Published {published_count} flood alerts to Redis")
            else:
                logger.warning("   Redis unavailable — skipping flood_alert publish")
            
            # Calculate processing time
            processing_time = (datetime.utcnow() - cycle_start).total_seconds()
            
            # Determine next update interval (adaptive polling)
            next_update = self._calculate_next_update_interval(predictions)
            
            # Create agent output
            output = AgentOutput(
                agent_id=self.config.agent_id,
                timestamp=datetime.utcnow(),
                predictions=predictions,
                alerts=alerts,
                monitored_zones=self.sentinel_zones,
                data_sources_status={
                    'weather_api': 'operational',
                    'social_media': 'operational',
                    'spatial_db': 'operational',
                    'satellite_gee': 'operational' if satellite_summary else 'unavailable',
                    'river_discharge': 'operational' if river_status else 'unavailable'
                },
                processing_time_seconds=processing_time,
                next_update_in_seconds=next_update
            )
            
            # Store as latest output
            self.latest_output = output
            self.last_update = datetime.utcnow()
            
            # Log summary
            logger.info(f"Monitoring cycle complete in {processing_time:.2f}s")
            logger.info(f"   Predictions: {len(predictions)}")
            logger.info(f"   Alerts: {len(alerts)} ({len(output.critical_alerts)} critical)")
            logger.info(f"   Next update in: {next_update}s")
            logger.info("=" * 60)
            
            return output
        
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {e}", exc_info=True)
            raise
    
    def _calculate_next_update_interval(
        self,
        predictions: List
    ) -> float:
        """Calculate adaptive polling interval based on predictions"""
        if not self.config.enable_adaptive_polling:
            return self.config.monitoring_interval
        
        # Find highest risk level
        max_severity = SeverityLevel.MINIMAL
        for pred in predictions:
            if pred.severity_level.value > max_severity.value:
                max_severity = pred.severity_level
        
        # Map severity to interval
        intervals = {
            SeverityLevel.CRITICAL: 60,      # 1 minute
            SeverityLevel.HIGH: 180,         # 3 minutes
            SeverityLevel.MODERATE: 300,     # 5 minutes
            SeverityLevel.LOW: 900,          # 15 minutes
            SeverityLevel.MINIMAL: 1800      # 30 minutes
        }
        
        return intervals.get(max_severity, self.config.monitoring_interval)
    
    async def start_monitoring(self):
        """Start continuous monitoring loop"""
        self.running = True
        logger.info("Starting continuous monitoring...")
        
        while self.running:
            try:
                # Run monitoring cycle
                output = await self.run_monitoring_cycle()
                
                # Wait for next update
                await asyncio.sleep(output.next_update_in_seconds)
                
            except asyncio.CancelledError:
                logger.info("Monitoring task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}", exc_info=True)
                # Wait before retrying
                await asyncio.sleep(60)
    
    def get_status(self) -> MonitoringStatus:
        """Get current monitoring status"""
        if not self.latest_output:
            return MonitoringStatus(
                active_zones=len(self.sentinel_zones),
                total_predictions=0,
                critical_alerts=0,
                last_update=datetime.utcnow(),
                next_update=datetime.utcnow(),
                data_freshness_seconds=float('inf')
            )
        
        freshness = (
            datetime.utcnow() - self.last_update
        ).total_seconds() if self.last_update else 0
        
        return MonitoringStatus(
            active_zones=len(self.sentinel_zones),
            total_predictions=len(self.latest_output.predictions),
            critical_alerts=len(self.latest_output.critical_alerts),
            last_update=self.last_update or datetime.utcnow(),
            next_update=(self.last_update or datetime.utcnow()) + 
                       timedelta(seconds=self.latest_output.next_update_in_seconds),
            data_freshness_seconds=freshness
        )


# =====================================================================
# FASTAPI APPLICATION
# =====================================================================

# Global agent instance
agent: Optional[EnvironmentalIntelligenceAgent] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager"""
    global agent
    
    # Startup
    config = AgentConfig()
    agent = EnvironmentalIntelligenceAgent(config)
    await agent.startup()
    
    # Start monitoring in background
    agent.monitoring_task = asyncio.create_task(agent.start_monitoring())
    
    # Start river discharge monitoring (separate 30-min loop)
    if agent.river_monitor:
        agent.river_monitoring_task = asyncio.create_task(
            agent.river_monitor.start_monitoring()
        )
    
    yield
    
    # Shutdown
    await agent.shutdown()


# Create FastAPI app
app = FastAPI(
    title="Environmental Intelligence Agent",
    description="Agent 1: Real-time flood risk monitoring and prediction",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================================
# API ENDPOINTS
# =====================================================================

@app.get("/", response_model=Dict[str, str])
async def root():
    """Root endpoint"""
    return {
        "agent": "Environmental Intelligence Agent",
        "status": "operational",
        "version": "1.0.0"
    }


@app.get("/health", response_model=HealthCheckResponse)
async def health_check():
    """Health check endpoint"""
    global agent
    
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    return HealthCheckResponse(
        status="healthy",
        agent_id=agent.config.agent_id,
        version="1.0.0",
        data_sources={
            'weather': agent.weather_collector is not None,
            'social_media': agent.social_collector is not None,
            'spatial_db': agent.spatial_analyzer is not None
        },
        database_connected=agent.db_pool is not None,
        cache_connected=agent.redis_client is not None
    )


@app.get("/status", response_model=MonitoringStatus)
async def get_status():
    """Get current monitoring status"""
    global agent
    
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    return agent.get_status()


@app.get("/output", response_model=AgentOutput)
async def get_latest_output():
    """Get latest agent output"""
    global agent
    
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    if not agent.latest_output:
        raise HTTPException(status_code=404, detail="No output available yet")
    
    return agent.latest_output


@app.post("/trigger")
async def trigger_monitoring_cycle():
    """Manually trigger a monitoring cycle"""
    global agent
    
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    asyncio.create_task(agent.run_monitoring_cycle())
    
    return {"message": "Monitoring cycle triggered"}


@app.get("/zones", response_model=List[SentinelZone])
async def get_zones():
    """Get all sentinel zones"""
    global agent
    
    if not agent:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    return agent.sentinel_zones


@app.get("/zones/{zone_id}/prediction")
async def get_zone_prediction(zone_id: str):
    """Get latest prediction for a specific zone"""
    global agent
    
    if not agent or not agent.latest_output:
        raise HTTPException(status_code=404, detail="No predictions available")
    
    for pred in agent.latest_output.predictions:
        if str(pred.zone.id) == zone_id:
            return pred
    
    raise HTTPException(status_code=404, detail="Zone not found")


# =====================================================================
# SAR FLOOD DETECTION IMAGES
# =====================================================================

# Resolve the inference_results directory relative to this file
_INFERENCE_DIR = Path(__file__).resolve().parent / "models" / "inference_results"

# Map scenario keys to filenames
_SAR_IMAGES = {
    "before":   "prediction_1_light_flooding.png",    # baseline / light
    "during":   "prediction_3_severe_flooding.png",   # active flooding
    "moderate": "prediction_2_moderate_flooding.png",
    "analysis_before": "analysis_1_light_flooding.png",
    "analysis_during": "analysis_3_severe_flooding.png",
    "comparison": "scenario_comparison.png",
}


@app.get("/sar/images/{scenario}")
async def get_sar_image(scenario: str):
    """
    Serve SAR flood detection images for the dashboard.

    Scenarios: before, during, moderate, analysis_before, analysis_during, comparison
    """
    filename = _SAR_IMAGES.get(scenario)
    if not filename:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown scenario '{scenario}'. Available: {list(_SAR_IMAGES.keys())}",
        )
    filepath = _INFERENCE_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Image not found: {filename}")
    return FileResponse(filepath, media_type="image/png")


@app.get("/sar/latest")
async def get_sar_latest():
    """
    Return metadata + image URLs for the dashboard SAR panel.
    The dashboard fetches this to populate the before/after view.
    """
    results_file = _INFERENCE_DIR / "inference_results.json"
    metadata = {}
    if results_file.exists():
        with open(results_file) as f:
            metadata = json.load(f)

    # Pick the most relevant scenarios from inference results
    scenarios = metadata.get("scenarios", [])
    before_stats = scenarios[0] if len(scenarios) > 0 else {}
    during_stats = scenarios[2] if len(scenarios) > 2 else {}

    return {
        "sar_available": True,
        "sensor": "Sentinel-1",
        "model": "U-Net CNN",
        "accuracy": 94.64,
        "before": {
            "label": before_stats.get("scenario", "Light Flooding"),
            "image_url": "/sar/images/before",
            "flood_fraction": before_stats.get("flood_fraction", 0),
            "flooded_area_km2": before_stats.get("flooded_area_km2", 0),
        },
        "during": {
            "label": during_stats.get("scenario", "Severe Flooding"),
            "image_url": "/sar/images/during",
            "flood_fraction": during_stats.get("flood_fraction", 0),
            "flooded_area_km2": during_stats.get("flooded_area_km2", 0),
            "depth_stats": during_stats.get("depth_statistics", {}),
        },
    }


# =====================================================================
# MAIN ENTRY POINT
# =====================================================================

def main():
    """Main entry point for the agent"""
    # Setup signal handlers
    def signal_handler(sig, frame):
        logger.info("Interrupt received, shutting down...")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Run FastAPI server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8001,
        log_level="info",
        access_log=True
    )


if __name__ == "__main__":
    main()