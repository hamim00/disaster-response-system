# FloodShield BD — Integration Setup Guide

## What's Included

This integration adds **three new interfaces** to your existing FloodShield BD system:

| Interface | URL | Purpose |
|-----------|-----|---------|
| 999 Emergency Gateway | `http://localhost:8000/gateway` | Call center intake view with auto-feeder |
| Command Center | `http://localhost:8000/command` | Unified strategic dashboard |
| Field Team Portal | `http://localhost:8000/field` | Mobile-friendly team interface |

Plus a **Scenario Feeder** that auto-plays 45 realistic flood events into the pipeline.

---

## File Structure

```
your_project/
├── backend/                    ← NEW: Unified FastAPI backend
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── __init__.py
│   ├── main.py                 ← Entry point (serves all 3 interfaces)
│   ├── routes/
│   │   ├── gateway.py          ← /api/gateway/* endpoints
│   │   ├── field.py            ← /api/field/* endpoints
│   │   └── command.py          ← /api/command/* endpoints
│   ├── websocket/
│   │   ├── manager.py          ← WebSocket connection manager
│   │   └── bridge.py           ← Redis → WebSocket forwarder
│   └── models/
├── frontend/                   ← NEW: Three interface HTML files
│   ├── gateway/index.html      ← 999 Gateway UI
│   ├── field/index.html        ← Field Portal UI
│   └── command/index.html      ← Command Center UI
├── scenario_feeder/            ← NEW: Auto-plays scenario events
│   ├── Dockerfile
│   ├── requirements.txt
│   └── feeder.py
├── scenarios/                  ← NEW: Scenario data
│   └── sylhet_flood_2024.json  ← 45 events across 30 min
├── migrations/                 ← NEW: Database tables
│   └── 007_integration_tables.sql
├── docker-compose.yml          ← UPDATED: +scenario-feeder, +unified-backend
└── (existing agents, database/, shared/, etc.)
```

---

## Step-by-Step Setup

### Step 0: Backup Current State

```powershell
# In your project root
cp docker-compose.yml docker-compose.yml.backup
```

### Step 1: Copy New Files

Copy these folders from the delivered package into your existing project root:

```
backend/          → your_project/backend/
frontend/         → your_project/frontend/
scenario_feeder/  → your_project/scenario_feeder/
scenarios/        → your_project/scenarios/
migrations/       → your_project/migrations/  (add the new file)
```

### Step 2: Replace docker-compose.yml

Replace your existing `docker-compose.yml` with the new one. It includes all your existing services **unchanged** plus two new ones:

- `scenario-feeder` on port 8010
- `unified-backend` on port 8000

### Step 3: Run Database Migration

Start just Postgres first, then run the migration:

```powershell
docker-compose up -d postgres
# Wait for it to be healthy, then:
docker exec -i disaster_postgres psql -U disaster_admin -d disaster_response < migrations/007_integration_tables.sql
```

This creates 6 new tables and seeds 5 field teams. Your existing tables are untouched.

### Step 4: Start Everything

```powershell
docker-compose up -d
```

This starts:
- `postgres` (port 5432)
- `redis` (port 6379)
- `agent1` (port 8001)
- `agent2` (port 8002)
- `agent3` (port 8003)
- `agent4` (port 8004)
- `scenario-feeder` (port 8010)
- `unified-backend` (port 8000) ← **your new dashboard hub**

### Step 5: Verify

```powershell
# Check all containers are running
docker-compose ps

# Check backend health
curl http://localhost:8000/health

# Check feeder status
curl http://localhost:8010/status
```

---

## Running Without Docker (Local Dev)

If you prefer to run locally for faster iteration:

```powershell
# Terminal 1: Start Postgres + Redis via Docker
docker-compose up -d postgres redis

# Terminal 2: Run the migration
docker exec -i disaster_postgres psql -U disaster_admin -d disaster_response < migrations/007_integration_tables.sql

# Terminal 3: Start Scenario Feeder
cd scenario_feeder
pip install -r requirements.txt
python feeder.py

# Terminal 4: Start Unified Backend
pip install -r backend/requirements.txt
python -m backend.main

# Terminal 5 (optional): Start Agent 2
cd src/agents/agent_2_distress_intelligence
python main.py
```

Then open:
- Gateway: http://localhost:8000/gateway
- Command: http://localhost:8000/command
- Field:   http://localhost:8000/field

---

## Defense Demo Playbook (15–20 minutes)

### Before Panel Arrives

1. `docker-compose up -d` — start all containers
2. Open 3 browser tabs:
   - **Tab 1**: http://localhost:8000/gateway (999 Gateway)
   - **Tab 2**: http://localhost:8000/command (Command Center)
   - **Tab 3**: http://localhost:8000/field (Field Portal — login as Team Alpha, PIN: 1234)
3. Arrange side-by-side (projector for Command Center)
4. Verify all 3 pages load and show "Connected" indicators

### Demo Script

**Opening (2 min)**
> "FloodShield BD is a multi-agent autonomous flood response system. I'll demonstrate a simulated flood in the Sunamganj-Sylhet corridor. The system has three interfaces: the 999 Emergency Gateway for intake, the Command Center for strategic coordination, and the Field Team Portal for ground operations."

**Start Scenario (1 min)**
- Click **▶ Play** on Gateway, set speed to 5x
> "I'm starting a pre-scripted scenario with 45 realistic events — 999 calls, SMS messages, and social media posts. They auto-feed into the system."

