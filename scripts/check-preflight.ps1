# scripts/check-preflight.ps1
# SuperOffice AI Support MCP Platform — Terminal Pre-Flight Health Checker

$ErrorActionPreference = "Stop"

$repoRoot = (Get-Item -Path $PSScriptRoot).Parent.FullName
Set-Location $repoRoot

Write-Host "Executing Platform Pre-Flight Diagnostics..." -ForegroundColor Cyan
uv run python -m platform_core.preflight
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host "`nReady to launch platform services: powershell -File scripts/start-local.ps1" -ForegroundColor Green
} else {
    Write-Host "`nPre-flight diagnostics reported failures. Please address blocking items before startup." -ForegroundColor Red
}

exit $exitCode
