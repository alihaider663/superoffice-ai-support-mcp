# scripts/check-local.ps1
# Local Development Readiness & Pre-Flight Environment Checker

$ErrorActionPreference = 'Continue'

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " SuperOffice AI Support MCP - Local Pre-Flight Check" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$repoRoot = (Get-Item -Path $PSScriptRoot).Parent.FullName
Set-Location $repoRoot
Write-Host ""
Write-Host "[1] Repository Root:" -ForegroundColor Yellow
Write-Host "    $repoRoot"

Write-Host ""
Write-Host "[2] Local Environment File (.env):" -ForegroundColor Yellow
$envPath = Join-Path $repoRoot ".env"
if (Test-Path $envPath) {
    Write-Host "    .env file exists: YES (Git-Ignored)" -ForegroundColor Green
    
    $envContent = Get-Content $envPath
    $checkKeys = @(
        "SUPEROFFICE_API_URL",
        "SUPEROFFICE_USERNAME",
        "SUPEROFFICE_PASSWORD",
        "SUPEROFFICE_ALLOW_SELF_SIGNED_CERT",
        "DIAGNOSTICS_MSSQL_HOST",
        "DIAGNOSTICS_MSSQL_DATABASE",
        "DIAGNOSTICS_MSSQL_USER",
        "DIAGNOSTICS_MSSQL_PASSWORD",
        "SECURITY_JWT_SECRET_KEY"
    )
    
    foreach ($key in $checkKeys) {
        $foundLine = $envContent | Where-Object { $_ -match ("^\s*" + [regex]::Escape($key) + "\s*=") } | Select-Object -First 1
        if ($foundLine) {
            $val = ($foundLine -split "=", 2)[1].Trim()
            if ($key -match "PASSWORD|SECRET") {
                if ($val.Length -gt 0 -and $val -notmatch "your-") {
                    Write-Host "    $key : <SET>" -ForegroundColor Green
                } else {
                    Write-Host "    $key : <PLACEHOLDER / UNSET>" -ForegroundColor Red
                }
            } elseif ($key -eq "SUPEROFFICE_ALLOW_SELF_SIGNED_CERT") {
                $color = if ($val -eq "true") { "Yellow" } else { "Green" }
                Write-Host "    $key : $val" -ForegroundColor $color
            } else {
                Write-Host "    $key : $val" -ForegroundColor Green
            }
        } else {
            Write-Host "    $key : <MISSING / USING DEFAULT>" -ForegroundColor Yellow
        }
    }
} else {
    Write-Host "    .env file exists: NO (.env missing! Copy from .env.example)" -ForegroundColor Red
}

Write-Host ""
Write-Host "[3] Local TCP Ports (127.0.0.1):" -ForegroundColor Yellow
$ports = @(8000, 8001, 8002, 8005)
$portLabels = @{
    8000 = "Gateway"
    8001 = "SuperOffice MCP"
    8002 = "Diagnostics MCP"
    8005 = "Investigation MCP"
}

foreach ($port in $ports) {
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        Write-Host "    Port $port ($($portLabels[$port])) : OCCUPIED (PID: $($conn.OwningProcess))" -ForegroundColor Red
    } else {
        Write-Host "    Port $port ($($portLabels[$port])) : AVAILABLE" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "[4] SuperOffice Upstream Network Reachability:" -ForegroundColor Yellow
$soHost = "superoffice.example.internal"
$soDns = Resolve-DnsName $soHost -ErrorAction SilentlyContinue | Select-Object -First 1
if ($soDns) {
    Write-Host "    SuperOffice DNS ($soHost) : RESOLVED ($($soDns.IPAddress))" -ForegroundColor Green
    $soTcp = Test-NetConnection -ComputerName $soHost -Port 443 -WarningAction SilentlyContinue
    if ($soTcp.TcpTestSucceeded) {
        Write-Host "    SuperOffice TCP/443 : REACHABLE (VPN Active)" -ForegroundColor Green
    } else {
        Write-Host "    SuperOffice TCP/443 : UNREACHABLE" -ForegroundColor Red
    }
} else {
    Write-Host "    SuperOffice DNS ($soHost) : FAILED (Check VPN connection)" -ForegroundColor Red
}

Write-Host ""
Write-Host "[5] Diagnostics MSSQL Upstream Reachability:" -ForegroundColor Yellow
$sqlHost = "sql.example.internal"
$sqlDns = Resolve-DnsName $sqlHost -ErrorAction SilentlyContinue | Select-Object -First 1
if ($sqlDns) {
    Write-Host "    MSSQL DNS ($sqlHost) : RESOLVED ($($sqlDns.IPAddress))" -ForegroundColor Green
    $sqlTcp = Test-NetConnection -ComputerName $sqlHost -Port 1433 -WarningAction SilentlyContinue
    if ($sqlTcp.TcpTestSucceeded) {
        Write-Host "    MSSQL TCP/1433 : REACHABLE" -ForegroundColor Green
    } else {
        Write-Host "    MSSQL TCP/1433 : NETWORK RESTRICTED / TIMED OUT (Expected in Mode A)" -ForegroundColor Yellow
    }
} else {
    Write-Host "    MSSQL DNS ($sqlHost) : UNRESOLVED" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Pre-Flight Check Completed." -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
