"""
FloodShield BD — Scenario Feeder
==================================
Reads a scenario JSON file and auto-publishes events to Redis
raw_distress_intake channel on a timer. Logs each event to
PostgreSQL intake_log table.

Runs standalone or inside Docker.
Controlled via FastAPI endpoints on port 8010.
"""
import asyncio
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import asyncpg
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from redis import asyncio as aioredis
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [feeder] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("scenario_feeder")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://disaster_admin:disaster123@localhost:5432/disaster_response",
)
SCENARIO_FILE = os.getenv("SCENARIO_FILE", "scenarios/sylhet_flood_2024.json")
SPEED_MULTIPLIER = float(os.getenv("SPEED_MULTIPLIER", "5"))
AUTO_START = os.getenv("AUTO_START", "false").lower() == "true"
FEEDER_PORT = int(os.getenv("FEEDER_PORT", "8010"))


class FeederState(str, Enum):
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    COMPLETED = "completed"


# ---------------------------------------------------------------------------
# Feeder Engine
# ---------------------------------------------------------------------------
class ScenarioFeeder:
    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self.db_pool: Optional[asyncpg.Pool] = None
        self.scenario: Optional[dict] = None
        self.events: list = []
        self.state: FeederState = FeederState.IDLE
        self.current_index: int = 0
        self.start_time: float = 0
        self.pause_offset: float = 0
        self.speed: float = SPEED_MULTIPLIER
        self._play_task: Optional[asyncio.Task] = None

    async def startup(self):
        # Redis
        try:
            self.redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
            await self.redis.ping()
            logger.info("Redis connected")
        except Exception as e:
            logger.error("Redis connection failed: %s", e)
            self.redis = None

        # PostgreSQL
        try:
            self.db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
            await self.db_pool.fetchval("SELECT 1")
            logger.info("PostgreSQL connected")
        except Exception as e:
            logger.warning("PostgreSQL not available: %s", e)
            self.db_pool = None

        # Load scenario
        self.load_scenario(SCENARIO_FILE)

    def load_scenario(self, path: str):
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.scenario = json.load(f)
            self.events = sorted(
                self.scenario.get("events", []),
                key=lambda e: e.get("scenario_minute", 0),
            )
            logger.info(
                "Loaded scenario '%s' — %d events over %d minutes",
                self.scenario.get("scenario_name", "unknown"),
                len(self.events),
                self.scenario.get("total_duration_minutes", 0),
            )
        except FileNotFoundError:
            logger.warning("Scenario file not found: %s — will wait for upload", path)
            self.events = []

    async def shutdown(self):
        if self._play_task and not self._play_task.done():
            self._play_task.cancel()
        if self.redis:
            await self.redis.aclose()
        if self.db_pool:
            await self.db_pool.close()

    # ------------------------------------------------------------------
    # Playback control
    # ------------------------------------------------------------------
    def start(self, speed: Optional[float] = None):
        if speed is not None:
            self.speed = speed
        if self.state == FeederState.PAUSED:
            # Resume from pause
            self.pause_offset += time.time() - self._pause_time
            self.state = FeederState.PLAYING
            logger.info("Resumed playback at %.1fx", self.speed)
            return
        # Fresh start
        self.current_index = 0
        self.start_time = time.time()
        self.pause_offset = 0
        self.state = FeederState.PLAYING
        if self._play_task and not self._play_task.done():
            self._play_task.cancel()
        self._play_task = asyncio.create_task(self._play_loop())
        logger.info("Started scenario at %.1fx speed", self.speed)

    def pause(self):
        if self.state == FeederState.PLAYING:
            self._pause_time = time.time()
            self.state = FeederState.PAUSED
            logger.info("Paused at event %d/%d", self.current_index, len(self.events))

    def reset(self):
        if self._play_task and not self._play_task.done():
            self._play_task.cancel()
        self.state = FeederState.IDLE
        self.current_index = 0
        self.start_time = 0
        self.pause_offset = 0
        logger.info("Scenario reset")

    # ------------------------------------------------------------------
    # Core playback loop
    # ------------------------------------------------------------------
    async def _play_loop(self):
        try:
            while self.current_index < len(self.events):
                if self.state != FeederState.PLAYING:
                    await asyncio.sleep(0.2)
                    continue

                event = self.events[self.current_index]
                target_minute = event.get("scenario_minute", 0)

                # Convert scenario minutes to real seconds
                target_seconds = (target_minute * 60) / self.speed
                elapsed = (time.time() - self.start_time) - self.pause_offset

                if elapsed < target_seconds:
                    await asyncio.sleep(min(0.5, target_seconds - elapsed))
                    continue

                # Time to publish this event
                await self._publish_event(event)
                self.current_index += 1

            # All events played
            self.state = FeederState.COMPLETED
            if self.redis:
                await self.redis.publish(
                    "raw_distress_intake",
                    json.dumps({"type": "scenario_complete", "scenario_id": self.scenario.get("scenario_id")}),
                )
            logger.info("Scenario completed — all %d events published", len(self.events))

        except asyncio.CancelledError:
            logger.info("Playback cancelled")
        except Exception as e:
            logger.error("Playback error: %s", e, exc_info=True)

    async def _publish_event(self, event: dict):
        event_id = event.get("event_id", f"evt_{self.current_index}")

        # Add timestamp
        enriched = {**event, "timestamp": datetime.now(timezone.utc).isoformat()}

        # Publish to Redis
        if self.redis:
            try:
                await self.redis.publish("raw_distress_intake", json.dumps(enriched, ensure_ascii=False))
            except Exception as e:
                logger.error("Redis publish failed: %s", e)

        # Log to intake_log table
        if self.db_pool:
            try:
                loc = event.get("location", {})
                await self.db_pool.execute(
                    """
                    INSERT INTO intake_log
                        (source_type, source_phone, caller_name, raw_message,
                         location_lat, location_lng, location_description,
                         auto_detected_urgency, processing_status, scenario_event_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'received', $9)
                    """,
                    event.get("source_type", "sms"),
                    event.get("source_phone"),
                    event.get("caller_name"),
                    event.get("raw_message", ""),
                    loc.get("lat"),
                    loc.get("lng"),
                    event.get("location_description"),
                    event.get("auto_detected_urgency", "medium"),
                    event_id,
                )
            except Exception as e:
                logger.warning("DB insert failed (non-fatal): %s", e)

        logger.info(
            "Event %s published — %s from %s (%s)",
            event_id,
            event.get("source_type"),
            event.get("location_description", "unknown"),
            event.get("auto_detected_urgency"),
        )

    @property
    def status(self) -> dict:
        return {
            "state": self.state.value,
            "scenario": self.scenario.get("scenario_name") if self.scenario else None,
            "speed_multiplier": self.speed,
            "total_events": len(self.events),
            "events_played": self.current_index,
            "events_remaining": len(self.events) - self.current_index,
            "progress_pct": round((self.current_index / max(len(self.events), 1)) * 100, 1),
        }


# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------
feeder = ScenarioFeeder()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await feeder.startup()
    if AUTO_START and feeder.events:
        feeder.start()
    yield
    await feeder.shutdown()


app = FastAPI(title="FloodShield Scenario Feeder", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/")
async def root():
    return {"service": "scenario_feeder", "status": feeder.state.value}


@app.get("/status")
async def get_status():
    return feeder.status


@app.post("/start")
async def start_scenario(speed: Optional[float] = None):
    if not feeder.events:
        raise HTTPException(status_code=400, detail="No scenario loaded")
    feeder.start(speed)
    return {"message": "Scenario started", **feeder.status}


@app.post("/pause")
async def pause_scenario():
    feeder.pause()
    return {"message": "Scenario paused", **feeder.status}


@app.post("/reset")
async def reset_scenario():
    feeder.reset()
    return {"message": "Scenario reset", **feeder.status}


@app.post("/speed")
async def set_speed(multiplier: float):
    feeder.speed = max(0.5, min(20, multiplier))
    return {"speed_multiplier": feeder.speed}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=FEEDER_PORT, log_level="info")
