# scripts/stop-local.ps1
# Local MCP Stack Safe Stopper (Development Tooling)

$ErrorActionPreference = 'Continue'

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Stopping SuperOffice AI Support MCP Platform (Local Dev)" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$repoRoot = (Get-Item -Path $PSScriptRoot).Parent.FullName
Set-Location $repoRoot

$pidFile = Join-Path $repoRoot "tmp\local-pids.json"
$stoppedPids = @()

if (Test-Path $pidFile) {
    try {
        $json = Get-Content $pidFile -Raw | ConvertFrom-Json
        foreach ($prop in $json.PSObject.Properties) {
            $name = $prop.Name
            $pidToStop = $prop.Value
            if ($pidToStop) {
                $proc = Get-Process -Id $pidToStop -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Host "Stopping $name (PID: $pidToStop)..." -ForegroundColor Yellow
                    Stop-Process -Id $pidToStop -Force -ErrorAction SilentlyContinue
                    $stoppedPids += $pidToStop
                } else {
                    Write-Host "$name (PID: $pidToStop) is not running." -ForegroundColor Gray
                }
            }
        }
        Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Host "Error parsing $pidFile : $_" -ForegroundColor Red
    }
}

# Clean all processes associated with ports 8000, 8001, 8002, 8005
$ports = @(8000, 8001, 8002, 8005)
foreach ($p in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $ownerPid = $c.OwningProcess
        if ($ownerPid -and ($ownerPid -ne 0) -and ($ownerPid -ne 4) -and ($stoppedPids -notcontains $ownerPid)) {
            Write-Host "Found lingering process on port $p (PID: $ownerPid). Stopping..." -ForegroundColor Yellow
            Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
            $stoppedPids += $ownerPid
        }
    }
}

Write-Host "`n==========================================================" -ForegroundColor Cyan
Write-Host " All Local MCP services stopped successfully." -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Cyan
