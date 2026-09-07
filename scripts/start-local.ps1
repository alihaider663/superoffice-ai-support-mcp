# scripts/start-local.ps1
# Local MCP Stack Safe Starter (Development Tooling)

$ErrorActionPreference = 'Stop'

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Starting SuperOffice AI Support MCP Platform (Local Dev)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$repoRoot = (Get-Item -Path $PSScriptRoot).Parent.FullName
Set-Location $repoRoot

$tmpDir = Join-Path $repoRoot "tmp"
if (-not (Test-Path $tmpDir)) {
    New-Item -ItemType Directory -Path $tmpDir | Out-Null
}

$pidFile = Join-Path $tmpDir "local-pids.json"
$pids = @{}

# Helper to start service
function Start-LocalService {
    param (
        [string]$Name,
        [int]$Port,
        [string[]]$Arguments,
        [string]$HealthUrl
    )
    Write-Host "`n[$Name] Starting on 127.0.0.1:$Port..." -ForegroundColor Yellow
    $proc = Start-Process -FilePath "uv" -ArgumentList $Arguments -WorkingDirectory $repoRoot -WindowStyle Hidden -PassThru
    $script:pids[$Name] = $proc.Id
    Write-Host "      $Name started (PID: $($proc.Id))" -ForegroundColor Green
}

# 1. SuperOffice MCP (:8001)
Start-LocalService -Name "so_mcp" -Port 8001 -Arguments @("run", "python", "-m", "so_mcp.main") -HealthUrl "http://127.0.0.1:8001/mcp"

# 2. Diagnostics MCP (:8002)
Start-LocalService -Name "diag_mcp" -Port 8002 -Arguments @("run", "python", "-m", "diag_mcp.main") -HealthUrl "http://127.0.0.1:8002/mcp"

# 3. Investigation MCP (:8005)
Start-LocalService -Name "investigation_mcp" -Port 8005 -Arguments @("run", "uvicorn", "investigation_mcp.main:app", "--host", "127.0.0.1", "--port", "8005") -HealthUrl "http://127.0.0.1:8005/health"

# 4. Platform Gateway (:8000)
Start-LocalService -Name "gateway" -Port 8000 -Arguments @("run", "python", "-m", "platform_gateway.main") -HealthUrl "http://127.0.0.1:8000/health"

# Save PIDs
$pids | ConvertTo-Json | Set-Content -Path $pidFile -Force

Write-Host "`nWaiting for Gateway to become ready..." -ForegroundColor Cyan
$maxAttempts = 30
$isHealthy = $false
for ($i = 1; $i -le $maxAttempts; $i++) {
    Start-Sleep -Milliseconds 800
    try {
        $resp = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -Method Get -TimeoutSec 2 -ErrorAction Stop
        if ($resp -and ($resp.status -eq "healthy")) {
            $isHealthy = $true
            break
        }
    } catch {
        # Retry
    }
}

if ($isHealthy) {
    Write-Host "`n==========================================================" -ForegroundColor Green
    Write-Host " Local MCP Stack is ONLINE and HEALTHY!" -ForegroundColor Green
    Write-Host "==========================================================" -ForegroundColor Green
    Write-Host "  Gateway Health:     http://127.0.0.1:8000/health"
    Write-Host "  Gateway MCP:        http://127.0.0.1:8000/mcp (Primary Entrypoint)"
    Write-Host "  SuperOffice MCP:    http://127.0.0.1:8001/mcp"
    Write-Host "  Diagnostics MCP:    http://127.0.0.1:8002/mcp (Mode A Degraded)"
    Write-Host "  Investigation MCP:  http://127.0.0.1:8005/mcp"
    Write-Host "`nPIDs recorded in: tmp\local-pids.json"
    Write-Host "To stop all services: .\scripts\stop-local.ps1`n"
} else {
    Write-Host "`nGateway failed to report healthy within timeout." -ForegroundColor Red
    Write-Host "Inspect tmp\local-pids.json and service logs." -ForegroundColor Red
    exit 1
}
