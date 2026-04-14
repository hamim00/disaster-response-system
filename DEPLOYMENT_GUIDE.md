# FloodShield BD — Deployment & Demo Guide

## Quick Start

```powershell
.\start.ps1 clean
# Wait for "FloodShield BD is running!"
```

## Three Interfaces

| Interface | URL | Purpose |
|-----------|-----|---------|
| Main Dashboard | Open `dashboard.html` in browser (file://) | Command center — sees all agents, map, intake, dispatches |
| 999 Emergency Gateway | `http://localhost:8000/gateway` | Call center simulation — events enter the system here |
| Field Team Portal | `http://localhost:8000/field` | Team login, dispatch acceptance, ground reports |

## Demo Workflow (Correct Order)

1. **Start services:** `.\start.ps1 clean`
2. **Open Dashboard:** Open `dashboard.html` in browser — verify all 4 agents show ONLINE
3. **Open Gateway:** Navigate to `http://localhost:8000/gateway` — wait for green "Connected" dot
4. **Open Field Portal:** Navigate to `http://localhost:8000/field` — login as `team_alpha` / PIN `1234`
5. **Start scenario:** On the Gateway, press **Play** (optionally set speed to 10x first)
6. **Watch events stream** into the Gateway live feed
7. **Switch to Dashboard** — see 999 Intake Activity counts rising, distress queue filling, allocations appearing
8. **Switch to Field Portal** — dispatch notification arrives, press **Accept**
9. **Switch to Dashboard** — see team status change to "en_route", team marker appears on map
10. **On Field Portal** — submit a Ground Report
11. **On Dashboard** — amber alert banner appears with ground truth vs estimate comparison

> **Important:** The Gateway must be open BEFORE pressing Play. It only shows events that arrive via WebSocket while the page is open.

## Field Team Credentials

| Team ID | Name | PIN |
|---------|------|-----|
| team_alpha | Team Alpha - Sylhet | 1234 |
| team_bravo | Team Bravo - Sunamganj | 1234 |
| team_charlie | Team Charlie - Dhaka | 1234 |
| team_delta | Team Delta - Sirajganj | 1234 |
| team_echo | Team Echo - Companiganj | 1234 |

## Troubleshooting

- **Field Portal "Login failed"** — Run `.\start.ps1 clean` to ensure `team_status` table is created and seeded.
- **Gateway shows zeros** — Make sure Gateway page was open before pressing Play.
- **Dashboard panels show "Loading..."** — Check that all Docker containers are running: `docker ps`
- **Agent logs** — `docker logs agent2_distress_intelligence --follow` (replace with any agent container name)

## Talking Points for Defense

- "Events enter through the 999 Gateway — real calls, SMS, and social media"
- "Agent 2 processes them using NLP in Bengali/English/Banglish"
- "Agent 3 allocates resources using Haversine proximity matching"
- "Agent 4 optimizes dispatch routes with flood-adjusted safety scores"
- "Field teams receive dispatch orders in real-time and report ground truth"
- "The command center dashboard shows the entire pipeline live"
