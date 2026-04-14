# Debug Patch — Apply Instructions

## Files in this patch
```
backend/main.py                    — Bridge crash wrapper + diagnostics route
backend/websocket/bridge.py        — Verbose debug logging on every message
backend/websocket/manager.py       — Verbose logging on connect/disconnect/send
backend/routes/field.py            — New /team/{id}/mission endpoint
frontend/diagnostics.html          — Diagnostic test page
```

## How to apply

### Step 1: Copy files
Copy each file into the matching path in your project, overwriting existing.

### Step 2: Restart the unified-backend
```powershell
docker compose restart unified-backend
```
This is ALL you need — no rebuild, no down -v. The backend volume-mounts
./backend and ./frontend, so it picks up the new files on restart.

### Step 3: Check startup logs
```powershell
docker logs floodshield_backend --tail 50
```
You MUST see these lines:
  - "[OK] Redis connected"
  - "Bridge task starting..."
  - "Redis → WebSocket bridge started"
  - "Bridge connected to Redis"
  - "Bridge subscribed to 13 channels"

If you see "Redis not connected — bridge NOT started!" that's the problem.
If you see "BRIDGE TASK CRASHED" that tells you exactly what went wrong.

### Step 4: Open diagnostics
Open: http://localhost:8000/diagnostics
Click "Run All Tests" then "Fire Test Event"

### Step 5: Check live logs while scenario runs
```powershell
docker logs floodshield_backend -f
```
When the scenario plays, you should see:
  "Bridge received: channel=raw_distress_intake, gw_clients=1..."
  "Routing new_intake to 1 gateway + 1 command clients"

If gw_clients=0 → Gateway WebSocket isn't connected
If you see no "Bridge received" lines at all → Bridge is dead