**Watch Intake (3 min)**
- Point to Gateway: calls appearing one by one
> "Each call is automatically processed by Agent 2 — our NLP pipeline classifies urgency, extracts location, detects language. Watch the status change from 'Received' to 'Processed.'"

**Command Center Reacting (3 min)**
- Switch to Command Center: distress markers appearing on map
> "The command center sees verified distress signals. Agent 3 allocates resources from nearest depots. Agent 4 optimizes dispatch routes. You can see team status and inventory levels updating."

**Field Portal Dispatch (3 min)**
- Switch to Field Portal: dispatch notification appears
> "Team Alpha receives the mission — location, priority, estimated affected, resource manifest."
- Click **✓ Accept**. Status → "EN ROUTE"
- Back to Command Center: "The command center immediately knows Team Alpha accepted."

**Ground Truth (3 min)**
- Field Portal: click **📍 Arrived**, then **📋 Ground Report**
- Enter: Actual affected = 120, Boat Only, Rising
- Submit
- Back to Command: alert appears
> "Ground truth shows 120 people, not estimated 45. The system flags this discrepancy for Agent 3 to send additional resources."

**Closing (2 min)**
> "This demonstrates the full loop: intake → processing → dispatch → field confirmation → ground truth → system adaptation. In production, the 999 Gateway connects to Bangladesh's emergency infrastructure, and the Field Portal is a PWA with SMS fallback."

### If Something Breaks

- Gateway feeder not starting? Manually trigger: `curl -X POST http://localhost:8010/start?speed=5`
- WebSocket disconnected? Refresh the page — auto-reconnects
- Database error? Re-run migration: `docker exec -i disaster_postgres psql -U disaster_admin -d disaster_response < migrations/007_integration_tables.sql`
- Have screenshots/screen recordings as backup

---

## Redis Channels Reference

| Channel | Publisher | Subscriber |
|---------|-----------|------------|
| `raw_distress_intake` | Scenario Feeder | Agent 2, Gateway WS, Command WS |
| `intake_status_update` | Agent 2 | Gateway WS |
| `verified_distress` | Agent 2 | Command WS |
| `dispatch_order` | Agent 4 | Command WS |
| `team_notifications` | Agent 4 | Field Portal WS |
| `team_feedback` | Field Portal | Command WS |
| `team_location` | Field Portal | Command WS (map) |
| `team_status_update` | Field Portal | Command WS |
| `ground_reports` | Field Portal | Command WS, Agent 3 |
| `resource_consumed` | Field Portal | Command WS, Agent 3 |
| `resupply_alerts` | Agent 3 | Command WS |

---

## Connecting Agent 2 to the New Intake Channel

Your existing Agent 2 already works. To make it **also** listen to the scenario feeder, add this to Agent 2's `main.py` in the `start_monitoring` method:

```python
# In DistressIntelligenceAgent.start_monitoring(), after the flood_alert subscription:
if self.redis_client:
    asyncio.create_task(self._subscribe_intake())

# Add this new method to the class:
async def _subscribe_intake(self):
    """Subscribe to raw_distress_intake from the 999 Gateway."""
    if not self.redis_client:
        return
    try:
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe("raw_distress_intake")
        logger.info("Subscribed to raw_distress_intake channel")
        async for message in pubsub.listen():
            if not self.running:
                break
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    if data.get("type") == "scenario_complete":
                        logger.info("Scenario complete signal received")
                        continue
                    # Feed into existing channels based on source_type
                    src = data.get("source_type", "sms")
                    if src == "call_999" and self.hotline_channel:
                        self.hotline_channel.load_simulated_calls([{
                            "zone": data.get("location_description", ""),
                            "urgency": data.get("auto_detected_urgency", "medium"),
                            "situation": "flood_report",
                            "people_count": 5,
                            "water_feet": 4,
                            "notes": data.get("raw_message", ""),
                        }])
                    elif src == "sms" and self.sms_channel:
                        self.sms_channel.load_simulated_messages([{
                            "text": data.get("raw_message", ""),
                            "sender_phone": data.get("source_phone", ""),
                            "timestamp": data.get("timestamp", ""),
                        }])
                    elif src == "social_media" and self.social_channel:
                        self.social_channel.load_simulated_posts([{
                            "id": data.get("event_id", ""),
                            "platform": "facebook",
                            "text": data.get("raw_message", ""),
                            "author": "flood_report",
                            "engagement": 100,
                        }])
                    logger.info("Intake event %s routed to %s channel",
                                data.get("event_id"), src)
                except Exception as e:
                    logger.warning("Intake processing error: %s", e)
    except Exception as e:
        logger.error("raw_distress_intake subscription error: %s", e)
```

This is **optional** — the demo works without it because the Gateway shows the intake feed independently, and the scenario feeder logs directly to PostgreSQL. But wiring Agent 2 creates the full autonomous pipeline.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Port 8000 already in use | Change `BACKEND_PORT` in docker-compose.yml or kill the existing process |
| "Database not connected" on API | Check postgres is running: `docker-compose ps postgres` |
| Tables don't exist | Re-run: `docker exec -i disaster_postgres psql -U disaster_admin -d disaster_response < migrations/007_integration_tables.sql` |
| WebSocket not connecting | Check that unified-backend container is running on port 8000 |
| Feeder not reachable from backend | Both must be on `disaster_network`. Check: `docker network inspect disaster_network` |
| Bengali text garbled | Ensure your terminal/browser supports UTF-8. All files are UTF-8 encoded. |
| Team login fails | PIN is `1234` for all teams. Check team_status table is seeded. |
