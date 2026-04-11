# ===========================================================================
# FloodShield BD — Single-command startup (PowerShell)
# Usage:  .\start.ps1          (start everything)
#         .\start.ps1 clean    (nuke old containers + volumes, fresh start)
#         .\start.ps1 stop     (stop everything)
#         .\start.ps1 status   (health check all services)
# ===========================================================================

param([string]$Action = "start")

function Write-Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Write-Fail($msg) { Write-Host "  [XX] $msg" -ForegroundColor Red }

# ---------- STOP ----------
if ($Action -eq "stop") {
    Write-Host "Stopping FloodShield BD..."
    docker compose down
    Write-Ok "All services stopped"
    exit 0
}

# ---------- STATUS ----------
if ($Action -eq "status") {
    Write-Host ""
    Write-Host "=== FloodShield BD --- Health Check ==="
    Write-Host ""

    foreach ($svc in @("postgres","redis","agent1","agent2","agent3","agent4")) {
        try {
            $state = docker compose ps --format '{{.State}}' $svc 2>$null
            if ($state -match "running") {
                Write-Ok "$svc is running"
            } else {
                Write-Fail "$svc is $state"
            }
        } catch {
            Write-Fail "$svc not found"
        }
    }
    Write-Host ""

    foreach ($port in @(8001,8002,8003,8004)) {
        $agent = "Agent $($port - 8000)"
        try {
            $resp = Invoke-RestMethod -Uri "http://localhost:$port/health" -TimeoutSec 3 -ErrorAction Stop
            Write-Ok "$agent (port $port) healthy"
        } catch {
            Write-Fail "$agent (port $port) not responding"
        }
    }
    Write-Host ""
    exit 0
}

# ---------- CLEAN ----------
if ($Action -eq "clean") {
    Write-Host ""
    Write-Host "=== Full cleanup + fresh start ==="
    Write-Host ""

    # 1. Stop project containers
    docker compose down -v 2>$null
    Write-Ok "Project containers stopped"

    # 2. Kill ANY container using our ports
    foreach ($port in @(5432,6379,8001,8002,8003,8004)) {
        $cid = docker ps -q --filter "publish=$port" 2>$null
        if ($cid) {
            $cname = docker inspect --format '{{.Name}}' $cid 2>$null
            docker rm -f $cid >$null 2>$null
            Write-Warn "Killed ghost container $cname on port $port"
        }
    }

    # 3. Kill stale containers by name pattern
    foreach ($pattern in @("agent1","agent2","agent3","agent4","disaster","churn-postgres")) {
        $cids = docker ps -aq --filter "name=$pattern" 2>$null
        if ($cids) {
            docker rm -f $cids >$null 2>$null
            Write-Warn "Removed stale container(s) matching $pattern"
        }
    }

    Write-Ok "Cleanup complete"
    Write-Host ""
}

# ---------- START ----------
Write-Host ""
Write-Host "=== FloodShield BD --- Starting ==="
Write-Host ""

# Step 1: Check for port conflicts
$conflict = $false
foreach ($port in @(5432,6379,8001,8002,8003,8004)) {
    $cid = docker ps -q --filter "publish=$port" 2>$null
    if ($cid) {
        $cname = docker inspect --format '{{.Name}}' $cid 2>$null
        Write-Fail "Port $port used by container $cname"
        $conflict = $true
    }
}

if ($conflict -and $Action -ne "clean") {
    Write-Host ""
    Write-Fail 'Port conflicts detected. Run: .\start.ps1 clean'
    exit 1
}

# Step 2: Build and start
Write-Host "Building images..."
docker compose build --quiet
Write-Ok "Images built"

Write-Host "Starting services..."
docker compose up -d
Write-Ok "Containers started"

# Step 3: Wait for health checks
Write-Host "Waiting for services to be healthy..."
$timeout = 60
$elapsed = 0
while ($elapsed -lt $timeout) {
    $pgHealth = docker compose ps postgres --format '{{.Health}}' 2>$null
    $rdHealth = docker compose ps redis --format '{{.Health}}' 2>$null
    if ($pgHealth -match "healthy" -and $rdHealth -match "healthy") {
        Write-Ok "PostgreSQL healthy"
        Write-Ok "Redis healthy"
        break
    }
    Start-Sleep -Seconds 2
    $elapsed += 2
}

if ($elapsed -ge $timeout) {
    Write-Fail "Timeout waiting for services --- check: docker compose logs"
    exit 1
}

# Step 4: Wait for agents
Start-Sleep -Seconds 5
foreach ($port in @(8001,8002,8003,8004)) {
    $agent = "Agent $($port - 8000)"
    try {
        Invoke-RestMethod -Uri "http://localhost:$port/" -TimeoutSec 3 -ErrorAction Stop >$null
        Write-Ok "$agent online (port $port)"
    } catch {
        Write-Warn "$agent not responding yet (port $port)"
    }
}

Write-Host ""
Write-Ok "FloodShield BD is running!"
Write-Host '   Dashboard: open dashboard.html in browser'
Write-Host '   Logs:      docker compose logs -f'
Write-Host '   Stop:      .\start.ps1 stop'
Write-Host '   Health:    .\start.ps1 status'
Write-Host ""