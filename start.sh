#!/usr/bin/env bash
# ===========================================================================
# FloodShield BD — Single-command startup
# Usage:  ./start.sh          (start everything)
#         ./start.sh clean    (nuke old containers + volumes, fresh start)
#         ./start.sh stop     (stop everything)
#         ./start.sh status   (health check all services)
# ===========================================================================
set -euo pipefail

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; RST='\033[0m'
ok()   { echo -e "  ${GRN}✓${RST} $1"; }
warn() { echo -e "  ${YLW}⚠${RST} $1"; }
fail() { echo -e "  ${RED}✗${RST} $1"; }

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

# ---------- STOP ----------
if [[ "${1:-}" == "stop" ]]; then
    echo "Stopping FloodShield BD..."
    docker compose down
    ok "All services stopped"
    exit 0
fi

# ---------- STATUS ----------
if [[ "${1:-}" == "status" ]]; then
    echo ""
    echo "═══ FloodShield BD — Health Check ═══"
    echo ""

    # Check Docker containers
    for svc in postgres redis agent1 agent2 agent3 agent4; do
        status=$(docker compose ps --format '{{.State}}' "$svc" 2>/dev/null || echo "not found")
        if [[ "$status" == "running" ]]; then
            ok "$svc: running"
        else
            fail "$svc: $status"
        fi
    done
    echo ""

    # Check API endpoints
    for port in 8001 8002 8003 8004; do
        agent="Agent $((port - 8000))"
        if curl -sf "http://localhost:$port/health" > /dev/null 2>&1; then
            health=$(curl -sf "http://localhost:$port/health")
            ok "$agent (port $port): $health"
        else
            fail "$agent (port $port): not responding"
        fi
    done
    echo ""
    exit 0
fi

# ---------- CLEAN ----------
if [[ "${1:-}" == "clean" ]]; then
    echo ""
    echo "═══ Full cleanup + fresh start ═══"
    echo ""

    # 1. Stop project containers
    docker compose down -v 2>/dev/null || true
    ok "Project containers stopped"

    # 2. Kill ANY container using our ports
    for port in 5432 6379 8001 8002 8003 8004; do
        cid=$(docker ps -q --filter "publish=$port" 2>/dev/null || true)
        if [[ -n "$cid" ]]; then
            cname=$(docker inspect --format '{{.Name}}' "$cid" | sed 's/\///')
            docker rm -f "$cid" > /dev/null
            warn "Killed ghost container '$cname' on port $port"
        fi
    done

    # 3. Kill stale containers by name pattern
    for pattern in agent1 agent2 agent3 agent4 disaster churn-postgres; do
        cids=$(docker ps -aq --filter "name=$pattern" 2>/dev/null || true)
        if [[ -n "$cids" ]]; then
            docker rm -f $cids > /dev/null
            warn "Removed stale container(s) matching '$pattern'"
        fi
    done

    ok "Cleanup complete"
    echo ""
fi

# ---------- START ----------
echo ""
echo "═══ FloodShield BD — Starting ═══"
echo ""

# Step 1: Check for port conflicts BEFORE docker compose up
CONFLICT=false
for port in 5432 6379 8001 8002 8003 8004; do
    # Check non-Docker processes
    pid=$(lsof -ti ":$port" 2>/dev/null || true)
    if [[ -n "$pid" ]]; then
        pname=$(ps -p "$pid" -o comm= 2>/dev/null || echo "unknown")
        fail "Port $port already in use by '$pname' (PID $pid)"
        CONFLICT=true
    fi
    # Check Docker containers from other projects
    cid=$(docker ps -q --filter "publish=$port" 2>/dev/null || true)
    if [[ -n "$cid" ]]; then
        cname=$(docker inspect --format '{{.Name}}' "$cid" 2>/dev/null | sed 's/\///')
        # Only flag if it's NOT our container
        our=$(docker compose ps -q 2>/dev/null | grep "$cid" || true)
        if [[ -z "$our" ]]; then
            fail "Port $port used by foreign container '$cname' — run ./start.sh clean"
            CONFLICT=true
        fi
    fi
done

if [[ "$CONFLICT" == "true" ]]; then
    echo ""
    fail "Port conflicts detected. Run: ./start.sh clean"
    exit 1
fi

# Step 2: Build and start
echo "Building images..."
docker compose build --quiet
ok "Images built"

echo "Starting services..."
docker compose up -d
ok "Containers started"

# Step 3: Wait for health checks
echo "Waiting for services to be healthy..."
TIMEOUT=60
ELAPSED=0
while [[ $ELAPSED -lt $TIMEOUT ]]; do
    PG_OK=$(docker compose ps postgres --format '{{.Health}}' 2>/dev/null || echo "")
    RD_OK=$(docker compose ps redis --format '{{.Health}}' 2>/dev/null || echo "")
    if [[ "$PG_OK" == *"healthy"* && "$RD_OK" == *"healthy"* ]]; then
        ok "PostgreSQL healthy"
        ok "Redis healthy"
        break
    fi
    sleep 2
    ELAPSED=$((ELAPSED + 2))
done

if [[ $ELAPSED -ge $TIMEOUT ]]; then
    fail "Timeout waiting for services — check: docker compose logs"
    exit 1
fi

# Step 4: Wait for agents
sleep 5
for port in 8001 8002 8003 8004; do
    agent="Agent $((port - 8000))"
    if curl -sf "http://localhost:$port/" > /dev/null 2>&1; then
        ok "$agent online (port $port)"
    else
        warn "$agent not responding yet (port $port) — may need more time"
    fi
done

echo ""
ok "FloodShield BD is running!"
echo "   Dashboard: open dashboard.html in browser"
echo "   Logs:      docker compose logs -f"
echo "   Stop:      ./start.sh stop"
echo "   Health:    ./start.sh status"
echo ""
